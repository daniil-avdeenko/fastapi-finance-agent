"""Тесты хендлеров aiogram с подменёнными Message и agent_service."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Message

from app.services.agent_service import AgentResult
from app.telegram import handlers


def make_message(text: str, chat_id: int = 1) -> Message:
    """Фейковый Message с минимально нужным набором атрибутов."""
    message = MagicMock(spec=Message)
    message.text = text
    message.chat = MagicMock(id=chat_id)
    message.from_user = MagicMock(id=chat_id)
    message.answer = AsyncMock()
    message.bot = MagicMock()
    message.bot.send_chat_action = AsyncMock()
    return message


def make_callback(data: str, chat_id: int = 1) -> CallbackQuery:
    """Фейковый CallbackQuery с message, проходящим isinstance-проверку."""
    callback = MagicMock(spec=CallbackQuery)
    callback.data = data
    callback.answer = AsyncMock()

    message = MagicMock(spec=Message)
    # Подменяем __class__, чтобы хендлер видел настоящий Message.
    message.__class__ = Message
    message.chat = MagicMock()
    message.chat.id = chat_id
    message.answer = AsyncMock()

    callback.message = message
    callback.bot = MagicMock()
    callback.bot.send_chat_action = AsyncMock()
    return callback


class _FakeSession:
    """Заглушка async context manager для SessionLocal."""

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


async def test_cmd_start_sends_greeting() -> None:
    message = make_message("/start")

    await handlers.cmd_start(message)

    message.answer.assert_awaited_once()
    text = message.answer.call_args[0][0]
    assert "ассистент" in text.lower()


async def test_cmd_help_lists_intents() -> None:
    """Help перечисляет возможности бота."""
    message = make_message("/help")

    await handlers.cmd_help(message)

    message.answer.assert_awaited_once()
    text = message.answer.call_args[0][0]
    assert "Что я умею" in text
    assert "Прибыль" in text
    assert "Транзакции" in text
    assert "Курсы валют" in text


async def test_handle_question_calls_agent_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Хендлер зовёт process_question и отдаёт его answer в чат."""
    captured: dict[str, Any] = {}

    async def fake_process(session: Any, *, chat_id: int, question: str) -> AgentResult:
        captured["chat_id"] = chat_id
        captured["question"] = question
        return AgentResult(answer="Сводка готова", llm_provider="mock", latency_ms=42)

    monkeypatch.setattr(handlers, "process_question", fake_process)
    monkeypatch.setattr(handlers, "SessionLocal", _FakeSession)

    message = make_message("Какие доходы?", chat_id=99)

    await handlers.handle_question(message)

    assert captured == {"chat_id": 99, "question": "Какие доходы?"}
    message.bot.send_chat_action.assert_awaited_once()
    message.answer.assert_awaited_once_with("Сводка готова")


async def test_handle_question_reports_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Падение агента не уходит наружу — пользователь получает текст."""

    async def failing_process(session: Any, *, chat_id: int, question: str) -> AgentResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(handlers, "process_question", failing_process)
    monkeypatch.setattr(handlers, "SessionLocal", _FakeSession)

    message = make_message("Вопрос")

    await handlers.handle_question(message)

    message.answer.assert_awaited_once()
    assert "ошибка" in message.answer.call_args[0][0].lower()


async def test_cmd_start_shows_keyboard() -> None:
    message = make_message("/start")
    await handlers.cmd_start(message)

    message.answer.assert_awaited_once()
    markup = message.answer.call_args.kwargs.get("reply_markup")
    assert markup is not None
    # 6 кнопок в 3 рядах
    assert len(markup.inline_keyboard) == 3
    assert all(len(row) == 2 for row in markup.inline_keyboard)


async def test_quick_action_help(monkeypatch) -> None:
    """Кнопка «Помощь» показывает справку без вызова графа."""

    def boom(*args, **kwargs):
        raise AssertionError("граф не должен вызываться для help")

    monkeypatch.setattr(handlers, "process_question", boom)

    callback = make_callback("ask:help")
    await handlers.handle_quick_action(callback)

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    assert "Что я умею" in callback.message.answer.call_args[0][0]


async def test_quick_action_summary(monkeypatch) -> None:
    """Кнопка «Сводка» отправляет вопрос в граф."""
    captured = {}

    async def fake_process(session, *, chat_id, question):
        captured["chat_id"] = chat_id
        captured["question"] = question
        return AgentResult(answer="ok", llm_provider="mock", latency_ms=10)

    monkeypatch.setattr(handlers, "process_question", fake_process)
    monkeypatch.setattr(handlers, "SessionLocal", _FakeSession)

    callback = make_callback("ask:summary", chat_id=42)
    await handlers.handle_quick_action(callback)

    assert captured["chat_id"] == 42
    assert captured["question"] == "Сводка по финансам"
    callback.message.answer.assert_awaited_once_with("ok")


async def test_quick_action_unknown_data() -> None:
    """Неизвестный action — подсказываем нажать /start, граф не зовём."""
    callback = make_callback("ask:nonexistent")
    await handlers.handle_quick_action(callback)

    callback.answer.assert_awaited_once()
    text = callback.answer.call_args[0][0]
    assert "/start" in text


async def test_quick_action_bad_prefix() -> None:
    """Callback без префикса ask: — не наш, отвечаем пустым."""
    callback = make_callback("other:data")
    await handlers.handle_quick_action(callback)

    callback.answer.assert_awaited_once()

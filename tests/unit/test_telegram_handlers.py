"""Тесты хендлеров aiogram с подменёнными Message и agent_service."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

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


async def test_cmd_help_lists_examples() -> None:
    message = make_message("/help")

    await handlers.cmd_help(message)

    message.answer.assert_awaited_once()
    assert "Примеры" in message.answer.call_args[0][0]


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

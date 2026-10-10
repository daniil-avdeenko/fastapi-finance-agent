"""Тесты MockLLM и фабрики провайдеров."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.llm.factory import get_llm
from app.agent.llm.gigachat import GigaChatLLM
from app.agent.llm.mock import MockLLM
from app.agent.llm.openrouter import OpenRouterLLM
from app.config import get_settings


async def test_mock_llm_returns_responses_in_order() -> None:
    """MockLLM возвращает заготовленные ответы по порядку."""
    llm = MockLLM(responses=["first", "second"])

    assert await llm.chat("sys", "u1") == "first"
    assert await llm.chat("sys", "u2") == "second"


async def test_mock_llm_repeats_last_response() -> None:
    """Когда ответы кончились — повторяет последний."""
    llm = MockLLM(responses=["only"])

    assert await llm.chat("s", "u1") == "only"
    assert await llm.chat("s", "u2") == "only"


async def test_mock_llm_stores_calls() -> None:
    """MockLLM записывает все вызовы для ассертов."""
    llm = MockLLM(responses=["x"])

    await llm.chat("system prompt", "user question")

    assert len(llm.calls) == 1
    assert llm.calls[0] == ("system prompt", "user question")


async def test_mock_llm_handler() -> None:
    """Handler вызывается вместо списка ответов."""
    llm = MockLLM(handler=lambda s, u: f"echo:{u}")

    assert await llm.chat("s", "hello") == "echo:hello"


async def test_mock_llm_raises_without_responses() -> None:
    """Без responses и без handler — RuntimeError."""
    llm = MockLLM()

    with pytest.raises(RuntimeError, match="нет заготовленных ответов"):
        await llm.chat("s", "u")


def test_factory_returns_mock_in_dev() -> None:
    """По умолчанию (LLM_PROVIDER=mock) фабрика возвращает MockLLM."""
    llm = get_llm()
    assert isinstance(llm, MockLLM)
    assert llm.name == "mock"


# ---------- OpenRouter ----------


class _FakeCompletions:
    """Заглушка client.chat.completions: пишет kwargs и возвращает фиксированный ответ."""

    def __init__(self, content: str | None, captured: dict[str, Any]) -> None:
        self._content = content
        self._captured = captured

    async def create(self, **kwargs: Any) -> Any:
        self._captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    """Минимальный fake AsyncOpenAI: только то, что использует OpenRouterLLM."""

    def __init__(self, content: str | None, captured: dict[str, Any]) -> None:
        self.chat = _FakeChat(_FakeCompletions(content, captured))


async def test_openrouter_sends_correct_request() -> None:
    """OpenRouterLLM шлёт правильные model и messages, возвращает content."""
    captured: dict[str, Any] = {}
    client = _FakeClient("Ответ модели", captured)
    llm = OpenRouterLLM(api_key="test-key", model="test-model", client=client)

    result = await llm.chat("system prompt", "user question")

    assert result == "Ответ модели"
    assert captured["model"] == "test-model"
    assert captured["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user question"},
    ]


async def test_openrouter_handles_empty_content() -> None:
    """Пустой content от LLM → пустая строка, не None."""
    captured: dict[str, Any] = {}
    client = _FakeClient(None, captured)
    llm = OpenRouterLLM(api_key="k", model="m", client=client)

    assert await llm.chat("s", "u") == ""


def test_openrouter_build_client_passes_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """При создании клиента провайдер прокидывает api_key, base_url, timeout."""
    captured: dict[str, Any] = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("app.agent.llm.openrouter.AsyncOpenAI", FakeAsyncOpenAI)

    llm = OpenRouterLLM(api_key="test-key", model="m", timeout=5.0)
    llm._build_client()

    assert captured == {
        "api_key": "test-key",
        "base_url": "https://openrouter.ai/api/v1",
        "timeout": 5.0,
    }


def test_openrouter_name() -> None:
    assert OpenRouterLLM(api_key="k", model="m").name == "openrouter"


def test_factory_returns_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    """При LLM_PROVIDER=openrouter фабрика возвращает OpenRouterLLM."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    llm = get_llm()
    assert isinstance(llm, OpenRouterLLM)
    assert llm.name == "openrouter"


class _FakeGigaChatResponse:
    """Мок ответа langchain-gigachat."""

    def __init__(self, content: str) -> None:
        self.content = content


def test_gigachat_name() -> None:
    llm = GigaChatLLM(credentials="key", model="GigaChat")
    assert llm.name == "gigachat"


async def test_gigachat_sends_messages() -> None:
    fake_client = MagicMock()
    fake_client.ainvoke = AsyncMock(return_value=_FakeGigaChatResponse("Ответ"))

    llm = GigaChatLLM(credentials="key", model="GigaChat", client=fake_client)
    result = await llm.chat("system prompt", "user question")

    assert result == "Ответ"
    fake_client.ainvoke.assert_awaited_once()
    call_args = fake_client.ainvoke.call_args[0][0]
    assert ("system", "system prompt") in call_args
    assert ("human", "user question") in call_args


def test_gigachat_verify_ssl_explicit() -> None:
    """verify_ssl прокидывается явно, не зависит от env."""
    llm_true = GigaChatLLM(credentials="key", model="GigaChat-3-Pro", verify_ssl=True)
    assert llm_true._verify_ssl is True

    llm_false = GigaChatLLM(credentials="key", model="GigaChat-3-Pro", verify_ssl=False)
    assert llm_false._verify_ssl is False


def test_gigachat_build_client_passes_config(monkeypatch) -> None:
    """Проверяем, что credentials, model, scope прокидываются."""
    captured: dict = {}

    class FakeGigaChat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.agent.llm.gigachat.GigaChat", FakeGigaChat)

    llm = GigaChatLLM(
        credentials="test-key",
        model="GigaChat-Pro",
        scope="GIGACHAT_API_B2B",
        verify_ssl=False,
    )
    llm._build_client()

    assert captured["credentials"] == "test-key"
    assert captured["model"] == "GigaChat-Pro"
    assert captured["scope"] == "GIGACHAT_API_B2B"
    assert captured["verify_ssl_certs"] is False


def test_factory_returns_gigachat(monkeypatch) -> None:
    """При LLM_PROVIDER=gigachat фабрика возвращает GigaChatLLM."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "gigachat")

    llm = get_llm()
    assert isinstance(llm, GigaChatLLM)
    assert llm.name == "gigachat"

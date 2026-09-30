"""Тесты MockLLM и фабрики провайдеров."""

import pytest

from app.agent.llm.factory import get_llm
from app.agent.llm.mock import MockLLM


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

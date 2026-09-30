"""Интеграционные тесты POST /chat (БД через testcontainers)."""

from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import nodes
from app.agent.llm.mock import MockLLM
from app.db import get_session
from app.main import app
from app.models.message import Message


@pytest.fixture
def mock_agent(monkeypatch: pytest.MonkeyPatch) -> MockLLM:
    """Подменяет LLM и tools — детерминированный прогон без сети."""
    llm = MockLLM(
        responses=[
            '{"intent": "summary", "params": {}}',
            "Доходы 100 ₽, расходы 40 ₽.",
        ]
    )
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    async def fake_dispatch(intent: str, params: dict[str, Any]) -> Any:
        return {"income": 100, "expense": 40}

    monkeypatch.setattr(nodes, "dispatch", fake_dispatch)
    return llm


@pytest.fixture
def override_session(db_session: AsyncSession) -> Iterator[None]:
    """Подменяет get_session на тестовую сессию из conftest."""

    async def _override() -> Any:
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.clear()


async def test_chat_returns_answer(
    client: AsyncClient,
    override_session: None,
    mock_agent: MockLLM,
) -> None:
    response = await client.post(
        "/chat",
        json={"chat_id": 12345, "question": "Как финансы?"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "Доходы 100" in body["answer"]
    assert body["llm_provider"] == "mock"
    assert body["latency_ms"] >= 0


async def test_chat_persists_message(
    client: AsyncClient,
    db_session: AsyncSession,
    override_session: None,
    mock_agent: MockLLM,
) -> None:
    await client.post(
        "/chat",
        json={"chat_id": 777, "question": "Сводка"},
    )

    result = await db_session.execute(select(Message).where(Message.chat_id == 777))
    message = result.scalar_one()

    assert message.question == "Сводка"
    assert "Доходы" in message.answer
    assert message.llm_provider == "mock"
    assert message.latency_ms is not None


async def test_chat_rejects_empty_question(
    client: AsyncClient,
    override_session: None,
) -> None:
    response = await client.post("/chat", json={"chat_id": 1, "question": ""})

    assert response.status_code == 422


async def test_chat_rejects_missing_question(
    client: AsyncClient,
    override_session: None,
) -> None:
    response = await client.post("/chat", json={"chat_id": 1})

    assert response.status_code == 422

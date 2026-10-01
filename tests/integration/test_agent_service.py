"""Тесты agent_service (реальный Postgres, фейковый граф)."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.services import agent_service


@pytest.fixture
def mock_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяет get_graph на фейк — не гоняем реальный LangGraph."""

    class FakeGraph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {"answer": f"Ответ на: {state['question']}"}

    monkeypatch.setattr(agent_service, "get_graph", lambda: FakeGraph())


async def test_process_question_persists_message(
    db_session: AsyncSession,
    mock_graph: None,
) -> None:
    """Успешный прогон сохраняет Message и возвращает AgentResult."""
    result = await agent_service.process_question(
        db_session,
        chat_id=42,
        question="Как дела?",
    )

    assert result.answer == "Ответ на: Как дела?"
    assert result.llm_provider == "mock"
    assert result.latency_ms >= 0

    saved = (await db_session.execute(select(Message).where(Message.chat_id == 42))).scalar_one()

    assert saved.question == "Как дела?"
    assert saved.answer == "Ответ на: Как дела?"
    assert saved.llm_provider == "mock"
    assert saved.latency_ms is not None


async def test_process_question_raises_without_answer(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой answer от графа → RuntimeError, в БД ничего не пишем."""

    class EmptyGraph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(agent_service, "get_graph", lambda: EmptyGraph())

    with pytest.raises(RuntimeError, match="failed to produce"):
        await agent_service.process_question(
            db_session,
            chat_id=1,
            question="q",
        )

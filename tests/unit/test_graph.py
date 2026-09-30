"""Тесты LangGraph-графа агента."""

from typing import Any

import pytest

from app.agent import nodes
from app.agent.graph import build_graph, get_graph
from app.agent.llm.mock import MockLLM


@pytest.fixture
def mock_agent(monkeypatch: pytest.MonkeyPatch) -> MockLLM:
    """Подменяет LLM и tools в узлах графа на предсказуемые."""
    llm = MockLLM(
        responses=[
            '{"intent": "summary", "params": {}}',
            "Доходы 100 ₽, расходы 40 ₽, прибыль 60 ₽.",
        ]
    )
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    async def fake_dispatch(intent: str, params: dict[str, Any]) -> Any:
        return {"income": 100, "expense": 40}

    monkeypatch.setattr(nodes, "dispatch", fake_dispatch)
    return llm


async def test_graph_end_to_end(mock_agent: MockLLM) -> None:
    """Линейный прогон: вопрос → understand → query_data → format_answer."""
    graph = build_graph()

    result = await graph.ainvoke({"question": "Как финансы?", "chat_id": 1})

    assert result["intent"] == "summary"
    assert result["data"] == {"income": 100, "expense": 40}
    assert "Доходы 100" in result["answer"]


async def test_graph_handles_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ошибка tool не роняет граф — format_answer отдаёт честный текст."""
    from app.agent.tools import MainAPIError

    llm = MockLLM(responses=['{"intent": "summary", "params": {}}', "unused"])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    async def failing_dispatch(intent: str, params: dict[str, Any]) -> Any:
        raise MainAPIError("boom")

    monkeypatch.setattr(nodes, "dispatch", failing_dispatch)

    graph = build_graph()
    result = await graph.ainvoke({"question": "q", "chat_id": 1})

    assert result["error"] == "boom"
    assert "boom" in result["answer"]


def test_get_graph_is_cached() -> None:
    """get_graph возвращает один и тот же объект (lru_cache)."""
    assert get_graph() is get_graph()

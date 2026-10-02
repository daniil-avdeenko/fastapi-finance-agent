"""Тесты узлов графа агента."""

from typing import Any

import pytest

from app.agent import nodes
from app.agent.llm.mock import MockLLM
from app.agent.tools import MainAPIError

# ---------- understand_node ----------


async def test_understand_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=['{"intent": "summary", "params": {}}'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.understand_node({"question": "Как дела с финансами?", "chat_id": 1})

    assert result["intent"] == "summary"
    assert result["params"] == {}


async def test_understand_extracts_json_from_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=['```json\n{"intent": "projects", "params": {}}\n```'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.understand_node({"question": "Список проектов", "chat_id": 1})

    assert result["intent"] == "projects"


async def test_understand_extracts_json_from_surrounding_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = MockLLM(responses=['Вот ответ: {"intent": "currencies", "params": {}} — как-то так'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.understand_node({"question": "Курсы", "chat_id": 1})

    assert result["intent"] == "currencies"


async def test_understand_returns_unknown_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=["полный бред без json"])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.understand_node({"question": "абракадабра", "chat_id": 1})

    assert result["intent"] == "unknown"
    assert result["params"] == {}


async def test_understand_ignores_non_dict_params(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=['{"intent": "summary", "params": "нет"}'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.understand_node({"question": "q", "chat_id": 1})

    assert result["params"] == {}


# ---------- query_data_node ----------


async def test_query_data_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(intent: str, params: dict[str, Any]) -> dict[str, Any]:
        assert intent == "summary"
        return {"income": 100}

    monkeypatch.setattr(nodes, "dispatch", fake_dispatch)

    result = await nodes.query_data_node({"question": "q", "intent": "summary", "params": {}})

    assert result == {"data": {"income": 100}, "error": None}


async def test_query_data_wraps_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(intent: str, params: dict[str, Any]) -> Any:
        raise MainAPIError("boom")

    monkeypatch.setattr(nodes, "dispatch", fake_dispatch)

    result = await nodes.query_data_node({"question": "q", "intent": "summary", "params": {}})

    assert result["data"] is None
    assert result["error"] == "boom"


# ---------- format_answer_node ----------


async def test_format_answer_uses_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=["Доходы — 100 ₽, расходы — 40 ₽."])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.format_answer_node(
        {"question": "Как дела?", "data": {"income": 100, "expense": 40}}
    )

    assert result["answer"] == "Доходы — 100 ₽, расходы — 40 ₽."
    _, user_msg = llm.calls[0]
    assert "100" in user_msg
    assert "Как дела?" in user_msg


async def test_format_answer_short_circuits_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться при error")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node({"question": "q", "error": "timeout"})

    assert "timeout" in result["answer"]


async def test_understand_handles_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Падение LLM не роняет узел — пишем в state.error."""

    class BrokenLLM:
        async def chat(self, system: str, user: str) -> str:
            raise RuntimeError("LLM down")

    monkeypatch.setattr(nodes, "get_llm", lambda: BrokenLLM())

    result = await nodes.understand_node({"question": "q", "chat_id": 1})

    assert result["intent"] == "unknown"
    assert "LLM down" in result["error"]


async def test_format_answer_handles_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenLLM:
        async def chat(self, system: str, user: str) -> str:
            raise RuntimeError("timeout")

    monkeypatch.setattr(nodes, "get_llm", lambda: BrokenLLM())

    result = await nodes.format_answer_node({"question": "q", "data": {}})

    assert "timeout" in result["answer"]


async def test_query_data_skips_when_error_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если understand уже упал — dispatch не вызывается."""

    async def boom(intent: str, params: dict[str, Any]) -> Any:
        raise AssertionError("dispatch не должен вызываться при error")

    monkeypatch.setattr(nodes, "dispatch", boom)

    result = await nodes.query_data_node(
        {"question": "q", "intent": "summary", "params": {}, "error": "LLM down"}
    )

    assert result == {"data": None}


async def test_understand_prompt_contains_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """В system prompt подставляется текущая дата."""
    llm = MockLLM(responses=['{"intent": "summary", "params": {}}'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    await nodes.understand_node({"question": "q", "chat_id": 1})

    system, _ = llm.calls[0]
    assert "Сегодняшняя дата:" in system
    assert "{today}" not in system  # placeholder заменён

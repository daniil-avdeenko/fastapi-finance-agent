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


async def test_understand_includes_history(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=['{"intent": "profit", "params": {}}'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    await nodes.understand_node(
        {
            "question": "А рентабельность?",
            "chat_id": 1,
            "history": [
                {
                    "question": "Доходы за август",
                    "intent": "aggregate",
                    "params": {"type": "income", "date_from": "2026-08-01"},
                },
                {
                    "question": "А прибыль?",
                    "intent": "profit",
                    "params": {"date_from": "2026-08-01", "date_to": "2026-08-31"},
                },
            ],
        }
    )

    system, _ = llm.calls[0]
    assert "ИСТОРИЯ ДИАЛОГА" in system
    assert "А прибыль?" in system
    assert "profit" in system


async def test_understand_without_history_has_no_block(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=['{"intent": "summary", "params": {}}'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    await nodes.understand_node({"question": "Сводка", "chat_id": 1, "history": []})

    system, _ = llm.calls[0]
    assert "ИСТОРИЯ ДИАЛОГА" not in system


async def test_understand_prompt_contains_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """В system prompt подставляется текущая дата."""
    llm = MockLLM(responses=['{"intent": "summary", "params": {}}'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    await nodes.understand_node({"question": "q", "chat_id": 1})

    system, _ = llm.calls[0]
    assert "Сегодняшняя дата:" in system
    assert "{today}" not in system


async def test_understand_handles_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Падение LLM не роняет узел — пишем в state.error."""

    class BrokenLLM:
        async def chat(self, system: str, user: str) -> str:
            raise RuntimeError("LLM down")

    monkeypatch.setattr(nodes, "get_llm", lambda: BrokenLLM())

    result = await nodes.understand_node({"question": "q", "chat_id": 1})

    assert result["intent"] == "unknown"
    assert "LLM down" in result["error"]


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


async def test_query_data_skips_unknown_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Для intent='unknown' dispatch не вызывается — там нечего выполнять."""

    async def boom(intent: str, params: dict[str, Any]) -> Any:
        raise AssertionError("dispatch не должен вызываться для unknown")

    monkeypatch.setattr(nodes, "dispatch", boom)

    result = await nodes.query_data_node({"question": "q", "intent": "unknown", "params": {}})

    assert result == {"data": None, "error": None}


async def test_query_data_skips_when_error_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если understand уже упал — dispatch не вызывается."""

    async def boom(intent: str, params: dict[str, Any]) -> Any:
        raise AssertionError("dispatch не должен вызываться при error")

    monkeypatch.setattr(nodes, "dispatch", boom)

    result = await nodes.query_data_node(
        {"question": "q", "intent": "summary", "params": {}, "error": "LLM down"}
    )

    assert result == {"data": None}


async def test_query_data_handles_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(intent: str, params: dict[str, Any]) -> Any:
        raise ValueError("неожиданно")

    monkeypatch.setattr(nodes, "dispatch", boom)

    result = await nodes.query_data_node({"question": "q", "intent": "aggregate", "params": {}})

    assert result["data"] is None
    assert "Внутренняя ошибка" in result["error"]


# ---------- format_answer_node ----------


async def test_format_answer_uses_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=["Доходы — 100 ₽, расходы — 40 ₽."])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.format_answer_node(
        {"question": "Как дела?", "intent": "summary", "data": {"income": 100, "expense": 40}}
    )

    assert result["answer"] == "Доходы — 100 ₽, расходы — 40 ₽."
    _, user_msg = llm.calls[0]
    assert "100" in user_msg
    assert "Как дела?" in user_msg


async def test_format_answer_formats_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=["Доход составил 1234567.89 RUB"])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.format_answer_node({"question": "q", "intent": "summary", "data": {}})

    assert result["answer"] == "Доход составил 1 234 567.89 RUB"


async def test_format_answer_short_circuits_on_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown intent → готовый текст, без вызова LLM."""

    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться при unknown")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {"question": "погода?", "intent": "unknown", "data": None}
    )

    assert "Не понял вопрос" in result["answer"]
    assert "Прибыль" in result["answer"]


async def test_format_answer_short_circuits_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться при error")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {"question": "q", "error": "ReadTimeout: connection closed"}
    )

    assert "превышено" in result["answer"].lower()


async def test_format_answer_handles_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenLLM:
        async def chat(self, system: str, user: str) -> str:
            raise RuntimeError("Request timed out")

    monkeypatch.setattr(nodes, "get_llm", lambda: BrokenLLM())

    result = await nodes.format_answer_node({"question": "q", "intent": "summary", "data": {}})

    assert "превышено" in result["answer"].lower()


async def test_format_answer_no_double_punctuation() -> None:
    result = await nodes.format_answer_node(
        {"question": "q", "error": "Объект не найден.", "data": None}
    )

    assert ".." not in result["answer"]
    assert "Объект не найден." in result["answer"]


async def test_format_answer_not_found_skips_retry_hint() -> None:
    result = await nodes.format_answer_node(
        {"question": "q", "error": "Объект не найден.", "data": None}
    )
    assert "Попробуйте позже" not in result["answer"]
    assert "Объект не найден" in result["answer"]


async def test_format_answer_hides_llm_credits_error() -> None:
    error = (
        "LLM error: Error code: 402 - {'error': {'message': "
        "'This request would exceed your available credits'}}"
    )
    result = await nodes.format_answer_node({"question": "q", "error": error, "data": None})

    assert "402" not in result["answer"]
    assert "credits" not in result["answer"].lower()
    assert "временно" in result["answer"].lower()


# ---------- format_answer_node — интенты, отданные Python-рендеру ----------


async def test_format_answer_transactions_uses_python_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться для transactions")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {
            "question": "Перечисли транзакции",
            "intent": "transactions",
            "data": {
                "items": [
                    {
                        "type": "expense",
                        "category_name": "Налоги",
                        "amount_rub": 240_500.0,
                        "project_name": "Alpha",
                    }
                ],
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
            },
        }
    )

    assert "Расход: Налоги" in result["answer"]


async def test_format_answer_top_n_uses_python_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться для top_n")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {
            "question": "Топ-3 проекта",
            "intent": "top_n",
            "data": {
                "metric": "profit",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "items": [
                    {"project_name": "Alpha", "metric_value": 1000000.0},
                    {"project_name": "Beta", "metric_value": 500000.0},
                ],
            },
        }
    )

    assert "Топ-2 проекта по прибыли" in result["answer"]
    assert "Alpha — прибыль 1 000 000 ₽" in result["answer"]


async def test_format_answer_profit_uses_python_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться для profit")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {
            "question": "Прибыль за август",
            "intent": "profit",
            "data": {
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "grand_income_rub": 1000.0,
                "grand_expense_rub": 300.0,
                "grand_profit_rub": 700.0,
                "grand_profitability_percent": 70.0,
                "by_project": [
                    {
                        "project_id": 1,
                        "project_name": "A",
                        "profit_rub": 700.0,
                        "profitability_percent": 70.0,
                    }
                ],
            },
        }
    )

    assert "Проект A за август 2026:" in result["answer"]
    assert "• Прибыль: 700 ₽" in result["answer"]


async def test_format_answer_profitability_uses_python_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться для profitability")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {
            "question": "Рентабельность за июнь",
            "intent": "profitability",
            "data": {
                "date_from": "2026-06-01",
                "date_to": "2026-06-30",
                "grand_profitability_percent": 25.73,
                "by_project": [
                    {"project_name": "A", "profitability_percent": 33.08},
                ],
            },
        }
    )

    assert "Рентабельность проекта A за июнь 2026" in result["answer"]
    assert "Доход" not in result["answer"]


async def test_format_answer_aggregate_uses_python_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться для aggregate")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {
            "question": "Суммарный доход за июль",
            "intent": "aggregate",
            "data": {
                "date_from": "2026-07-01",
                "date_to": "2026-07-31",
                "type": "income",
                "total_transactions": 5,
                "grand_total_rub": 1000.0,
                "by_project": [
                    {"project_id": 1, "project_name": "A", "total_rub": 1000.0, "count": 5},
                ],
            },
        }
    )

    assert "Доходы по проекту A за июль 2026:" in result["answer"]


async def test_format_answer_compare_uses_python_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться для compare")

    monkeypatch.setattr(nodes, "get_llm", boom)

    result = await nodes.format_answer_node(
        {
            "question": "Сравни май и июнь",
            "intent": "compare",
            "data": {
                "metric": "profit",
                "period1": {"date_from": "2026-05-01", "date_to": "2026-05-31"},
                "period2": {"date_from": "2026-06-01", "date_to": "2026-06-30"},
                "grand": {
                    "period1_value": 1000.0,
                    "period2_value": 1200.0,
                    "diff_abs": 200.0,
                    "diff_pct": 20.0,
                },
                "by_project": [],
            },
        }
    )

    assert "Сравнение прибыли" in result["answer"]
    assert "1 000 ₽ → 1 200 ₽ (+200 ₽, +20%)" in result["answer"]


async def test_format_answer_count_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await nodes.format_answer_node(
        {
            "question": "Сколько транзакций?",
            "intent": "count",
            "data": {
                "count": 10,
                "project_id": 1,
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "type": "expense",
            },
        }
    )

    assert "Транзакций: 10" in result["answer"]
    assert "проекту 1" in result["answer"]
    assert "расходных" in result["answer"]

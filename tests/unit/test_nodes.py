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


async def test_understand_includes_history(monkeypatch):
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


async def test_understand_without_history_has_no_block(monkeypatch):
    llm = MockLLM(responses=['{"intent": "summary", "params": {}}'])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    await nodes.understand_node({"question": "Сводка", "chat_id": 1, "history": []})

    system, _ = llm.calls[0]
    assert "ИСТОРИЯ ДИАЛОГА" not in system


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


def test_format_numbers_inserts_separators() -> None:
    assert nodes.format_numbers("1234567.89 руб") == "1 234 567.89 руб"
    assert nodes.format_numbers("Доход 1000.50") == "Доход 1 000.50"


def test_format_numbers_keeps_years() -> None:
    assert nodes.format_numbers("за август 2026") == "за август 2026"
    assert nodes.format_numbers("с 1999 по 2024") == "с 1999 по 2024"


async def test_format_answer_formats_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = MockLLM(responses=["Доход составил 1234567.89 RUB"])
    monkeypatch.setattr(nodes, "get_llm", lambda: llm)

    result = await nodes.format_answer_node({"question": "q", "data": {}})

    assert result["answer"] == "Доход составил 1 234 567.89 RUB"


async def test_query_data_handles_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(intent: str, params: dict[str, Any]) -> Any:
        raise ValueError("неожиданно")

    monkeypatch.setattr(nodes, "dispatch", boom)

    result = await nodes.query_data_node({"question": "q", "intent": "aggregate", "params": {}})

    assert result["data"] is None
    assert "Внутренняя ошибка" in result["error"]


def test_format_numbers_removes_trailing_zero() -> None:
    assert nodes.format_numbers("14 450 744.0 RUB") == "14 450 744 RUB"
    assert nodes.format_numbers("1234567,00 руб") == "1 234 567 руб"


def test_format_numbers_keeps_decimals() -> None:
    assert nodes.format_numbers("1234.56") == "1 234.56"


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


def test_format_transactions_plain_renders_items() -> None:
    """Форматирует список транзакций без LLM, категории из своей записи."""
    data = {
        "items": [
            {
                "type": "income",
                "category_name": "Консультационные услуги",
                "amount_rub": 1_247_062.51,
                "project_name": "CRM для банка «Альфа»",
            },
            {
                "type": "expense",
                "category_name": "Расходы на ИИ",
                "amount_rub": 716_671.56,
                "project_name": "CRM для банка «Альфа»",
            },
        ],
    }
    params = {"date_from": "2026-08-01", "date_to": "2026-08-31"}

    result = nodes._format_transactions_plain(data, params)

    assert result is not None
    assert "Доход: Консультационные услуги — 1 247 062.51 ₽" in result
    assert "Расход: Расходы на ИИ — 716 671.56 ₽" in result
    assert "август 2026" in result


def test_format_transactions_plain_empty_returns_none() -> None:
    assert nodes._format_transactions_plain({"items": []}, {}) is None


def test_format_transactions_plain_caps_at_15() -> None:
    """Больше 15 записей — обрезаем и пишем, сколько осталось."""
    items = [
        {
            "type": "income",
            "category_name": f"Cat{i}",
            "amount_rub": 100.0,
            "project_name": "P",
        }
        for i in range(20)
    ]
    result = nodes._format_transactions_plain(
        {"items": items},
        {"date_from": "2026-08-01", "date_to": "2026-08-31"},
    )

    assert result is not None
    assert result.count("•") == 15
    assert "и ещё 5 записей" in result


async def test_format_answer_transactions_uses_python_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """intent=transactions → LLM не вызывается вообще."""

    def boom() -> Any:
        raise AssertionError("LLM не должен вызываться для списка транзакций")

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


def test_format_transactions_plain_period_from_params_only() -> None:
    """Период берётся из params, а не из data — API не возвращает его."""
    data = {
        "items": [
            {
                "type": "income",
                "category_name": "X",
                "amount_rub": 100.0,
                "project_name": "Alpha",
            }
        ],
    }
    result = nodes._format_transactions_plain(
        data, {"date_from": "2026-08-01", "date_to": "2026-08-31"}
    )

    assert result is not None
    assert "август 2026" in result


def test_format_transactions_plain_strips_trailing_zeros() -> None:
    data = {
        "items": [
            {
                "type": "expense",
                "category_name": "Налоги",
                "amount_rub": 240_500.0,
                "project_name": "P",
            },
            {
                "type": "income",
                "category_name": "Услуги",
                "amount_rub": 1_247_062.51,
                "project_name": "P",
            },
        ]
    }
    result = nodes._format_transactions_plain(data, {})

    assert result is not None
    assert "240 500 ₽" in result
    assert "240 500.00" not in result
    assert "1 247 062.51 ₽" in result  # значимая дробь не тронута


def test_format_transactions_plain_single_month_period() -> None:
    data = {
        "items": [
            {"type": "expense", "category_name": "Н", "amount_rub": 100.0, "project_name": "P"}
        ]
    }
    result = nodes._format_transactions_plain(
        data, {"date_from": "2026-08-01", "date_to": "2026-08-31"}
    )
    assert result is not None
    assert "P, август 2026:" in result


def test_format_transactions_plain_custom_range() -> None:
    data = {
        "items": [
            {"type": "expense", "category_name": "Н", "amount_rub": 100.0, "project_name": "P"}
        ]
    }
    result = nodes._format_transactions_plain(
        data, {"date_from": "2026-08-15", "date_to": "2026-08-20"}
    )
    assert result is not None
    assert "с 15.08.2026 по 20.08.2026" in result


def test_format_numbers_ignores_decimal_part() -> None:
    """94,3201 не должно превращаться в 94,3 201."""
    assert nodes.format_numbers("94,3201 ₽") == "94,3201 ₽"
    assert nodes.format_numbers("83.4839 ₽") == "83.4839 ₽"


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


async def test_format_answer_no_double_punctuation() -> None:
    result = await nodes.format_answer_node(
        {"question": "q", "error": "Объект не найден.", "data": None}
    )

    assert ".." not in result["answer"]
    assert "Объект не найден." in result["answer"]


def test_format_numbers_pads_percent_to_two_digits() -> None:
    assert nodes.format_numbers("Рентабельность 37,9%") == "Рентабельность 37,90%"
    assert nodes.format_numbers("Рентабельность 22,76%") == "Рентабельность 22,76%"


def test_format_numbers_rounds_long_percent() -> None:
    assert nodes.format_numbers("26,756%") == "26,76%"

"""Тесты HTTP-инструментов агента (respx поверх httpx)."""

import httpx
import pytest
import respx

from app.agent import tools
from app.agent.tools import MainAPIError
from app.config import get_settings


@pytest.fixture
def base_url() -> str:
    """Базовый URL основного API из настроек — без хвостового слеша."""
    return get_settings().main_api_url.rstrip("/")


# ---------- успешные вызовы ----------


@respx.mock
async def test_get_summary_returns_json(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/summary").mock(
        return_value=httpx.Response(200, json={"income": 100, "expense": 40})
    )

    assert await tools.get_summary() == {"income": 100, "expense": 40}


@respx.mock
async def test_list_projects_returns_json(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"id": 1, "name": "A"}]})
    )

    result = await tools.list_projects()
    assert result["projects"][0]["name"] == "A"


@respx.mock
async def test_get_project_detail_uses_path_id(base_url: str) -> None:
    route = respx.get(f"{base_url}/api/v1/projects/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "X"})
    )

    result = await tools.get_project_detail(42)

    assert result == {"id": 42, "name": "X"}
    assert route.called


@respx.mock
async def test_get_currency_rates_returns_json(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/currencies").mock(
        return_value=httpx.Response(200, json={"USD": 92.5, "EUR": 100.1})
    )

    assert await tools.get_currency_rates() == {"USD": 92.5, "EUR": 100.1}


# ---------- параметры запроса ----------


@respx.mock
async def test_get_transactions_passes_filters(base_url: str) -> None:
    route = respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    await tools.get_transactions(type="expense", page=2, per_page=5)

    request = route.calls.last.request
    assert request.url.params["type"] == "expense"
    assert request.url.params["page"] == "2"
    assert request.url.params["per_page"] == "5"
    # None-параметры не должны попадать в query string
    assert "project_id" not in request.url.params
    assert "date_from" not in request.url.params


@respx.mock
async def test_get_transactions_defaults_page_and_per_page(base_url: str) -> None:
    route = respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    await tools.get_transactions()

    params = route.calls.last.request.url.params
    assert params["page"] == "1"
    assert params["per_page"] == "20"


# ---------- ошибки ----------


@respx.mock
async def test_http_error_wrapped_in_main_api_error(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/summary").mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(MainAPIError, match="GET /api/v1/summary"):
        await tools.get_summary()


@respx.mock
async def test_network_error_wrapped_in_main_api_error(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/summary").mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(MainAPIError):
        await tools.get_summary()


# ---------- dispatch ----------


@respx.mock
async def test_dispatch_routes_summary(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/summary").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    assert await tools.dispatch("summary") == {"ok": True}


@respx.mock
async def test_dispatch_routes_project_detail(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/projects/7").mock(
        return_value=httpx.Response(200, json={"id": 7})
    )

    assert await tools.dispatch("project_detail", {"project_id": 7}) == {"id": 7}


async def test_dispatch_project_detail_without_id_raises() -> None:
    with pytest.raises(MainAPIError, match="project_id"):
        await tools.dispatch("project_detail", {})


@respx.mock
async def test_dispatch_transactions_ignores_unknown_keys(base_url: str) -> None:
    """LLM может выдумать лишние ключи — они не должны долетать до httpx."""
    route = respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    await tools.dispatch(
        "transactions",
        {"type": "income", "banana": "yes", "project_id": 3},
    )

    params = route.calls.last.request.url.params
    assert params["type"] == "income"
    assert params["project_id"] == "3"
    assert "banana" not in params


async def test_dispatch_unknown_intent_raises() -> None:
    with pytest.raises(MainAPIError, match="Неизвестный intent"):
        await tools.dispatch("weather")


@respx.mock
async def test_get_transactions_all_paginates(base_url: str) -> None:
    """Итерирует пагинацию, пока не кончатся записи."""
    page1 = [{"id": i, "amount": 100} for i in range(100)]
    page2 = [{"id": 100, "amount": 200}]

    respx.get(f"{base_url}/api/v1/transactions").mock(
        side_effect=[
            httpx.Response(200, json={"items": page1, "total": 101}),
            httpx.Response(200, json={"items": page2, "total": 101}),
        ]
    )

    items = await tools.get_transactions_all()

    assert len(items) == 101


@respx.mock
async def test_aggregate_transactions_sums_in_rub(base_url: str) -> None:
    """Считает по amount_rub, игнорирует валюту транзакции."""
    items = [
        {
            "project_id": 1,
            "project_name": "A",
            "currency": "USD",
            "amount": 50.0,
            "amount_rub": 4200.0,
        },
        {
            "project_id": 1,
            "project_name": "A",
            "currency": "RUB",
            "amount": 1000.0,
            "amount_rub": 1000.0,
        },
        {
            "project_id": 2,
            "project_name": "B",
            "currency": "RUB",
            "amount": 500.0,
            "amount_rub": 500.0,
        },
    ]
    respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": items})
    )

    result = await tools.aggregate_transactions(type="income")

    assert result["grand_total_rub"] == 5700.0
    by_pid = {p["project_id"]: p for p in result["by_project"]}
    assert by_pid[1]["total_rub"] == 5200.0
    assert by_pid[2]["total_rub"] == 500.0


@respx.mock
async def test_dispatch_routes_aggregate(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    result = await tools.dispatch(
        "aggregate", {"type": "income", "date_from": "2026-05-01", "date_to": "2026-05-31"}
    )

    assert result["grand_total_rub"] == 0


@respx.mock
async def test_aggregate_profit_computes_difference(base_url: str) -> None:
    """Прибыль = income_rub − expense_rub, рентабельность = profit/income*100."""

    def make_response(items: list[dict]) -> httpx.Response:
        return httpx.Response(200, json={"items": items})

    income_items = [
        {
            "project_id": 1,
            "project_name": "A",
            "currency": "RUB",
            "amount": 1000.0,
            "amount_rub": 1000.0,
        },
    ]
    expense_items = [
        {
            "project_id": 1,
            "project_name": "A",
            "currency": "RUB",
            "amount": 300.0,
            "amount_rub": 300.0,
        },
    ]

    respx.get(f"{base_url}/api/v1/transactions").mock(
        side_effect=[make_response(income_items), make_response(expense_items)]
    )

    result = await tools.aggregate_profit()

    assert result["grand_income_rub"] == 1000.0
    assert result["grand_expense_rub"] == 300.0
    assert result["grand_profit_rub"] == 700.0
    assert result["grand_profitability_percent"] == 70.0

    entry = result["by_project"][0]
    assert entry["profit_rub"] == 700.0
    assert entry["profitability_percent"] == 70.0


@respx.mock
async def test_aggregate_profit_handles_zero_income(base_url: str) -> None:
    """При нулевом доходе рентабельность = None, не ZeroDivisionError."""
    respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    result = await tools.aggregate_profit()

    assert result["grand_profitability_percent"] is None

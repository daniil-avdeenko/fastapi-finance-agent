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
async def test_http_500_wrapped_with_friendly_message(base_url: str) -> None:
    """5xx → нейтральное сообщение без URL и деталей httpx."""
    respx.get(f"{base_url}/api/v1/summary").mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(MainAPIError, match="временно недоступен"):
        await tools.get_summary()


@respx.mock
async def test_http_404_wrapped_with_friendly_message(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/projects/999").mock(
        return_value=httpx.Response(404, text="not found")
    )

    with pytest.raises(MainAPIError, match="Объект не найден"):
        await tools.get_project_detail(999)


@respx.mock
async def test_http_400_wrapped_with_friendly_message(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/summary").mock(return_value=httpx.Response(400, text="bad"))

    with pytest.raises(MainAPIError, match="Некорректный запрос"):
        await tools.get_summary()


@respx.mock
async def test_network_error_wrapped_with_friendly_message(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/summary").mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(MainAPIError, match="недоступен"):
        await tools.get_summary()


@respx.mock
async def test_main_api_error_does_not_leak_url(base_url: str) -> None:
    """Сообщение об ошибке не содержит URL API — иначе утечка во фронт."""
    respx.get(f"{base_url}/api/v1/projects/999").mock(
        return_value=httpx.Response(404, text="not found")
    )

    with pytest.raises(MainAPIError) as exc_info:
        await tools.get_project_detail(999)

    msg = str(exc_info.value)
    assert "http://" not in msg
    assert "https://" not in msg
    assert "/api/v1/" not in msg


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


def test_to_rub_falls_back_to_amount_without_amount_rub() -> None:
    """Если API не отдал amount_rub — используем amount как есть."""
    tx = {"amount": 100.5, "currency": "RUB"}
    assert tools._to_rub(tx) == 100.5


@respx.mock
async def test_get_summary_passes_dates(base_url: str) -> None:
    route = respx.get(f"{base_url}/api/v1/summary").mock(
        return_value=httpx.Response(200, json={"total_profit": 100})
    )

    await tools.get_summary(date_from="2026-08-01", date_to="2026-08-31")

    params = route.calls.last.request.url.params
    assert params["date_from"] == "2026-08-01"
    assert params["date_to"] == "2026-08-31"


@respx.mock
async def test_get_summary_without_dates_sends_no_params(base_url: str) -> None:
    route = respx.get(f"{base_url}/api/v1/summary").mock(return_value=httpx.Response(200, json={}))

    await tools.get_summary()

    assert not route.calls.last.request.url.params


@respx.mock
async def test_dispatch_summary_passes_dates(base_url: str) -> None:
    route = respx.get(f"{base_url}/api/v1/summary").mock(return_value=httpx.Response(200, json={}))

    await tools.dispatch("summary", {"date_from": "2026-08-01", "date_to": "2026-08-31"})

    params = route.calls.last.request.url.params
    assert params["date_from"] == "2026-08-01"


@respx.mock
async def test_count_transactions_returns_total(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"total": 10, "items": []})
    )

    result = await tools.count_transactions(project_id=1)

    assert result["count"] == 10
    assert result["project_id"] == 1


@respx.mock
async def test_top_projects_sorts_by_profit(base_url: str) -> None:
    """Сортирует по прибыли убывающая, обрезает до n."""
    income_items = [
        {"project_id": 1, "project_name": "A", "amount_rub": 1000.0, "type": "income"},
        {"project_id": 2, "project_name": "B", "amount_rub": 500.0, "type": "income"},
        {"project_id": 3, "project_name": "C", "amount_rub": 800.0, "type": "income"},
    ]
    expense_items = [
        {"project_id": 1, "project_name": "A", "amount_rub": 900.0, "type": "expense"},
        {"project_id": 2, "project_name": "B", "amount_rub": 100.0, "type": "expense"},
        {"project_id": 3, "project_name": "C", "amount_rub": 700.0, "type": "expense"},
    ]

    respx.get(f"{base_url}/api/v1/transactions").mock(
        side_effect=[
            httpx.Response(200, json={"items": income_items}),
            httpx.Response(200, json={"items": expense_items}),
        ]
    )

    result = await tools.top_projects(n=2, metric="profit")

    assert result["n"] == 2
    assert len(result["items"]) == 2
    # C: 800-700=100, A: 1000-900=100, B: 500-100=400 → порядок B, A/C
    names = [p["project_name"] for p in result["items"]]
    assert names[0] == "B"  # 400 ₽ прибыли


@respx.mock
async def test_top_projects_sorts_by_income(base_url: str) -> None:
    """metric=income берёт только доходы."""
    items = [
        {"project_id": 1, "project_name": "A", "amount_rub": 1000.0, "type": "income"},
        {"project_id": 2, "project_name": "B", "amount_rub": 500.0, "type": "income"},
    ]
    respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": items})
    )

    result = await tools.top_projects(n=3, metric="income")

    assert result["items"][0]["project_name"] == "A"
    assert result["items"][0]["metric_value"] == 1000.0


async def test_top_projects_clamps_n() -> None:
    """n ограничивается сверху."""
    # Если n=100 — обрезается до 10 при запросе
    from unittest.mock import AsyncMock

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            tools,
            "aggregate_transactions",
            AsyncMock(return_value={"by_project": []}),
        )
        result = await tools.top_projects(n=100, metric="income")
        assert result["n"] == 10


@respx.mock
async def test_dispatch_routes_top_n(base_url: str) -> None:
    respx.get(f"{base_url}/api/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    result = await tools.dispatch("top_n", {"n": 3, "metric": "income"})

    assert result["n"] == 3
    assert result["metric"] == "income"


@respx.mock
async def test_compare_periods_profit(base_url: str) -> None:
    """Считает дельту по прибыли между двумя периодами."""

    def make_income(project_values: list[tuple[int, str, float]]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"project_id": pid, "project_name": name, "amount_rub": v, "type": "income"}
                    for pid, name, v in project_values
                ]
            },
        )

    def make_expense(project_values: list[tuple[int, str, float]]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"project_id": pid, "project_name": name, "amount_rub": v, "type": "expense"}
                    for pid, name, v in project_values
                ]
            },
        )

    # 4 вызова: period1 (income, expense), period2 (income, expense)
    respx.get(f"{base_url}/api/v1/transactions").mock(
        side_effect=[
            make_income([(1, "A", 1000.0)]),
            make_expense([(1, "A", 400.0)]),
            make_income([(1, "A", 1500.0)]),
            make_expense([(1, "A", 500.0)]),
        ]
    )

    result = await tools.compare_periods(
        metric="profit",
        period1_from="2026-05-01",
        period1_to="2026-05-31",
        period2_from="2026-06-01",
        period2_to="2026-06-30",
    )

    assert result["grand"]["period1_value"] == 600.0
    assert result["grand"]["period2_value"] == 1000.0
    assert result["grand"]["diff_abs"] == 400.0
    assert result["grand"]["diff_pct"] == 66.67
    assert result["by_project"][0]["project_name"] == "A"


@respx.mock
async def test_compare_periods_handles_missing_baseline(base_url: str) -> None:
    """Если в period1 проекта нет — дельта считается от нуля, pct=None."""
    respx.get(f"{base_url}/api/v1/transactions").mock(
        side_effect=[
            httpx.Response(200, json={"items": []}),  # p1 income
            httpx.Response(200, json={"items": []}),  # p1 expense
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "project_id": 1,
                            "project_name": "A",
                            "amount_rub": 1000.0,
                            "type": "income",
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"items": []}),  # p2 expense
        ]
    )

    result = await tools.compare_periods(
        metric="profit",
        period1_from="2026-05-01",
        period1_to="2026-05-31",
        period2_from="2026-06-01",
        period2_to="2026-06-30",
    )

    entry = result["by_project"][0]
    assert entry["period1_value"] == 0.0
    assert entry["period2_value"] == 1000.0
    assert entry["diff_abs"] == 1000.0
    assert entry["diff_pct"] is None  # от нуля относительную не считаем


async def test_compare_periods_requires_both_periods() -> None:
    with pytest.raises(MainAPIError, match="оба периода"):
        await tools.dispatch("compare", {"metric": "profit"})

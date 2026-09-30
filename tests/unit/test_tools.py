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

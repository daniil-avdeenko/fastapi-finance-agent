"""Тесты healthcheck."""

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    """GET /health возвращает 200 и корректный JSON."""
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "finance-agent"
    assert data["version"] == "0.1.0"


async def test_docs_available_in_dev(client: AsyncClient) -> None:
    """В dev-режиме /docs доступен (APP_ENV=development в conftest)."""
    response = await client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_openapi_json_returns_spec(client: AsyncClient) -> None:
    """OpenAPI-спецификация доступна в dev."""
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "Finance Agent"
    assert "/health" in spec["paths"]

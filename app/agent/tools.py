"""
Инструменты агента: HTTP-обёртки над публичным API project-finance.
"""

from typing import Any

import httpx

from app.config import get_settings


class MainAPIError(RuntimeError):
    """Ошибка при обращении к публичному API основного проекта."""


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """
    GET-запрос к основному проекту.
    """
    settings = get_settings()
    url = f"{settings.main_api_url.rstrip('/')}{path}"

    async with httpx.AsyncClient(timeout=settings.main_api_timeout) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MainAPIError(f"GET {path}: {exc}") from exc

        return response.json()


async def get_summary() -> Any:
    """Сводка по финансам: доходы, расходы, прибыль, рентабельность."""
    return await _get("/api/v1/summary")


async def list_projects() -> Any:
    """Список проектов."""
    return await _get("/api/v1/projects")


async def get_project_detail(project_id: int) -> Any:
    """Детали проекта по id."""
    return await _get(f"/api/v1/projects/{project_id}")


async def get_transactions(
    *,
    type: str | None = None,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> Any:
    """
    Транзакции с фильтрами и пагинацией.
    """
    params: dict[str, Any] = {"page": page, "per_page": per_page}
    for key, value in (
        ("type", type),
        ("project_id", project_id),
        ("date_from", date_from),
        ("date_to", date_to),
    ):
        if value is not None:
            params[key] = value

    return await _get("/api/v1/transactions", params=params)


async def get_currency_rates() -> Any:
    """Курсы валют ЦБ на последнюю доступную дату."""
    return await _get("/api/v1/currencies")


async def dispatch(intent: str, params: dict[str, Any] | None = None) -> Any:
    """
    Роутер по intent → нужный tool.
    """
    params = params or {}

    match intent:
        case "summary":
            return await get_summary()

        case "projects":
            return await list_projects()

        case "project_detail":
            project_id = params.get("project_id")
            if project_id is None:
                raise MainAPIError("project_detail: не указан project_id")
            return await get_project_detail(int(project_id))

        case "transactions":
            allowed = {"type", "project_id", "date_from", "date_to", "page", "per_page"}
            kwargs = {k: v for k, v in params.items() if k in allowed}
            return await get_transactions(**kwargs)

        case "currencies":
            return await get_currency_rates()

        case _:
            raise MainAPIError(f"Неизвестный intent: {intent!r}")

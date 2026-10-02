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

        case "aggregate":
            allowed = {"type", "date_from", "date_to", "project_id"}
            kwargs = {k: v for k, v in params.items() if k in allowed}
            return await aggregate_transactions(**kwargs)

        case _:
            raise MainAPIError(f"Неизвестный intent: {intent!r}")


def _extract_items(data: Any) -> list[dict[str, Any]]:
    """Достаёт список транзакций из ответа API, независимо от формы."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "transactions", "results", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


async def get_transactions_all(
    *,
    type: str | None = None,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """
    Забирает ВСЕ транзакции по фильтрам, итерируя пагинацию.
    """
    all_items: list[dict[str, Any]] = []
    page = 1
    per_page = 100

    while page <= max_pages:
        data = await get_transactions(
            type=type,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            per_page=per_page,
        )
        items = _extract_items(data)
        if not items:
            break
        all_items.extend(items)
        if len(items) < per_page:
            break
        page += 1

    return all_items


async def aggregate_transactions(
    *,
    type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    """
    Агрегирует транзакции по проектам за период.

    Суммы группируются по (project_id, currency). Итог — по каждой валюте
    отдельно, без кросс-конвертации.
    """
    items = await get_transactions_all(
        type=type,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
    )

    by_project: dict[int, dict[str, Any]] = {}
    grand_total: dict[str, float] = {}

    for tx in items:
        pid = tx.get("project_id")
        if pid is None:
            continue

        project_name = tx.get("project_name") or (
            tx.get("project", {}).get("name") if isinstance(tx.get("project"), dict) else None
        )
        currency = tx.get("currency", "RUB")
        amount = float(tx.get("amount", 0))

        entry = by_project.setdefault(
            pid,
            {
                "project_id": pid,
                "project_name": project_name,
                "totals_by_currency": {},
                "count": 0,
            },
        )
        entry["totals_by_currency"][currency] = round(
            entry["totals_by_currency"].get(currency, 0.0) + amount, 2
        )
        entry["count"] += 1

        grand_total[currency] = round(grand_total.get(currency, 0.0) + amount, 2)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "type": type,
        "total_transactions": len(items),
        "grand_total_by_currency": grand_total,
        "by_project": list(by_project.values()),
    }

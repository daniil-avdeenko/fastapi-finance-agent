"""
Инструменты агента: HTTP-обёртки над публичным API project-finance.
"""

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class MainAPIError(RuntimeError):
    """Ошибка при обращении к публичному API основного проекта."""


def _friendly_http_error(status: int) -> str:
    """Человеческое сообщение об ошибке без URL и деталей httpx."""
    if status == 404:
        return "Объект не найден."
    if 500 <= status < 600:
        return "Основной сервис временно недоступен."
    if 400 <= status < 500:
        return "Некорректный запрос к основному сервису."
    return "Не удалось получить данные."


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
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP %s on %s", exc.response.status_code, path)
            raise MainAPIError(_friendly_http_error(exc.response.status_code)) from exc
        except httpx.RequestError as exc:
            logger.warning("Network error on %s: %s", path, exc)
            raise MainAPIError("Основной сервис недоступен.") from exc

        return response.json()


async def get_summary(*, date_from: str | None = None, date_to: str | None = None) -> Any:
    """Сводка по финансам за период (или за всё время)."""
    params: dict[str, Any] = {}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    return await _get("/api/v1/summary", params=params or None)


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


def _to_rub(tx: dict[str, Any]) -> float:
    """
    Возвращает сумму транзакции в рублях.

    API app 1 отдаёт `amount_rub` — уже сконвертировано по курсу на дату.
    """
    if "amount_rub" in tx and tx["amount_rub"] is not None:
        return float(tx["amount_rub"])
    return float(tx.get("amount", 0))


async def aggregate_transactions(
    *,
    type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    """
    Агрегирует транзакции по проектам за период.
    """
    items = await get_transactions_all(
        type=type,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
    )

    by_project: dict[int, dict[str, Any]] = {}
    grand_total_rub = 0.0

    for tx in items:
        pid = tx.get("project_id")
        if pid is None:
            continue

        amount_rub = _to_rub(tx)

        entry = by_project.setdefault(
            pid,
            {
                "project_id": pid,
                "project_name": tx.get("project_name"),
                "total_rub": 0.0,
                "count": 0,
            },
        )
        entry["total_rub"] = round(entry["total_rub"] + amount_rub, 2)
        entry["count"] += 1
        grand_total_rub = round(grand_total_rub + amount_rub, 2)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "type": type,
        "total_transactions": len(items),
        "grand_total_rub": grand_total_rub,
        "by_project": list(by_project.values()),
    }


async def aggregate_profit(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    """
    Прибыль и рентабельность по проектам за период.
    """
    income = await aggregate_transactions(
        type="income", date_from=date_from, date_to=date_to, project_id=project_id
    )
    expense = await aggregate_transactions(
        type="expense", date_from=date_from, date_to=date_to, project_id=project_id
    )

    income_by_pid = {p["project_id"]: p for p in income["by_project"]}
    expense_by_pid = {p["project_id"]: p for p in expense["by_project"]}

    all_pids = set(income_by_pid) | set(expense_by_pid)

    by_project: list[dict[str, Any]] = []
    grand_income = 0.0
    grand_expense = 0.0

    for pid in sorted(all_pids):
        inc_entry = income_by_pid.get(pid, {})
        exp_entry = expense_by_pid.get(pid, {})

        income_rub = inc_entry.get("total_rub", 0.0)
        expense_rub = exp_entry.get("total_rub", 0.0)
        profit_rub = round(income_rub - expense_rub, 2)

        profitability = round(profit_rub / income_rub * 100, 2) if income_rub > 0 else None

        by_project.append(
            {
                "project_id": pid,
                "project_name": inc_entry.get("project_name") or exp_entry.get("project_name"),
                "income_rub": income_rub,
                "expense_rub": expense_rub,
                "profit_rub": profit_rub,
                "profitability_percent": profitability,
            }
        )

        grand_income = round(grand_income + income_rub, 2)
        grand_expense = round(grand_expense + expense_rub, 2)

    grand_profit = round(grand_income - grand_expense, 2)
    grand_profitability = round(grand_profit / grand_income * 100, 2) if grand_income > 0 else None

    return {
        "date_from": date_from,
        "date_to": date_to,
        "grand_income_rub": grand_income,
        "grand_expense_rub": grand_expense,
        "grand_profit_rub": grand_profit,
        "grand_profitability_percent": grand_profitability,
        "by_project": by_project,
    }


async def count_transactions(
    *,
    type: str | None = None,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Считает транзакции по фильтрам, без выборки записей."""
    params: dict[str, Any] = {"page": 1, "per_page": 1}
    for key, value in (
        ("type", type),
        ("project_id", project_id),
        ("date_from", date_from),
        ("date_to", date_to),
    ):
        if value is not None:
            params[key] = value

    data = await _get("/api/v1/transactions", params=params)
    total = data.get("total") if isinstance(data, dict) else None
    return {
        "count": int(total) if total is not None else 0,
        "project_id": project_id,
        "date_from": date_from,
        "date_to": date_to,
        "type": type,
    }


async def dispatch(intent: str, params: dict[str, Any] | None = None) -> Any:
    """
    Роутер по intent → нужный tool.
    """
    params = params or {}

    match intent:
        case "summary":
            allowed = {"date_from", "date_to"}
            kwargs = {k: v for k, v in params.items() if k in allowed}
            return await get_summary(**kwargs)

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

        case "profit":
            allowed = {"date_from", "date_to", "project_id"}
            kwargs = {k: v for k, v in params.items() if k in allowed}
            return await aggregate_profit(**kwargs)

        case "aggregate":
            allowed = {"type", "date_from", "date_to", "project_id"}
            kwargs = {k: v for k, v in params.items() if k in allowed}
            return await aggregate_transactions(**kwargs)

        case "count":
            allowed = {"type", "project_id", "date_from", "date_to"}
            kwargs = {k: v for k, v in params.items() if k in allowed}
            return await count_transactions(**kwargs)

        case _:
            raise MainAPIError(f"Неизвестный intent: {intent!r}")

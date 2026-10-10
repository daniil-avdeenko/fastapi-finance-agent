"""
Узлы графа агента.

Каждый узел — async-функция, принимает AgentState, возвращает dict.
Поток: understand → query_data → format_answer.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.agent.formatters import (
    _extract_json,
    _format_aggregate_plain,
    _format_compare_plain,
    _format_profit_plain,
    _format_profitability_plain,
    _format_top_projects_plain,
    _format_transactions_plain,
    _humanize_error,
    _period_or_all_time,
    format_numbers,
)
from app.agent.llm.factory import get_llm
from app.agent.prompts import FORMAT_SYSTEM_PROMPT, UNDERSTAND_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tools import MainAPIError, dispatch

logger = logging.getLogger(__name__)


async def understand_node(state: AgentState) -> dict[str, Any]:
    """LLM разбирает вопрос → intent + params, учитывая историю."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    system = UNDERSTAND_SYSTEM_PROMPT.replace("{today}", today)

    history = state.get("history") or []
    if history:
        lines = ["ИСТОРИЯ ДИАЛОГА (последние вопросы):"]
        for turn in history:
            turn_intent = turn.get("intent") or "unknown"
            turn_params = json.dumps(turn.get("params") or {}, ensure_ascii=False)
            lines.append(f"- Q: {turn['question']}")
            lines.append(f"  intent: {turn_intent}, params: {turn_params}")
        lines.append("")
        lines.append(
            "Если новый вопрос ссылается на предыдущие («тот же», «такой же», "
            "«а прибыль?», «а за май?», «а рентабельность?») — подставь intent "
            "и params из подходящего хода истории. Если явно меняется только "
            "дата или тип — измени только их, остальное бери из контекста."
        )
        system += "\n\n" + "\n".join(lines)

    try:
        llm = get_llm()
        raw = await llm.chat(system, state["question"])
    except Exception as exc:
        logger.exception("understand_node failed")
        return {"intent": "unknown", "params": {}, "error": f"LLM error: {exc}"}

    parsed = _extract_json(raw)
    intent = parsed.get("intent", "unknown")
    params = parsed.get("params", {})

    if not isinstance(params, dict):
        params = {}

    return {"intent": intent, "params": params}


async def query_data_node(state: AgentState) -> dict[str, Any]:
    """Вызывает нужный tool по intent. Ошибки пишет в state.error."""
    if state.get("error"):
        return {"data": None}

    intent = state.get("intent", "unknown")
    if intent == "unknown":
        return {"data": None, "error": None}

    params = state.get("params", {})

    try:
        data = await dispatch(intent, params)
    except MainAPIError as exc:
        logger.warning("query_data: %s", exc)
        return {"data": None, "error": str(exc)}
    except Exception as exc:
        logger.exception("query_data: unexpected error")
        return {"data": None, "error": f"Внутренняя ошибка: {exc}"}

    return {"data": data, "error": None}


async def format_answer_node(state: AgentState) -> dict[str, Any]:
    """LLM превращает JSON-данные в человеческий текст. При error — без LLM."""
    error = state.get("error")
    if error:
        msg = error.rstrip(".!?")
        if "не найден" in msg.lower():
            return {"answer": f"{msg}."}
        humanized = _humanize_error(msg)
        if humanized:
            return {"answer": humanized}
        return {"answer": f"Не удалось получить данные: {msg}. Попробуйте позже."}

    intent = state.get("intent")

    if intent == "transactions":
        formatted = _format_transactions_plain(state.get("data"), state.get("params") or {})
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if intent == "top_n":
        formatted = _format_top_projects_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if intent == "profit":
        formatted = _format_profit_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if intent == "profitability":
        formatted = _format_profitability_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if intent == "aggregate":
        formatted = _format_aggregate_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if intent == "compare":
        formatted = _format_compare_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if intent == "count":
        data = state.get("data") or {}
        count = data.get("count", 0)
        parts: list[str] = []
        if data.get("project_id"):
            parts.append(f"по проекту {data['project_id']}")
        if data.get("type") == "income":
            parts.append("доходных")
        elif data.get("type") == "expense":
            parts.append("расходных")
        period = _period_or_all_time(data.get("date_from") or "", data.get("date_to") or "")
        if period:
            parts.append(period)
        suffix = f" ({', '.join(parts)})" if parts else ""
        return {"answer": f"Транзакций: {count}{suffix}."}

    # Явный «не понял» вместо попытки пересказать пустые данные.
    if intent == "unknown":
        return {
            "answer": (
                "Не понял вопрос. Я умею: сводка по финансам, список проектов, "
                "детали проекта, транзакции с фильтрами, суммы за период, "
                "прибыль и рентабельность, курсы валют.\n\n"
                "Например: «Прибыль по проектам за август» или "
                "«Суммарный доход за май»."
            )
        }

    llm = get_llm()
    user = (
        f"Вопрос пользователя: {state['question']}\n\n"
        f"Данные:\n{json.dumps(state.get('data'), ensure_ascii=False, indent=2)}"
    )

    try:
        answer = await llm.chat(FORMAT_SYSTEM_PROMPT, user)
    except Exception as exc:
        logger.exception("format_answer_node failed")
        humanized = _humanize_error(str(exc))
        if humanized:
            return {"answer": humanized}
        return {"answer": "Ошибка генерации ответа. Попробуйте позже."}

    return {"answer": format_numbers(answer)}

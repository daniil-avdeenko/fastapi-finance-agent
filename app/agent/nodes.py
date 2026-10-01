"""
Узлы графа агента.

Каждый узел — async-функция, принимает AgentState, возвращает dict с обновлениями.
LangGraph мерджит обновления в общий state. Поток: understand → query_data → format_answer.
"""

import json
import logging
from typing import Any

from app.agent.llm.factory import get_llm
from app.agent.state import AgentState
from app.agent.tools import MainAPIError, dispatch

logger = logging.getLogger(__name__)


UNDERSTAND_SYSTEM_PROMPT = """Ты — классификатор вопросов к финансовой системе компании.

Проанализируй вопрос пользователя и верни JSON:
{
  "intent": "<один из списка>",
  "params": { ... }
}

Доступные intent:
- "summary" — общая сводка по финансам (доходы, расходы, прибыль, рентабельность)
- "projects" — список всех проектов
- "project_detail" — детали одного проекта (обязательно params.project_id)
- "transactions" — список транзакций, params могут содержать:
    type ("income" | "expense"), project_id (int),
    date_from / date_to ("YYYY-MM-DD"), page (int), per_page (int)
- "currencies" — курсы валют ЦБ
- "unknown" — вопрос не относится к финансам проектов

Правила:
- Отвечай ТОЛЬКО валидным JSON, без markdown-обёрток и пояснений.
- Если параметр не указан в вопросе — не добавляй его в params.
- Если вопрос непонятен или не о финансах — верни {"intent": "unknown", "params": {}}.
"""


FORMAT_SYSTEM_PROMPT = """Ты — финансовый ассистент.

Тебе дают вопрос и JSON с данными. Сформулируй ответ на русском языке.

ЖЁСТКИЕ ПРАВИЛА:
- Используй ТОЛЬКО числа и текст из JSON. Ни одного числа, которого там нет.
- Валюту указывай ровно так, как в JSON (руб./₽, не доллары, если в JSON рубли).
- Не добавляй пояснений, рассуждений, извинений и предложений «помочь дальше».
- Не упоминай JSON, API, поля, ids, названия эндпоинтов.
- Если данных для ответа нет — скажи «В данных нет информации» и остановись.
- Максимум 5 предложений или короткий список. Без вступлений.
"""


def _extract_json(raw: str) -> dict[str, Any]:
    """
    Достаёт JSON из ответа LLM.
    """
    raw = raw.strip()

    # Случай 1: чистый JSON
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Случай 2: markdown-обёртка или текст вокруг JSON
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return {}


async def understand_node(state: AgentState) -> dict[str, Any]:
    """LLM разбирает вопрос → intent + params."""
    try:
        llm = get_llm()
        raw = await llm.chat(UNDERSTAND_SYSTEM_PROMPT, state["question"])
    except Exception as exc:
        # Ловим всё: любая ошибка LLM (сеть, 429, 5xx) не должна ронять граф.
        # В state.error кладём текст, format_answer_node вернёт его пользователю.
        logger.exception("understand_node failed")
        return {"intent": "unknown", "params": {}, "error": f"LLM error: {exc}"}

    parsed = _extract_json(raw)
    intent = parsed.get("intent", "unknown")
    params = parsed.get("params", {})

    if not isinstance(params, dict):
        params = {}

    logger.info("understand: intent=%s params=%s", intent, params)
    return {"intent": intent, "params": params}


async def query_data_node(state: AgentState) -> dict[str, Any]:
    """Вызывает нужный tool по intent. Ошибки пишет в state.error."""
    # Если understand уже упал — не дёргаем API, сохраняем исходную ошибку.
    if state.get("error"):
        return {"data": None}

    intent = state.get("intent", "unknown")
    params = state.get("params", {})

    try:
        data = await dispatch(intent, params)
    except MainAPIError as exc:
        logger.warning("query_data failed: %s", exc)
        return {"data": None, "error": str(exc)}

    return {"data": data, "error": None}


async def format_answer_node(state: AgentState) -> dict[str, Any]:
    """LLM превращает JSON-данные в человеческий текст. При error — без LLM."""
    if state.get("error"):
        return {"answer": f"Не удалось получить данные: {state['error']}. Попробуйте позже."}

    llm = get_llm()
    user = (
        f"Вопрос пользователя: {state['question']}\n\n"
        f"Данные:\n{json.dumps(state.get('data'), ensure_ascii=False, indent=2)}"
    )

    try:
        answer = await llm.chat(FORMAT_SYSTEM_PROMPT, user)
    except Exception as exc:
        logger.exception("format_answer_node failed")
        return {"answer": f"Ошибка генерации ответа: {exc}. Попробуйте позже."}

    return {"answer": answer}

"""
Узлы графа агента.

Каждый узел — async-функция, принимает AgentState, возвращает dict с обновлениями.
LangGraph мерджит обновления в общий state. Поток: understand → query_data → format_answer.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.agent.llm.factory import get_llm
from app.agent.state import AgentState
from app.agent.tools import MainAPIError, dispatch

logger = logging.getLogger(__name__)


UNDERSTAND_SYSTEM_PROMPT = """Ты — классификатор вопросов к финансовой системе компании.
Проанализируй вопрос пользователя и верни JSON:
{"intent": "<название>", "params": { ... }}

Сегодняшняя дата: {today}
Используй её для относительных дат: "за май" → 2026-05-01..2026-05-31,
"за прошлый месяц" → предыдущий календарный месяц, "за квартал" → 3 месяца.

Доступные intent:

- "summary" — общая сводка по финансам (доходы, расходы, прибыль, рентабельность).
  params: {}.

- "projects" — список всех проектов.
  params: {}.

- "project_detail" — детали одного проекта.
  params: {"project_id": int} — обязателен.

- "transactions" — список транзакций (без агрегации).
  params: type ("income"|"expense"), project_id (int),
  date_from, date_to ("YYYY-MM-DD"), page (int), per_page (int).

- "aggregate" — сумма транзакций за период, сгруппированная по проектам.
  Используй, если вопрос содержит: "суммарный", "итого", "просуммируй",
  "сколько всего", "общая сумма", "всего за период".
  params: type ("income"|"expense"), date_from, date_to ("YYYY-MM-DD"),
  project_id (int, опционально).

- "currencies" — курсы валют на текущую дату.
  params: {}.

- "unknown" — вопрос не относится к финансам проектов.

ПРАВИЛА:
- Отвечай ТОЛЬКО валидным JSON, без markdown-обёрток и пояснений.
- Если параметр не указан явно — не включай его в params.
- Даты всегда в формате YYYY-MM-DD. Месяц — с 1-го по последний день включительно.
- Если вопрос про сумму/итог — это "aggregate", не "transactions".
- Если вопрос непонятен или не о финансах — {"intent": "unknown", "params": {}}.

ПРИМЕРЫ:

"summary" → {"intent": "summary", "params": {}}
"Как дела с финансами?" → {"intent": "summary", "params": {}}
"Сколько проектов?" → {"intent": "projects", "params": {}}
"Детали проекта 3" → {"intent": "project_detail", "params": {"project_id": 3}}
"Транзакции за март" → {"intent": "transactions", "params": {"date_from": "2026-03-01", "date_to": "2026-03-31"}}
"Расходы проекта 1 за август" → {"intent": "transactions", "params": {"type": "expense", "project_id": 1, "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Суммарный доход за май 2026" → {"intent": "aggregate", "params": {"type": "income", "date_from": "2026-05-01", "date_to": "2026-05-31"}}
"Просуммируй расходы по всем проектам за август" → {"intent": "aggregate", "params": {"type": "expense", "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Курсы валют" → {"intent": "currencies", "params": {}}
"Какая погода?" → {"intent": "unknown", "params": {}}
"""


FORMAT_SYSTEM_PROMPT = """Ты — финансовый ассистент.

Тебе дают вопрос и JSON с данными. Сформулируй ответ на русском языке.

ЖЁСТКИЕ ПРАВИЛА:
- Используй ТОЛЬКО числа и текст из JSON. Ни одного числа, которого там нет.
- Валюту указывай ровно так, как в JSON.
- Если в JSON есть поля grand_total_by_currency или totals_by_currency —
  пересказывай ИХ. Не складывай числа сам.
- Если в JSON есть by_project — покажи разбивку по проектам.
- Не добавляй пояснений, рассуждений, извинений, предложений «помочь дальше».
- Не упоминай JSON, API, поля, ids, названия эндпоинтов.
- Если данных нет — скажи «В данных нет информации» и остановись.
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
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    system = UNDERSTAND_SYSTEM_PROMPT.replace("{today}", today)

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

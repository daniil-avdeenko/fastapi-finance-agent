"""
Узлы графа агента.

Каждый узел — async-функция, принимает AgentState, возвращает dict с обновлениями.
LangGraph мерджит обновления в общий state. Поток: understand → query_data → format_answer.
"""

import json
import logging
import re
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

- "summary" — общая сводка по финансам за период (доходы, расходы,
  прибыль, рентабельность).
  params: date_from, date_to ("YYYY-MM-DD", опционально).

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

- "profit" — прибыль (доходы минус расходы) по проектам за период.
  Используй, если вопрос содержит: "прибыль", "profit", "маржа", "рентабельность",
  "чистая прибыль", "выручка минус расходы".
  params: date_from, date_to ("YYYY-MM-DD"), project_id (int, опционально).

- "unknown" — вопрос не относится к финансам проектов.

ПРАВИЛА:
- Отвечай ТОЛЬКО валидным JSON, без markdown-обёрток и пояснений.
- Если параметр не указан явно И нет подходящего хода в истории — не включай
  его в params. Если вопрос ссылается на предыдущий — переноси параметры
  оттуда, даже если в новом вопросе они не названы.
- Даты всегда в формате YYYY-MM-DD. Месяц — с 1-го по последний день включительно.
- Если вопрос про сумму/итог — это "aggregate", не "transactions".
- Если вопрос непонятен или не о финансах — {"intent": "unknown", "params": {}}.
- Если вопрос ссылается на предыдущий («а в июне?», «а прибыль?», «а тот же
  проект?», «а рентабельность?») — бери ВСЕ params из последнего подходящего
  хода истории и переопределяй только те, что явно меняются в новом вопросе.
  Пример:
  История: [{question: "Проект 1 какая прибыль в мае?",
           intent: "profit",
           params: {project_id: 1, date_from: "2026-05-01", date_to: "2026-05-31"}}]
  Новый вопрос: "А в июне?"
  → {"intent": "profit", "params": {project_id: 1, date_from: "2026-06-01", "date_to": "2026-06-30"}}
   (project_id сохранён из истории, даты изменены)
- Если предыдущий вопрос был про конкретный проект (project_detail,
  aggregate/profit/transactions с project_id) и новый вопрос НЕ называет
  другой проект явно и НЕ говорит «по всем», «везде», «в целом» — сохраняй
  project_id из предыдущего хода.
  Пример:
    История: «Скинь всю информацию по проекту 5» → project_detail, {project_id: 5}
    Новый: «Какой доход был в марте?»
    → {"intent": "aggregate", "params": {"type": "income", "project_id": 5,
        "date_from": "2026-03-01", "date_to": "2026-03-31"}}
- Если вопрос ссылается на предыдущий и НЕ вводит новое действие
  («прибыль», «доход», «расход», «сводка», «список», «курсы») — сохраняй
  intent предыдущего хода, как и project_id.
  Пример:
    История: «Перечисли транзакции по проекту 1 за август» →
      transactions, {project_id: 1, date_from: "2026-08-01", date_to: "2026-08-31"}
    Новый: «А по проекту 3?»
    → {"intent": "transactions", "params": {"project_id": 3,
        "date_from": "2026-08-01", "date_to": "2026-08-31"}}
    (intent и даты сохранены, project_id заменён)

ПРИМЕРЫ:

"Сводка за август" → {"intent": "summary", "params": {"date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Как дела с финансами?" → {"intent": "summary", "params": {}}
"Сколько проектов?" → {"intent": "projects", "params": {}}
"Детали проекта 3" → {"intent": "project_detail", "params": {"project_id": 3}}
"Транзакции за март" → {"intent": "transactions", "params": {"date_from": "2026-03-01", "date_to": "2026-03-31"}}
"Расходы проекта 1 за август" → {"intent": "transactions", "params": {"type": "expense", "project_id": 1, "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Суммарный доход за май 2026" → {"intent": "aggregate", "params": {"type": "income", "date_from": "2026-05-01", "date_to": "2026-05-31"}}
"Просуммируй расходы по всем проектам за август" → {"intent": "aggregate", "params": {"type": "expense", "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Курсы валют" → {"intent": "currencies", "params": {}}
"Прибыль за август" → {"intent": "profit", "params": {"date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Прибыль по проектам за май" → {"intent": "profit", "params": {"date_from": "2026-05-01", "date_to": "2026-05-31"}}
"Какая погода?" → {"intent": "unknown", "params": {}}
"""


FORMAT_SYSTEM_PROMPT = """Ты — финансовый ассистент.

Тебе дают вопрос и JSON с данными. Сформулируй ответ на русском языке.

ЖЁСТКИЕ ПРАВИЛА:
- Используй ТОЛЬКО числа и текст из JSON. Ни одного числа, которого там нет.
- Все суммы уже в рублях (поля *_rub). Не конвертируй.
- Валюту указывай только символом ₽ после числа. Не пиши "RUB", "руб.", "рублей".
- Если в by_project ровно одна запись — не выводи grand_total_rub или
  grand_profit_rub отдельной строкой, покажи только цифры этого проекта.
- Если в by_project больше одной записи — сначала итог (grand_*), потом
  маркированный список по проектам.
- Никогда не повторяй одно и то же число дважды. Если grand_* совпадает
  с единственной записью by_project — выведи один раз.
- Если ответ — агрегат или отчёт по проекту, начинай с названия проекта
  и периода: «Проект X за август 2026: …».
- Если ответ предполагает перечисление нескольких параметров, делай
  маркированный список.
- Период указывай человеческим языком: «за август 2026», «за май 2026»,
  «за 2026 год». Не выводи ISO-даты (2026-08-01) и не пиши диапазоны.
- Если profit_rub отрицательный — покажи как минус: «−1 234 ₽».
- Если profitability_percent равен null или отсутствует — не упоминай
  рентабельность вовсе. Не пиши «0%» или «нет данных» вместо неё.
- Не дублируй вложенные кавычки в названии проектов. Если название само
  содержит «...», внешние кавычки не ставь.
- Если в JSON есть поле items (список транзакций):
  • Выведи маркированный список.
  • Для каждой записи бери поля СТРОГО из этой же записи:
      type           → «Доход» или «Расход»
      category_name  → категория (только category_name, НЕ description)
      amount_rub     → сумма
  • Не переноси поля из соседних записей. Не склеивай type, category_name
    и amount_rub из разных записей одного items.
  • Поле description — это примечание. Не выводи его.
  • Пример: «Доход: Консультационные услуги — 1 247 062,51 ₽»
- Если items содержит больше 15 записей — выведи первые 15 и напиши
  «и ещё N записей». Не выводи итоги, прибыль и рентабельность —
  пользователь просил список.
- Не добавляй пояснений, рассуждений, извинений, предложений «помочь дальше».
- Не упоминай JSON, API, поля, ids, названия эндпоинтов.
- Если данных нет — скажи «В данных нет информации» и остановись.
- Максимум 5 предложений или короткий список. Без вступлений.
"""


_NUMBER_GROUPING_RE = re.compile(r"(?<=\d)\s(?=\d{3}(?!\d))")
_NUMBER_RE = re.compile(r"(?<![\d.])(\d{4,})([.,]\d+)?(?!\d)")


def format_numbers(text: str) -> str:
    """
    Приводит числа в тексте к виду '1 234 567.89'.

    - Убирает .0 / ,0 у целых (1234.0 → 1 234).
    - Схлопывает уже расставленные пробелы перед форматированием
      (14 450 744.0 → 14 450 744), чтобы работать с идемпотентным входом.
    - Годы 1900–2100 не трогает.
    """
    text = _NUMBER_GROUPING_RE.sub("", text)

    def repl(match: re.Match[str]) -> str:
        int_part = match.group(1)
        frac = match.group(2) or ""
        value = int(int_part)

        if not frac and 1900 <= value <= 2100:
            return match.group(0)

        if frac and float(frac.replace(",", ".")) == 0:
            frac = ""

        grouped = f"{value:,}".replace(",", " ")
        return f"{grouped}{frac}"

    return _NUMBER_RE.sub(repl, text)


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


_MONTH_NAMES = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]


def _human_date(iso: str) -> str:
    """'2026-08-15' → '15.08.2026'."""
    try:
        year, month, day = iso[:10].split("-")
        return f"{day}.{month}.{year}"
    except (ValueError, AttributeError):
        return iso


def _human_period(date_from: str, date_to: str) -> str:
    """
    Период в читаемом виде.

    Если диапазон покрывает месяц целиком (с 1-го по 28+ число) —
    «август 2026». Иначе — «с 15.08.2026 по 20.08.2026».
    """
    if not date_from and not date_to:
        return ""
    if not date_from:
        return f"по {_human_date(date_to)}"
    if not date_to:
        return f"с {_human_date(date_from)}"

    ym_from = date_from[:7]
    ym_to = date_to[:7]

    is_full_month = (
        ym_from == ym_to
        and date_from[-2:] == "01"
        and date_to[-2:].isdigit()
        and int(date_to[-2:]) >= 28
    )

    if is_full_month:
        try:
            year, month = ym_from.split("-")
            idx = int(month) - 1
            if 0 <= idx < 12:
                return f"{_MONTH_NAMES[idx]} {year}"
        except (ValueError, AttributeError):
            pass

    return f"с {_human_date(date_from)} по {_human_date(date_to)}"


def _format_transactions_plain(data: Any, params: dict[str, Any]) -> str | None:
    """
    Собирает ответ для intent='transactions' без LLM.
    """
    if not isinstance(data, dict):
        return None

    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None

    project_name = items[0].get("project_name") or ""
    period = _human_period(
        params.get("date_from") or "",
        params.get("date_to") or "",
    )

    header_parts: list[str] = []
    if project_name:
        header_parts.append(project_name)
    if period:
        header_parts.append(period)

    if len(header_parts) == 2:
        lines = [f"{header_parts[0]}, {header_parts[1]}:", ""]
    elif header_parts:
        lines = [f"{header_parts[0]}:", ""]
    else:
        lines = ["Транзакции:", ""]

    shown = items[:15]
    for tx in shown:
        tx_type = "Доход" if tx.get("type") == "income" else "Расход"
        category = tx.get("category_name") or "—"
        amount = tx.get("amount_rub")
        if amount is None:
            amount = tx.get("amount")
        amount_str = f"{amount}" if amount is not None else "—"

        tx_date = (tx.get("date") or "")[:10]
        date_prefix = f"{_human_date(tx_date)} — " if tx_date else ""
        lines.append(f"• {date_prefix}{tx_type}: {category} — {amount_str} ₽")

    if len(items) > len(shown):
        lines.append("")
        lines.append(f"и ещё {len(items) - len(shown)} записей.")

    return format_numbers("\n".join(lines))


async def understand_node(state: AgentState) -> dict[str, Any]:
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
    if state.get("error"):
        return {"answer": f"Не удалось получить данные: {state['error']}. Попробуйте позже."}

    if state.get("intent") == "transactions":
        formatted = _format_transactions_plain(state.get("data"), state.get("params") or {})
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    # Явный «не понял» вместо попытки пересказать пустые данные.
    if state.get("intent") == "unknown":
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
        return {"answer": f"Ошибка генерации ответа: {exc}. Попробуйте позже."}

    return {"answer": format_numbers(answer)}

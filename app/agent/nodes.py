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

- "count" — количество транзакций (не сумма).
  Используй для вопросов «сколько транзакций», «сколько операций».
  params: type, project_id, date_from, date_to ("YYYY-MM-DD").

- "aggregate" — сумма транзакций за период, сгруппированная по проектам.
  Используй, если вопрос содержит: "суммарный", "итого", "просуммируй",
  "сколько всего", "общая сумма", "всего за период", "доходы", "расходы".
  params: type ("income"|"expense"), date_from, date_to ("YYYY-MM-DD"),
  project_id (int, опционально).

- "currencies" — курсы валют на текущую дату.
  params: {}.

- "profit" — прибыль (доходы минус расходы) по проектам за период.
  Используй, если вопрос содержит: "прибыль", "profit", "маржа",
  "чистая прибыль", "выручка минус расходы".
  params: date_from, date_to ("YYYY-MM-DD"), project_id (int, опционально).

- "profitability" — рентабельность проектов в процентах, без денежных
  показателей.
  Используй, если вопрос содержит ТОЛЬКО "рентабельность" или "маржа"
  без упоминания прибыли, дохода, расхода. Если упоминается и прибыль,
  и рентабельность — это "profit".
  params: date_from, date_to ("YYYY-MM-DD"), project_id (int, опционально).

- "top_n" — топ N проектов по метрике за период.
  Используй, если вопрос содержит: "топ", "топ-N", "лучшие",
  "самые прибыльные", "наибольшая прибыль", "лидеры".
  params: n (int, опционально — если не указано, вернём все проекты),
  metric ("profit" | "income" | "profitability", по умолчанию "profit"),
  date_from, date_to ("YYYY-MM-DD").

- "compare" — сравнение двух периодов по метрике.
  Используй для вопросов: "сравни", "динамика", "как изменилось",
  "что выросло", "больше/меньше чем".
  params: metric ("profit"|"income"|"expense"|"profitability",
  по умолчанию "profit"), period1_from, period1_to, period2_from,
  period2_to ("YYYY-MM-DD"), project_id (int, опционально).
  period1 — БАЗА, period2 — то, с чем сравниваем, обычно более поздний.

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
- Если новый вопрос меняет ТОЛЬКО даты («а за 15–20 августа», «а за июль»),
  и предыдущий ход был про конкретный проект — сохраняй project_id и intent.
  Пример:
    История: «Транзакции по проекту 2 за август» →
      transactions, {project_id: 2, date_from: "2026-08-01", date_to: "2026-08-31"}
    Новый: «Транзакции за 15–20 августа»
    → {"intent": "transactions", "params": {"project_id": 2,
        "date_from": "2026-08-15", "date_to": "2026-08-20"}}

ПРИМЕРЫ:

"Сводка за август" → {"intent": "summary", "params": {"date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Как дела с финансами?" → {"intent": "summary", "params": {}}
"Сколько проектов?" → {"intent": "projects", "params": {}}
"Детали проекта 3" → {"intent": "project_detail", "params": {"project_id": 3}}
"Транзакции за март" → {"intent": "transactions", "params": {"date_from": "2026-03-01", "date_to": "2026-03-31"}}
"Расходы проекта 1 за август" → {"intent": "transactions", "params": {"type": "expense", "project_id": 1, "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Суммарный доход за май 2026" → {"intent": "aggregate", "params": {"type": "income", "date_from": "2026-05-01", "date_to": "2026-05-31"}}
"Доходы по проектам за июль" → {"intent": "aggregate", "params": {"type": "income", "date_from": "2026-07-01", "date_to": "2026-07-31"}}
"Просуммируй расходы по всем проектам за август" → {"intent": "aggregate", "params": {"type": "expense", "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Курсы валют" → {"intent": "currencies", "params": {}}
"Прибыль за август" → {"intent": "profit", "params": {"date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Прибыль по проектам за май" → {"intent": "profit", "params": {"date_from": "2026-05-01", "date_to": "2026-05-31"}}
"Рентабельность за июнь" → {"intent": "profitability", "params": {"date_from": "2026-06-01", "date_to": "2026-06-30"}}
"Рентабельность проектов за май" → {"intent": "profitability", "params": {"date_from": "2026-05-01", "date_to": "2026-05-31"}}
"Какая погода?" → {"intent": "unknown", "params": {}}
"Сколько транзакций в августе по проекту 1" → {"intent": "count", "params": {"project_id": 1, "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Топ-3 проекта по прибыли за август" → {"intent": "top_n", "params": {"n": 3, "metric": "profit", "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Самые прибыльные проекты за май" → {"intent": "top_n", "params": {"metric": "profit", "date_from": "2026-05-01", "date_to": "2026-05-31"}}
"Топ-5 по доходу за август" → {"intent": "top_n", "params": {"n": 5, "metric": "income", "date_from": "2026-08-01", "date_to": "2026-08-31"}}
"Сравни прибыль за май и июнь" → {"intent": "compare", "params": {"metric": "profit", "period1_from": "2026-05-01", "period1_to": "2026-05-31", "period2_from": "2026-06-01", "period2_to": "2026-06-30"}}
"Как изменился доход в августе по сравнению с июлем" → {"intent": "compare", "params": {"metric": "income", "period1_from": "2026-07-01", "period1_to": "2026-07-31", "period2_from": "2026-08-01", "period2_to": "2026-08-31"}}
"Динамика расходов за квартал" → {"intent": "compare", "params": {"metric": "expense", "period1_from": "2026-07-01", "period1_to": "2026-07-31", "period2_from": "2026-08-01", "period2_to": "2026-09-30"}}
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
  - Если период не указан — пиши «за всё время», не «за весь период».
- Если profit_rub отрицательный — покажи как минус: «−1 234 ₽».
- Если profitability_percent равен null или отсутствует — не упоминай
  рентабельность вовсе. Не пиши «0%» или «нет данных» вместо неё.
- Не дублируй вложенные кавычки в названии проектов. Если название само
  содержит «...», внешние кавычки не ставь.
- Всегда указывай точное название проекта, а не его номер или ID.
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
  - Если в JSON несколько скалярных полей верхнего уровня
  (total_income, total_expense, total_profit, overall_profitability,
  grand_income_rub, grand_expense_rub, grand_profit_rub,
  grand_profitability_percent) — выводи их маркированным списком, а не
  одной строкой.
  Пример:
  Итоги за август 2026:
  • Доход: 20 154 503,77 ₽
  • Расход: 15 567 710,78 ₽
  • Прибыль: 4 586 792,99 ₽
  • Рентабельность: 22,76%
- Для маркированных списков используй символ «•». Не используй «*» и «-».
- Не добавляй пояснений, рассуждений, извинений, предложений «помочь дальше».
- Не упоминай JSON, API, поля, ids, названия эндпоинтов.
- Если данных нет — скажи «В данных нет информации» и остановись.
- Максимум 5 предложений или короткий список. Без вступлений.
"""


# 37,9% → 37,90%; 22,756% → 22,76%
_PERCENT_RE = re.compile(r"(\d+)[.,](\d+)%")

# Десятичная точка перед символом валюты или процента → запятая.
# Русский формат: 2 056 081,06 ₽ вместо 2 056 081.06 ₽.
_DECIMAL_DOT_RE = re.compile(r"(\d)\.(\d+)(?=\s*(?:[₽%]|пп))")

# ,0+ или .0+ перед ₽/% — незначащий хвост, убираем.
_DECIMAL_ZERO_RE = re.compile(r"(\d)[.,]0+(?=\s*[₽%])")

# Одна цифра в дробной части перед ₽ → добавляем ноль: 2 363 822,1 ₽ → 2 363 822,10 ₽
_MONEY_FRAC_RE = re.compile(r"(\d)[.,](\d)(?=\s*₽)")


def _fix_percent(match: re.Match[str]) -> str:
    whole = match.group(1)
    frac = match.group(2)
    if len(frac) == 1:
        frac += "0"
    elif len(frac) > 2:
        value = round(float(f"{whole}.{frac}"), 2)
        int_part, _, frac_part = f"{value:.2f}".partition(".")
        return f"{int_part},{frac_part}%"
    return f"{whole},{frac}%"


_NUMBER_GROUPING_RE = re.compile(r"(?<=\d)\s(?=\d{3}(?!\d))")
_NUMBER_RE = re.compile(r"(?<![\d.,])(\d{4,})([.,]\d+)?(?!\d)")


def format_numbers(text: str) -> str:
    """
    Приводит числа в тексте к виду '1 234 567,89'.

    - Разделители тысяч — пробелы.
    - Десятичный разделитель перед ₽ или % — запятая.
    - Дополняет до двух знаков: 100,5 ₽ → 100,50 ₽.
    - Убирает незначащий хвост ,0.
    - Схлопывает уже расставленные пробелы перед форматированием.
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

    text = _PERCENT_RE.sub(_fix_percent, text)
    text = _NUMBER_RE.sub(repl, text)
    text = _DECIMAL_DOT_RE.sub(r"\1,\2", text)
    text = _DECIMAL_ZERO_RE.sub(r"\1", text)
    text = _MONEY_FRAC_RE.sub(r"\1,\g<2>0", text)
    return text


def _extract_json(raw: str) -> dict[str, Any]:
    """Достаёт JSON из ответа LLM."""
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

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

_METRIC_LABELS = {
    "profit": "прибыль",
    "income": "доход",
    "profitability": "рентабельность",
}

_METRIC_LABELS_ABOUT = {
    "profit": "прибыли",
    "income": "доходу",
    "profitability": "рентабельности",
}

_METRIC_LABELS_COMPARE = {
    "profit": "прибыли",
    "income": "дохода",
    "expense": "расходов",
    "profitability": "рентабельности",
}


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


def _period_or_all_time(date_from: str, date_to: str) -> str:
    """
    Период или 'за всё время', если оба параметра пустые.
    """
    period = _human_period(date_from, date_to)
    return period if period else "всё время"


def _pluralize_transactions(n: int) -> str:
    """N транзакций в правильной форме."""
    if 10 <= n % 100 <= 20:
        return "транзакций"
    last = n % 10
    if last == 1:
        return "транзакция"
    if 2 <= last <= 4:
        return "транзакции"
    return "транзакций"


def _pluralize_projects(n: int) -> str:
    """N проектов в правильной форме."""
    if 10 <= n % 100 <= 20:
        return "проектов"
    last = n % 10
    if last == 1:
        return "проект"
    if 2 <= last <= 4:
        return "проекта"
    return "проектов"


def _humanize_error(msg: str) -> str:
    """
    Человеческое сообщение вместо технического об ошибке LLM.

    Возвращает пустую строку, если ошибка не из этой категории —
    вызывающий код решает сам, как её показать.
    """
    lowered = msg.lower()

    # 404 / нет модели.
    if "no such model" in lowered or "404" in msg:
        return "Модель недоступна. Обратитесь к администратору."

    # 403 / гео-ограничение.
    if "403" in msg or "region" in lowered or "geo" in lowered:
        return "Модель временно недоступна. Попробуйте позже."

    # 402 / кредиты.
    if "402" in msg or "credits" in lowered or "in_flight" in lowered:
        return "Сервис LLM временно недоступен. Попробуйте позже."

    # 429 / rate limit.
    if "429" in msg or "rate limit" in lowered:
        return "Слишком много запросов. Попробуйте через минуту."

    # Таймаут
    if any(
        marker in lowered
        for marker in ("readtimeout", "connecttimeout", "timed out", "timeout error")
    ):
        return "Превышено время ожидания LLM. Попробуйте позже."

    return ""


def _format_transactions_plain(data: Any, params: dict[str, Any]) -> str | None:
    """Собирает ответ для intent='transactions' без LLM."""
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


def _format_top_projects_plain(data: Any) -> str | None:
    """Собирает ответ для intent='top_n' без LLM."""
    if not isinstance(data, dict):
        return None

    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None

    metric = data.get("metric", "profit")
    metric_label = _METRIC_LABELS.get(metric, metric)
    metric_about = _METRIC_LABELS_ABOUT.get(metric, metric)
    period = _human_period(data.get("date_from") or "", data.get("date_to") or "")

    header = f"Топ-{len(items)} {_pluralize_projects(len(items))} по {metric_about}"
    if period:
        header += f" за {period}"
    header += ":"

    lines = [header, ""]
    for p in items:
        name = p.get("project_name") or "—"
        value = p.get("metric_value", 0)
        value_str = f"{value}%" if metric == "profitability" else f"{value} ₽"
        lines.append(f"• {name} — {metric_label} {value_str}")

    return format_numbers("\n".join(lines))


def _format_profit_plain(data: Any) -> str | None:
    """
    Собирает ответ для intent='profit' без LLM.
    """
    if not isinstance(data, dict):
        return None

    by_project = data.get("by_project")
    if not isinstance(by_project, list) or not by_project:
        return None

    period = _human_period(data.get("date_from") or "", data.get("date_to") or "")

    if len(by_project) == 1:
        name = by_project[0].get("project_name") or "проект"
        header = f"Проект {name}"
    else:
        header = "Показатели по проектам"
    if period:
        header += f" за {period}"
    header += ":"

    lines = [header, ""]

    grand_income = data.get("grand_income_rub")
    grand_expense = data.get("grand_expense_rub")
    grand_profit = data.get("grand_profit_rub")
    grand_profitability = data.get("grand_profitability_percent")

    if grand_income is not None:
        lines.append(f"• Доход: {grand_income} ₽")
    if grand_expense is not None:
        lines.append(f"• Расход: {grand_expense} ₽")
    if grand_profit is not None:
        lines.append(f"• Прибыль: {grand_profit} ₽")
    if grand_profitability is not None:
        lines.append(f"• Рентабельность: {grand_profitability}%")

    if len(by_project) > 1:
        lines.append("")
        lines.append("Прибыль по проектам:")
        for p in by_project:
            name = p.get("project_name") or "—"
            profit = p.get("profit_rub", 0)
            profitability = p.get("profitability_percent")
            if profitability is not None:
                lines.append(f"• {name} — {profit} ₽ ({profitability}%)")
            else:
                lines.append(f"• {name} — {profit} ₽")

    return format_numbers("\n".join(lines))


def _format_profitability_plain(data: Any) -> str | None:
    """
    Собирает ответ для intent='profitability' без LLM.

    Только проценты, без денежных показателей.
    """
    if not isinstance(data, dict):
        return None

    by_project = data.get("by_project")
    if not isinstance(by_project, list) or not by_project:
        return None

    period = _period_or_all_time(data.get("date_from") or "", data.get("date_to") or "")

    if len(by_project) == 1:
        name = by_project[0].get("project_name") or "проект"
        header = f"Рентабельность проекта {name} за {period}:"

        profitability = by_project[0].get("profitability_percent")
        value_line = f"{profitability}%" if profitability is not None else "нет данных"
        return format_numbers(f"{header}\n\n{value_line}")

    header = f"Рентабельность за {period}:"

    lines = [header, ""]

    grand_profitability = data.get("grand_profitability_percent")
    if grand_profitability is not None:
        lines.append(f"• Общая: {grand_profitability}%")

    lines.append("")
    lines.append("По проектам:")
    for p in by_project:
        name = p.get("project_name") or "—"
        profitability = p.get("profitability_percent")
        if profitability is None:
            lines.append(f"• {name} — нет данных")
        else:
            lines.append(f"• {name} — {profitability}%")

    return format_numbers("\n".join(lines))


def _period_label(date_from: str, date_to: str) -> str:
    """'2026-05-01', '2026-05-31' → 'май 2026' (без предлога 'за')."""
    period = _human_period(date_from, date_to)
    if period.startswith("за "):
        return period[3:]
    return period or "весь период"


def _fmt_number(value: float) -> str:
    """Всегда две цифры после запятой."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _compare_line(
    *,
    label: str,
    v1: float | None,
    v2: float | None,
    diff_abs: float,
    diff_pct: float | None,
    is_percent: bool,
) -> str | None:
    """Форматирует строку сравнения: 'Итого: 100 ₽ → 120 ₽ (+20 ₽, +20%)'."""
    if v1 is None and v2 is None:
        return None

    unit = "%" if is_percent else " ₽"
    v1_str = f"{_fmt_number(v1)}{unit}" if v1 is not None else "—"
    v2_str = f"{_fmt_number(v2)}{unit}" if v2 is not None else "—"

    sign = "+" if diff_abs > 0 else ""
    diff_abs_str = _fmt_number(diff_abs)
    if is_percent:
        diff_str = f"{sign}{diff_abs_str}"
    else:
        diff_str = f"{sign}{diff_abs_str} ₽"
        if diff_pct is not None:
            pct_sign = "+" if diff_pct > 0 else ""
            diff_str += f", {pct_sign}{_fmt_number(diff_pct)}%"

    return f"{label}: {v1_str} → {v2_str} ({diff_str})"


def _format_compare_plain(data: Any) -> str | None:
    """
    Собирает ответ для intent='compare' без LLM.

    Формат: «Сравнение метрики: период1 → период2», строка итога,
    разбивка по проектам (если больше одного).
    """
    if not isinstance(data, dict):
        return None

    metric = data.get("metric", "profit")
    metric_label = _METRIC_LABELS_COMPARE.get(metric, metric)
    is_percent = metric == "profitability"

    p1 = data.get("period1", {}) or {}
    p2 = data.get("period2", {}) or {}
    label1 = _period_label(p1.get("date_from") or "", p1.get("date_to") or "")
    label2 = _period_label(p2.get("date_from") or "", p2.get("date_to") or "")

    lines = [f"Сравнение {metric_label}: {label1} → {label2}", ""]

    grand = data.get("grand", {}) or {}
    grand_line = _compare_line(
        label="Итого",
        v1=grand.get("period1_value"),
        v2=grand.get("period2_value"),
        diff_abs=grand.get("diff_abs", 0),
        diff_pct=grand.get("diff_pct"),
        is_percent=is_percent,
    )
    if grand_line:
        lines.append(f"• {grand_line}")

    by_project = data.get("by_project") or []
    if len(by_project) > 1:
        lines.append("")
        lines.append("По проектам:")
        for p in by_project:
            line = _compare_line(
                label=p.get("project_name") or "—",
                v1=p.get("period1_value"),
                v2=p.get("period2_value"),
                diff_abs=p.get("diff_abs", 0),
                diff_pct=p.get("diff_pct"),
                is_percent=is_percent,
            )
            if line:
                lines.append(f"• {line}")

    return format_numbers("\n".join(lines))


def _format_aggregate_plain(data: Any) -> str | None:
    """
    Собирает ответ для intent='aggregate' без LLM.

    Верхний блок — итог. Нижний — разбивка по проектам.
    """
    if not isinstance(data, dict):
        return None

    by_project = data.get("by_project")
    if not isinstance(by_project, list) or not by_project:
        return None

    type_ = data.get("type")
    type_plural = {"income": "Доходы", "expense": "Расходы"}.get(type_ or "", "Сумма")

    period = _period_or_all_time(data.get("date_from") or "", data.get("date_to") or "")

    if len(by_project) == 1:
        name = by_project[0].get("project_name") or "проект"
        header = f"{type_plural} по проекту {name}"
    else:
        header = type_plural
    if period:
        header += f" за {period}"
    header += ":"

    lines = [header, ""]

    grand_total = data.get("grand_total_rub")
    total_tx = data.get("total_transactions")

    if grand_total is not None:
        line = f"• Всего: {grand_total} ₽"
        if total_tx:
            line += f" ({total_tx} {_pluralize_transactions(total_tx)})"
        lines.append(line)

    if len(by_project) > 1:
        lines.append("")
        lines.append(f"{type_plural} по проектам:")
        for p in by_project:
            name = p.get("project_name") or "—"
            total = p.get("total_rub", 0)
            count = p.get("count")
            line = f"• {name} — {total} ₽"
            if count:
                line += f" ({count} {_pluralize_transactions(count)})"
            lines.append(line)

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
    error = state.get("error")
    if error:
        msg = error.rstrip(".!?")
        if "не найден" in msg.lower():
            return {"answer": f"{msg}."}
        humanized = _humanize_error(msg)
        if humanized:
            return {"answer": humanized}
        return {"answer": f"Не удалось получить данные: {msg}. Попробуйте позже."}

    if state.get("intent") == "transactions":
        formatted = _format_transactions_plain(state.get("data"), state.get("params") or {})
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if state.get("intent") == "top_n":
        formatted = _format_top_projects_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if state.get("intent") == "profit":
        formatted = _format_profit_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if state.get("intent") == "profitability":
        formatted = _format_profitability_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if state.get("intent") == "aggregate":
        formatted = _format_aggregate_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if state.get("intent") == "compare":
        formatted = _format_compare_plain(state.get("data"))
        if formatted is not None:
            return {"answer": formatted}
        return {"answer": "В данных нет информации."}

    if state.get("intent") == "count":
        data = state.get("data") or {}
        count = data.get("count", 0)
        parts = []
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
        humanized = _humanize_error(str(exc))
        if humanized:
            return {"answer": humanized}
        return {"answer": "Ошибка генерации ответа. Попробуйте позже."}

    return {"answer": format_numbers(answer)}

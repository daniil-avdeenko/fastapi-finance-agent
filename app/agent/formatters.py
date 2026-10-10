"""
Форматтеры и утилиты агента.

- Нормализация чисел и дат перед отправкой пользователю.
- Рендер структурированных ответов (транзакции, агрегаты, топ, сравнение).
- Парсинг JSON из ответа LLM.
- Маппинг технических ошибок LLM в человеческие сообщения.
"""

import json
import re
from typing import Any

# ============================================================
#   Регулярки
# ============================================================

# 37,9% → 37,90%; 22,756% → 22,76%
_PERCENT_RE = re.compile(r"(\d+)[.,](\d+)%")

# Десятичная точка перед символом валюты или процента → запятая.
# Русский формат: 2 056 081,06 ₽ вместо 2 056 081.06 ₽.
_DECIMAL_DOT_RE = re.compile(r"(\d)\.(\d+)(?=\s*[₽%])")

# ,0+ или .0+ перед ₽/% — незначащий хвост, убираем.
_DECIMAL_ZERO_RE = re.compile(r"(\d)[.,]0+(?=\s*[₽%])")

# Одна цифра в дробной части перед ₽ → добавляем ноль.
# 2 363 822,1 ₽ → 2 363 822,10 ₽
_MONEY_FRAC_RE = re.compile(r"(\d)[.,](\d)(?=\s*₽)")

# Схлопываем уже расставленные разделители тысяч: "14 450 744" → "14450744".
_NUMBER_GROUPING_RE = re.compile(r"(?<=\d)\s(?=\d{3}(?!\d))")

# Число от 4 цифр с опциональной дробной частью.
_NUMBER_RE = re.compile(r"(?<![\d.,])(\d{4,})([.,]\d+)?(?!\d)")


# ============================================================
#   Числа
# ============================================================


def _fix_percent(match: re.Match[str]) -> str:
    """37,9% → 37,90%; 22,756% → 22,76%."""
    whole = match.group(1)
    frac = match.group(2)
    if len(frac) == 1:
        frac += "0"
    elif len(frac) > 2:
        value = round(float(f"{whole}.{frac}"), 2)
        int_part, _, frac_part = f"{value:.2f}".partition(".")
        return f"{int_part},{frac_part}%"
    return f"{whole},{frac}%"


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


def _fmt_number(value: float) -> str:
    """Всегда две цифры после запятой, разделители тысяч — пробелы."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


# ============================================================
#   JSON
# ============================================================


def _extract_json(raw: str) -> dict[str, Any]:
    """
    Достаёт JSON из ответа LLM.
    """
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


# ============================================================
#   Даты и периоды
# ============================================================


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


def _period_or_all_time(date_from: str, date_to: str) -> str:
    """Период или 'всё время', если оба параметра пустые."""
    period = _human_period(date_from, date_to)
    return period if period else "всё время"


def _period_label(date_from: str, date_to: str) -> str:
    """'2026-05-01', '2026-05-31' → 'май 2026' (без предлога 'за')."""
    period = _human_period(date_from, date_to)
    if period.startswith("за "):
        return period[3:]
    return period or "весь период"


# ============================================================
#   Склонения
# ============================================================


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


# ============================================================
#   Обработка ошибок LLM
# ============================================================


def _humanize_error(msg: str) -> str:
    """
    Человеческое сообщение вместо технического об ошибке LLM.
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

    # Настоящий таймаут — только явные формы, не подстроки в headers.
    if any(
        marker in lowered
        for marker in ("readtimeout", "connecttimeout", "timed out", "timeout error")
    ):
        return "Превышено время ожидания LLM. Попробуйте позже."

    return ""


# ============================================================
#   Метки метрик
# ============================================================


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


# ============================================================
#   Рендеры ответов
# ============================================================


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

    Верхний блок — показатели: доход, расход, прибыль, рентабельность.
    Нижний — разбивка по проектам (прибыль + рентабельность).
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


def _format_aggregate_plain(data: Any) -> str | None:
    """
    Собирает ответ для intent='aggregate' без LLM.
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

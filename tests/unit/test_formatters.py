"""Тесты форматтеров и утилит агента."""

from app.agent import formatters

# ---------- format_numbers ----------


def test_format_numbers_inserts_separators() -> None:
    assert formatters.format_numbers("1234567.89 руб") == "1 234 567.89 руб"
    assert formatters.format_numbers("Доход 1000.50") == "Доход 1 000.50"


def test_format_numbers_keeps_years() -> None:
    assert formatters.format_numbers("за август 2026") == "за август 2026"
    assert formatters.format_numbers("с 1999 по 2024") == "с 1999 по 2024"


def test_format_numbers_removes_trailing_zero() -> None:
    assert formatters.format_numbers("14 450 744.0 RUB") == "14 450 744 RUB"
    assert formatters.format_numbers("1234567,00 руб") == "1 234 567 руб"


def test_format_numbers_keeps_decimal_dot_outside_currency() -> None:
    """Точка в не-валютном контексте сохраняется."""
    assert formatters.format_numbers("1234.56") == "1 234.56"
    assert formatters.format_numbers("1234.56 руб") == "1 234.56 руб"
    assert formatters.format_numbers("версия 1.2") == "версия 1.2"


def test_format_numbers_ignores_decimal_part() -> None:
    """94,3201 не должно превращаться в 94,3 201."""
    assert formatters.format_numbers("94,3201 ₽") == "94,3201 ₽"
    assert formatters.format_numbers("83.4839 ₽") == "83,4839 ₽"


def test_format_numbers_decimal_comma_before_currency() -> None:
    """Десятичная точка перед ₽ или % меняется на запятую."""
    assert formatters.format_numbers("2 056 081.06 ₽") == "2 056 081,06 ₽"
    assert formatters.format_numbers("1234.56 ₽") == "1 234,56 ₽"


def test_format_numbers_pads_money_fraction() -> None:
    assert formatters.format_numbers("2 363 822,1 ₽") == "2 363 822,10 ₽"
    assert formatters.format_numbers("1234.5 ₽") == "1 234,50 ₽"
    assert formatters.format_numbers("100 ₽") == "100 ₽"
    assert formatters.format_numbers("21,50%") == "21,50%"


def test_format_numbers_pads_percent_to_two_digits() -> None:
    assert formatters.format_numbers("Рентабельность 37,9%") == "Рентабельность 37,90%"
    assert formatters.format_numbers("Рентабельность 22,76%") == "Рентабельность 22,76%"


def test_format_numbers_rounds_long_percent() -> None:
    assert formatters.format_numbers("26,756%") == "26,76%"


def test_fmt_number_pads_to_two_digits() -> None:
    assert formatters._fmt_number(5.4) == "5,40"
    assert formatters._fmt_number(228734.09) == "228 734,09"
    assert formatters._fmt_number(-100.0) == "-100,00"


# ---------- плюрализация ----------


def test_pluralize_projects() -> None:
    assert formatters._pluralize_projects(1) == "проект"
    assert formatters._pluralize_projects(3) == "проекта"
    assert formatters._pluralize_projects(5) == "проектов"
    assert formatters._pluralize_projects(11) == "проектов"
    assert formatters._pluralize_projects(21) == "проект"


def test_pluralize_transactions() -> None:
    assert formatters._pluralize_transactions(1) == "транзакция"
    assert formatters._pluralize_transactions(2) == "транзакции"
    assert formatters._pluralize_transactions(5) == "транзакций"
    assert formatters._pluralize_transactions(11) == "транзакций"


# ---------- _humanize_error ----------


def test_humanize_error_no_such_model() -> None:
    """404 No such model — приоритетнее таймаута из headers."""
    msg = (
        "404 https://api.giga.chat/v1/chat/completions: "
        'b\'{"status":404,"message":"No such model"}\' Headers({'
        "'keep-alive': 'timeout=15'})"
    )
    result = formatters._humanize_error(msg)
    assert "модель" in result.lower()


def test_humanize_error_llm_credits() -> None:
    msg = "LLM error: Error code: 402 - credits in_flight"
    assert "временно недоступен" in formatters._humanize_error(msg).lower()


def test_humanize_error_rate_limit() -> None:
    assert "минуту" in formatters._humanize_error("429 rate limit exceeded").lower()


def test_humanize_error_timeout() -> None:
    assert "превышено" in formatters._humanize_error("Request timed out").lower()
    assert "превышено" in formatters._humanize_error("ReadTimeout: connection").lower()


def test_humanize_error_unknown_returns_empty() -> None:
    assert formatters._humanize_error("Объект не найден") == ""
    assert formatters._humanize_error("Что-то другое") == ""


# ---------- _format_transactions_plain ----------


def test_format_transactions_plain_renders_items() -> None:
    data = {
        "items": [
            {
                "type": "income",
                "category_name": "Консультационные услуги",
                "amount_rub": 1_247_062.51,
                "project_name": "CRM для банка «Альфа»",
            },
            {
                "type": "expense",
                "category_name": "Расходы на ИИ",
                "amount_rub": 716_671.56,
                "project_name": "CRM для банка «Альфа»",
            },
        ],
    }
    params = {"date_from": "2026-08-01", "date_to": "2026-08-31"}

    result = formatters._format_transactions_plain(data, params)

    assert result is not None
    assert "Доход: Консультационные услуги — 1 247 062,51 ₽" in result
    assert "Расход: Расходы на ИИ — 716 671,56 ₽" in result
    assert "август 2026" in result


def test_format_transactions_plain_empty_returns_none() -> None:
    assert formatters._format_transactions_plain({"items": []}, {}) is None


def test_format_transactions_plain_caps_at_15() -> None:
    items = [
        {
            "type": "income",
            "category_name": f"Cat{i}",
            "amount_rub": 100.0,
            "project_name": "P",
        }
        for i in range(20)
    ]
    result = formatters._format_transactions_plain(
        {"items": items},
        {"date_from": "2026-08-01", "date_to": "2026-08-31"},
    )

    assert result is not None
    assert result.count("•") == 15
    assert "и ещё 5 записей" in result


def test_format_transactions_plain_period_from_params_only() -> None:
    data = {
        "items": [
            {
                "type": "income",
                "category_name": "X",
                "amount_rub": 100.0,
                "project_name": "Alpha",
            }
        ],
    }
    result = formatters._format_transactions_plain(
        data, {"date_from": "2026-08-01", "date_to": "2026-08-31"}
    )

    assert result is not None
    assert "август 2026" in result


def test_format_transactions_plain_strips_trailing_zeros() -> None:
    data = {
        "items": [
            {
                "type": "expense",
                "category_name": "Налоги",
                "amount_rub": 240_500.0,
                "project_name": "P",
            },
            {
                "type": "income",
                "category_name": "Услуги",
                "amount_rub": 1_247_062.51,
                "project_name": "P",
            },
        ]
    }
    result = formatters._format_transactions_plain(data, {})

    assert result is not None
    assert "240 500 ₽" in result
    assert "240 500,00" not in result
    assert "1 247 062,51 ₽" in result


def test_format_transactions_plain_single_month_period() -> None:
    data = {
        "items": [
            {"type": "expense", "category_name": "Н", "amount_rub": 100.0, "project_name": "P"}
        ]
    }
    result = formatters._format_transactions_plain(
        data, {"date_from": "2026-08-01", "date_to": "2026-08-31"}
    )
    assert result is not None
    assert "P, август 2026:" in result


def test_format_transactions_plain_custom_range() -> None:
    data = {
        "items": [
            {"type": "expense", "category_name": "Н", "amount_rub": 100.0, "project_name": "P"}
        ]
    }
    result = formatters._format_transactions_plain(
        data, {"date_from": "2026-08-15", "date_to": "2026-08-20"}
    )
    assert result is not None
    assert "с 15.08.2026 по 20.08.2026" in result


# ---------- _format_top_projects_plain ----------


def test_format_top_projects_plain_profit() -> None:
    data = {
        "metric": "profit",
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "items": [
            {"project_name": "A", "metric_value": 100.5},
            {"project_name": "B", "metric_value": 50},
        ],
    }
    result = formatters._format_top_projects_plain(data)

    assert result is not None
    assert "Топ-2 проекта по прибыли за август 2026:" in result
    assert "• A — прибыль 100,50 ₽" in result
    assert "• B — прибыль 50 ₽" in result


def test_format_top_projects_plain_profitability() -> None:
    data = {
        "metric": "profitability",
        "date_from": "2026-05-01",
        "date_to": "2026-05-31",
        "items": [
            {"project_name": "A", "metric_value": 25.5},
            {"project_name": "B", "metric_value": 12.75},
        ],
    }
    result = formatters._format_top_projects_plain(data)

    assert result is not None
    assert "Топ-2 проекта по рентабельности за май 2026:" in result
    assert "• A — рентабельность 25,50%" in result
    assert "• B — рентабельность 12,75%" in result


def test_format_top_projects_plain_income_no_period() -> None:
    data = {
        "metric": "income",
        "date_from": None,
        "date_to": None,
        "items": [{"project_name": "A", "metric_value": 1000}],
    }
    result = formatters._format_top_projects_plain(data)

    assert result is not None
    assert "Топ-1 проект по доходу:" in result
    assert "• A — доход 1 000 ₽" in result


def test_format_top_projects_plain_empty_returns_none() -> None:
    assert formatters._format_top_projects_plain({"items": []}) is None
    assert formatters._format_top_projects_plain(None) is None


# ---------- _format_profit_plain ----------


def test_format_profit_plain_single_project() -> None:
    data = {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "grand_income_rub": 1_947_239.72,
        "grand_expense_rub": 586_640.61,
        "grand_profit_rub": 1_360_599.11,
        "grand_profitability_percent": 69.9,
        "by_project": [
            {
                "project_id": 1,
                "project_name": "CRM для банка «Альфа»",
                "income_rub": 1_947_239.72,
                "expense_rub": 586_640.61,
                "profit_rub": 1_360_599.11,
                "profitability_percent": 69.9,
            }
        ],
    }
    result = formatters._format_profit_plain(data)

    assert result is not None
    assert "Проект CRM для банка «Альфа» за август 2026:" in result
    assert "• Доход: 1 947 239,72 ₽" in result
    assert "• Рентабельность: 69,90%" in result
    assert "По проектам" not in result


def test_format_profit_plain_multiple_projects() -> None:
    data = {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "grand_income_rub": 20_492_003.65,
        "grand_expense_rub": 15_393_544.83,
        "grand_profit_rub": 5_098_458.82,
        "grand_profitability_percent": 24.88,
        "by_project": [
            {
                "project_id": 1,
                "project_name": "A",
                "profit_rub": 1_360_599.11,
                "profitability_percent": 21.5,
            },
            {
                "project_id": 2,
                "project_name": "B",
                "profit_rub": 205_064.13,
                "profitability_percent": 8.9,
            },
        ],
    }
    result = formatters._format_profit_plain(data)

    assert result is not None
    assert "Показатели по проектам за август 2026:" in result
    assert "Прибыль по проектам:" in result
    assert "• A — 1 360 599,11 ₽ (21,50%)" in result
    assert "• B — 205 064,13 ₽ (8,90%)" in result


def test_format_profit_plain_without_profitability() -> None:
    data = {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "grand_income_rub": 0.0,
        "grand_expense_rub": 100.0,
        "grand_profit_rub": -100.0,
        "grand_profitability_percent": None,
        "by_project": [
            {
                "project_id": 1,
                "project_name": "A",
                "profit_rub": -100.0,
                "profitability_percent": None,
            }
        ],
    }
    result = formatters._format_profit_plain(data)

    assert result is not None
    assert "Рентабельность" not in result
    assert "• Прибыль: -100 ₽" in result


def test_format_profit_plain_empty_returns_none() -> None:
    assert formatters._format_profit_plain({"by_project": []}) is None
    assert formatters._format_profit_plain(None) is None


# ---------- _format_profitability_plain ----------


def test_format_profitability_plain_single() -> None:
    data = {
        "date_from": "2026-06-01",
        "date_to": "2026-06-30",
        "grand_profitability_percent": 33.08,
        "by_project": [
            {"project_name": "A", "profitability_percent": 33.08},
        ],
    }
    result = formatters._format_profitability_plain(data)

    assert result is not None
    assert "Рентабельность проекта A за июнь 2026:" in result
    assert "33,08%" in result
    assert "Общая" not in result
    assert "По проектам" not in result


def test_format_profitability_plain_all_time() -> None:
    data = {
        "date_from": None,
        "date_to": None,
        "grand_profitability_percent": 23.04,
        "by_project": [
            {"project_name": "Gamma", "profitability_percent": 23.04},
        ],
    }
    result = formatters._format_profitability_plain(data)

    assert result is not None
    assert "за всё время" in result
    assert "23,04%" in result
    assert "Общая" not in result


def test_format_profitability_plain_empty_returns_none() -> None:
    assert formatters._format_profitability_plain({"by_project": []}) is None
    assert formatters._format_profitability_plain(None) is None


# ---------- _format_aggregate_plain ----------


def test_format_aggregate_plain_income_multiple() -> None:
    data = {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "type": "income",
        "total_transactions": 120,
        "grand_total_rub": 20_492_003.65,
        "by_project": [
            {"project_id": 1, "project_name": "A", "total_rub": 5_708_474.65, "count": 25},
            {"project_id": 2, "project_name": "B", "total_rub": 2_394_594.16, "count": 12},
        ],
    }
    result = formatters._format_aggregate_plain(data)

    assert result is not None
    assert "Доходы за август 2026:" in result
    assert "• Всего: 20 492 003,65 ₽ (120 транзакций)" in result
    assert "Доходы по проектам:" in result
    assert "• A — 5 708 474,65 ₽ (25 транзакций)" in result


def test_format_aggregate_plain_expense_single() -> None:
    data = {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "type": "expense",
        "total_transactions": 1,
        "grand_total_rub": 240_500.0,
        "by_project": [
            {"project_id": 1, "project_name": "Alpha", "total_rub": 240_500.0, "count": 1},
        ],
    }
    result = formatters._format_aggregate_plain(data)

    assert result is not None
    assert "Расходы по проекту Alpha за август 2026:" in result
    assert "• Всего: 240 500 ₽ (1 транзакция)" in result
    assert "По проектам" not in result


def test_format_aggregate_plain_no_type() -> None:
    """Без type и периода — «Сумма за всё время»."""
    data = {
        "date_from": None,
        "date_to": None,
        "type": None,
        "total_transactions": 3,
        "grand_total_rub": 300.0,
        "by_project": [
            {"project_id": 1, "project_name": "A", "total_rub": 200.0, "count": 2},
            {"project_id": 2, "project_name": "B", "total_rub": 100.0, "count": 1},
        ],
    }
    result = formatters._format_aggregate_plain(data)

    assert result is not None
    assert "Сумма за всё время:" in result
    assert "Сумма по проектам:" in result


def test_format_aggregate_plain_empty_returns_none() -> None:
    assert formatters._format_aggregate_plain({"by_project": []}) is None
    assert formatters._format_aggregate_plain(None) is None


# ---------- _format_compare_plain ----------


def test_format_compare_plain_profit_multiple() -> None:
    data = {
        "metric": "profit",
        "period1": {"date_from": "2026-05-01", "date_to": "2026-05-31"},
        "period2": {"date_from": "2026-06-01", "date_to": "2026-06-30"},
        "grand": {
            "period1_value": 5_433_209.90,
            "period2_value": 5_204_475.81,
            "diff_abs": -228_734.09,
            "diff_pct": -4.21,
        },
        "by_project": [
            {
                "project_id": 1,
                "project_name": "CRM для банка «Альфа»",
                "period1_value": 2_085_868.56,
                "period2_value": 1_789_702.27,
                "diff_abs": -296_166.29,
                "diff_pct": -14.20,
            },
            {
                "project_id": 2,
                "project_name": "Интеграция 1С",
                "period1_value": 271_870.07,
                "period2_value": 563_019.66,
                "diff_abs": 291_149.59,
                "diff_pct": 107.09,
            },
        ],
    }
    result = formatters._format_compare_plain(data)

    assert result is not None
    assert "Сравнение прибыли: май 2026 → июнь 2026" in result
    assert "• Итого: 5 433 209,90 ₽ → 5 204 475,81 ₽ (-228 734,09 ₽, -4,21%)" in result
    assert "По проектам:" in result
    assert (
        "• CRM для банка «Альфа»: 2 085 868,56 ₽ → 1 789 702,27 ₽ "
        "(-296 166,29 ₽, -14,20%)" in result
    )
    assert "• Интеграция 1С: 271 870,07 ₽ → 563 019,66 ₽ (+291 149,59 ₽, +107,09%)" in result


def test_format_compare_plain_profitability() -> None:
    """Для рентабельности дельта без единицы, без относительной."""
    data = {
        "metric": "profitability",
        "period1": {"date_from": "2026-05-01", "date_to": "2026-05-31"},
        "period2": {"date_from": "2026-06-01", "date_to": "2026-06-30"},
        "grand": {
            "period1_value": 26.72,
            "period2_value": 25.73,
            "diff_abs": -0.99,
            "diff_pct": -3.71,
        },
        "by_project": [
            {
                "project_id": 1,
                "project_name": "A",
                "period1_value": 38.12,
                "period2_value": 33.08,
                "diff_abs": -5.04,
                "diff_pct": -13.22,
            }
        ],
    }
    result = formatters._format_compare_plain(data)

    assert "Сравнение рентабельности:" in result
    assert "(-0,99)" in result
    assert "(-13,22%)" not in result
    assert "(-3,71%)" not in result
    assert "пп" not in result


def test_format_compare_plain_income() -> None:
    data = {
        "metric": "income",
        "period1": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
        "period2": {"date_from": "2026-08-01", "date_to": "2026-08-31"},
        "grand": {
            "period1_value": 21_361_381.60,
            "period2_value": 20_492_003.65,
            "diff_abs": -869_377.95,
            "diff_pct": -4.07,
        },
        "by_project": [],
    }
    result = formatters._format_compare_plain(data)

    assert result is not None
    assert "Сравнение дохода: июль 2026 → август 2026" in result
    assert "По проектам" not in result


def test_format_compare_plain_empty_returns_none() -> None:
    assert formatters._format_compare_plain(None) is None

"""Inline-клавиатуры и предопределённые интенты для быстрых действий."""

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Тексты, которые уходят в граф (попадают в Message.question для истории).
QUICK_ACTIONS: dict[str, str] = {
    "summary": "Сводка по финансам",
    "profit": "Прибыль по проектам",
    "projects": "Список проектов",
    "transactions": "Последние транзакции",
    "currencies": "Курсы валют",
    "help": "help",
}

# Предопределённые intent + params для быстрых действий.
# Позволяет пропустить understand_node (LLM-вызов ~2-4 секунды):
QUICK_ACTION_INTENTS: dict[str, tuple[str, dict[str, Any]]] = {
    "summary": ("summary", {}),
    "profit": ("profit", {}),
    "projects": ("projects", {}),
    "transactions": ("transactions", {"per_page": 15}),
    "currencies": ("currencies", {}),
}


def start_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура быстрых действий под /start."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Сводка", callback_data="ask:summary"),
                InlineKeyboardButton(text="💰 Прибыль", callback_data="ask:profit"),
            ],
            [
                InlineKeyboardButton(text="📁 Проекты", callback_data="ask:projects"),
                InlineKeyboardButton(text="📋 Транзакции", callback_data="ask:transactions"),
            ],
            [
                InlineKeyboardButton(text="💱 Курсы", callback_data="ask:currencies"),
                InlineKeyboardButton(text="❓ Помощь", callback_data="ask:help"),
            ],
        ]
    )

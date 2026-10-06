"""
Inline-клавиатуры для Telegram.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

QUICK_ACTIONS: dict[str, str] = {
    "summary": "Сводка по финансам",
    "profit": "Прибыль по проектам за последний месяц",
    "projects": "Список проектов",
    "transactions": "Транзакции за последний месяц",
    "currencies": "Курсы валют",
    "help": "help",
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

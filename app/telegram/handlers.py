"""
Хендлеры aiogram.

Текстовые сообщения идут напрямую в agent_service — без HTTP-хопа
на собственный /chat. Одна сессия SQLAlchemy на запрос, тот же
process_question, что и в HTTP-роуте.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db import SessionLocal
from app.services.agent_service import process_question
from app.telegram.keyboards import QUICK_ACTIONS, start_keyboard

logger = logging.getLogger(__name__)

router = Router(name="agent")


HELP_TEXT = (
    "<b>Что я умею:</b>\n"
    "• Сводка по финансам\n"
    "• Список проектов и детали по каждому\n"
    "• Транзакции с фильтрами (тип, проект, даты)\n"
    "• Суммы за период по проектам\n"
    "• Прибыль и рентабельность\n"
    "• Курсы валют ЦБ\n\n"
    "<b>Задавайте любые вопросы, постараюсь на них ответить!</b>\n"
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Приветствие и краткая справка."""
    await message.answer(
        "Привет! Я — финансовый ассистент системы <b>project-finance</b>.\n\n" + HELP_TEXT,
        reply_markup=start_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Справка по возможностям."""
    await message.answer(HELP_TEXT)


@router.message(F.text)
async def handle_question(message: Message) -> None:
    """Основной хендлер: текст → граф → ответ."""
    if not message.text or not message.chat or not message.bot:
        return

    # Отправляем «печатает…» до вызова LLM — иначе пользователь ждёт молча.
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    async with SessionLocal() as session:
        try:
            result = await process_question(
                session,
                chat_id=message.chat.id,
                question=message.text,
            )
        except Exception:
            logger.exception("bot handler failed")
            await message.answer("Произошла ошибка. Попробуйте позже.")
            return

    await message.answer(result.answer)


@router.callback_query(F.data.startswith("ask:"))
async def handle_quick_action(callback: CallbackQuery) -> None:
    """Обрабатывает нажатия кнопок под /start."""
    if callback.data is None or callback.message is None or callback.bot is None:
        await callback.answer()
        return

    action = callback.data.removeprefix("ask:")
    if action not in QUICK_ACTIONS:
        await callback.answer("Кнопка устарела")
        return

    await callback.answer()

    # «Помощь» — показать справку, без графа.
    if action == "help":
        await callback.message.answer(HELP_TEXT)
        return

    # Остальное — обычный вопрос через граф.
    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action="typing")

    async with SessionLocal() as session:
        try:
            result = await process_question(
                session,
                chat_id=callback.message.chat.id,
                question=QUICK_ACTIONS[action],
            )
        except Exception:
            logger.exception("callback handler failed")
            await callback.message.answer("Произошла ошибка. Попробуйте позже.")
            return

    await callback.message.answer(result.answer)

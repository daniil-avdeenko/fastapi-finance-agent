"""
Хендлеры aiogram.

Текстовые сообщения идут напрямую в agent_service — без HTTP-хопа
на собственный /chat. Одна сессия SQLAlchemy на запрос, тот же
process_question, что и в HTTP-роуте.
"""

import logging

from aiogram import Bot, F, Router
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


async def _ask_agent(
    *,
    bot: Bot,
    answer_to: Message,
    chat_id: int,
    question: str,
) -> None:
    """
    Общий путь обработки вопроса: typing → process_question → ответ.

    Используется текстовым хендлером и callback-кнопками. Ошибки не летят
    наружу — пользователь всегда получает текст.
    """
    await bot.send_chat_action(chat_id=chat_id, action="typing")

    async with SessionLocal() as session:
        try:
            result = await process_question(session, chat_id=chat_id, question=question)
        except Exception:
            logger.exception("agent call failed")
            await answer_to.answer("Произошла ошибка. Попробуйте позже.")
            return

    await answer_to.answer(result.answer)


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

    await _ask_agent(
        bot=message.bot,
        answer_to=message,
        chat_id=message.chat.id,
        question=message.text,
    )


@router.callback_query(F.data.startswith("ask:"))
async def handle_quick_action(callback: CallbackQuery) -> None:
    """Обрабатывает нажатия кнопок под /start."""
    if callback.data is None or callback.bot is None:
        await callback.answer()
        return

    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    action = callback.data.removeprefix("ask:")
    if action not in QUICK_ACTIONS:
        await callback.answer("Нажмите /start, чтобы обновить меню", show_alert=False)
        return

    await callback.answer()

    if action == "help":
        await callback.message.answer(HELP_TEXT)
        return

    await _ask_agent(
        bot=callback.bot,
        answer_to=callback.message,
        chat_id=callback.message.chat.id,
        question=QUICK_ACTIONS[action],
    )

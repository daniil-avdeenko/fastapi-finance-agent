"""
Хендлеры aiogram.

Текстовые сообщения идут напрямую в agent_service — без HTTP-хопа
на собственный /chat. Одна сессия SQLAlchemy на запрос, тот же
process_question, что и в HTTP-роуте.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.db import SessionLocal
from app.services.agent_service import process_question

logger = logging.getLogger(__name__)

router = Router(name="agent")


HELP_TEXT = (
    "Я — финансовый ассистент. Задайте вопрос о проектах, доходах и расходах.\n\n"
    "<b>Примеры:</b>\n"
    "• Сводка по финансам\n"
    "• Список проектов\n"
    "• Расходы за март\n"
    "• Курсы валют"
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Приветствие и краткая справка."""
    await message.answer("Привет! Я финансовый ассистент системы project-finance.\n\n" + HELP_TEXT)


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

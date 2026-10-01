"""
Сборка aiogram: Bot + Dispatcher.
"""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import get_settings


def create_bot() -> Bot:
    """Создаёт Bot с HTML-разметкой по умолчанию."""
    settings = get_settings()
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Собирает Dispatcher, подключает middleware и роутеры."""
    from app.telegram import handlers
    from app.telegram.middlewares.throttling import create_throttling_middleware

    dispatcher = Dispatcher(storage=MemoryStorage())

    # middleware на все входящие сообщения, до роутеров.
    dispatcher.message.middleware(create_throttling_middleware())

    dispatcher.include_router(handlers.router)
    return dispatcher

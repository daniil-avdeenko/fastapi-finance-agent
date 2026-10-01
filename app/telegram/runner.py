"""
Polling-режим для локальной разработки.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import get_settings
from app.db import engine
from app.main import _setup_logging
from app.telegram.bot import create_bot, create_dispatcher

logger = logging.getLogger(__name__)


async def run_polling() -> None:
    """Бесконечный long polling до Ctrl+C или сигнала."""
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    bot: Bot = create_bot()
    dispatcher: Dispatcher = create_dispatcher()

    # Явно удаляем webhook — иначе Telegram не отдаёт апдейты через getUpdates.
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info(
        "Starting polling (rate limit: %d/%ds)",
        settings.telegram_rate_limit,
        settings.telegram_rate_window,
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
        logger.info("Polling stopped")


def main() -> None:
    """Синхронная обёртка для python -m."""
    settings = get_settings()
    _setup_logging(settings.log_level)

    try:
        asyncio.run(run_polling())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()

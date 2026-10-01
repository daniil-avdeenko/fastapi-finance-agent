"""
FastAPI-приложение: точка входа.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.telegram import router as telegram_router
from app.config import get_settings
from app.db import engine


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения."""
    settings = get_settings()
    _setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting %s in %s mode", app.title, settings.app_env)

    # Telegram: только в webhook-режиме и только если задан токен.
    if settings.telegram_mode == "webhook" and settings.telegram_bot_token:
        from app.telegram.bot import create_bot, create_dispatcher

        bot = create_bot()
        dispatcher = create_dispatcher()
        app.state.bot = bot
        app.state.dispatcher = dispatcher

        if settings.telegram_webhook_url:
            await bot.set_webhook(
                url=settings.telegram_webhook_url,
                secret_token=settings.telegram_webhook_secret or None,
                drop_pending_updates=True,
            )
            logger.info("Telegram webhook set: %s", settings.telegram_webhook_url)

    yield

    # Shutdown
    shutdown_bot = getattr(app.state, "bot", None)
    if shutdown_bot is not None:
        await shutdown_bot.session.close()
        logger.info("Telegram bot session closed")

    await engine.dispose()
    logger.info("Shutdown complete")


settings = get_settings()

app = FastAPI(
    title="Finance Agent",
    description="Telegram AI agent for project-finance system",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

app.include_router(chat_router)
app.include_router(telegram_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """
    Healthcheck для Railway/Docker.

    Не ходит в БД, не требует авторизации.
    """
    return {"status": "ok", "service": "finance-agent", "version": "0.1.0"}

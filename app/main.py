"""
FastAPI-приложение: точка входа.

Lifespan управляет startup/shutdown: закрывает engine при остановке.
Эндпоинты подключаются через роутеры.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

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

    yield

    # Shutdown
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


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """
    Healthcheck для Railway/Docker.

    Не ходит в БД, не требует авторизации.
    """
    return {"status": "ok", "service": "finance-agent", "version": "0.1.0"}

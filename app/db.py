"""
Async SQLAlchemy: engine, session factory, dependency для FastAPI.

Паттерн: session per request через dependency. Закрывается автоматически
после отдачи ответа.
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""

    pass


async def get_session() -> AsyncGenerator[AsyncSession, Any]:
    """
    FastAPI dependency: сессия на запрос.

    Использование:
        async def endpoint(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

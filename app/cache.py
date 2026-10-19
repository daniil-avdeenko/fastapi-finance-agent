"""
Асинхронный клиент Redis.

Используется для rate limit в Telegram-боте. При недоступности Redis
middleware переключается на in-memory fallback.
"""

import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://localhost:6379/0"

_client: aioredis.Redis | None = None
_client_unavailable: bool = False


async def get_cache() -> aioredis.Redis | None:
    """
    Возвращает singleton async-клиента Redis или None.

    Первый вызов пробует подключиться. При неудаче запоминает это
    в _client_unavailable и следующие вызовы возвращают None сразу,
    без ожидания на TCP-connect.
    """
    global _client, _client_unavailable

    if _client_unavailable:
        return None
    if _client is not None:
        return _client

    settings = get_settings()
    url = settings.redis_url or DEFAULT_REDIS_URL
    try:
        client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        )
        await client.ping()
        _client = client
        logger.info("Redis connected: %s", url)
    except (RedisError, OSError) as e:
        logger.warning("Redis unavailable (%s): %s. Using in-memory fallback.", url, e)
        _client_unavailable = True

    return _client


async def close_cache() -> None:
    """Закрывает соединение при shutdown (lifespan)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Redis connection closed")

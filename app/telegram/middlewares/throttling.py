"""
Rate limit: точное скользящее окно на user_id.

Redis sorted set с Lua-скриптом. Алгоритм (sliding window log):
- Каждый запрос — член sorted set со score = время в наносекундах.
- При новом запросе удаляются члены старше окна, проверяется размер.
- Если размер < max_requests — добавляется новый член.

При недоступности Redis middleware переключается на in-memory fallback
(тот же sliding window log через deque).
"""

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from redis.exceptions import RedisError

from app.cache import get_cache
from app.config import get_settings

logger = logging.getLogger(__name__)


# Lua: атомарный sliding window log.
# KEYS[1] — ключ пользователя (ratelimit:<user_id>)
# ARGV[1] — текущее время в наносекундах
# ARGV[2] — размер окна в секундах
# ARGV[3] — максимальное число запросов
# Возвращает 1, если запрос пропущен; 0, если лимит превышен.
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ns = tonumber(ARGV[1])
local window_ns = tonumber(ARGV[2]) * 1000000000
local max_req = tonumber(ARGV[3])
local cutoff = now_ns - window_ns

redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
local count = redis.call('ZCARD', key)

if count >= max_req then
    return 0
end

redis.call('ZADD', key, now_ns, now_ns)
redis.call('PEXPIRE', key, math.floor(window_ns / 1000000))
return 1
"""


class ThrottlingMiddleware(BaseMiddleware):
    """
    Скользящее окно запросов на user_id.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # user_id → очередь таймстампов (монотонных). Fallback.
        self._fallback_history: dict[int, deque[float]] = defaultdict(deque)
        self._script: Any = None
        self._redis: aioredis.Redis | None = None
        self._redis_initialized = False

    async def _get_redis(self) -> aioredis.Redis | None:
        """
        Ленивая инициализация клиента и регистрация Lua-скрипта.

        Регистрация через register_script кеширует SHA на клиенте.
        """
        if self._redis_initialized:
            return self._redis

        self._redis_initialized = True
        client = await get_cache()
        if client is None:
            return None

        self._redis = client
        self._script = client.register_script(SLIDING_WINDOW_LUA)
        return client

    def _check_memory(self, user_id: int) -> bool:
        """
        Fallback: in-memory sliding window log.

        Возвращает True, если запрос пропущен; False, если заблокирован.
        """
        now = time.monotonic()
        history = self._fallback_history[user_id]
        cutoff = now - self.window_seconds

        while history and history[0] < cutoff:
            history.popleft()

        if len(history) >= self.max_requests:
            return False

        history.append(now)
        return True

    async def _respond_blocked(self, event: Message) -> None:
        await event.answer(
            f"Слишком много запросов. Подождите "
            f"{self.window_seconds} секунд и попробуйте снова."
        )

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Пропускает событие, если лимит не превышен."""
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        user_id = event.from_user.id

        client = await self._get_redis()
        if client is not None and self._script is not None:
            try:
                now_ns = time.time_ns()
                allowed = await self._script(
                    keys=[f"ratelimit:{user_id}"],
                    args=[now_ns, self.window_seconds, self.max_requests],
                )
                if not allowed:
                    await self._respond_blocked(event)
                    return None
                return await handler(event, data)
            except RedisError as e:
                logger.warning("Redis error in throttle: %s. Falling back to memory.", e)

        if not self._check_memory(user_id):
            await self._respond_blocked(event)
            return None
        return await handler(event, data)


def create_throttling_middleware() -> ThrottlingMiddleware:
    """Собирает middleware из настроек."""
    settings = get_settings()
    return ThrottlingMiddleware(
        max_requests=settings.telegram_rate_limit,
        window_seconds=settings.telegram_rate_window,
    )

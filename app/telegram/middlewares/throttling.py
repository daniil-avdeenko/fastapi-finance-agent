"""
Rate limit: скользящее окно на пользователя.

Проверяет количество сообщений от user_id за последние N секунд.
При превышении — отвечает один раз и не пропускает в хендлер.
"""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.config import get_settings


class ThrottlingMiddleware(BaseMiddleware):
    """Скользящее окно запросов на user_id."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # user_id → очередь таймстампов (монотонных).
        self._history: dict[int, deque[float]] = defaultdict(deque)

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
        now = time.monotonic()
        history = self._history[user_id]

        # Убираем всё, что старше окна.
        cutoff = now - self.window_seconds
        while history and history[0] < cutoff:
            history.popleft()

        if len(history) >= self.max_requests:
            await event.answer(
                f"Слишком много запросов. Подождите "
                f"{self.window_seconds} секунд и попробуйте снова."
            )
            return None

        history.append(now)
        return await handler(event, data)


def create_throttling_middleware() -> ThrottlingMiddleware:
    """Собирает middleware из настроек."""
    settings = get_settings()
    return ThrottlingMiddleware(
        max_requests=settings.telegram_rate_limit,
        window_seconds=settings.telegram_rate_window,
    )

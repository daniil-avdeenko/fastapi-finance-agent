"""Тесты rate limit middleware."""

import time
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message

from app.telegram.middlewares.throttling import ThrottlingMiddleware


def make_message(user_id: int = 1) -> Message:
    """Фейковый Message с нужными полями для middleware."""
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(id=user_id)
    message.answer = AsyncMock()
    return message


async def test_passes_under_limit() -> None:
    """Первые N сообщений проходят в хендлер."""
    middleware = ThrottlingMiddleware(max_requests=3, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    for _ in range(3):
        result = await middleware(handler, make_message(), {})

    assert handler.await_count == 3
    assert result == "ok"


async def test_blocks_over_limit() -> None:
    """На N+1 сообщении middleware отвечает и не зовёт хендлер."""
    middleware = ThrottlingMiddleware(max_requests=2, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, make_message(), {})
    await middleware(handler, make_message(), {})

    blocked = make_message()
    result = await middleware(handler, blocked, {})

    assert result is None
    assert handler.await_count == 2
    blocked.answer.assert_awaited_once()
    assert "Слишком много запросов" in blocked.answer.call_args[0][0]


async def test_separate_limits_per_user() -> None:
    """Лимит считается на каждого пользователя отдельно."""
    middleware = ThrottlingMiddleware(max_requests=1, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, make_message(user_id=1), {})
    await middleware(handler, make_message(user_id=2), {})

    assert handler.await_count == 2


async def test_window_expires(monkeypatch) -> None:
    """Сообщения старше окна не учитываются."""
    middleware = ThrottlingMiddleware(max_requests=1, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, make_message(), {})

    # Сдвигаем монотонное время на 61 секунду вперёд.
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        "app.telegram.middlewares.throttling.time.monotonic",
        lambda: real_monotonic() + 61,
    )

    result = await middleware(handler, make_message(), {})

    assert result == "ok"
    assert handler.await_count == 2


async def test_non_message_event_passes_through() -> None:
    """События, не являющиеся Message, middleware не трогает."""
    middleware = ThrottlingMiddleware(max_requests=1, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    # Подсовываем не-Message событие.
    other_event = MagicMock()

    result = await middleware(handler, other_event, {})

    assert result == "ok"
    assert handler.await_count == 1

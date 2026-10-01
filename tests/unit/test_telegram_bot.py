"""Тесты сборки Dispatcher (bot.py)."""

from aiogram import Dispatcher

from app.telegram.bot import create_dispatcher


def test_create_dispatcher_returns_dispatcher() -> None:
    """create_dispatcher возвращает Dispatcher с подключённым middleware."""
    dispatcher = create_dispatcher()

    assert isinstance(dispatcher, Dispatcher)
    # Router хендлеров подключён.
    assert dispatcher.sub_routers, "должен быть хотя бы один подключённый роутер"

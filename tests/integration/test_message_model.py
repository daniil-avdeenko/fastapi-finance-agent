"""Тесты модели Message: сохранение, дефолты, работа с полями."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message


async def test_message_creation_with_defaults(db_session: AsyncSession) -> None:
    """Создание сообщения с минимальным набором полей."""
    message = Message(
        chat_id=123456789,
        question="Сколько доходов за сентябрь?",
        answer="За сентябрь 2026 доходы составили 165 043 060 ₽.",
        llm_provider="mock",
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    assert message.id is not None
    assert message.chat_id == 123456789
    assert message.llm_provider == "mock"
    assert message.latency_ms is None
    assert message.created_at is not None


async def test_message_created_at_is_utc(db_session: AsyncSession) -> None:
    """
    created_at — tz-aware UTC.
    """
    message = Message(
        chat_id=1,
        question="q",
        answer="a",
        llm_provider="mock",
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    assert message.created_at.tzinfo is not None
    now = datetime.now(UTC)
    delta = abs((now - message.created_at).total_seconds())
    assert delta < 5


async def test_message_with_latency(db_session: AsyncSession) -> None:
    """latency_ms сохраняется, если задан."""
    message = Message(
        chat_id=42,
        question="q",
        answer="a",
        llm_provider="openrouter",
        latency_ms=850,
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    assert message.latency_ms == 850


async def test_messages_are_queryable_by_chat_id(db_session: AsyncSession) -> None:
    """Запрос по chat_id возвращает только сообщения этого чата."""
    db_session.add_all(
        [
            Message(chat_id=100, question="q1", answer="a1", llm_provider="mock"),
            Message(chat_id=100, question="q2", answer="a2", llm_provider="mock"),
            Message(chat_id=200, question="q3", answer="a3", llm_provider="mock"),
        ]
    )
    await db_session.commit()

    stmt = select(Message).where(Message.chat_id == 100)
    result = await db_session.execute(stmt)
    messages = result.scalars().all()

    assert len(messages) == 2
    assert all(m.chat_id == 100 for m in messages)


async def test_message_repr(db_session: AsyncSession) -> None:
    """repr показывает chat_id и начало вопроса."""
    message = Message(
        chat_id=999,
        question="Очень длинный вопрос, который должен обрезаться в repr",
        answer="a",
        llm_provider="mock",
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    assert "chat=999" in repr(message)
    assert "Очень длинный вопрос" in repr(message)


async def test_message_stores_intent_and_params(db_session: AsyncSession) -> None:
    """Message сохраняет intent и params для контекста диалога."""
    msg = Message(
        chat_id=1,
        question="Доходы за август",
        answer="...",
        llm_provider="mock",
        intent="aggregate",
        params={"type": "income", "date_from": "2026-08-01", "date_to": "2026-08-31"},
    )
    db_session.add(msg)
    await db_session.commit()

    result = await db_session.execute(select(Message).where(Message.chat_id == 1))
    saved = result.scalar_one()

    assert saved.intent == "aggregate"
    assert saved.params == {"type": "income", "date_from": "2026-08-01", "date_to": "2026-08-31"}


async def test_message_intent_and_params_default_to_none(db_session: AsyncSession) -> None:
    """Старые сообщения (до миграции) и ручные — без intent/params."""
    msg = Message(chat_id=1, question="q", answer="a", llm_provider="mock")
    db_session.add(msg)
    await db_session.commit()

    assert msg.intent is None
    assert msg.params is None

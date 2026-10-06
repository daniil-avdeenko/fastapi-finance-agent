"""
Сервис обработки вопроса: гоняет LangGraph и сохраняет Message.

Используется двумя адаптерами: HTTP-роутом POST /chat и aiogram-хендлером.
Держит в одном месте инварианты — запись в БД, метрики, обработка пустого answer.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import get_graph
from app.config import get_settings
from app.models.message import Message

logger = logging.getLogger(__name__)

# Сколько последних вопросов подаём в промпт understand как контекст диалога.
HISTORY_DEPTH = 5


@dataclass(frozen=True)
class AgentResult:
    """Результат обработки одного вопроса."""

    answer: str
    llm_provider: str
    latency_ms: int


async def _load_history(session: AsyncSession, chat_id: int) -> list[dict[str, Any]]:
    """
    Возвращает последние HISTORY_DEPTH вопросов от chat_id — новые в конце.
    """
    stmt = (
        select(Message.question, Message.intent, Message.params)
        .where(Message.chat_id == chat_id)
        .order_by(desc(Message.created_at), desc(Message.id))
        .limit(HISTORY_DEPTH)
    )
    rows = (await session.execute(stmt)).all()

    # Разворачиваем: старые вперёд, новые в конец — так удобнее читать в промпте.
    return [
        {"question": row.question, "intent": row.intent, "params": row.params}
        for row in reversed(rows)
    ]


async def process_question(
    session: AsyncSession,
    *,
    chat_id: int,
    question: str,
    use_history: bool = True,
) -> AgentResult:
    """
    Прогоняет вопрос через граф агента и сохраняет пару в Message.

    use_history=False отключает подкладывание предыдущих сообщений в промпт
    understand. Нужно для inline-кнопок.
    """
    started = time.perf_counter()

    history = await _load_history(session, chat_id) if use_history else []

    graph = get_graph()
    result = await graph.ainvoke(
        {
            "question": question,
            "chat_id": chat_id,
            "history": history,
        }
    )

    latency_ms = int((time.perf_counter() - started) * 1000)

    answer = result.get("answer")
    if not answer:
        raise RuntimeError("Agent failed to produce an answer")

    llm_provider = get_settings().llm_provider

    session.add(
        Message(
            chat_id=chat_id,
            question=question,
            answer=answer,
            llm_provider=llm_provider,
            latency_ms=latency_ms,
            intent=result.get("intent"),
            params=result.get("params"),
        )
    )
    await session.commit()

    logger.info(
        "agent: chat_id=%s intent=%s latency=%dms provider=%s",
        chat_id,
        result.get("intent"),
        latency_ms,
        llm_provider,
    )

    return AgentResult(
        answer=answer,
        llm_provider=llm_provider,
        latency_ms=latency_ms,
    )

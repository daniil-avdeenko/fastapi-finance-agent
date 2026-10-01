"""
Сервис обработки вопроса: гоняет LangGraph и сохраняет Message.

Используется двумя адаптерами: HTTP-роутом POST /chat и aiogram-хендлером.
Держит в одном месте инварианты — запись в БД, метрики, обработка пустого answer.
"""

import logging
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import get_graph
from app.config import get_settings
from app.models.message import Message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentResult:
    """Результат обработки одного вопроса."""

    answer: str
    llm_provider: str
    latency_ms: int


async def process_question(
    session: AsyncSession,
    *,
    chat_id: int,
    question: str,
) -> AgentResult:
    """
    Прогоняет вопрос через граф агента и сохраняет пару в Message.

    Бросает RuntimeError, если граф не сформировал answer —
    это баг в узлах, наверх отдаём явно, без None.
    """
    started = time.perf_counter()

    graph = get_graph()
    result = await graph.ainvoke({"question": question, "chat_id": chat_id})

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
        )
    )
    await session.commit()

    logger.info(
        "agent: chat_id=%s latency=%dms provider=%s",
        chat_id,
        latency_ms,
        llm_provider,
    )

    return AgentResult(
        answer=answer,
        llm_provider=llm_provider,
        latency_ms=latency_ms,
    )

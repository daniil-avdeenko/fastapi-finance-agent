"""
POST /chat — точка входа агента.

Схема: FastAPI принимает вопрос → запускает LangGraph-граф
(understand → query_data → format_answer) → сохраняет Message →
возвращает ответ клиенту.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import get_graph
from app.config import get_settings
from app.db import get_session
from app.models.message import Message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


class ChatRequest(BaseModel):
    """Входящее сообщение от пользователя."""

    chat_id: int = Field(..., description="Telegram chat_id пользователя")
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Вопрос агента на естественном языке",
    )


class ChatResponse(BaseModel):
    """Ответ агента."""

    answer: str
    llm_provider: str
    latency_ms: int


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """Обрабатывает вопрос через LangGraph-агента и сохраняет историю."""
    started = time.perf_counter()

    graph = get_graph()
    result = await graph.ainvoke({"question": payload.question, "chat_id": payload.chat_id})

    latency_ms = int((time.perf_counter() - started) * 1000)

    answer = result.get("answer")
    if not answer:
        # Сюда попадаем только если граф отработал, но answer не сформировал —
        # это баг в узлах, отдаём 500 явно, чтобы не возвращать None клиенту.
        raise HTTPException(status_code=500, detail="Agent failed to produce an answer")

    llm_provider = get_settings().llm_provider

    session.add(
        Message(
            chat_id=payload.chat_id,
            question=payload.question,
            answer=answer,
            llm_provider=llm_provider,
            latency_ms=latency_ms,
        )
    )
    await session.commit()

    logger.info(
        "chat: chat_id=%s latency=%dms provider=%s",
        payload.chat_id,
        latency_ms,
        llm_provider,
    )

    return ChatResponse(
        answer=answer,
        llm_provider=llm_provider,
        latency_ms=latency_ms,
    )

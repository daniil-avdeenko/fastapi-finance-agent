"""
POST /chat — точка входа агента.

Тонкий адаптер: валидирует тело, зовёт agent_service, заворачивает
RuntimeError в HTTP 500. Вся логика — в сервисе.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.agent_service import process_question

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
    try:
        result = await process_question(
            session,
            chat_id=payload.chat_id,
            question=payload.question,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(
        answer=result.answer,
        llm_provider=result.llm_provider,
        latency_ms=result.latency_ms,
    )

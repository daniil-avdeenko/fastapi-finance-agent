"""
POST /chat — точка входа агента.

Тонкий адаптер: валидирует тело, проверяет API key (если настроен),
зовёт agent_service. Вся логика — в сервисе.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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


async def _verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """
    Проверяет X-API-Key, если API_KEY задан в настройках.

    Пустой API_KEY — endpoint открыт (dev и публичное демо).
    Задан API_KEY — требуется совпадающий header, иначе 401.
    """
    expected = get_settings().api_key
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(_verify_api_key)],
)
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

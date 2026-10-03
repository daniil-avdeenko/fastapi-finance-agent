"""
История диалогов с агентом.

Одна строка = одна пара «вопрос пользователя — ответ агента».
Хранится для контекста в LangGraph (последние N сообщений подаются
в LLM при следующем запросе) и для аналитики использования.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Message(Base):
    """Сообщение в диалоге с агентом."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    params: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

    def __init__(
        self,
        *,
        chat_id: int,
        question: str,
        answer: str,
        llm_provider: str,
        latency_ms: int | None = None,
        intent: str | None = None,
        params: dict[str, object] | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.question = question
        self.answer = answer
        self.llm_provider = llm_provider
        self.latency_ms = latency_ms
        self.intent = intent
        self.params = params

    def __repr__(self) -> str:
        preview = self.question[:40].replace("\n", " ")
        return f"<Message chat={self.chat_id} q='{preview}'>"

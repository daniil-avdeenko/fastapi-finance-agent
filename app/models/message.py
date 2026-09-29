"""
История диалогов с агентом.

Одна строка = одна пара «вопрос пользователя — ответ агента».
Хранится для контекста в LangGraph (последние N сообщений подаются
в LLM при следующем запросе) и для аналитики использования.
"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Message(Base):
    """Сообщение в диалоге с агентом."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # chat_id — Telegram ID пользователя (int64, влезает в BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    # Вопрос пользователя
    question: Mapped[str] = mapped_column(Text, nullable=False)

    # Ответ агента
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    # Какой LLM-провайдер обработал (openrouter / yandex / mock)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)

    # Время обработки в миллисекундах — для аналитики и дебага
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        preview = self.question[:40].replace("\n", " ")
        return f"<Message chat={self.chat_id} q='{preview}'>"

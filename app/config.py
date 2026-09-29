"""
Конфигурация приложения.

Загружается из .env через pydantic-settings.
Все обязательные переменные валидируются при старте —
если чего-то не хватает, приложение не поднимется.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: Literal["development", "production"] = "development"
    secret_key: str = Field(..., min_length=8, description="Секрет для подписи")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Database
    database_url: str = Field(..., description="postgresql+asyncpg://...")

    # Main project API
    main_api_url: str = Field(..., description="URL публичного API основного проекта")
    main_api_timeout: float = 10.0

    # LLM
    llm_provider: Literal["openrouter", "yandex", "mock"] = "openrouter"
    llm_api_key: str = ""
    llm_model: str = "meta-llama/llama-3.1-8b-instruct:free"

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    # NoDecode — pydantic-settings не пытается парсить как JSON.
    # Значение-строка "1,2,3" уходит в field_validator ниже.
    telegram_allowed_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_chat_ids(cls, v: object) -> list[int]:
        """Парсит строку '1,2,3' в список int."""
        if v is None or v == "":
            return []
        if isinstance(v, list | tuple):
            return [int(x) for x in v]
        return [int(x.strip()) for x in str(v).split(",") if x.strip().isdigit()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает singleton с настройками (кэш для DI)."""
    return Settings()

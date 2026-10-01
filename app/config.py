"""
Конфигурация приложения.

Загружается из .env через pydantic-settings.
Все обязательные переменные валидируются при старте —
если чего-то не хватает, приложение не поднимется.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    llm_model: str = "meta-llama/llama-3.1-8b-instruct"

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_webhook_url: str = ""
    telegram_mode: Literal["webhook", "polling"] = "webhook"

    # Rate limit для Telegram (на user_id)
    telegram_rate_limit: int = Field(default=10, ge=1, le=1000)
    telegram_rate_window: int = Field(default=60, ge=1, le=3600)

    @model_validator(mode="after")
    def _require_openrouter_key(self) -> "Settings":
        """Проверяет, что для openrouter задан ключ — падаем на старте, а не в рантайме."""
        if self.llm_provider == "openrouter" and not self.llm_api_key:
            raise ValueError("LLM_API_KEY обязателен при LLM_PROVIDER=openrouter")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает singleton с настройками (кэш для DI)."""
    return Settings()

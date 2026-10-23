# Changelog

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

## [1.0.0] — 2026-10-23

Первый стабильный релиз.

### Возможности

- LangGraph-граф с тремя узлами: `understand → query_data → format_answer`.
- 11 интентов: `summary`, `projects`, `project_detail`, `transactions`, `count`, `aggregate`, `currencies`, `profit`, `profitability`, `top_n`, `compare`.
- Контекст диалога: последние 5 сообщений по `chat_id` подкладываются в промпт `understand`.
- GigaChat как основной LLM-провайдер (`langchain-gigachat`), OpenRouter как fallback (`openai` SDK).
- Рендер структурированных ответов в Python для транзакций, топ-N, прибыли, рентабельности, агрегатов и сравнения — без вызова LLM.
- aiogram 3: webhook для прода, polling для локальной разработки.
- Inline-кнопки быстрого доступа под `/start`.
- История сообщений в PostgreSQL: `chat_id`, `question`, `answer`, `intent`, `params`, `llm_provider`, `latency_ms`, `created_at`.

### Инфраструктура

- FastAPI + uvicorn, Pydantic v2.
- PostgreSQL 16, SQLAlchemy 2.0 async, asyncpg, Alembic.
- Redis 7 для rate limit на `user_id` — sliding window log на sorted set + Lua-скрипт, fallback на in-memory `deque` при недоступности.
- Docker Compose (dev + prod).
- GitHub Actions: `Tests`, `Lint & Type Check` (ruff + mypy strict), `Secrets scan` (gitleaks).
- Deploy Preview на PR, Deploy prod после merge в `main` через self-hosted runner.
- Разделение зависимостей prod/dev через `pip-tools`, lock-файлы в Linux-контейнере.

### Качество

- 194 тестов, покрытие 92%.
- ruff, mypy strict, pre-commit, gitleaks.
- Conventional Commits, feature-ветки, branch protection.

### Безопасность

- `POST /chat` защищён `X-API-Key`, если `API_KEY` задан в env. Пустой `API_KEY` — endpoint открыт (dev и публичное демо), см. `SECURITY.md`.
- Проверка `X-Telegram-Bot-Api-Secret-Token` на webhook.
- Валидация конфигурации на старте: GigaChat без credentials и OpenRouter без ключа не поднимают приложение.
- Rate limit на `user_id` в Telegram-боте (10 запросов/мин).
- HTML-escape ответов агента перед отправкой в Telegram.
- Санитизация ошибок LLM: технические детали (URL, коды 402/403/404/429/timeout) не утекают в ответ.
- Секреты только в env, `.env` в `.gitignore`, gitleaks в CI.

### Известные ограничения

- `POST /chat` без авторизации, если `API_KEY` пуст — для dev и публичного демо. Для production необходимо задать `API_KEY`.
- `GIGACHAT_VERIFY_SSL=false` в production.
- HSTS не настроен.
- Rate limit только на Telegram `user_id`, на HTTP-эндпоинте `/chat` не настроен.

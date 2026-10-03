# 🤖 Finance Agent

[![CI](https://github.com/daniil-avdeenko/FastApi-Finance-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/daniil-avdeenko/FastApi-Finance-Agent/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

Telegram AI-агент для системы [project-finance](https://github.com/daniil-avdeenko/project-finance).
Отвечает на вопросы о проектах и финансах на естественном языке.

Агент не ходит в БД основного проекта напрямую — только через публичный
REST API `/api/v1/*`. Развязка сервисов, отказ от shared-credentials,
независимый деплой.

## Что умеет

- Сводка по финансам — доходы, расходы, прибыль, рентабельность.
- Список проектов и детали по каждому.
- Транзакции с фильтрами: тип, проект, даты.
- Агрегация: суммарный доход/расход за период по проектам.
- Прибыль и рентабельность за период, в рублях.
- Курсы валют ЦБ.

Примеры: `Сводка по финансам`, `Прибыль по проектам за август`,
`Суммарный доход за май`, `Курсы валют`.

## Стек

- **FastAPI** + uvicorn + Pydantic v2
- **PostgreSQL 16** + SQLAlchemy 2.0 (async) + asyncpg + Alembic
- **LangGraph** + LangChain + OpenRouter (openai SDK)
- **aiogram 3** (webhook + polling)
- **httpx** — клиент к API основного проекта
- **pytest** + pytest-asyncio + testcontainers + respx
- **ruff** + mypy (strict) + pre-commit + gitleaks
- **Docker** + Railway

## Быстрый старт

```bash
git clone https://github.com/daniil-avdeenko/FastApi-Finance-Agent.git
cd FastApi-Finance-Agent

python -m venv .venv
.venv\Scripts\activate                    # Windows
pip install -r requirements-dev.txt

docker compose up -d                      # Postgres + Adminer
cp .env.example .env                      # заполнить TELEGRAM_BOT_TOKEN и LLM_API_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

Healthcheck: http://127.0.0.1:8000/health
Swagger: http://127.0.0.1:8000/docs

### Telegram-бот

**Webhook (прод).**

```dotenv
`TELEGRAM_MODE=webhook`,
`TELEGRAM_WEBHOOK_URL=https://<домен>/telegram/webhook`.
```

**Polling (локально).** Публичного URL нет, бот сам опрашивает Telegram:

```dotenv
# .env
TELEGRAM_MODE=polling
TELEGRAM_BOT_TOKEN=...
```

```bash
python -m app.telegram.runner
```

## Деплой на Railway

- **PostgreSQL** — managed, `DATABASE_URL` подставляется в web.
- **web** — Dockerfile, публичный HTTPS, он же Telegram-бот.

`railway.toml`: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`.

Переменные для web:

```dotenv
APP_ENV=production
SECRET_KEY=<random>
DATABASE_URL=<reference>
MAIN_API_URL=https://project-finance-production-21.up.railway.app
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-v1-...
LLM_MODEL=google/gemini-3.1-flash-lite
TELEGRAM_MODE=webhook
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_URL=https://<домен>/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=<random>
TELEGRAM_RATE_LIMIT=10
TELEGRAM_RATE_WINDOW=60
```

## Тесты

```bash
pytest                                    # coverage ≥ 90%
ruff check app/ tests/
mypy app/
```

Integration-тесты используют реальный Postgres через testcontainers.

## Структура

```
app/
├── agent/         # LangGraph: state, nodes, tools, graph, LLM-провайдеры
├── api/           # FastAPI: /chat, /telegram/webhook
├── telegram/      # aiogram: bot, handlers, middlewares, runner
├── models/        # SQLAlchemy: Message
├── services/      # agent_service
├── config.py      # pydantic-settings
├── db.py          # engine, session factory
└── main.py        # FastAPI app + lifespan
migrations/        # Alembic
tests/unit/
tests/integration/
```

## Управление зависимостями

Lock-файлы (`requirements*.txt`) собираются `pip-tools` **внутри Linux-контейнера**.
Версия `pip-tools` и Python зафиксированы в
[`scripts/requirements-compile.Dockerfile`](scripts/requirements-compile.Dockerfile).

```bash
./scripts/compile-requirements.sh      # Linux / macOS / Git Bash
.\scripts\compile-requirements.ps1     # Windows PowerShell
```

## Лицензия

MIT

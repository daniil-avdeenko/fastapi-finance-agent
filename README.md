# 🤖 Finance Agent

[![CI](https://github.com/daniil-avdeenko/FastApi-Finance-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/daniil-avdeenko/FastApi-Finance-Agent/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

Telegram AI-агент для системы [project-finance](https://github.com/daniil-avdeenko/project-finance).
Отвечает на вопросы о проектах и финансах на естественном языке.

**Статус:** в активной разработке. Сейчас готов скелет приложения
(FastAPI + PostgreSQL + Alembic). LangGraph-агент и Telegram-бот — в следующих PR.

## Стек

- **FastAPI** + uvicorn + Pydantic v2
- **PostgreSQL 16** + SQLAlchemy 2.0 (async) + asyncpg + Alembic
- **LangGraph** + LangChain + OpenRouter (в разработке)
- **aiogram 3** (в разработке)
- **pytest** + pytest-asyncio + testcontainers
- **ruff** + mypy (strict) + pre-commit

## Быстрый старт

```bash
git clone https://github.com/daniil-avdeenko/FastApi-Finance-Agent.git
cd FastApi-Finance-Agent

python -m venv .venv
.venv\Scripts\activate                    # Windows
pip install -r requirements-dev.txt

docker compose up -d                      # Postgres + Adminer
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Healthcheck: http://127.0.0.1:8000/health
Swagger: http://127.0.0.1:8000/docs

## Тесты

```bash
pytest
```

Integration-тесты используют реальный Postgres через testcontainers —
достаточно установленного Docker.

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

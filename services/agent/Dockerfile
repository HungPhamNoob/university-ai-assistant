# services/agent/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# COPY cả uv.lock: build reproducible + layer deps cache riêng (xem chi tiết
# giải thích trong services/identity/Dockerfile — cùng một pattern).
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

# Code agent + prompts (router/faq/search/booking/general nằm cùng service agent).
COPY services/__init__.py ./services/__init__.py
COPY services/agent/ ./services/agent/

ENV PYTHONPATH=/app

EXPOSE 8000

# Agent KHÔNG có alembic — checkpointer Postgres do LangGraph tự quản.
CMD ["uv", "run", "--no-sync", "uvicorn", "services.agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

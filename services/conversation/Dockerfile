# services/conversation/Dockerfile
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

# Only the conversation service code goes into this image.
COPY services/__init__.py ./services/__init__.py
COPY services/conversation/ ./services/conversation/

ENV PYTHONPATH=/app

EXPOSE 8004

# Chạy migrations trước khi serve (service sở hữu bảng → sở hữu migrations).
CMD ["sh", "-c", "cd services/conversation && uv run --no-sync alembic upgrade head && cd /app && exec uv run --no-sync uvicorn services.conversation.main:app --host 0.0.0.0 --port 8004"]

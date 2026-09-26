# services/rag/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# COPY cả uv.lock: build reproducible + layer deps cache riêng (xem chi tiết
# giải thích trong services/identity/Dockerfile — cùng một pattern).
# Lưu ý image này nặng (torch + sentence-transformers) — bình thường với RAG.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

# Chỉ copy code RAG vào container (+ services/__init__.py để import services.rag.*,
# Retrieval dùng prompt template của LangChain, không phụ thuộc prompt của agent.
COPY services/__init__.py ./services/__init__.py
COPY services/rag/ ./services/rag/

ENV PYTHONPATH=/app

EXPOSE 8002

# --no-sync: không re-sync lúc start — deps đã cài đủ từ build (offline start).
CMD ["uv", "run", "--no-sync", "uvicorn", "services.rag.main:app", "--host", "0.0.0.0", "--port", "8002"]

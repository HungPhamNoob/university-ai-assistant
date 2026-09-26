# services/identity/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# COPY cả uv.lock (không chỉ pyproject.toml): build reproducible theo lock và
# layer deps được cache riêng — sửa code không làm mất cache dependencies.
COPY pyproject.toml uv.lock ./
# --no-install-project: chỉ cài dependencies, chưa cần source (pattern chuẩn
# của uv cho Docker). KHÔNG dùng `|| true` — lỗi cài đặt phải fail ngay từ build.
RUN uv sync --no-dev --no-install-project

# Only the identity service code goes into this image.
COPY services/__init__.py ./services/__init__.py
COPY services/identity/ ./services/identity/

# Import trực tiếp từ source (/app) thay vì cài project wheel:
# `services` là package, các service con import được mà không cần build project.
ENV PYTHONPATH=/app

EXPOSE 8001

# Chạy migrations trước khi serve (service sở hữu bảng → sở hữu migrations).
# --no-sync: không re-sync môi trường lúc container start (deps đã đủ từ build)
# → start nhanh, không cần network.
CMD ["sh", "-c", "cd services/identity && uv run --no-sync alembic upgrade head && cd /app && exec uv run --no-sync uvicorn services.identity.app:app --host 0.0.0.0 --port 8001"]

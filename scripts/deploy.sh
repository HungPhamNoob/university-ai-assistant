#!/usr/bin/env bash
# scripts/deploy.sh — start the DEV stack from source.
set -e
cd "$(dirname "$0")/.."

# --env-file: the compose project dir is configs/, so the repo-root .env is
# not auto-discovered; pass it explicitly (POSTGRES_PASSWORD etc.).
COMPOSE="docker compose --env-file .env -f configs/docker-compose.dev.yml"

# Conversation connects to managed Redis Cloud through REDIS_URL in .env;
# this Compose stack intentionally has no Redis image or container.
$COMPOSE up -d --build
echo "Dev stack started. Health endpoints:"
echo "  frontend:     http://localhost:3000"
echo "  gateway:      http://localhost:8080"
echo "  agent:        http://localhost:8000/health"
echo "  identity:     http://localhost:8001/health"
echo "  rag:          http://localhost:8002/health"
echo "  booking:      http://localhost:8003/health"
echo "  conversation: http://localhost:8004/health"

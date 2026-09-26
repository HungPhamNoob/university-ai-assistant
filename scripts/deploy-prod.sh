#!/usr/bin/env bash
# ============================================
# scripts/deploy-prod.sh
# Deploy the production stack on this host:
#   1. Login to Amazon ECR (uses the active AWS CLI credentials).
#   2. Pull the pinned images from ECR.
#   3. (Re)start all services from configs/docker-compose.prod.yml.
#
# Usage:
#   ./scripts/deploy-prod.sh              # use IMAGE_TAG from .env (default: prod)
#   ./scripts/deploy-prod.sh <tag>        # deploy a specific image tag
# ============================================
set -euo pipefail

# Always run from the project root, no matter where the script is invoked.
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"

# 1. Sanity check: refuse to deploy without an env file.
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: env file '$ENV_FILE' not found." >&2
    echo "Copy .env.example to .env and fill in the production values first." >&2
    exit 1
fi

# Helper to read KEY=VALUE from the env file (host env always wins).
read_env_value() {
    local key="$1"
    printf '%s' "$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
}

AWS_REGION="${AWS_REGION:-$(read_env_value AWS_REGION)}"
ECR_REGISTRY="${ECR_REGISTRY:-$(read_env_value ECR_REGISTRY)}"
IMAGE_TAG="${1:-${IMAGE_TAG:-$(read_env_value IMAGE_TAG)}}"
IMAGE_TAG="${IMAGE_TAG:-prod}"

if [ -z "$AWS_REGION" ] || [ -z "$ECR_REGISTRY" ]; then
    echo "ERROR: AWS_REGION and ECR_REGISTRY must be set (env or $ENV_FILE)." >&2
    exit 1
fi

echo "==> Deploying UET HR AI to production"
echo "    Registry : $ECR_REGISTRY"
echo "    Region   : $AWS_REGION"
echo "    Image tag: $IMAGE_TAG"
export IMAGE_TAG

echo "==> Redis Cloud configured through REDIS_URL (no local Redis container)"

# 2. Docker login to ECR (password is piped in, never stored on disk).
echo "==> Logging in to Amazon ECR..."
aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY"

# 3. Pull pinned images and (re)start the stack.
echo "==> Pulling production images..."
docker compose --env-file "$ENV_FILE" -f configs/docker-compose.prod.yml pull

echo "==> Starting production stack..."
docker compose --env-file "$ENV_FILE" -f configs/docker-compose.prod.yml up -d --remove-orphans

# 4. Light cleanup of dangling images from previous deployments.
echo "==> Pruning dangling images..."
docker image prune -f

echo "==> Current status:"
docker compose --env-file "$ENV_FILE" -f configs/docker-compose.prod.yml ps

echo "==> Production deployment finished."
echo "    Frontend: http://localhost:${FRONTEND_PORT:-3000}"
echo "    Gateway : http://localhost:${GATEWAY_PORT:-8080}"

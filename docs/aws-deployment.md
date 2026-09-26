# AWS Deployment — UET HR AI

Production deployment map: **ECR (images) → ECS (compute) → RDS (PostgreSQL) → ALB (traffic)**,
plus **Qdrant Cloud** (managed vector DB/cache), **Redis Cloud** (exact-match cache),
and **S3** (document storage).

- AWS Account ID: `0050-9788-5316`
- CI user: `HungPV82_user` (IAM, programmatic access)
- Region: `ap-southeast-1` (Singapore)
- ECR registry: `005097885316.dkr.ecr.ap-southeast-1.amazonaws.com`

## 1. Architecture overview

```
                       Internet
                          │
                     ┌────▼────┐
                     │   ALB   │  (HTTP 80)
                     └────┬────┘
             ┌────────────┴────────────┐
             │ / (UI)                  │ /api/*
        ┌────▼─────┐            ┌──────▼──────┐
        │ frontend │            │   gateway   │  Kong, port 8000
        │ nginx    │            │  JWT auth   │
        │ :3000    │            └──────┬──────┘
        └──────────┘      ┌────────┬───┴────┬─────────────┐
                     ┌────▼───┐ ┌──▼───┐ ┌──▼───────┐ ┌───▼──────────┐
                     │ agent  │ │identity│ │   rag    │ │ booking /    │
                     │ :8000  │ │ :8001 │ │  :8002   │ │ conversation │
                     └───┬────┘ └───┬───┘ └────┬─────┘ │ :8003/:8004  │
                         │          │          │        └──────┬───────┘
                    ┌────▼──────────▼──────────▼───────────────▼────┐
                    │            Amazon RDS (PostgreSQL)            │
                    │            database: uet_ai_db                │
                    └────────────────────────────────────────────────┘
                                        rag ──► Qdrant Cloud (external)
                               conversation ──► Redis Cloud (external)
                                        rag ──► S3 bucket (uploads, optional)
```

Request flow: `ALB → Kong → backend` with two injected headers:

| Header               | Value                          | Checked by                      |
|----------------------|--------------------------------|---------------------------------|
| `X-User-Id`          | user_id from the verified JWT  | all internal services           |
| `X-Gateway-Token`    | `GATEWAY_SHARED_SECRET`        | agent (`AGENT_REQUIRE_GATEWAY=true`), identity, booking, conversation |

> Service discovery inside ECS uses **ECS Service Connect / Cloud Map** with the
> same short names used in `kong.yml` and docker-compose: `agent`, `identity`,
> `rag`, `booking`, `conversation`, `gateway`.

## 2. IAM — CI user `HungPV82_user`

Access key of `HungPV82_user` is stored in GitHub Actions secrets
(`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`). Minimum policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRPush",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:BatchGetImage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECSDeploy",
      "Effect": "Allow",
      "Action": [
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassTaskRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::005097885316:role/uet-ecs-task-execution-role",
        "arn:aws:iam::005097885316:role/uet-rag-task-role"
      ]
    }
  ]
}
```

## 3. ECR repositories

Create one repository per image (same names used by `.github/workflows/ci-cd.yml`):

| Repository         | Dockerfile                        |
|--------------------|-----------------------------------|
| `uet-agent`        | `services/agent/Dockerfile`       |
| `uet-identity`     | `services/identity/Dockerfile`    |
| `uet-rag`          | `services/rag/Dockerfile`         |
| `uet-booking`      | `services/booking/Dockerfile`     |
| `uet-conversation` | `services/conversation/Dockerfile`|
| `uet-gateway`      | `services/gateway/Dockerfile`     |
| `uet-frontend`     | `services/frontend/Dockerfile`    |

```bash
for svc in agent identity rag booking conversation gateway frontend; do
  aws ecr create-repository --repository-name "uet-${svc}" --region ap-southeast-1
done
```

Images are tagged `<commit-sha>` and `latest` by CI; the compose stack pins
`${IMAGE_TAG}` (default `prod`).


## 4. ECS — cluster, tasks, services

Cluster: `uet-ai-cluster` (Fargate). One task definition + one service per
container, named `uet-<service>`. All services run inside the same VPC and
talk to each other through ECS Service Connect using the short names above.

### Common environment (every backend task)

| Variable                | Source                                   |
|-------------------------|------------------------------------------|
| `POSTGRES_HOST`         | RDS endpoint                             |
| `POSTGRES_PORT`         | `5432`                                   |
| `POSTGRES_USER`         | RDS master user                          |
| `POSTGRES_PASSWORD`     | Secrets Manager / SSM (never hard-coded) |
| `POSTGRES_DB`           | `uet_ai_db`                              |
| `GATEWAY_SHARED_SECRET` | Secrets Manager                          |
| `INTERNAL_API_TOKEN`    | Secrets Manager                          |

### agent (`uet-agent`, port 8000)

| Variable                      | Value                                          |
|-------------------------------|------------------------------------------------|
| `POSTGRES_URI`                | `postgresql+psycopg://<user>:<pass>@<host>:5432/uet_ai_db` |
| `LLM_MODEL` / `API_KEY` / `BASE_URL` | production LLM gateway                 |
| `AGENT_REQUIRE_GATEWAY`       | `true` (reject any request without `X-Gateway-Token`) |
| `RAG_SERVICE_URL`             | `http://rag:8002` (Service Connect name)       |
| `BOOKING_SERVICE_URL`         | `http://booking:8003`                          |
| `CONVERSATION_SERVICE_URL`    | `http://conversation:8004`                     |
| `TAVILY_API_KEY`              | Secrets Manager                                |
| `LANGSMITH_*`                 | optional tracing                               |

### identity (`uet-identity`, port 8001)

| Variable             | Value                          |
|----------------------|--------------------------------|
| `JWT_SECRET_KEY`     | Secrets Manager (shared with gateway) |
| `JWT_EXPIRE_MINUTES` | `60`                           |
| `JWT_ISSUER`         | `uet-identity`                 |

### rag (`uet-rag`, port 8002)

| Variable                     | Value                                  |
|------------------------------|----------------------------------------|
| `QDRANT_URL` / `QDRANT_API_KEY` | Qdrant Cloud cluster (external)     |
| `QDRANT_KB_COLLECTION`       | `uet_hr_docs`                          |
| `QDRANT_CACHE_COLLECTION`    | `uet_hr_cache`                         |
| `VECTOR_SIZE`                | `384`                                  |
| `HYDE_ENABLED`               | `true`                                 |
| `HYDE_LLM_MODEL`             | `LLM_MODEL` (sentinel: use primary LLM)|
| `LLM_MODEL` / `API_KEY` / `BASE_URL` | same as agent                  |
| `STORAGE_BACKEND`            | `s3` (uses the task role below)        |
| `S3_BUCKET`                  | `uet-hr-rag-uploads`                   |

Give the **rag task role** (`uet-rag-task-role`) S3 access so
`S3DocumentStorage` can upload/download without static keys:

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
  "Resource": "arn:aws:s3:::uet-hr-rag-uploads/*"
}
```

### booking (`uet-booking`, port 8003) and conversation (`uet-conversation`, port 8004)

Booking uses the common backend variables. Conversation additionally receives
`REDIS_ENABLED=true` plus the credential-bearing `REDIS_URL` from Secrets
Manager. Local, Compose, and ECS all connect to the same managed Redis Cloud
database; no Redis container/image or `uet-redis` ECS service exists. The cache
still degrades gracefully and reconnects lazily when the managed service is
temporarily unavailable.

### gateway (`uet-gateway`, port 8000)

| Variable                | Value                                    |
|-------------------------|------------------------------------------|
| `JWT_SECRET_KEY`        | same secret as identity                  |
| `GATEWAY_SHARED_SECRET` | injected into `kong.yml` by `render-config.sh` |

Kong runs DB-less with `services/gateway/declarative/kong.yml`; upstreams are
the Service Connect names (`http://agent:8000`, ...).

### frontend (`uet-frontend`, port 3000)

| Variable               | Value                                        |
|------------------------|----------------------------------------------|
| `FRONTEND_API_BASE_URL`| empty → Next.js uses the same-origin nginx proxy to `gateway:8000` |

## 5. RDS — PostgreSQL

One shared instance (db.t3.micro is enough for the intern phase), database
`uet_ai_db`, PostgreSQL 16. All five Python services use the same tables:

| Tables                                   | Owner service  |
|------------------------------------------|----------------|
| `users`, `user_roles`                    | identity       |
| `conversations`, `messages`              | conversation   |
| `agents_checkpoints`, `agents_checkpoint_writes`, `agents_checkpoint_blobs` | agent (LangGraph) |
| `booking_requests`, `booking_history`    | booking        |

- Master username: `admin`, password in Secrets Manager.
- `POSTGRES_HOST` = the RDS writer endpoint, `POSTGRES_DB=uet_ai_db`.
- Deletion protection ON; automated backups 7 days.
- Tables are created by `init_db.py` / SQLAlchemy `Base.metadata.create_all`
  on first boot — no manual SQL needed.

## 6. Managed data services & S3

- **Qdrant Cloud**: create a free cluster, then set `QDRANT_URL` and
  `QDRANT_API_KEY` on the rag task. Collections `uet_hr_docs` (KB) and
  `uet_hr_cache` (answers) are created automatically by the rag service.
  Qdrant Cloud is public; keep the API key in Secrets Manager.
- **Redis Cloud**: set the full credential-bearing URI as `redis_url` in the
  gitignored `terraform/terraform.tfvars`. Terraform stores it under
  `REDIS_URL` in Secrets Manager and injects it only into conversation.
- **S3**: bucket `uet-hr-rag-uploads` (private, encryption on). Used only
  when `STORAGE_BACKEND=s3`; access goes through the rag task role.

## 7. ALB — Application Load Balancer

One internet-facing ALB, HTTP:80 (terminate TLS at the ALB when a domain exists).

| Target group     | Registered target | Port | Path rule          |
|------------------|-------------------|------|--------------------|
| `tg-frontend`    | frontend tasks    | 3000 | default (`/*`)     |
| `tg-gateway`     | gateway (Kong)    | 8000 | `/api/*`           |

Kong itself authenticates JWTs and strips/injects headers, so nothing
internal is exposed directly: only `frontend` and `gateway` are in any
target group.

## 8. Security groups

| Security group    | Attached to            | Inbound rules                                        |
|-------------------|------------------------|------------------------------------------------------|
| `sg-alb`          | ALB                    | 80/tcp, 443/tcp from `0.0.0.0/0`                     |
| `sg-frontend`     | frontend tasks         | 3000/tcp from `sg-alb`                               |
| `sg-gateway`      | gateway tasks          | 8000/tcp from `sg-alb`                               |
| `sg-backend`      | agent/identity/rag/booking/conversation tasks | 8000–8004/tcp from `sg-gateway` (all backend-to-backend traffic stays inside this SG) |
| `sg-rds`          | RDS instance           | 5432/tcp from `sg-backend` only                      |

Rules of thumb:

- RDS port 5432 is **never** open to the ALB or the internet.
- Backend services are **never** in a target group and have no public IPs.
- All secrets come from Secrets Manager / SSM — never baked into images.

## 9. Deployment flow

Automated (`.github/workflows/ci-cd.yml`):

1. PR → ruff lint + offline tests (`tests/test_graph.py`).
2. Push to `main` → build 7 images → push to ECR (`<sha>` + `latest`).
3. `aws ecs update-service --force-new-deployment` for every `uet-*` service.

Manual fallback on a single EC2 host (same images, compose instead of ECS):

```bash
./scripts/deploy-prod.sh          # ECR login + docker compose -f configs/docker-compose.prod.yml up -d
./scripts/deploy-prod.sh v1.2.0   # deploy a specific tag
```

The `.env` file must contain every `VAR` marked `:?` in
`configs/docker-compose.prod.yml` (Postgres, JWT, Qdrant, LLM keys,
Redis Cloud URL, `ECR_REGISTRY`, `AWS_REGION`), otherwise compose refuses to start.

## 10. Post-deploy checklist

```bash
curl http://<alb>/api/health                          # Kong route
curl http://<alb>/api/auth/health                     # identity via Kong
curl http://<alb>/api/booking/health                  # booking via Kong
curl http://<alb>/api/conversation/health             # conversation via Kong
# Full loop: register -> login -> chat via the frontend UI
```

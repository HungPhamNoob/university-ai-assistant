# terraform.md — Kiến trúc hạ tầng Terraform (`uet-hr-ai` trên AWS)

> Tài liệu thiết kế chi tiết cho `terraform/`. Đọc kèm:
> [`README.md`](README.md) (hướng dẫn deploy) · [`docs/aws-deployment.md`](../docs/aws-deployment.md) (tổng quan AWS) ·
> [`docs/architecture.md`](../docs/architecture.md) (kiến trúc ứng dụng).
>
> Mục đích chính: **(1)** mô tả từng lớp tài nguyên mà Terraform provision,
> **(2)** chỉ rõ **sửa một config ở đây thì phải sửa những file code nào**
> (bảng mapping ở §7) để infra và application code không lệch nhau.
>
> **CI/CD**: origin của repo là **GitLab** (`ssh.gitlab.ops-ai.dev`), pipeline
> thật chạy từ `.gitlab-ci.yml` ở **gốc repo** (ngoài thư mục `Final/`);
> `.github/workflows/ci-cd.yml` là bản GitHub Actions tương đương (chỉ chạy
> nếu mirror sang GitHub). Mọi quy tắc mapping tên/region/tag ở §7 áp dụng
> cho **cả hai file** — sửa một bên phải sửa bên kia.

---

## 1. Tổng quan

Stack tái hiện đúng kiến trúc Docker Compose (`configs/docker-compose.prod.yml`)
trên AWS ECS Fargate, account `005097885316`, region `ap-southeast-1`:

```mermaid
flowchart LR
    U[Browser] -->|HTTP :80| ALB[ALB internet-facing<br/>uet-ai-alb]

    subgraph VPC["VPC uet-ai-vpc — 10.20.0.0/16"]
        subgraph PUB["Public subnets (2 AZ)"]
            ALB
            NAT[NAT Gateway x1<br/>+ EIP]
        end
        subgraph PRIV["Private subnets (2 AZ)"]
            FE[ECS: uet-frontend<br/>nginx :3000]
            GW[ECS: uet-gateway<br/>Kong DB-less :8000]
            AG[ECS: uet-agent :8000]
            ID[ECS: uet-identity :8001]
            RG[ECS: uet-rag :8002]
            BK[ECS: uet-booking :8003]
            CV[ECS: uet-conversation :8004]
            RDS[(RDS Postgres 16<br/>uet-ai-postgres)]
        end
        CM[Cloud Map namespace<br/>uet.internal<br/>ECS Service Connect]
    end

    ALB -->|"/ , static"| FE
    ALB -->|"/api/* /auth/* /conversations*"| GW
    FE -->|same-origin proxy /api /auth /conversations| GW
    GW -->|JWT verify + inject X-User-*| AG & ID & RG & BK & CV
    AG -->|internal HTTP + X-Gateway-Token| RG & BK & CV
    AG & ID & BK & CV --> RDS
    AG & RG & CV -->|qua NAT| EXT[LLM API · Qdrant Cloud · Redis Cloud ·<br/>Tavily · LangSmith · ECR]

    SM[Secrets Manager<br/>uet-ai/application] -.->|secrets inject qua<br/>ECS execution role| AG & ID & RG & BK & CV & GW
    S3[S3 uet-hr-rag-uploads-*] -.->|task role riêng| RG
```

Điểm thiết kế quan trọng:

- **7 service = 7 ECS Fargate service** trong 1 cluster `uet-ai-cluster`, tên
  khớp hardcode trong `.github/workflows/ci-cd.yml`.
- **ECS Service Connect** với private DNS namespace `uet.internal`: mỗi service
  đăng ký `discovery_name` = tên service (`agent`, `rag`, ...), nên container
  resolve nhau bằng `http://rag:8002` — **giống hệt hostname Docker Compose**.
  Đó là lý do `RAG_SERVICE_URL=http://rag:8002` trong `locals.tf` và upstream
  default trong `render-config.sh` không cần đổi khi lên ECS.
- **Chỉ ALB exposed ra Internet.** Kong và 5 backend nằm ở subnet private,
  ra ngoài (LLM/Qdrant/Redis/Tavily/ECR) qua 1 NAT gateway.
- **Mọi secret runtime nằm trong 1 Secrets Manager secret** (`uet-ai/application`),
  inject vào container qua `secrets` của task definition — không bao giờ nằm
  trong plaintext `environment`.
- **Stateful**: RDS (checkpointer LangGraph + bảng business), Qdrant Cloud
  (KB + semantic cache), và Redis Cloud (exact-match cache) nằm ngoài ECS.
  S3 bucket provision sẵn cho `STORAGE_BACKEND=s3` nhưng code RAG hiện tại
  chưa dùng (xem §8).

---

## 2. Bố cục file `.tf` — vai trò từng file

| File | Vai trò | Resource chính |
|---|---|---|
| `versions.tf` | Pin Terraform `>= 1.6`, provider `aws ~> 6.0` + `random ~> 3.6`; khai báo `provider "aws"` (region + `default_tags`) | — |
| `variables.tf` | Toàn bộ input: region, CIDR, DB sizing, credentials LLM/Qdrant/Redis/Tavily/LangSmith, secret overrides, `service_desired_counts`, `image_tag` | 34 variable |
| `locals.tf` | **Trung tâm cấu hình runtime**: map 7 service (port/cpu/memory/tier), env var từng service (`service_environment`), secret key từng service (`service_secret_keys`), `coalesce` secret override ↔ random | — (kèm 2 data source `aws_caller_identity`, `aws_availability_zones`) |
| `network.tf` | VPC, IGW, 2 public + 2 private subnet, route table, EIP + 1 NAT gateway, Cloud Map namespace `uet.internal` | `aws_vpc.main`, `aws_nat_gateway.main`, `aws_service_discovery_private_dns_namespace.main` |
| `security.tf` | 5 security group: `alb`, `frontend`, `gateway`, `backend`, `rds` | `aws_security_group.*` |
| `iam.tf` | Execution role (+ policy đọc secret), task role chung, task role riêng cho RAG (+ S3), policy `ecs exec` (SSM channels) | `aws_iam_role.ecs_execution/ecs_task/rag_task` |
| `ecr.tf` | 7 ECR repo `uet-<service>` (scan on push, AES256) + lifecycle giữ 20 image mới nhất | `aws_ecr_repository.service` |
| `data.tf` | **Lớp dữ liệu**: 4 `random_password`, RDS Postgres 16, Secrets Manager secret `uet-ai/application` (11 key), S3 bucket `rag_uploads` (+ block public, SSE, versioning) | `aws_db_instance.main`, `aws_secretsmanager_secret.app`, `aws_s3_bucket.rag_uploads` |
| `ecs.tf` | CloudWatch log group `/ecs/uet-<svc>` (30 ngày), cluster `uet-ai-cluster` (Container Insights + Service Connect defaults), 7 task definition, 7 service (circuit breaker, `enable_execute_command`, LB attachment cho frontend/gateway) | `aws_ecs_cluster.main`, `aws_ecs_task_definition.service`, `aws_ecs_service.service` |
| `alb.tf` | ALB internet-facing, 2 target group (frontend `:3000`, gateway `:8000`), listener `:80` default → frontend, rule priority 10: `/api/*`, `/auth/*`, `/conversations*` → gateway | `aws_lb.main`, `aws_lb_listener_rule.gateway` |
| `outputs.tf` | `alb_url`, `ecr_registry`, `ecr_repository_urls`, `ecs_cluster_name`, `rds_endpoint`, `application_secret_arn`, `rag_upload_bucket` | — |
| `terraform.tfvars` | Giá trị thật (secret) — **gitignored**, không commit | — |
| `terraform.tfvars.example` | Template không chứa secret để commit | — |

> **Gotcha đặt tên file** (hiện trạng, không phải chuẩn): `data.tf` chứa
> *resource* (RDS/Secrets/S3/random) còn `locals.tf` lại chứa *data source*
> (`aws_caller_identity`, `aws_availability_zones`). Terraform không quan tâm
> tên file, nhưng khi tìm resource hãy nhớ quy ước ngược này.

Mọi resource lặp theo 7 service đều đi qua `for_each = local.services`
(`ecr.tf`, `ecs.tf`) — **thêm/bớt service trong `locals.tf` là ECR/task
def/log group/service tự sinh theo**, không phải copy-paste block.

---

## 3. Network (`network.tf`)

| Thành phần | Giá trị | Ghi chú |
|---|---|---|
| VPC | `10.20.0.0/16` (`var.vpc_cidr`) | DNS support + hostnames bật (bắt buộc cho Service Connect) |
| Public subnet | `10.20.0.0/24`, `10.20.1.0/24` — 2 AZ đầu tiên từ `data.aws_availability_zones` | Chứa ALB + NAT; `map_public_ip_on_launch = true` |
| Private subnet | `10.20.10.0/24`, `10.20.11.0/24` | Chứa ECS tasks + RDS; route `0.0.0.0/0` → NAT |
| NAT | **1 gateway duy nhất** đặt ở `public[0]` + 1 EIP | Chi phí cố định chính của stack; đánh đổi HA để tiết kiệm (1 NAT/AZ ~ $32/tháng). Muốn HA thật: nâng lên 2 NAT + 2 route table private |
| Cloud Map | private namespace `uet.internal` (hardcode) | Nền cho ECS Service Connect — `discovery_name`/`client_alias dns_name` = tên service nên DNS alias ngắn `http://agent:8000` hoạt động trong cluster |

Biến validation: `public_subnet_cidrs` và `private_subnet_cidrs` bắt buộc
đúng **2 phần tử** (2 AZ) — sửa số lượng subnet phải sửa cả validation trong
`variables.tf` lẫn `count = 2` trong `network.tf`.

## 4. Security groups (`security.tf`) — chuỗi trust

5 SG xếp lớp, ingress **chỉ tham chiếu SG khác, không mở CIDR** (trừ ALB):

```
Internet ──:80──► [alb] ──:3000──► [frontend] ──:8000──► [gateway]
              └──────────:8000──────────────────────▲ (ALB → Kong trực tiếp)
[gateway] ──:8000-8004──► [backend]   (Kong → 5 Python service)
[backend] ──self :8000-8004──► [backend]   (service-to-service, vd agent → rag)
[backend] ──:5432──► [rds]
```

| SG | Gắn cho | Ingress |
|---|---|---|
| `alb` | ALB | `:80` từ `0.0.0.0/0` |
| `frontend` | task `frontend` | `:3000` từ SG `alb` |
| `gateway` | task `gateway` | `:8000` từ SG `alb` **và** SG `frontend` (nginx same-origin proxy) |
| `backend` | 5 task Python (tier `backend`) | `:8000-8004` từ SG `gateway` + `self` |
| `rds` | RDS instance | `:5432` từ SG `backend` |

Lưu ý: **gateway KHÔNG nằm trong SG `backend`** — Kong không gọi thẳng RDS;
mọi DB access đi qua identity/booking/conversation. Mapping tier → SG nằm ở
`ecs.tf` (`network_configuration.security_groups`, theo `local.services[*].tier`).

Chưa có HTTPS: listener chỉ có `:80`. Thêm TLS = sửa `alb.tf` (ACM
certificate + listener `:443` + redirect 80→443) — không đụng code service.

## 5. IAM (`iam.tf`)

| Role | Ai dùng | Quyền |
|---|---|---|
| `uet-ecs-task-execution-role` | **execution role** của cả 7 task def | `AmazonECSTaskExecutionRolePolicy` (pull image, đẩy log) + `secretsmanager:GetSecretValue` **chỉ** trên ARN của `aws_secretsmanager_secret.app` |
| `uet-ecs-task-role` | task role của 6 service (mọi service trừ rag) | `ssmmessages:*` 4 action (cho `aws ecs execute-command` debug container) |
| `uet-rag-task-role` | task role riêng của `rag` | ecs-exec như trên + S3 `Get/Put/DeleteObject` trên `uet-hr-rag-uploads-*/*` và `ListBucket` |

Logic chọn role nằm ở `ecs.tf`:
`task_role_arn = each.key == "rag" ? aws_iam_role.rag_task.arn : aws_iam_role.ecs_task.arn`
— thêm service cần quyền AWS riêng thì theo pattern này (role mới + sửa
ternary thành lookup map).

## 6. Data layer (`data.tf`) + ECS/ALB (`ecs.tf`, `alb.tf`)

### 6.1 RDS Postgres 16

- `db.t3.micro`, gp3 20 GiB (autoscale tới 100), single-AZ, `storage_encrypted`,
  không public, SG `rds`.
- Backup 7 ngày, cửa sổ `18:00-19:00` UTC; `deletion_protection = true` mặc định
  (muốn destroy phải set `db_deletion_protection = false` trong tfvars trước).
- `password = local.postgres_password` = `coalesce(var.postgres_password, random_password.postgres.result)`.
- Migration: **không có gì trong Terraform** — container CMD tự chạy
  `alembic upgrade head` trước khi serve (Dockerfile của identity/booking/conversation).
  Agent không cần migration (LangGraph checkpointer tự tạo bảng).

### 6.2 Secrets Manager — `uet-ai/application`

Một secret JSON duy nhất, 11 key, task definition inject theo tên key
(`valueFrom = "<arn>:<KEY>::"`):

| Key trong secret | Nguồn giá trị | Service consume (qua `local.service_secret_keys`) |
|---|---|---|
| `POSTGRES_PASSWORD` | random 32 ký tự | identity, booking, conversation |
| `POSTGRES_URI` | **ghép sẵn** `postgresql+psycopg://user:pass@rds-address:5432/db` | agent (LangGraph checkpointer dùng sync URI driver `psycopg`) |
| `JWT_SECRET_KEY` | random 64 | identity (ký JWT), gateway (Kong verify — `render-config.sh`) |
| `GATEWAY_SHARED_SECRET` | random 48 | cả 7 trừ frontend, rag* (giá trị `X-Gateway-Token` Kong inject) |
| `INTERNAL_API_TOKEN` | random 48 | agent, booking, conversation (service-to-service) |
| `API_KEY` | `var.llm_api_key` | agent, rag, conversation |
| `API_KEY_2` | `var.backup_llm_api_key` | agent (failover LLM) |
| `QDRANT_API_KEY` | `var.qdrant_api_key` | rag |
| `REDIS_URL` | `var.redis_url` | conversation |
| `TAVILY_API_KEY` | `var.tavily_api_key` | agent |
| `LANGSMITH_API_KEY` | `var.langsmith_api_key` | agent, rag |

\* danh sách chính xác theo service: xem `local.service_secret_keys` trong
`locals.tf` — frontend nhận `[]`, rag không nhận `GATEWAY_SHARED_SECRET`
(RAG chỉ được gọi nội bộ, không expose route ghi qua Kong).

Cùng một `JWT_SECRET_KEY`/`GATEWAY_SHARED_SECRET` được phát cho cả hai phía
(identity↔Kong, Kong↔backends) **từ một nguồn duy nhất** nên không thể lệch —
đây là khác biệt cốt lõi so với dev (phải tự đồng bộ trong `.env`).

### 6.3 S3 — `uet-hr-rag-uploads-<account>-<region>`

Block public ACL/policy, SSE AES256, versioning Enabled. Provision sẵn cho
`STORAGE_BACKEND=s3` — **code RAG hiện chưa đọc bucket này** (xem §8).

### 6.4 ECS

- **Cluster** `uet-ai-cluster`: Container Insights enabled, `service_connect_defaults`
  trỏ namespace `uet.internal`.
- **Task definition** (1/service): Fargate, `awsvpc`, X86_64, cpu/memory từ
  `local.services` (rag nặng nhất 1024/4096 vì load model sentence-transformers
  local; frontend nhẹ nhất 256/512). `environment` = plaintext từ
  `local.service_environment`, `secrets` = từ `local.service_secret_keys`.
- **Health check trong container** (khác ALB health check):
  - 5 Python service: `python -c urllib.request.urlopen('http://127.0.0.1:<port>/health')`
    → **yêu cầu mọi service phải có route `/health`** trong `main.py`/`app.py`.
  - gateway: `kong health`; frontend: `wget http://127.0.0.1:3000/`.
  - `startPeriod` của rag = 120s (thời gian download/load model lần đầu).
- **Service**: `desired_count` từ `var.service_desired_counts` (bootstrap = 0),
  deployment circuit breaker + auto rollback, `enable_execute_command = true`
  (debug qua `aws ecs execute-command`, cần policy ecs-exec ở `iam.tf`),
  `health_check_grace_period_seconds = 120` cho frontend/gateway (2 service gắn ALB).
- **Service Connect**: mỗi service publish `port_name = discovery_name = dns_name = <tên service>`,
  port = port container → DNS alias `http://<service>:<port>` trong cluster.
- **LB attachment**: chỉ frontend và gateway gắn target group (dynamic block
  `load_balancer` trong `aws_ecs_service.service`).

### 6.5 ALB (`alb.tf`)

- Internet-facing, đặt trên 2 public subnet, `drop_invalid_header_fields = true`.
- Listener `:80`: **default action → target group frontend**; rule priority 10:
  path `/api/*`, `/auth/*`, `/conversations*` → target group gateway.
- Health check target group: frontend `/` matcher `200-399`; gateway `/` matcher
  `200-499` (Kong trả 404 cho `/` khi không có route root — vẫn là "alive").
- Hai đường vào Kong (ALB rule và nginx proxy) cùng tồn tại: browser có thể đi
  same-origin qua frontend nginx (`proxy_pass http://gateway:8000` — resolve nhờ
  Service Connect) hoặc ALB route thẳng. `FRONTEND_API_BASE_URL = ""` trong
  `locals.tf` → `entrypoint.sh` sinh config `proxyGateway: true` (đường nginx).

---

## 7. ⭐ Sửa config ở đây → sửa file code nào?

Nguyên tắc chung: Terraform chỉ **cung cấp env var/secret/hạ tầng**; code
Python đọc chúng qua pydantic `Settings`. Đổi *giá trị* (model name, threshold,
budget...) thường **không cần sửa code**. Đổi *tên key, port, tên service,
đường dẫn route* thì **bắt buộc** sửa đồng bộ các file dưới đây.

### 7.0 File config trung tâm của từng service (nơi env var được đọc)

| Service | File Settings | Env prefix liên quan trong `locals.tf` |
|---|---|---|
| agent | `services/agent/config.py` | `service_environment.agent` |
| rag | `services/rag/config.py` | `service_environment.rag` |
| identity | `services/identity/settings.py` | `service_environment.identity` |
| booking | `services/booking/settings.py` | `service_environment.booking` |
| conversation | `services/conversation/settings.py` | `service_environment.conversation` |
| gateway | `services/gateway/declarative/kong.yml` + `services/gateway/render-config.sh` | `service_environment.gateway` (`KONG_DATABASE=off`) |
| frontend | `services/frontend/nginx/entrypoint.sh` → sinh `static/js/runtime-config.js` + `services/frontend/nginx/default.conf` | `service_environment.frontend` (`FRONTEND_API_BASE_URL`) |

### 7.1 Đổi PORT của một service (`local.services.<svc>.port`)

Phía Terraform tự đồng bộ (task def, Service Connect, SG backend dùng range
8000-8004). Phía **code phải sửa tay**:

| File cần sửa | Chỗ sửa |
|---|---|
| `services/<svc>/Dockerfile` | `EXPOSE` + `uvicorn --port` trong `CMD` |
| `services/gateway/declarative/kong.yml` | `url: http://__<SVC>_UPSTREAM__:<port>` |
| `services/frontend/nginx/default.conf` | `proxy_pass http://gateway:<port>` (chỉ khi đổi port **gateway**) |
| `locals.tf` → `service_environment.agent` | `RAG_SERVICE_URL` / `BOOKING_SERVICE_URL` / `CONVERSATION_SERVICE_URL` (agent gọi service khác bằng port cứng) |
| `configs/docker-compose.dev.yml`, `configs/docker-compose.prod.yml` | ports mapping + healthcheck |
| `scripts/local.sh` | port khi chạy uvicorn native + health-check + Kong upstream override |
| `.env.example` / `.env` | `<SVC>_PORT`, `AGENT_SERVICE_URL` (cli.py/eval đọc) |
| `security.tf` | chỉ khi port mới **ra ngoài** range 8000-8004 (sửa ingress SG `backend`) |
| `alb.tf` | chỉ khi đổi port frontend/gateway — target group tự lấy từ `local.services`, không cần sửa tay |

### 7.2 Thêm service MỚI (service thứ 8)

| File | Việc phải làm |
|---|---|
| `locals.tf` | thêm entry vào **cả 3 map**: `services` (port/cpu/memory/tier), `service_environment`, `service_secret_keys` |
| `services/<new>/Dockerfile` | EXPOSE + CMD (nếu có DB: `alembic upgrade head && uvicorn ...` theo pattern booking) |
| `.github/workflows/ci-cd.yml` | thêm vào `matrix.include` (repo `uet-<new>` + dockerfile) **và** vòng lặp `for service in ...` của job `deploy-ecs` |
| `services/gateway/declarative/kong.yml` | thêm `services:` entry + route (+ jwt/post-function plugin nếu route protected) |
| `services/gateway/render-config.sh` | thêm placeholder `__<NEW>_UPSTREAM__` + sed |
| `alb.tf` | thêm path pattern vào `aws_lb_listener_rule.gateway` nếu route đi qua Kong |
| `security.tf` | chỉ khi port ngoài 8000-8004 |
| `data.tf` | thêm key secret mới vào `secret_string` nếu service cần secret riêng |
| `configs/docker-compose.*.yml`, `scripts/local.sh` | parity môi trường dev |

ECR repo, log group, task def, ECS service, Service Connect alias **tự sinh**
qua `for_each = local.services`.

### 7.3 Đổi GIÁ TRỊ env var runtime (model, threshold, token budget, HyDE...)

Sửa `local.service_environment.<svc>` trong `locals.tf` → `terraform apply` →
ECS rolling deploy. **Không cần sửa code** nếu key đã tồn tại trong file
Settings của service (mục 7.0). Nếu là **key mới**: thêm field vào Settings
tương ứng + `.env.example` (dev parity) + `configs/docker-compose.*.yml` nếu dev cần.

Ví dụ thực tế: `TOKEN_BUDGET_*`/`CONTEXT_LIMIT` trong `locals.tf` phải khớp
field trong `services/agent/config.py`; `EPISODIC_*` khớp
`services/conversation/settings.py`; `HYDE_*`/`CACHE_*` khớp `services/rag/config.py`.

### 7.4 Thêm/đổi SECRET

| Bước | File |
|---|---|
| 1. Khai báo input (nếu user cấp) | `variables.tf` (`sensitive = true`) + `terraform.tfvars` / `.example` |
| 2. Đưa vào secret JSON | `data.tf` → `aws_secretsmanager_secret_version.app.secret_string` |
| 3. Phát cho service | `locals.tf` → `service_secret_keys.<svc>` (đúng tên key JSON) |
| 4. Code đọc | Settings file của service (7.0) — field **cùng tên** với key |
| 5. Dev parity | `.env.example`, `configs/docker-compose.*.yml` |

Không cần sửa `ecs.tf` — block `secrets` sinh từ `service_secret_keys`.
Đổi **giá trị** secret (rotate key LLM...): chỉ sửa `terraform.tfvars` →
apply → **force new deployment** (`aws ecs update-service --force-new-deployment`,
như job `deploy-ecs` trong CI) vì ECS chỉ đọc secret lúc task start.

### 7.5 Đổi đường dẫn API (ALB rule / Kong route)

Path `/api/*`, `/auth/*`, `/conversations*` xuất hiện ở **4 tầng**, đổi một
chỗ phải đổi cả bốn:

1. `alb.tf` → `aws_lb_listener_rule.gateway.condition.path_pattern`
2. `services/gateway/declarative/kong.yml` → `routes[].paths`
3. `services/frontend/nginx/default.conf` → các `location` proxy
4. Frontend JS gọi API (`services/frontend/static/js/`) + route prefix trong
   code service (`services/*/main.py`, `routers/`, `routes/`) + `cli.py`/`eval/*`

### 7.6 Đổi `project_name` / tên cluster / tên ECR repo

⚠️ **Phá vỡ**: tên resource AWS đổi = Terraform destroy + create lại (ECR repo
mất toàn bộ image). Nếu buộc phải đổi:

- `.github/workflows/ci-cd.yml`: `ECS_CLUSTER`, danh sách repo `uet-*` trong
  matrix, prefix `uet-${service}` trong `deploy-ecs`.
- `scripts/deploy-prod.sh`, `docs/aws-deployment.md` nếu hardcode tên.

### 7.7 Đổi region

- `terraform.tfvars` (`aws_region`) — provider + log config tự theo `var.aws_region`.
- `.github/workflows/ci-cd.yml`: `AWS_REGION` + `ECR_REGISTRY` (hardcode
  `005097885316.dkr.ecr.ap-southeast-1.amazonaws.com` — phải sửa tay, đối chiếu
  output `ecr_registry`).
- `docs/aws-deployment.md`, `scripts/deploy-prod.sh`.

### 7.8 Đổi CPU/memory task

Chỉ `local.services.<svc>.cpu/memory` trong `locals.tf`. Ràng buộc Fargate:
cặp cpu/memory hợp lệ (512→1024/2048/3072/4096; 1024→2048..8192; 256→512/1024/2048).
Không cần sửa Dockerfile/code.

### 7.9 Đổi DB (`postgres_db`, `postgres_user`, instance class, storage)

- Instance class/storage: tfvars, không đụng code.
- `postgres_db`/`postgres_user`: `data.tf` tự ghép `POSTGRES_URI` secret và
  `common_database_environment` — code không cần sửa (đọc từ env). Nhưng DB
  **đã tồn tại** thì đổi tên = migrate dữ liệu tay; và sửa `.env` local +
  `configs/docker-compose.dev.yml` (Postgres dev) để parity.

### 7.10 Đổi `image_tag`

`terraform.tfvars` (`image_tag`) phải khớp tag CI push — hiện CI push cả
`latest` và `<git-sha>` (`.github/workflows/ci-cd.yml` step "Build and push image").
Deploy theo SHA (immutable, rollback được): set `image_tag = "<sha>"`.

### 7.11 Đổi health check

- **Container health check** (`ecs.tf` block `healthCheck`): Python service dựa
  vào route `/health` trong `services/<svc>/main.py` (identity: `app.py`) —
  đổi path/code phải sửa cả hai phía.
- **ALB health check** (`alb.tf` `health_check` block): frontend dựa vào nginx
  serve `/`; gateway dựa vào Kong trả lời `/` (bất kỳ status < 500).

### 7.12 Frontend API base

`FRONTEND_API_BASE_URL` (plaintext env, đang là `""` = same-origin qua nginx
proxy). Nếu chuyển sang gọi Kong trực tiếp bằng absolute URL: sửa
`locals.tf` + kiểm tra CORS trong `kong.yml` (plugin `cors` đang để
`origins: ["*"]`) — `entrypoint.sh` và `runtime-config.js` tự xử lý phần còn lại.

---

## 8. Khác biệt có chủ đích so với môi trường dev & gotcha

1. **S3 `rag_uploads` provision nhưng chưa dùng**: `services/rag/storage.py`
   đã bị xóa; RAG ingest đọc file local → Qdrant. Bucket + IAM sẵn sàng cho
   `STORAGE_BACKEND=s3` khi implement lại.
2. **Redis luôn là Cloud** (cả dev lẫn prod): Terraform không tạo Redis ECS
   service/container/image. `redis_url` là sensitive input trong tfvars, được
   lưu thành `REDIS_URL` trong Secrets Manager và chỉ inject vào conversation.
   Redis Cloud lỗi tạm thời → conversation tự fallback no-cache và lazy reconnect.
3. **Qdrant luôn là Cloud** (cả dev lẫn prod) — Terraform không tạo Qdrant;
   `qdrant_url`/`qdrant_api_key` đến từ tfvars. Khác region (cluster đang ở
   `sa-east-1`) → traffic RAG↔Qdrant đi qua NAT, latency cao hơn intra-region.
4. **Secret nội bộ KHÔNG dùng lại giá trị `.env` dev** (`secret_password`,
   `your-super-secret-jwt-key-change-in-prod`...): Terraform tự sinh random
   (xem `terraform.tfvars` — các key này giữ comment). Hệ quả: JWT/session
   dev không dùng được trên prod và ngược lại — đúng ý đồ.
5. **State local**: chưa có remote backend — `terraform.tfstate` chứa secret
   plaintext, đang gitignore. Trước khi dùng theo team: chuyển S3 backend +
   DynamoDB lock (README.md mục Notes).
6. **1 NAT gateway**: single point of failure cho mọi outbound (LLM/Qdrant/ECR
   pull). Chấp nhận được cho 1 môi trường demo/production nhỏ.
7. **`HYDE_LLM_MODEL = "LLM_MODEL"`** trong `service_environment.rag` là
   *sentinel string* có chủ đích: code RAG hiểu giá trị chữ `"LLM_MODEL"` =
   "tái sử dụng model chat primary" (`services/rag/config.py`). Đừng "sửa"
   thành tên model thật nếu không có nhu cầu tách model HyDE.
8. **Bootstrap theo thứ tự** (README.md): apply với `service_desired_counts`
   toàn 0 → CI push 7 image `latest` → bỏ override, apply lần 2. ECS service
   không start được nếu ECR repo rỗng (deployment circuit breaker sẽ rollback).

---

## 9. Tham chiếu nhanh: variable → nơi tiêu thụ

| Variable (`variables.tf`) | Tiêu thụ bởi |
|---|---|
| `aws_region` | `versions.tf` provider, log config trong `ecs.tf`, output `ecr_registry` |
| `project_name` | tên ECR/ECS/IAM/SG/target group (`uet-*`, `uet-ai-*`) — khớp `ci-cd.yml` |
| `vpc_cidr`, `public/private_subnet_cidrs` | `network.tf` |
| `image_tag` | `aws_ecs_task_definition.service` (image URL) |
| `service_desired_counts` | `aws_ecs_service.service.desired_count` |
| `db_*`, `postgres_user/db/password` | `data.tf` (RDS + `POSTGRES_URI` secret) |
| `jwt_secret_key`, `gateway_shared_secret`, `internal_api_token` | `data.tf` secret JSON → identity/gateway/agent/booking/conversation |
| `llm_model/base_url/api_key`, `backup_llm_*` | `common_llm_environment` + secret `API_KEY`/`API_KEY_2` → agent/rag/conversation |
| `qdrant_url/api_key` | `service_environment.rag` + secret → rag |
| `redis_url` | secret `REDIS_URL` → conversation |
| `tavily_api_key` | secret → agent (`tools.py` web search) |
| `langsmith_*` | `service_environment.agent/rag` + secret |
| `rag_upload_bucket_name` | `data.tf` S3 bucket |
| `tags` | merge vào `local.common_tags` → `default_tags` toàn provider |

#!/usr/bin/env bash
# ============================================
# local.sh — chạy FULL stack UET AI local chỉ với 1 lệnh:
#   - 5 Python services (agent/identity/rag/booking/conversation): chạy NATIVE bằng uv
#   - Docker CHỈ cho thứ bắt buộc: Postgres, Kong gateway, frontend nginx
#     (image tự pull nếu thiếu)
#   - Qdrant: LUÔN dùng Qdrant Cloud theo QDRANT_URL trong .env —
#     KHÔNG chạy qdrant docker local (script từ chối nếu .env trỏ localhost)
#   - Redis: dùng Redis Cloud qua REDIS_URL; KHÔNG chạy container/image local
#
# Usage (chạy bằng bash, không cần uv run):
#   bash scripts/local.sh           # up tất cả + health check
#   bash scripts/local.sh status    # kiểm tra services + gateway/frontend + Redis Cloud
#   bash scripts/local.sh stop      # tắt app (5 services + gateway + frontend), GIỮ Postgres/Qdrant
#   bash scripts/local.sh down      # tắt + xóa TOÀN BỘ container (data giữ trong volume)
#
# Sau khi up:
#   Web UI:  http://localhost:3000   (nginx -> Kong :8080 -> services)
#   Gateway: http://localhost:8080   (Kong proxy — JWT + X-User-* injection)
#   uv run python cli.py             # chat tương tác (REPL)
#   bash scripts/run_all_queries.sh  # test TOÀN BỘ eval/queries.txt qua cli.py
# ============================================
set -e
# cd vào thư mục chứa script; nếu không có .env ở đó (vd script nằm trong scripts/)
# thì lùi lên repo root — chạy được cả `bash local.sh` lẫn `bash scripts/local.sh`.
cd "$(dirname "$0")"
[[ -f .env ]] || cd ..

# Load toàn bộ biến môi trường từ .env (API keys, Postgres, ports...)
set -a && source .env && set +a

# Qdrant: LUÔN dùng Qdrant Cloud (quy ước project: local hay AWS đều dùng
# cloud, không dùng qdrant docker). .env trỏ localhost là cấu hình sai ->
# dừng sớm với hướng dẫn rõ ràng thay vì âm thầm chạy local.
QDRANT_URL="${QDRANT_URL:?Thieu QDRANT_URL trong .env}"
case "$QDRANT_URL" in
  *localhost*|*127.0.0.1*)
    echo "❌ QDRANT_URL trong .env đang trỏ local ($QDRANT_URL)." >&2
    echo "   Project dùng Qdrant Cloud cho mọi môi trường — đặt QDRANT_URL" >&2
    echo "   = https://<cluster>.cloud.qdrant.io:6333 trong .env." >&2
    exit 1
    ;;
esac
export QDRANT_URL

# Redis Cloud is the only supported Redis deployment. Fail early when the
# credential is missing or still points at a local instance.
REDIS_URL="${REDIS_URL:?Thieu REDIS_URL trong .env}"
case "$REDIS_URL" in
  *localhost*|*127.0.0.1*)
    echo "❌ REDIS_URL trong .env đang trỏ local." >&2
    echo "   Project dùng Redis Cloud cho mọi môi trường." >&2
    exit 1
    ;;
esac
export REDIS_URL

LOG_DIR=logs
mkdir -p "$LOG_DIR"

AGENT_PORT=${AGENT_PORT:-8000}
IDENTITY_PORT=${IDENTITY_PORT:-8001}
RAG_PORT=${RAG_PORT:-8002}
BOOKING_PORT=${BOOKING_PORT:-8003}
CONVERSATION_PORT=${CONVERSATION_PORT:-8004}
# Gateway + frontend chạy trong Docker; port publish khai báo trong
# docker-compose.dev.yml (${GATEWAY_PORT:-8080}:8000 / ${FRONTEND_PORT:-3000}:3000).
GATEWAY_PORT=${GATEWAY_PORT:-8080}
FRONTEND_PORT=${FRONTEND_PORT:-3000}

COMPOSE="docker compose --env-file .env -f configs/docker-compose.dev.yml"

kill_port() {
  local pids
  pids=$(lsof -ti:"$1" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "  Killing old process(es) on port $1: $(echo $pids | tr '\n' ' ')"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

start_service() { # $1=module  $2=port  $3=logfile
  kill_port "$2"
  # --host 0.0.0.0 (KHÔNG phải 127.0.0.1): Kong gateway chạy trong Docker
  # gọi services qua host.docker.internal (= IP bridge của host). Nếu bind
  # loopback thì container không kết nối được. Chỉ acceptable cho local dev.
  nohup uv run uvicorn "$1" --host 0.0.0.0 --port "$2" >"$LOG_DIR/$3" 2>&1 &
  echo "  ▶ $1 -> http://localhost:$2  (pid $!, log: $LOG_DIR/$3)"
}

wait_health() { # $1=name  $2=port  $3=max_seconds
  local name=$1 port=$2 tries=${3:-90}
  for _ in $(seq 1 "$tries"); do
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      echo "  ✅ $name (:$port) healthy"
      return 0
    fi
    sleep 1
  done
  echo "  ❌ $name (:$port) KHÔNG khởi động được — xem $LOG_DIR/ và $0 status" >&2
  return 1
}

wait_http_any() { # $1=name  $2=port  $3=max_seconds
  # Chấp nhận MỌI HTTP status: Kong DB-less trả 404 cho path không có route,
  # nhưng có HTTP response nghĩa là proxy đã listen. Code 000 = chưa kết nối được.
  # Lưu ý: `|| code=000` (gán) chứ không phải `|| echo 000` (sẽ NỐI chuỗi
  # thành "000000" vì curl đã tự in 000 khi không kết nối được).
  local name=$1 port=$2 tries=${3:-60} code
  for _ in $(seq 1 "$tries"); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$port/" 2>/dev/null) || code=000
    if [[ "$code" != "000" ]]; then
      echo "  ✅ $name (:$port) đang chạy (HTTP $code)"
      return 0
    fi
    sleep 1
  done
  echo "  ❌ $name (:$port) KHÔNG khởi động được — xem: $COMPOSE logs $name" >&2
  return 1
}

check_redis_cloud() {
  # redis-py parses credentials and both redis:// / rediss:// safely. Never
  # print REDIS_URL because it contains the database password.
  uv run python - <<'PY'
import os

from redis import Redis
from redis.exceptions import RedisError

client = Redis.from_url(
    os.environ["REDIS_URL"],
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
)

try:
    client.ping()
except RedisError:
    raise SystemExit(1)
finally:
    client.close()
PY
}

ensure_postgres_database() {
  # POSTGRES_DB is only created automatically when Docker initializes a fresh
  # volume. A renamed database on an existing volume therefore needs this
  # explicit, idempotent bootstrap.
  uv run python - <<'PY'
import os
import re

import psycopg
from psycopg import sql

database = os.environ.get("POSTGRES_DB", "uet_ai_db")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
    raise SystemExit("POSTGRES_DB contains unsupported characters")

connection = psycopg.connect(
    host=os.environ.get("POSTGRES_HOST", "localhost"),
    port=int(os.environ.get("POSTGRES_PORT", "5432")),
    user=os.environ.get("POSTGRES_USER", "admin"),
    password=os.environ.get("POSTGRES_PASSWORD", ""),
    dbname="postgres",
    autocommit=True,
)
try:
    exists = connection.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (database,),
    ).fetchone()
    if not exists:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        print(f"  ✅ Created PostgreSQL database: {database}")
    else:
        print(f"  ✅ PostgreSQL database exists: {database}")
finally:
    connection.close()
PY
}

status() {
  local pair name port code
  for pair in "agent:$AGENT_PORT" "identity:$IDENTITY_PORT" "rag:$RAG_PORT" \
              "booking:$BOOKING_PORT" "conversation:$CONVERSATION_PORT"; do
    name=${pair%%:*}; port=${pair##*:}
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      echo "  ✅ $name -> http://localhost:$port/health"
    else
      echo "  ❌ $name -> http://localhost:$port (DOWN)"
    fi
  done
  # Gateway (Kong) + frontend (nginx) — chạy Docker, không có /health:
  # mọi HTTP status != 000 nghĩa là container đang listen.
  for pair in "gateway:$GATEWAY_PORT" "frontend:$FRONTEND_PORT"; do
    name=${pair%%:*}; port=${pair##*:}
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$port/" 2>/dev/null) || code=000
    if [[ "$code" != "000" ]]; then
      echo "  ✅ $name -> http://localhost:$port (HTTP $code)"
    else
      echo "  ❌ $name -> http://localhost:$port (DOWN)"
    fi
  done
  if check_redis_cloud; then
    echo "  ✅ Redis Cloud -> PONG"
  else
    echo "  ❌ Redis Cloud -> không kết nối được"
  fi
}

stop_services() {
  local port
  for port in "$AGENT_PORT" "$IDENTITY_PORT" "$RAG_PORT" "$BOOKING_PORT" "$CONVERSATION_PORT"; do
    kill_port "$port"
  done
  # Dừng gateway + frontend (container) nhưng giữ Postgres; Qdrant/Redis ở cloud.
  $COMPOSE stop gateway frontend >/dev/null 2>&1 || true
}

case "${1:-up}" in
  up)
    # Fail-fast: render-config.sh của gateway cần 2 secret này lúc container
    # start — thiếu chúng thì Kong crash-loop với log khó hiểu.
    if [[ -z "${JWT_SECRET_KEY:-}" || -z "${GATEWAY_SHARED_SECRET:-}" ]]; then
      echo "❌ .env thiếu JWT_SECRET_KEY hoặc GATEWAY_SHARED_SECRET — gateway không start được." >&2
      echo "   Copy .env.example -> .env và điền đủ giá trị." >&2
      exit 1
    fi

    echo "=== 0) uv sync (đồng bộ .venv theo pyproject.toml + uv.lock) ==="
    uv sync

    echo "=== 1) Postgres (docker) + managed cloud checks ==="
    # Idempotent: nếu Postgres ĐÃ chạy sẵn trên localhost:$POSTGRES_PORT (ví dụ
    # container standalone ngoài compose project) thì dùng luôn nó — tránh lỗi
    # "port is already allocated" làm chết cả script.
    PG_PORT=${POSTGRES_PORT:-5432}
    if (exec 3<>"/dev/tcp/localhost/$PG_PORT") 2>/dev/null; then
      exec 3>&- 3<&- || true
      echo "  ✅ Postgres đã chạy sẵn trên localhost:$PG_PORT — bỏ qua compose postgres"
    else
      $COMPOSE up -d postgres
      echo "Waiting for Postgres..."
      for _ in $(seq 1 30); do
        CID=$($COMPOSE ps -q postgres 2>/dev/null || true)
        if [[ -n "$CID" ]] && docker exec "$CID" pg_isready -U "${POSTGRES_USER:-admin}" -d "${POSTGRES_DB:-uet_ai_db}" >/dev/null 2>&1; then
          echo "  ✅ Postgres ready — localhost:$PG_PORT db=${POSTGRES_DB:-uet_ai_db} user=${POSTGRES_USER:-admin}"
          break
        fi
        sleep 1
      done
    fi
    ensure_postgres_database
    # Qdrant Cloud: fail-fast nếu không kết nối được — rag/agent/conversation
    # đều phụ thuộc Qdrant, cloud chết thì cả stack vô nghĩa.
    echo "  ▶ Qdrant Cloud: $QDRANT_URL"
    qdrant_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
      -H "api-key: ${QDRANT_API_KEY:-}" "$QDRANT_URL/collections") || qdrant_code=000
    if [[ "$qdrant_code" == "200" ]]; then
      echo "  ✅ Qdrant Cloud kết nối OK"
    else
      echo "  ❌ Qdrant Cloud không phản hồi (HTTP $qdrant_code)." >&2
      echo "     Kiểm tra QDRANT_URL / QDRANT_API_KEY trong .env." >&2
      exit 1
    fi

    if check_redis_cloud; then
      echo "  ✅ Redis Cloud kết nối OK"
    else
      echo "  ❌ Redis Cloud không phản hồi." >&2
      echo "     Kiểm tra REDIS_URL trong .env." >&2
      exit 1
    fi

    echo "=== 2) Qdrant collections + knowledge base ==="
    # Idempotent: tạo collection KB + semantic cache nếu chưa có (README step 4).
    uv run python scripts/create_collections.py
    # Re-index when the source PDF changes. The local marker prevents repeated
    # costly embedding on the same laptop, while a missing marker deliberately
    # forces one verified ingest even when a cloud collection already exists.
    KB_COLL=${QDRANT_KB_COLLECTION:-uet_hr_docs}
    SOURCE_FILE=${FILE_PATH:-data/UET_HR.pdf}
    [[ -f "$SOURCE_FILE" ]] || {
      echo "  ❌ Không tìm thấy source PDF: $SOURCE_FILE" >&2
      exit 1
    }
    mkdir -p tmp
    SOURCE_HASH=$(sha256sum "$SOURCE_FILE" | awk '{print $1}')
    HASH_MARKER="tmp/${KB_COLL}.source.sha256"
    STORED_HASH=""
    if [[ -f "$HASH_MARKER" ]]; then
      STORED_HASH=$(tr -d '[:space:]' <"$HASH_MARKER")
    fi
    kb_points=$(curl -s -H "api-key: ${QDRANT_API_KEY:-}" "$QDRANT_URL/collections/$KB_COLL" | grep -o '"points_count":[0-9]*' | head -1 | grep -o '[0-9]*' || true)
    if [[ -z "$kb_points" || "$kb_points" == "0" || "$SOURCE_HASH" != "$STORED_HASH" ]]; then
      echo "  ▶ PDF mới/chưa xác minh -> reingest '$SOURCE_FILE' vào '$KB_COLL'..."
      uv run python -m services.rag.ingestion.run --file "$SOURCE_FILE"
      printf '%s\n' "$SOURCE_HASH" >"$HASH_MARKER"
      kb_points=$(curl -s -H "api-key: ${QDRANT_API_KEY:-}" "$QDRANT_URL/collections/$KB_COLL" | grep -o '"points_count":[0-9]*' | head -1 | grep -o '[0-9]*' || true)
      [[ -n "$kb_points" && "$kb_points" != "0" ]] || {
        echo "  ❌ Reingest kết thúc nhưng collection không có point." >&2
        exit 1
      }
      echo "  ✅ KB '$KB_COLL' đã reingest: $kb_points points"
    else
      echo "  ✅ KB '$KB_COLL' khớp SHA-256 hiện tại ($kb_points points)"
    fi

    echo "=== 2b) Alembic migrations (identity, booking, conversation) ==="
    # Service nào sở hữu bảng DB thì sở hữu migrations: chạy `alembic upgrade head`
    # trước khi uvicorn serve (agent không cần — checkpointer do LangGraph tự quản).
    for svc in identity booking conversation; do
      echo "  ▶ Chạy migrations cho $svc ..."
      (cd "services/$svc" && uv run alembic upgrade head) \
        || { echo "  ❌ Migration $svc thất bại — dừng stack (xem logs/ hoặc chạy thủ công)." >&2; exit 1; }
    done

    echo "=== 3) 5 services (uvicorn chạy nền) ==="
    start_service services.rag.main:app          "$RAG_PORT"          rag.log          # load model chậm nhất -> khởi động trước
    start_service services.identity.app:app      "$IDENTITY_PORT"     identity.log
    start_service services.booking.main:app      "$BOOKING_PORT"      booking.log
    start_service services.conversation.main:app "$CONVERSATION_PORT" conversation.log
    sleep 3   # chờ RAG kịp load embedder trước khi agent (service gọi RAG) khởi động
    start_service services.agent.main:app        "$AGENT_PORT"        agent.log

    echo "=== 4) Health checks ==="
    wait_health rag          "$RAG_PORT" 120
    wait_health identity     "$IDENTITY_PORT"
    wait_health booking      "$BOOKING_PORT"
    wait_health conversation "$CONVERSATION_PORT"
    wait_health agent        "$AGENT_PORT" 120

    echo "=== 5) Gateway (Kong) + Frontend (nginx) — Docker ==="
    # 5 Python services chạy NATIVE trên host nên Kong phải gọi chúng qua
    # host.docker.internal (khai báo extra_hosts: host-gateway trong compose)
    # thay vì DNS nội bộ compose network. render-config.sh thế các giá trị này
    # vào placeholder __*_UPSTREAM__ của kong.yml lúc container start.
    export IDENTITY_UPSTREAM=host.docker.internal
    export AGENT_UPSTREAM=host.docker.internal
    export RAG_UPSTREAM=host.docker.internal
    export BOOKING_UPSTREAM=host.docker.internal
    export CONVERSATION_UPSTREAM=host.docker.internal
    # --no-deps: KHÔNG start container identity/agent/rag/booking/conversation
    # (chúng đang chạy native — start thêm sẽ xung đột port).
    # --build: tự pull base image (kong:3.7, nginx:alpine) nếu chưa có, rồi
    # build lại image (rẻ — chỉ COPY config/static, layer cache dùng lại).
    $COMPOSE up -d --build --no-deps gateway
    wait_http_any gateway  "$GATEWAY_PORT" 90
    # Frontend nginx proxy_pass http://gateway:8000 — nginx resolve DNS name
    # 'gateway' LÚC START, nên phải đợi container gateway tồn tại trước
    # (không start song song 2 container).
    $COMPOSE up -d --build --no-deps frontend
    wait_http_any frontend "$FRONTEND_PORT" 60

    echo ""
    echo "🎉 Stack đã sẵn sàng:"
    echo "  🌐 Web UI (chat + HITL):  http://localhost:$FRONTEND_PORT"
    echo "  🔀 API gateway (Kong):    http://localhost:$GATEWAY_PORT"
    echo "  uv run python cli.py              # chat tương tác"
    echo "  bash scripts/run_all_queries.sh   # test toàn bộ eval/queries.txt"
    echo "  bash scripts/local.sh status | stop | down"
    if [[ "${AGENT_REQUIRE_GATEWAY:-false}" == "true" ]]; then
      echo ""
      echo "🔒 AGENT_REQUIRE_GATEWAY=true — agent chỉ nhận /api/chat qua Kong (:$GATEWAY_PORT):"
      echo "  cli.py cần AGENT_SERVICE_URL=http://localhost:$GATEWAY_PORT trong .env"
      echo "  và /login trước (Kong yêu cầu JWT). Smoke/flow test tự gửi header gateway."
    fi
    ;;
  status)
    status
    ;;
  stop)
    stop_services
    echo "Đã tắt 5 services + gateway + frontend (Postgres giữ nguyên; Qdrant/Redis ở cloud)."
    echo "Tắt + xóa toàn bộ container: bash scripts/local.sh down"
    ;;
  down)
    stop_services
    $COMPOSE down
    echo "Đã tắt + xóa toàn bộ container (data Postgres giữ trong volume; Qdrant/Redis ở cloud)."
    ;;
  *)
    echo "Usage: bash local.sh [up|status|stop|down]"
    exit 1
    ;;
esac

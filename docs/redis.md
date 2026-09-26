# Redis trong project — UET AI Assistant (`uet-hr-ai`)

> Redis trong hệ thống này có đúng MỘT vai trò: **exact-match JSON cache cho các
> read endpoint của conversation service**, chạy trên **Redis Cloud ở MỌI môi trường**
> (local, Compose, AWS ECS). Không có Redis container/image ở bất kỳ đâu.
> Sơ đồ tổng quan: [`architecture.md`](architecture.md) · API contract: [`api.md`](api.md).

Mục lục:

1. [Redis dùng ở đâu (và KHÔNG dùng ở đâu)](#1-redis-dùng-ở-đâu-và-không-dùng-ở-đâu)
2. [RedisCacheService — implementation](#2-rediscacheservice--implementation)
3. [Key schema, TTL và invalidation](#3-key-schema-ttl-và-invalidation)
4. [Wiring trong conversation service](#4-wiring-trong-conversation-service)
5. [Configuration](#5-configuration)
6. [Redis exact-match vs Qdrant semantic cache](#6-redis-exact-match-vs-qdrant-semantic-cache)
7. [Deployment theo môi trường](#7-deployment-theo-môi-trường)
8. [Gotchas](#8-gotchas)

---

## 1. Redis dùng ở đâu (và KHÔNG dùng ở đâu)

| Vai trò | Dùng Redis? | Thực tế dùng gì |
|---|---|---|
| Cache read endpoint của conversation (`GET /conversations`, `GET /conversations/{id}`) | ✅ **Redis Cloud** | `services/conversation/cache.py` |
| Semantic cache cho RAG search (query gần giống → trả kết quả cũ) | ❌ | **Qdrant** collection `uet_hr_cache` (`services/rag/retrieval/cache.py`) — xem mục 6 |
| LangGraph checkpointer (state của agent graph) | ❌ | **Postgres** |
| Episodic memory (summary per thread) | ❌ | **Postgres** (`episode_summaries`, SQL-only) |
| Session/JWT store | ❌ | JWT stateless; client tự giữ (localStorage / `data/.cli_session.json`) |
| Pub/Sub, queue, rate-limit store | ❌ | Kong rate-limit policy `local` (in-memory từng node) |

Duy nhất **conversation service** nói chuyện với Redis. Agent, RAG, booking,
identity không đụng Redis.

---

## 2. RedisCacheService — implementation

File: `services/conversation/cache.py`. Design goal: **cache không bao giờ được
phá request** — mọi lỗi Redis đều degrade thành "cache miss".

### 2.1 Interface

| Method | Hành vi |
|---|---|
| `get_json(key)` | `GET` + `json.loads`; miss/lỗi/disabled → `None` |
| `set_json(key, value, ttl_seconds=None)` | `SETEX key ttl json` (ttl mặc định `REDIS_TTL_SECONDS`); `ttl <= 0` → `SET` không hạn; lỗi serialize/Redis → log warning, bỏ qua |
| `delete(key)` | `DEL` best-effort |
| `delete_pattern(pattern)` | `SCAN` theo glob (non-blocking, không dùng `KEYS`) rồi `DEL` loạt — ví dụ `conversation:{id}:*` |

Client: `redis-py` đồng bộ (`Redis.from_url`, `decode_responses=True`,
`socket_connect_timeout=2`, `socket_timeout=2`) — mọi thao tác Redis là lệnh ngắn
vài ms, gọi thẳng trong async handler chấp nhận được; timeout 2s chặn trường hợp
Redis treo làm nghẽn request.

### 2.2 Graceful degradation + lazy reconnect

```
REDIS_ENABLED=false ──────────────► mọi method là no-op, service chạy không cache
REDIS_ENABLED=true:
  __init__ → _connect() (ping)
     ├─ OK      → dùng client
     └─ Fail    → _client = None, chạy không cache,
                  đặt cooldown _next_retry_at = now + 5s
  mỗi lần get/set: _ensure_client()
     ├─ client sống → dùng
     ├─ còn trong cooldown (5s) → trả None ngay (không tốn 2s timeout mỗi request)
     └─ hết cooldown → thử _connect() lại (Redis "sống dậy" được nhận
                        tự động, KHÔNG cần restart service)
```

`RETRY_INTERVAL_SECONDS = 5.0` chặn chi phí: khi Redis down, mỗi request chỉ tốn
tối đa một cú connect+ping (≤2s) cho **cả cửa sổ 5 giây**, không phải mỗi request
một cú.

---

## 3. Key schema, TTL và invalidation

Pattern chung: **cache-aside** (đọc: check cache → miss thì query Postgres →
set cache; ghi: invalidate).

| Key | Nội dung | Được cache bởi | TTL |
|---|---|---|---|
| `conversation:user:{user_id}:list` | Danh sách conversation header của user (newest first) | `list_conversations()` | `REDIS_TTL_SECONDS` (300s) |
| `conversation:{conversation_id}:detail` | Một conversation header | `get_conversation()` | `REDIS_TTL_SECONDS` (300s) |

Lưu ý: `list_messages()` **không cache** — history tin nhắn thay đổi mỗi turn và
luôn đọc thẳng Postgres.

### Ma trận invalidation (`services/conversation/service.py`)

| Sự kiện | Pattern bị xóa |
|---|---|
| `create_conversation` | `conversation:user:{user_id}:*` |
| `delete_conversation` | `conversation:{id}:*` **+** `conversation:user:{owner}:*` |
| `sync_messages` (agent sync history mỗi turn) | `conversation:{id}:*` **+** `conversation:user:{user_id}:*` |
| `force_summarize_episode` (nút "Tóm tắt" trên UI) | `conversation:{id}:*` |

Vì mọi turn chat đều kết thúc bằng một cú sync từ agent → `sync_messages` →
invalidate, cache chủ yếu tăng tốc các lần **đọc lặp lại trong cùng một khoảng
thời gian ngắn** (UI reload, đổi qua lại giữa các conversation) thay vì phục vụ
dữ liệu cũ.

---

## 4. Wiring trong conversation service

```
services/conversation/main.py (startup)
  cache = RedisCacheService()            # connect hoặc degrade ngay lúc boot
  app.state.redis_cache = cache
  app.state.conversation_service = ConversationService(repository, cache, episodic)
```

`ConversationService` nhận cache qua constructor — không có Redis client rải rác
trong route handler; test có thể thay bằng cache no-op.

---

## 5. Configuration

Đọc từ `.env` bởi `services/conversation/settings.py`:

| Biến | Giá trị hiện tại | Ý nghĩa |
|---|---|---|
| `REDIS_ENABLED` | `true` | `false` → mọi method thành no-op (chạy không cache, không lỗi) |
| `REDIS_URL` | `redis://default:<password>@<redis-cloud-host>:<port>/0` (giá trị thật chỉ nằm trong `.env`) | URI **kèm credential** — không bao giờ log/in ra hay chép vào docs (local.sh tuân thủ điều này) |
| `REDIS_TTL_SECONDS` | `300` | TTL mặc định cho mọi key |

---

## 6. Redis exact-match vs Qdrant semantic cache

Hai tầng cache khác nhau hoàn toàn, dễ nhầm — bảng so sánh:

| | **Redis** (conversation) | **Qdrant semantic cache** (RAG) |
|---|---|---|
| File | `services/conversation/cache.py` | `services/rag/retrieval/cache.py` (`QdrantSemanticCache`) |
| Loại match | **Exact** — cùng key string | **Semantic** — cosine similarity ≥ `CACHE_SIMILARITY_THRESHOLD` (0.95) giữa embedding của query mới và query đã cache |
| Lưu gì | JSON conversation header | Vector query + payload `{answer, timestamp}` trong collection `uet_hr_cache` |
| TTL | `REDIS_TTL_SECONDS=300` (SETEX — Redis tự xóa) | `CACHE_TTL_SECONDS=3600` — enforce **lúc đọc** bằng payload range filter (`timestamp > now - ttl`, payload index trên `timestamp`); `cleanup_expired()` xóa vật lý on-demand |
| Vị trí trong pipeline | Read endpoint của conversation | Bước 2 của `POST /api/kb/search`: cache check → hybrid → HyDE → rerank → MMR → cache write |
| Khi lỗi | Degrade no-cache + lazy retry | Degrade miss (log warning) — retrieval vẫn chạy |

Semantic cache **không** dùng Redis vì bản chất nó là vector search — Qdrant Cloud
đã có sẵn trong stack, thêm Redis-Stack/vector chỉ để cache là thừa một hạ tầng.

---

## 7. Deployment theo môi trường

Chính sách: **Redis Cloud là deployment Redis DUY NHẤT** cho mọi môi trường —
không provision Redis container/image ở local, Compose hay ECS.

| Môi trường | `REDIS_URL` đến từ đâu | Ghi chú |
|---|---|---|
| **Local** (`scripts/local.sh`) | `.env` | `local.sh` **từ chối start** nếu `REDIS_URL` trỏ localhost; `local.sh status` ping Redis Cloud (PONG) như một phần health-check. Không bao giờ in `REDIS_URL` (chứa password) |
| **Full Docker** (`scripts/deploy.sh`, `configs/docker-compose.dev.yml`) | `.env` | Compose stack cố tình KHÔNG có Redis image (comment ghi rõ trong `deploy.sh`) |
| **Prod Compose** (`configs/docker-compose.prod.yml`) | Env của deployment | `REDIS_URL: "${REDIS_URL:?set REDIS_URL}"` — stack refuse-to-start nếu thiếu; `REDIS_ENABLED` default `true` |
| **AWS ECS** (`terraform/`) | Inject từ **Secrets Manager** (`terraform/data.tf`: `REDIS_URL = var.redis_url`; `variables.tf` validate prefix `redis://`/`rediss://`) | `locals.tf` set `REDIS_ENABLED=true`, `REDIS_TTL_SECONDS=300` cho task conversation |

Hệ quả vận hành: không có Redis state nào phải migrate/backup — cache thuần túy,
mất Redis chỉ mất cache (service tự degrade rồi tự reconnect).

---

## 8. Gotchas

- **CẤM xóa Redis khỏi configs/scripts** (compose prod, local.sh, deploy, terraform):
  AWS ECS vẫn inject `REDIS_URL` từ Secrets Manager, `local.sh` fail-fast nếu thiếu.
  Redis **native/local đã disable** — không thêm container `redis:*` vào stack.
- **Redis down ≠ service down**: nhờ lazy reconnect (mục 2.2), conversation service
  chạy không cache vô thời hạn và tự nhận Redis khi nó trở lại — không cần
  restart, không cần health-check fail.
- **`delete_pattern` dùng `SCAN`, không `KEYS`**: `KEYS` block Redis server — cấm
  trên Redis Cloud production.
- **TTL 300s là chủ đích**: conversation header ít đổi nhưng `sync_messages` mỗi
  turn đã invalidate chủ động; TTL chỉ là lưới an toàn cho các đường ghi không
  đi qua service (ví dụ sửa DB tay).
- **Cache không chứa dữ liệu nhạy cảm chéo user**: key list được scope theo
  `user_id` (`conversation:user:{user_id}:list`), và route đã enforce owner trước
  khi đọc (403 cho conversation người khác) — xem [`token.md`](token.md) mục 9.

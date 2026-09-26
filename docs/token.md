# Token & Authentication Pipeline — UET AI Assistant (`uet-hr-ai`)

> Tài liệu này giải thích **toàn bộ vòng đời của token/credential** trong hệ thống:
> JWT được cấp thế nào, request từ client đi qua Kong gateway ra sao, các service
> phía sau xác thực bằng gì, và service-to-service gọi nhau dùng credential nào.
> API contract từng service: [`api.md`](api.md) · Sơ đồ tổng quan: [`architecture.md`](architecture.md).

Mục lục:

1. [Ba loại credential](#1-ba-loại-credential)
2. [JWT được cấp thế nào (identity service)](#2-jwt-được-cấp-thế-nào-identity-service)
3. [Client lưu và gửi JWT](#3-client-lưu-và-gửi-jwt)
4. [Pipeline request: client → Kong → service](#4-pipeline-request-client--kong--service)
5. [Route nào public, route nào protected](#5-route-nào-public-route-nào-protected)
6. [Render secrets lúc gateway start](#6-render-secrets-lúc-gateway-start)
7. [Xác thực phía từng service](#7-xác-thực-phía-từng-service)
8. [Request giữa các service (service-to-service)](#8-request-giữa-các-service-service-to-service)
9. [Owner enforcement — defense in depth](#9-owner-enforcement--defense-in-depth)
10. [Gotchas](#10-gotchas)

---

## 1. Ba loại credential

Hệ thống dùng đúng **3 loại credential**, mỗi loại sống ở một "trust plane" khác nhau:

| Credential | Ai giữ | Ai verify | Vai trò |
|---|---|---|---|
| **JWT** (`Authorization: Bearer <jwt>`) | Client (browser / CLI) | **Chỉ Kong** (jwt plugin) | Chứng minh danh tính end-user |
| **`X-Gateway-Token`** = `GATEWAY_SHARED_SECRET` | Kong (inject tự động) | agent / booking / conversation | Chứng minh "request ĐÃ đi qua gateway" |
| **`X-Internal-Token`** / **`X-Internal-Api-Token`** = `INTERNAL_API_TOKEN` | Service nội bộ (agent) | booking / rag (`X-Internal-Token`), conversation (`X-Internal-Api-Token`) | Chứng minh caller là service nội bộ (không qua Kong) |

Nguyên tắc thiết kế (*edge authentication / trusted header* — industry-standard cho
API gateway): **JWT chỉ được verify MỘT lần tại Kong**. Mọi service phía sau không
parse JWT nữa (trừ identity khi bị gọi direct ở local) — chúng chỉ đọc các header
tin cậy do Kong inject: `X-User-Id`, `X-User-Email`, `X-Gateway-Token`.

```
browser/CLI ──JWT──► Kong :8080 ──X-User-Id + X-Gateway-Token──► agent/booking/conversation/identity
                        (verify)                    (trusted headers)

agent ──X-Internal-Token (+ X-User-Id của end-user)──► rag / booking / conversation
                        (gọi thẳng, KHÔNG qua Kong)
```

---

## 2. JWT được cấp thế nào (identity service)

File: `services/identity/security/tokens.py`, `services/identity/users/routes.py`.

### 2.1 Register / Login (public)

```
POST /auth/register {email, password, name}   → 201 {token, user}   (409 nếu email đã tồn tại)
POST /auth/login    {email, password}         → 200 {token, user}   (401 nếu sai credential)
```

- Password được hash bằng **bcrypt** (`services/identity/security/hashing.py`) — DB
  không bao giờ chứa plaintext.
- Login thành công → `create_access_token()` ký JWT bằng **HS256** với
  `JWT_SECRET_KEY` (identity và Kong dùng CHUNG một secret).

### 2.2 Claims của JWT

| Claim | Giá trị | Ghi chú |
|---|---|---|
| `iss` | `uet-identity` (`JWT_ISSUER`) | Kong map issuer này → consumer `uet-users` để tìm secret verify |
| `sub` | user_id | Nguồn của header `X-User-Id` phía sau |
| `email` | email user | Nguồn của header `X-User-Email` |
| `name` | tên hiển thị | |
| `iat` | thời điểm cấp | |
| `exp` | `iat + JWT_EXPIRE_MINUTES` (60 phút) | Kong verify claim này (`claims_to_verify: [exp]`) |

Không có refresh token: hết hạn 60 phút thì client login lại.

---

## 3. Client lưu và gửi JWT

| Client | Lưu ở đâu | Gửi đi thế nào |
|---|---|---|
| **Web UI** (`services/frontend/static/js/auth.js`, `api.js`) | `localStorage` key `uet.session` (token + user_id + email + name) | Mọi request qua Kong kèm `Authorization: Bearer <token>`. Chat là SSE qua `fetch + ReadableStream` (KHÔNG dùng `EventSource` vì cần POST + header Authorization) |
| **CLI** (`cli.py`) | File `data/.cli_session.json` (lệnh `/login <email> <password>`) | Header `Authorization: Bearer <token>` giống hệt web |

Khi `AGENT_REQUIRE_GATEWAY=true` (giá trị trong `.env` hiện tại), CLI/eval **bắt buộc**
nói chuyện qua Kong (`AGENT_SERVICE_URL=http://localhost:8080`) và phải `/login`
trước — gọi thẳng agent `:8000` sẽ bị 401.

---

## 4. Pipeline request: client → Kong → service

Toàn bộ đường đi của một request đã đăng nhập (ví dụ `POST /api/chat/stream`):

```mermaid
sequenceDiagram
    participant C as Browser / CLI
    participant K as Kong :8080
    participant A as agent :8000

    C->>K: POST /api/chat/stream<br/>Authorization: Bearer <JWT>
    Note over K: 1. Match route "agent-chat" (path /api/chat, strip_path: false)
    Note over K: 2. Global plugins: CORS + rate-limit 120 req/phút
    Note over K: 3. jwt plugin: verify chữ ký HS256 (secret của consumer<br/>uet-users, key = iss "uet-identity") + claim exp → 401 nếu sai/hết hạn
    Note over K: 4. post-function (Lua): cắt payload JWT, chuẩn hóa<br/>base64URL → decode → regex lấy "sub" và "email"
    K->>A: Forward + set_header:<br/>X-Gateway-Token: <GATEWAY_SHARED_SECRET><br/>X-User-Id: <sub><br/>X-User-Email: <email>
    Note over A: 5. verify_gateway_request(): so X-Gateway-Token với<br/>GATEWAY_SHARED_SECRET → 401 nếu sai; thiếu X-User-Id → 400
    A-->>C: SSE stream (token / tool / agent / context / done)
```

Chi tiết bước 4 (`services/gateway/declarative/kong.yml`, plugin `post-function` —
một block Lua giống hệt nhau cho từng protected route):

1. Lấy header `Authorization`, match `Bearer <token>`.
2. Cắt segment payload của JWT (`header.payload.signature` → lấy phần giữa).
3. JWT dùng **base64URL không padding** → Lua phải thêm lại `=`/`==` theo
   `len % 4` và đổi `-`→`+`, `_`→`/` trước khi `ngx.decode_base64`.
4. Regex lấy `"sub"` và `"email"` từ JSON đã decode (không cần JSON parser đầy đủ —
   payload ĐÃ được jwt plugin verify chữ ký ở bước trước đó).
5. `kong.service.request.set_header(...)`: **ghi đè** 3 header gửi lên upstream —
   `X-Gateway-Token`, `X-User-Id`, `X-User-Email`. Vì là `set_header` ở phía
   service-request, client bên ngoài **không thể mạo danh** bằng cách tự gửi
   `X-User-Id`: giá trị đó luôn bị Kong ghi đè bằng `sub` trong JWT đã verify.

Bước 5 phía service (agent): `services/agent/auth.py` —
`verify_gateway_request()` so `X-Gateway-Token == GATEWAY_SHARED_SECRET`
(constant-time không dùng, so string thường — chấp nhận được vì đây là shared
secret nội bộ, không phải secret suy ra từ input user). Khi
`AGENT_REQUIRE_GATEWAY=false` (local dev), check này bỏ qua để CLI/eval gọi thẳng.

---

## 5. Route nào public, route nào protected

Bảng đầy đủ từ `kong.yml` — jwt plugin chỉ gắn lên 4 route protected:

| Route (Kong) | Path | Methods | JWT? | Header inject? | Upstream |
|---|---|---|---|---|---|
| `identity-public` | `/auth/register`, `/auth/login` | POST, OPTIONS | ❌ public | ❌ | identity :8001 |
| `identity-protected` | `/auth/me` | GET, OPTIONS | ✅ | ✅ | identity :8001 |
| `agent-chat` | `/api/chat` (prefix → `/api/chat/stream`, `/api/chat/resume`) | all | ✅ | ✅ | agent :8000 |
| `rag-kb` | `/api/kb` | GET, OPTIONS | ❌ | ❌ | rag :8002 |
| `booking-routes` | `/api/business/bookings` | all | ✅ | ✅ | booking :8003 |
| `conversation-routes` | `/conversations` | all | ✅ | ✅ | conversation :8004 |

Mọi route đều `strip_path: false` — path qua gateway **giống hệt** path gốc của
service. Global plugin áp dụng cho mọi route: CORS (mọi origin, cho phép header
`Authorization` + `X-Gateway-Token`) và rate-limiting 120 request/phút (policy local).

Lưu ý thực tế:

- **`rag-kb` không gắn jwt plugin**: endpoint RAG search qua Kong hiện ở dạng mở
  (chỉ GET). Đường chính mà RAG được gọi là **internal** từ agent
  (`POST /api/kb/search` — method POST thậm chí không nằm trong route Kong), mang
  `X-Internal-Token`. Xem mục 8.
- **`/internal/*` của conversation không có route Kong** → không thể gọi từ ngoài;
  chỉ agent gọi thẳng được (mục 8).

---

## 6. Render secrets lúc gateway start

`kong.yml` được commit với **placeholder**, không chứa secret thật. Container
gateway start chạy `services/gateway/render-config.sh`:

```
__JWT_SECRET__              ← $JWT_SECRET_KEY        (phải == secret identity dùng ký JWT)
__GATEWAY_SHARED_SECRET__   ← $GATEWAY_SHARED_SECRET (phải == secret các service dùng verify)
__IDENTITY_UPSTREAM__       ← $IDENTITY_UPSTREAM     (mặc định: "identity" — DNS name trong compose)
__AGENT_UPSTREAM__          ← $AGENT_UPSTREAM        (mặc định: "agent")
__RAG_UPSTREAM__ / __BOOKING_UPSTREAM__ / __CONVERSATION_UPSTREAM__  (tương tự)
```

`sed` thay tất cả vào `rendered.yml` rồi Kong DB-less load file đó. Hai chế độ:

| Chế độ | Upstream hosts | Vì sao |
|---|---|---|
| Full Docker (`scripts/deploy.sh`) | Mặc định = tên service trong compose (`identity`, `agent`, ...) | Kong và 5 service cùng network compose |
| `scripts/local.sh` | Override 5 biến `*_UPSTREAM=host.docker.internal` | Kong chạy container nhưng 5 service Python chạy **native trên host** (uvicorn bind `0.0.0.0` — bắt buộc, bind `127.0.0.1` là container không tới được) |

Quy ước: **không bao giờ sửa giá trị đã render** — sửa placeholder trong
`kong.yml` hoặc đổi biến môi trường rồi restart gateway.

Cặp secret phải khớp ở 2 đầu (đều lấy từ `.env`):

- `JWT_SECRET_KEY`: identity (ký) ↔ Kong consumer `uet-users` (verify).
- `GATEWAY_SHARED_SECRET`: Kong post-function (inject) ↔ agent/booking/conversation (verify).
- `INTERNAL_API_TOKEN`: agent (gửi) ↔ booking/rag/conversation (verify).

---

## 7. Xác thực phía từng service

| Service | File | Chấp nhận credential nào | Hành vi |
|---|---|---|---|
| **agent** | `services/agent/auth.py` | `X-Gateway-Token` (khi `AGENT_REQUIRE_GATEWAY=true`) | Sai/thiếu token → 401; token đúng nhưng thiếu `X-User-Id` → 400. `resolve_user()` (api.py): identity do gateway inject **thắng** `user_id` trong request body — body chỉ được dùng ở local dev |
| **booking** | `services/booking/auth.py` | `X-Internal-Token` **hoặc** `X-Gateway-Token` | Một trong hai khớp → pass (trả về `X-User-Id` nếu có); cả hai sai → 401. Hai cửa vì booking nhận cả traffic Kong (user gọi trực tiếp REST) lẫn internal (agent tools) |
| **conversation — public** `/conversations/*` | `services/conversation/routes/public.py` + `auth.py` | `X-User-Id` tin cậy (Kong inject) — soft check `X-Gateway-Token` | `resolve_user_id()`: header `X-User-Id` **luôn thắng** query param `?user_id=` (legacy); thiếu cả hai → 400. Owner check → 403 |
| **conversation — internal** `/internal/conversations/*` | `services/conversation/routes/internal.py` | `X-Internal-Api-Token` (router-level dependency) | Sai/thiếu → 401. Không expose qua Kong |
| **identity** `/auth/me` | `services/identity/users/routes.py` | `X-User-Id` (gateway) **hoặc** tự decode `Authorization: Bearer` | Nhánh Bearer chỉ dành cho direct access ở local (CLI không qua Kong); thứ tự: header trước, Bearer sau |
| **rag** `/api/kb/*` | `services/rag/api.py` | — | Router hiện **không gắn auth dependency**. Agent có gửi `X-Internal-Token` (clients.py) nhưng RAG chưa verify — xem Gotchas |

---

## 8. Request giữa các service (service-to-service)

File: `services/agent/clients.py` — mọi call dùng `httpx` gọi **thẳng URL service**
(`RAG_SERVICE_URL`, `BOOKING_SERVICE_URL`, `CONVERSATION_SERVICE_URL`), KHÔNG đi
vòng qua Kong. Credential là shared secret `INTERNAL_API_TOKEN`.

| Caller → Callee | Endpoint | Header gửi đi | Callee verify |
|---|---|---|---|
| agent → **rag** | `POST /api/kb/search` | `X-Internal-Token` | ❌ (RAG chưa verify — header gửi để sẵn sàng bật) |
| agent → **booking** | `POST/GET/PATCH/DELETE /api/business/bookings...` | `X-Internal-Token` **+ `X-User-Id` của end-user** | ✅ `verify_booking_access`; `X-User-Id` dùng enforce owner |
| agent → **conversation** | `PUT /internal/conversations/{id}/messages` (sync history), `GET /internal/conversations/{id}/memory` (episodic memory) | `X-Internal-Api-Token` | ✅ `verify_internal_token` (lưu ý: tên header KHÁC booking/rag) |

Hai điểm thiết kế đáng chú ý:

1. **Agent "ủy quyền danh tính" qua header**: khi tool booking chạy, agent gửi kèm
   `X-User-Id` của end-user (lấy từ gateway context của turn đó) để booking service
   enforce owner server-side — người A không thể đọc/hủy/đổi lịch của người B
   (403) kể cả khi LLM "bịa" `user_id` khác trong tool arguments.
2. **Internal call không mang JWT**: JWT là credential của end-user với edge; nội
   bộ tin nhau bằng shared secret + header ủy quyền. Timeout riêng từng call
   (RAG 150s vì HyDE chậm, booking 15s, conversation sync 10s, memory 5s) và mọi
   lỗi đều trả payload có cấu trúc để LLM báo user trung thực thay vì giả vờ
   thành công.

---

## 9. Owner enforcement — defense in depth

Identity của user được "kẹp" qua 3 lớp, lớp nào cũng có thể chặn:

```
Lớp 1 — Kong:        JWT verify → X-User-Id = sub (client không tự set được)
Lớp 2 — Router:      resolve_user_id(): X-User-Id header LUÔN thắng query/body param
Lớp 3 — Service/DB:  PermissionError → 403 (booking: mọi read/update/cancel/list;
                     conversation: require_owner() cho detail/messages/delete/summarize)
```

Ví dụ booking (`services/booking/routers/bookings.py`): kể cả khi ai đó gọi internal
API với `?user_id=<người khác>`, `resolve_user_id` ưu tiên header `X-User-Id` do
caller tin cậy set, và service layer so owner của row trong DB trước khi
update/cancel → 403 nếu lệch. Chi tiết hơn ở [`api.md`](api.md) mục 1.2.

---

## 10. Gotchas

- **Hai tên header internal khác nhau**: booking/rag dùng `X-Internal-Token`,
  conversation dùng `X-Internal-Api-Token` — cùng một giá trị
  `INTERNAL_API_TOKEN` nhưng khác tên header. Sửa một phía đừng quên phía kia.
- **RAG chưa verify token**: `X-Internal-Token` được agent gửi nhưng
  `services/rag/api.py` không có dependency nào check nó; route Kong của RAG cũng
  không gắn jwt plugin. RAG hiện là service "trusted network only" — nếu expose
  rộng hơn cần thêm auth.
- **base64URL padding trong Lua**: jwt plugin đã verify chữ ký, nhưng post-function
  vẫn phải tự normalize padding (`==`/`=`) và alphabet (`-_` → `+/`) trước khi
  decode — thiếu bước này payload có độ dài `%4 == 2/3` sẽ decode fail và header
  không được inject (service phía sau nhận request "vô danh").
- **`AGENT_REQUIRE_GATEWAY`**: local dev đặt `false` để CLI/eval gọi thẳng
  `:8000`; production **bắt buộc `true`** (`.env` hiện để `true`, và khi đó
  `AGENT_SERVICE_URL` phải trỏ Kong `:8080` + client phải login).
- **Secret placeholder**: không commit giá trị thật vào `kong.yml`; không sửa file
  `rendered.yml` trong container (restart là mất). Nguồn sự thật là `.env` /
  Secrets Manager (AWS inject `JWT_SECRET_KEY`, `GATEWAY_SHARED_SECRET`,
  `INTERNAL_API_TOKEN` — xem `docs/aws-deployment.md`).
- **JWT hết hạn giữa chừng**: SSE stream của một turn chat đã được Kong verify lúc
  request vào; token hết hạn trong lúc stream không cắt stream đang chạy, nhưng
  request kế tiếp sẽ 401 → client phải login lại (không có refresh token).
- **Rate limit 120/phút là policy `local`** của từng Kong node — đủ cho 1 node
  hiện tại; nếu scale nhiều node Kong cần đổi sang policy tập trung (redis/db).

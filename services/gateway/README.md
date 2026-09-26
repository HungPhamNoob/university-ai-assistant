# Gateway (Kong DB-less)

Single entrypoint of the platform. Kong runs without a database and loads the
whole routing table from `declarative/kong.yml`.

## Run

With the dev compose file (from the repo root):

```bash
docker compose -f configs/docker-compose.dev.yml up gateway
```

or standalone:

```bash
docker build -t uet-gateway -f services/gateway/Dockerfile .
docker run -p 8080:8000 uet-gateway
```

## Routes

| Path                    | Upstream      | Auth                          |
| ----------------------- | ------------- | ----------------------------- |
| /auth/register          | identity:8001 | public                        |
| /auth/login             | identity:8001 | public                        |
| /auth/me                | identity:8001 | JWT (HS256, iss=uet-identity) |
| /api/chat               | agent:8000    | gateway token                 |
| /api/kb                 | rag:8002      | gateway token                 |
| /api/business/bookings  | booking:8003  | gateway token                 |
| /conversations          | conversation:8004 | gateway token             |

Protected routes are validated by the `jwt` plugin. The `post-function` Lua
snippet decodes the token and injects `X-User-Id`, `X-User-Email` and
`X-Gateway-Token` so upstream services never handle JWTs themselves.
Global plugins: `cors` (browser access) and `rate-limiting` (120 req/min).

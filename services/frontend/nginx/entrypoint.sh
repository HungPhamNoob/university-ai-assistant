#!/bin/sh
# services/frontend/nginx/entrypoint.sh
# Injects the runtime API configuration into the runtime config, then starts nginx.
#
# In the container the frontend is ALWAYS served behind nginx, so:
#   - FRONTEND_API_BASE_URL empty -> same-origin relative paths proxied to Kong
#     (proxyGateway: true); the browser adds the Bearer JWT itself.
#   - FRONTEND_API_BASE_URL set   -> browser calls Kong directly with Bearer.

set -e

TARGET=/usr/share/nginx/html/js/runtime-config.js

cat > "$TARGET" <<EOF
/* Generated at container start by entrypoint.sh — do not edit by hand. */
window.API_BASE_URL = "${FRONTEND_API_BASE_URL:-}";
window.APP_CONFIG = {
  gatewayBaseUrl: "${FRONTEND_API_BASE_URL:-}",
  proxyGateway: true,
  direct: {
    agent: "http://localhost:8000",
    identity: "http://localhost:8001",
    conversation: "http://localhost:8004",
    rag: "http://localhost:8002"
  }
};
EOF

echo "[entrypoint] API_BASE_URL set to '${FRONTEND_API_BASE_URL:-}'"

exec nginx -g 'daemon off;'
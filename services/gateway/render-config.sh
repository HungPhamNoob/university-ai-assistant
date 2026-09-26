# services/gateway/render-config.sh
# Renders declarative/kong.yml at container startup: substitutes the shared
# secrets from env vars so the committed file never contains real secrets.
set -e

: "${JWT_SECRET_KEY:?JWT_SECRET_KEY must be set for the gateway}"
: "${GATEWAY_SHARED_SECRET:?GATEWAY_SHARED_SECRET must be set for the gateway}"

# Upstream hosts of the 5 backend services. Default = compose service DNS
# names (full-docker mode, e.g. deploy.sh). scripts/local.sh overrides them
# to host.docker.internal because there the Python services run natively
# on the host instead of as containers.
IDENTITY_UPSTREAM="${IDENTITY_UPSTREAM:-identity}"
AGENT_UPSTREAM="${AGENT_UPSTREAM:-agent}"
RAG_UPSTREAM="${RAG_UPSTREAM:-rag}"
BOOKING_UPSTREAM="${BOOKING_UPSTREAM:-booking}"
CONVERSATION_UPSTREAM="${CONVERSATION_UPSTREAM:-conversation}"

sed -e "s|__JWT_SECRET__|${JWT_SECRET_KEY}|g" \
    -e "s|__GATEWAY_SHARED_SECRET__|${GATEWAY_SHARED_SECRET}|g" \
    -e "s|__IDENTITY_UPSTREAM__|${IDENTITY_UPSTREAM}|g" \
    -e "s|__AGENT_UPSTREAM__|${AGENT_UPSTREAM}|g" \
    -e "s|__RAG_UPSTREAM__|${RAG_UPSTREAM}|g" \
    -e "s|__BOOKING_UPSTREAM__|${BOOKING_UPSTREAM}|g" \
    -e "s|__CONVERSATION_UPSTREAM__|${CONVERSATION_UPSTREAM}|g" \
    /usr/local/kong/declarative/kong.yml > /usr/local/kong/declarative/rendered.yml

echo "gateway: declarative config rendered at /usr/local/kong/declarative/rendered.yml"

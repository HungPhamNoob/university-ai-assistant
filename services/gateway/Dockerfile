# services/gateway/Dockerfile
# Kong in DB-less mode: the whole routing table comes from declarative/kong.yml.
# Secrets in kong.yml are __PLACEHOLDERS__ rendered at startup by render-config.sh
# from JWT_SECRET_KEY / GATEWAY_SHARED_SECRET env vars.
FROM kong:3.7

ENV KONG_DATABASE=off
ENV KONG_DECLARATIVE_CONFIG=/usr/local/kong/declarative/rendered.yml
ENV KONG_PROXY_ACCESS_LOG=/dev/stdout
ENV KONG_ADMIN_ACCESS_LOG=/dev/stdout
ENV KONG_PROXY_ERROR_LOG=/dev/stderr
ENV KONG_ADMIN_ERROR_LOG=/dev/stderr
ENV KONG_DNS_ORDER=LAST,A,CNAME,SRV

# Kong 3.7 chạy cả build step lẫn runtime với user 'kong' (uid 1000), KHÔNG
# phải root — nên file COPY vào phải chown cho kong:
#   - render-config.sh cần bit executable (755)
#   - declarative/ cần thuộc sở hữu của kong để render-config.sh ghi được
#     rendered.yml vào đó lúc container start.
COPY --chown=kong:kong --chmod=755 services/gateway/declarative/ /usr/local/kong/declarative/
COPY --chown=kong:kong --chmod=755 services/gateway/render-config.sh /usr/local/kong/render-config.sh

EXPOSE 8000 8443

# Render the declarative config, then hand control back to the image's
# official entrypoint. Note: `docker-start` is NOT a kong CLI subcommand —
# it is handled inside /docker-entrypoint.sh (prepares the prefix, execs
# nginx), so it must be invoked through that script.
CMD ["/bin/bash", "-c", "/usr/local/kong/render-config.sh && exec /docker-entrypoint.sh kong docker-start"]

# services/frontend/Dockerfile
FROM nginx:alpine

# Static chat UI
COPY services/frontend/static/ /usr/share/nginx/html/
# Nginx server block
COPY services/frontend/nginx/default.conf /etc/nginx/conf.d/default.conf
# Runtime config injection script
COPY services/frontend/nginx/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Default API base for local dev (overridable at runtime)
ENV FRONTEND_API_BASE_URL=""

EXPOSE 3000

ENTRYPOINT ["/entrypoint.sh"]

# Edge proxy image. Build context: infra/nginx
FROM nginx:1.31-alpine
# Every release passes its own VERSION, so the upgrade below re-runs instead of coming from the
# build cache, and picks up security fixes Alpine has published since the base image was built.
ARG VERSION=dev
RUN apk upgrade --no-cache \
 && apk add --no-cache openssl \
 && rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY snippets/ /etc/nginx/snippets/
COPY docker-entrypoint.d/ /docker-entrypoint.d/
# Templates are mounted per environment (http for staging, https for production) at
# /etc/nginx/templates and rendered by the image's envsubst step on start-up.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO /dev/null http://127.0.0.1/ || exit 1

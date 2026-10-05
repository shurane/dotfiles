FROM lucaslorentz/caddy-docker-proxy:ci-builder AS builder

RUN xcaddy build \
    --with github.com/lucaslorentz/caddy-docker-proxy/v2 \
    --with github.com/caddy-dns/porkbun

FROM lucaslorentz/caddy-docker-proxy:ci-alpine

COPY --from=builder /usr/bin/caddy /usr/bin/caddy

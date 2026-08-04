FROM ghcr.io/astral-sh/uv:alpine

RUN apk add --no-cache docker-cli docker-cli-compose

WORKDIR /homelab

ENTRYPOINT ["uv", "run", "./bootstrap-auth/bootstrap-auth.py"]

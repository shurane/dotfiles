# Homelab

Compose is run from this directory:

```bash
docker compose pull
docker compose up -d --remove-orphans
```

Auth bootstrap:

```bash
docker compose run --rm bootstrap-auth
docker compose run --rm bootstrap-auth --services jellyfin
```

`HOSTNAME_BASE` is the canonical local domain and `HOSTNAME_ALIAS_BASE` is the mirrored local domain.

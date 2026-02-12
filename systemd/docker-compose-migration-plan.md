# Docker Compose Migration Plan

## Why Migrate

- **Single source of truth**: one `docker-compose.yml` defines all services, networking, and volumes
- **Simple lifecycle**: `docker compose up -d` starts everything, `docker compose down` stops it
- **Easy upgrades**: change an image tag, `docker compose pull && docker compose up -d`
- **No system user management**: no creating users, setting permissions, managing `/var/lib` directories
- **Internal networking**: services talk to each other by name (e.g. `qui:7476`), only Caddy exposes ports to the host
- **Portable**: clone the repo on a new machine and `docker compose up -d`
- **Version controlled config**: bind-mount config files from the repo instead of scattering them across `/etc`

## Current Setup

| Service     | Port | Systemd Unit          | Config Location                              |
|-------------|------|-----------------------|----------------------------------------------|
| qui         | 7476 | `qui.service`         | `/etc/qui/config.toml`                       |
| qBittorrent | 8080 | `qbittorrent.service` | `/var/lib/qbittorrent/.config/qBittorrent/`  |
| Caddy       | 80   | `caddy.service`       | `/etc/caddy/Caddyfile`                       |

## Target Structure

```
dotfiles/
└── selfhosted/
    ├── docker-compose.yml
    ├── .env
    ├── .gitignore
    ├── caddy/
    │   └── Caddyfile
    ├── qui/
    │   └── config.toml
    └── qbittorrent/
```

## docker-compose.yml

```yaml
services:
  caddy:
    image: caddy:latest
    ports:
      - "80:80"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
    restart: unless-stopped

  qui:
    image: ghcr.io/autobrr/qui:latest
    volumes:
      - ./qui:/config
    restart: unless-stopped

  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    volumes:
      - ./qbittorrent:/config
      - ${DOWNLOADS_PATH}:/downloads
    environment:
      - PUID=${PUID}
      - PGID=${PGID}
    restart: unless-stopped

volumes:
  caddy-data:
```

## .env

```bash
PUID=1000
PGID=1000
DOWNLOADS_PATH=/path/to/downloads
```

## Caddyfile

```
:80 {
    handle /qui/* {
        reverse_proxy qui:7476
    }
    handle_path /qbt/* {
        reverse_proxy qbittorrent:8080
    }
}
```

## .gitignore

```
.env
```

## Migration Steps

1. Create `dotfiles/selfhosted/` directory structure
2. Copy config files into their subdirectories
3. Back up existing data (`/var/lib/qui`, `/var/lib/qbittorrent`)
4. Stop existing systemd services: `sudo systemctl stop qui qbittorrent caddy`
5. `docker compose up -d` from `dotfiles/selfhosted/`
6. Verify all services work at `http://m70q.lan/qui/` and `http://m70q.lan/qbt/`
7. Disable old systemd units: `sudo systemctl disable qui qbittorrent caddy`
8. Clean up old system users and `/var/lib` directories if desired

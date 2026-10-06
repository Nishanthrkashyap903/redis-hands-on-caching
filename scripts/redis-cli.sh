#!/usr/bin/env bash
# Interactive redis-cli in the caching-redis container (run from repo root).

set -euo pipefail

CONTAINER="caching-redis"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container '$CONTAINER' is not running." >&2
  echo "Start it: docker compose -f docker/docker-compose.yml up -d" >&2
  exit 1
fi

exec docker exec -it "$CONTAINER" redis-cli

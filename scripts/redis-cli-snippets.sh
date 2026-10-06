#!/usr/bin/env bash
# Quick snippets — run from repo root with Redis container up.

set -euo pipefail

CLI=(docker exec -i caching-redis redis-cli)

echo "=== PING ==="
"${CLI[@]}" PING

echo "=== INFO server (first lines) ==="
"${CLI[@]}" INFO server | head -n 12

echo "=== DBSIZE ==="
"${CLI[@]}" DBSIZE

"""Module 0 checkpoint: connect, SET with TTL, GET, print TTL."""

import os
import sys

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

def main() -> int:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    key = "module0:checkpoint"

    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        return 1

    client.set(key, "checkpoint-ok", ex=120)
    value = client.get(key)
    ttl = client.ttl(key)

    print(f"PING: OK")
    print(f"GET {key}: {value}")
    print(f"TTL {key}: {ttl}s")

    if value != "checkpoint-ok" or ttl <= 0:
        print("Checkpoint failed.", file=sys.stderr)
        return 1

    print("Checkpoint passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

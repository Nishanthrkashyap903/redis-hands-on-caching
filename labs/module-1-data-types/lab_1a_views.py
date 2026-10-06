"""
Lab 1A — Page view counter per URL.

Key design: app:url:{urlHash}
  - urlHash = stable SHA-256 hex digest of the URL string
  - Value: string integer (counter)

Flow — hit:
  1. Read URL
  2. urlHash = hash(URL)
  3. key = app:url:{urlHash}
  4. INCR key  (missing key is treated as 0, then incremented → first hit is 1)
  5. Print new count

Flow — stats:
  1. Read URL
  2. urlHash = hash(URL)
  3. key = app:url:{urlHash}
  4. GET key only (no INCR / SET / DEL)
  5. Print count (0 if key never hit)
"""

import argparse
import hashlib
import os
import sys

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KEY_PREFIX = "app:url:"


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def view_key(url: str) -> str:
    return f"{KEY_PREFIX}{url_hash(url)}"


def get_client() -> redis.Redis:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        raise SystemExit(1) from exc
    return client


def hit(client: redis.Redis, url: str) -> int:
    count = client.incr(view_key(url))
    return int(count)


def stats(client: redis.Redis, url: str) -> int:
    value = client.get(view_key(url))
    if value is None:
        return 0
    return int(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 1A: page view counter per URL")
    sub = parser.add_subparsers(dest="command", required=True)

    hit_parser = sub.add_parser("hit", help="Record one page view")
    hit_parser.add_argument("url", help="Page URL or path, e.g. /blog/post-1")

    stats_parser = sub.add_parser("stats", help="Read view count without changing it")
    stats_parser.add_argument("url", help="Page URL or path")

    args = parser.parse_args()
    client = get_client()

    if args.command == "hit":
        count = hit(client, args.url)
        print(count)
    else:
        count = stats(client, args.url)
        print(count)

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

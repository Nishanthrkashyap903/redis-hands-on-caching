"""
Lab 3A — Product catalog cache-aside.

Cache-aside read path:
  1. HGETALL m3:product:{id} — non-empty → hit
  2. EXISTS m3:nf:product:{id} — negative cache → not found (no JSON)
  3. Load from products.json → HSET + EXPIRE, or SET negative key with TTL

Commands:
  get <id>   — fetch one product (prints source: cache | db | negative-cache)
  get <id> --with-lock — stampede-safe path (SET m3:lock:product:{id} NX EX)
  stats      — print m3:stats:hits and m3:stats:misses from Redis
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PRODUCT_KEY_PREFIX = "m3:product:"
NEGATIVE_KEY_PREFIX = "m3:nf:product:"
LOCK_KEY_PREFIX = "m3:lock:product:"
STATS_HITS_KEY = "m3:stats:hits"
STATS_MISSES_KEY = "m3:stats:misses"

DEFAULT_CACHE_TTL = 30
DEFAULT_NEGATIVE_TTL = 60
DEFAULT_LOCK_TTL = 1
DEFAULT_LOCK_MAX_WAIT = 5
DEFAULT_LOCK_RETRY_SLEEP = 0.05

DATA_PATH = Path(__file__).resolve().parent / "data" / "products.json"


def product_key(product_id: int | str) -> str:
    return f"{PRODUCT_KEY_PREFIX}{product_id}"


def negative_key(product_id: int | str) -> str:
    return f"{NEGATIVE_KEY_PREFIX}{product_id}"


def lock_key(product_id: int | str) -> str:
    return f"{LOCK_KEY_PREFIX}{product_id}"


def get_client() -> redis.Redis:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        raise SystemExit(1) from exc
    return client


def load_catalog(path: Path = DATA_PATH) -> dict[int, dict]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    return {int(item["id"]): item for item in payload["products"]}


def product_to_hash(product: dict) -> dict[str, str]:
    return {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in product.items()}


def hash_to_product(fields: dict[str, str]) -> dict:
    out: dict = {}
    for key, value in fields.items():
        if key == "id":
            out[key] = int(value)
        elif key == "price_cents":
            out[key] = int(value)
        elif key == "in_stock":
            out[key] = value.lower() == "true"
        else:
            out[key] = value
    return out


def _lookup_product_cache(
    client: redis.Redis,
    product_id: int,
    use_negative_cache: bool,
) -> tuple[dict | None, str | None]:
    """Returns (product, source) on hit; (None, None) on cache miss."""
    key = product_key(product_id)
    cached = client.hgetall(key)
    if cached:
        return hash_to_product(cached), "cache"

    if use_negative_cache and client.exists(negative_key(product_id)):
        return None, "negative-cache"

    return None, None


def _load_product_from_catalog(
    client: redis.Redis,
    catalog: dict[int, dict],
    product_id: int,
    cache_ttl: int,
    negative_ttl: int,
    use_negative_cache: bool,
) -> tuple[dict | None, str]:
    client.incr(STATS_MISSES_KEY)
    product = catalog.get(product_id)
    if product is None:
        if use_negative_cache:
            client.set(negative_key(product_id), "1", ex=negative_ttl)
        return None, "miss"

    key = product_key(product_id)
    mapping = product_to_hash(product)
    client.hset(key, mapping=mapping)
    client.expire(key, cache_ttl)
    return product, "db"


def get_product(
    client: redis.Redis,
    catalog: dict[int, dict],
    product_id: int,
    cache_ttl: int,
    negative_ttl: int,
    use_negative_cache: bool,
) -> tuple[dict | None, str]:
    """
    Returns (product or None, source) where source is cache | db | negative-cache | miss.
    """
    product, source = _lookup_product_cache(client, product_id, use_negative_cache)
    if source:
        client.incr(STATS_HITS_KEY)
        return product, source

    return _load_product_from_catalog(
        client,
        catalog,
        product_id,
        cache_ttl,
        negative_ttl,
        use_negative_cache,
    )


def get_product_with_lock(
    client: redis.Redis,
    catalog: dict[int, dict],
    product_id: int,
    cache_ttl: int,
    negative_ttl: int,
    use_negative_cache: bool,
    lock_ttl: int = DEFAULT_LOCK_TTL,
    max_wait: float = DEFAULT_LOCK_MAX_WAIT,
    retry_sleep: float = DEFAULT_LOCK_RETRY_SLEEP,
) -> tuple[dict | None, str]:
    """
    Cache-aside with stampede protection: SET lock NX EX, double-check, single DB load.

    Returns source cache | db | negative-cache | miss. Waiters retry HGETALL until hit or timeout.
    """
    product, source = _lookup_product_cache(client, product_id, use_negative_cache)
    if source:
        client.incr(STATS_HITS_KEY)
        return product, source

    lk = lock_key(product_id)
    deadline = time.monotonic() + max_wait

    while time.monotonic() < deadline:
        acquired = client.set(lk, "1", nx=True, ex=lock_ttl)
        if acquired:
            try:
                product, source = _lookup_product_cache(client, product_id, use_negative_cache)
                if source == "cache":
                    client.incr(STATS_HITS_KEY)
                    return product, source
                if source == "negative-cache":
                    client.incr(STATS_HITS_KEY)
                    return None, source

                return _load_product_from_catalog(
                    client,
                    catalog,
                    product_id,
                    cache_ttl,
                    negative_ttl,
                    use_negative_cache,
                )
            finally:
                client.delete(lk)

        time.sleep(retry_sleep)
        product, source = _lookup_product_cache(client, product_id, use_negative_cache)
        if source:
            client.incr(STATS_HITS_KEY)
            return product, source

    raise TimeoutError(
        f"Timed out after {max_wait}s waiting for cache fill for product {product_id}"
    )


def print_product(product: dict) -> None:
    for field, value in product.items():
        print(f"  {field}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 3A: product catalog cache-aside")
    parser.add_argument("--cache-ttl", type=int, default=DEFAULT_CACHE_TTL, help="Product hash TTL (seconds)")
    parser.add_argument(
        "--negative-ttl",
        type=int,
        default=DEFAULT_NEGATIVE_TTL,
        help="Not-found marker TTL (seconds)",
    )
    parser.add_argument(
        "--no-negative-cache",
        action="store_true",
        help="Skip m3:nf:product:* keys; always read JSON on miss",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    get_parser = sub.add_parser("get", help="Get product by id")
    get_parser.add_argument("product_id", type=int)
    get_parser.add_argument(
        "--with-lock",
        action="store_true",
        help="Use SET NX lock + double-check (stampede-safe path)",
    )

    sub.add_parser("stats", help="Show cache hit/miss counters")

    args = parser.parse_args()
    client = get_client()
    catalog = load_catalog()
    use_negative = not args.no_negative_cache

    if args.command == "stats":
        hits = int(client.get(STATS_HITS_KEY) or 0)
        misses = int(client.get(STATS_MISSES_KEY) or 0)
        print(f"hits:   {hits}  ({STATS_HITS_KEY})")
        print(f"misses: {misses}  ({STATS_MISSES_KEY})")
        client.close()
        return 0

    started = time.perf_counter()
    fetch = get_product_with_lock if args.with_lock else get_product
    product, source = fetch(
        client,
        catalog,
        args.product_id,
        args.cache_ttl,
        args.negative_ttl,
        use_negative,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    if product is None:
        print(f"Product {args.product_id} not found (source={source}, {elapsed_ms:.2f} ms)")
        client.close()
        return 1

    print(f"Product {args.product_id} (source={source}, {elapsed_ms:.2f} ms):")
    print_product(product)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

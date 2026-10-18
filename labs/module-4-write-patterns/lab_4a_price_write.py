"""
Lab 4A — Product price writes: invalidate vs update cache.

Read path (cache-aside, m4: keys):
  HGETALL → hit | miss → load products.json → HSET + EXPIRE

Write path (DB first, then Redis):
  invalidate — update JSON, DEL m4:product:{id} and m4:nf:product:{id}
  update     — update JSON, HSET all product fields + EXPIRE (full hash refresh)

Commands:
  get <id>
  set-price <id> <price_cents> --mode invalidate|update
  stats
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Literal

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PRODUCT_KEY_PREFIX = "m4:product:"
NEGATIVE_KEY_PREFIX = "m4:nf:product:"
STATS_HITS_KEY = "m4:stats:hits"
STATS_MISSES_KEY = "m4:stats:misses"

DEFAULT_CACHE_TTL = 30
DEFAULT_NEGATIVE_TTL = 60

DATA_PATH = (
    Path(__file__).resolve().parent.parent / "module-3-cache-aside" / "data" / "products.json"
)

WriteMode = Literal["invalidate", "update"]


def product_key(product_id: int | str) -> str:
    return f"{PRODUCT_KEY_PREFIX}{product_id}"


def negative_key(product_id: int | str) -> str:
    return f"{NEGATIVE_KEY_PREFIX}{product_id}"


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


def save_product_price(path: Path, product_id: int, price_cents: int) -> dict:
    """Persist price_cents for product_id; returns the updated product dict."""
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)

    updated: dict | None = None
    for item in payload["products"]:
        if int(item["id"]) == product_id:
            item["price_cents"] = price_cents
            updated = item
            break

    if updated is None:
        raise LookupError(f"Product {product_id} not in catalog")

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    return dict(updated)


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
    cached = client.hgetall(product_key(product_id))
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
    client.hset(key, mapping=product_to_hash(product))
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


def apply_cache_invalidate(client: redis.Redis, product_id: int) -> None:
    client.delete(product_key(product_id), negative_key(product_id))


def apply_cache_update(
    client: redis.Redis,
    product: dict,
    cache_ttl: int,
) -> None:
    key = product_key(product["id"])
    client.hset(key, mapping=product_to_hash(product))
    client.expire(key, cache_ttl)
    client.delete(negative_key(product["id"]))


def set_product_price(
    client: redis.Redis,
    product_id: int,
    price_cents: int,
    mode: WriteMode,
    cache_ttl: int,
    data_path: Path = DATA_PATH,
) -> dict:
    if price_cents < 0:
        raise ValueError("price_cents must be non-negative")

    product = save_product_price(data_path, product_id, price_cents)

    if mode == "invalidate":
        apply_cache_invalidate(client, product_id)
    else:
        apply_cache_update(client, product, cache_ttl)

    return product


def print_product(product: dict) -> None:
    for field, value in product.items():
        print(f"  {field}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 4A: price write invalidate vs update")
    parser.add_argument("--cache-ttl", type=int, default=DEFAULT_CACHE_TTL)
    parser.add_argument("--negative-ttl", type=int, default=DEFAULT_NEGATIVE_TTL)
    parser.add_argument("--no-negative-cache", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    get_parser = sub.add_parser("get", help="Get product by id")
    get_parser.add_argument("product_id", type=int)

    price_parser = sub.add_parser("set-price", help="Update price in JSON then sync cache")
    price_parser.add_argument("product_id", type=int)
    price_parser.add_argument("price_cents", type=int)
    price_parser.add_argument(
        "--mode",
        choices=("invalidate", "update"),
        required=True,
        help="invalidate: DEL cache keys; update: HSET full hash + EXPIRE",
    )

    sub.add_parser("stats", help="Show m4 hit/miss counters")

    args = parser.parse_args()
    client = get_client()
    use_negative = not args.no_negative_cache

    if args.command == "stats":
        hits = int(client.get(STATS_HITS_KEY) or 0)
        misses = int(client.get(STATS_MISSES_KEY) or 0)
        print(f"hits:   {hits}  ({STATS_HITS_KEY})")
        print(f"misses: {misses}  ({STATS_MISSES_KEY})")
        client.close()
        return 0

    catalog = load_catalog()

    if args.command == "set-price":
        try:
            product = set_product_price(
                client,
                args.product_id,
                args.price_cents,
                args.mode,
                args.cache_ttl,
            )
        except LookupError as exc:
            print(exc, file=sys.stderr)
            client.close()
            return 1
        except ValueError as exc:
            print(exc, file=sys.stderr)
            client.close()
            return 1

        catalog[int(product["id"])] = product
        print(
            f"Updated product {args.product_id} price_cents={args.price_cents} "
            f"(mode={args.mode}, db={DATA_PATH})"
        )
        client.close()
        return 0

    started = time.perf_counter()
    product, source = get_product(
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

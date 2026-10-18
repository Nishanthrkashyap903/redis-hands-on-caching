"""
Lab 4B — Write-behind sketch (Variant C).

App: LPUSH job to m4:write-queue → return (JSON not updated yet).
Worker: BRPOP (FIFO with LPUSH) → update products.json → DEL cache keys on success.

Reads: cache-aside (same as Lab 4A / get subcommand here).

Commands:
  enqueue-price <id> <price_cents>
  get <id>
  worker
  queue-len
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import redis
from redis.exceptions import TimeoutError as RedisTimeoutError

# Shared read/write helpers with Lab 4A (same directory).
_LAB_DIR = Path(__file__).resolve().parent
if str(_LAB_DIR) not in sys.path:
    sys.path.insert(0, str(_LAB_DIR))

from lab_4a_price_write import (  # noqa: E402
    DATA_PATH,
    DEFAULT_CACHE_TTL,
    DEFAULT_NEGATIVE_TTL,
    apply_cache_invalidate,
    get_client,
    get_product,
    load_catalog,
    print_product,
    save_product_price,
)

WRITE_QUEUE_KEY = "m4:write-queue"
DEFAULT_BRPOP_TIMEOUT = 5
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def get_worker_client() -> redis.Redis:
    """
    BRPOP can block longer than the default socket read timeout in redis-py 5+.
    Use no socket timeout on the worker connection so idle BRPOP returns None
    instead of raising redis.exceptions.TimeoutError.
    """
    client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=None)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        raise SystemExit(1) from exc
    return client


def job_payload(product_id: int, price_cents: int) -> str:
    body = {
        "product_id": product_id,
        "price_cents": price_cents,
        "enqueued_at": time.time(),
    }
    return json.dumps(body, separators=(",", ":"))


def parse_job(raw: str) -> tuple[int, int]:
    data = json.loads(raw)
    product_id = int(data["product_id"])
    price_cents = int(data["price_cents"])
    return product_id, price_cents


def enqueue_price_write(
    client: redis.Redis,
    catalog: dict[int, dict],
    product_id: int,
    price_cents: int,
) -> int:
    if price_cents < 0:
        raise ValueError("price_cents must be non-negative")
    if product_id not in catalog:
        raise LookupError(f"Product {product_id} not in catalog")

    payload = job_payload(product_id, price_cents)
    return int(client.lpush(WRITE_QUEUE_KEY, payload))


def process_one_job(
    client: redis.Redis,
    raw: str,
    data_path: Path = DATA_PATH,
) -> None:
    product_id, price_cents = parse_job(raw)
    save_product_price(data_path, product_id, price_cents)
    apply_cache_invalidate(client, product_id)
    print(
        f"flushed product_id={product_id} price_cents={price_cents} "
        f"(json updated, cache invalidated)"
    )


def run_worker(
    client: redis.Redis,
    brpop_timeout: int,
    data_path: Path = DATA_PATH,
    demo_delay: float = 0,
) -> None:
    """
    BRPOP blocks until a job exists or timeout elapses (LPUSH + BRPOP = FIFO).

    If the worker crashes after BRPOP but before JSON write, the job is lost
    (at-most-once). No retry queue in this lab sketch.
    """
    delay_note = f", demo_delay={demo_delay}s" if demo_delay > 0 else ""
    print(f"Worker listening on {WRITE_QUEUE_KEY} (BRPOP timeout={brpop_timeout}s{delay_note})...")
    while True:
        try:
            result = client.brpop(WRITE_QUEUE_KEY, timeout=brpop_timeout)
        except RedisTimeoutError:
            # Fallback if socket_timeout is still bounded on this client.
            continue
        if result is None:
            continue
        _, raw = result
        try:
            if demo_delay > 0:
                print(f"demo: holding job {demo_delay}s before JSON flush...", flush=True)
                time.sleep(demo_delay)
            process_one_job(client, raw, data_path)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, LookupError) as exc:
            print(f"skipped bad job ({exc}): {raw!r}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 4B: write-behind queue + worker")
    parser.add_argument("--cache-ttl", type=int, default=DEFAULT_CACHE_TTL)
    parser.add_argument("--negative-ttl", type=int, default=DEFAULT_NEGATIVE_TTL)
    parser.add_argument("--no-negative-cache", action="store_true")
    parser.add_argument(
        "--brpop-timeout",
        type=int,
        default=DEFAULT_BRPOP_TIMEOUT,
        help="Worker BRPOP timeout in seconds (wake periodically if idle)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    enqueue_parser = sub.add_parser("enqueue-price", help="LPUSH write job; JSON updated later")
    enqueue_parser.add_argument("product_id", type=int)
    enqueue_parser.add_argument("price_cents", type=int)

    get_parser = sub.add_parser("get", help="Cache-aside read (may be stale until worker runs)")
    get_parser.add_argument("product_id", type=int)

    worker_parser = sub.add_parser("worker", help="BRPOP loop: JSON write then cache invalidation")
    worker_parser.add_argument(
        "--demo-delay",
        type=float,
        default=float(os.environ.get("M4_WORKER_DEMO_DELAY", "0")),
        help="Seconds to sleep after dequeue before flushing JSON (demo stale-read window)",
    )
    sub.add_parser("queue-len", help="LLEN m4:write-queue")

    args = parser.parse_args()
    client = get_client()
    use_negative = not args.no_negative_cache

    if args.command == "queue-len":
        length = client.llen(WRITE_QUEUE_KEY)
        print(f"queue: {WRITE_QUEUE_KEY}  len={length}")
        client.close()
        return 0

    if args.command == "worker":
        worker_client = get_worker_client()
        try:
            demo_delay = getattr(args, "demo_delay", 0) or 0
            run_worker(worker_client, args.brpop_timeout, demo_delay=demo_delay)
        except KeyboardInterrupt:
            print("\nWorker stopped.")
        worker_client.close()
        return 0

    catalog = load_catalog()

    if args.command == "enqueue-price":
        try:
            depth = enqueue_price_write(
                client,
                catalog,
                args.product_id,
                args.price_cents,
            )
        except LookupError as exc:
            print(exc, file=sys.stderr)
            client.close()
            return 1
        except ValueError as exc:
            print(exc, file=sys.stderr)
            client.close()
            return 1

        print(
            f"enqueued product_id={args.product_id} price_cents={args.price_cents} "
            f"(queue={WRITE_QUEUE_KEY}, depth={depth}; JSON not updated yet)"
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

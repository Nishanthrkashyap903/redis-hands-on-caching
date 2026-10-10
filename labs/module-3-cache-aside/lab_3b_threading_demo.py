"""
Lab 3B prep — threading + ThreadPoolExecutor.

  warmup    — 10 tasks sleep 0.1s each; see threads overlap in time.
  stampede  — delete cache key, hammer same product id; count how many load "db".

Requires Redis (Lab 3A). This does NOT fix stampede — it demonstrates the problem.

Example:
  python lab_3b_threading_demo.py warmup
  python lab_3b_threading_demo.py stampede --workers 30 --product-id 101
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import redis

from lab_3a_catalog import (
    DEFAULT_CACHE_TTL,
    DEFAULT_NEGATIVE_TTL,
    get_client,
    get_product,
    get_product_with_lock,
    load_catalog,
    product_key,
)


class SlowCatalogLookup:
    """Wraps the catalog dict so every JSON read sleeps (simulates slow DB)."""

    def __init__(self, catalog: dict, delay_seconds: float) -> None:
        self._catalog = catalog
        self._delay = delay_seconds
        self._lock = threading.Lock()
        self.db_reads = 0

    def get(self, product_id: int, default=None):
        with self._lock:
            self.db_reads += 1
        time.sleep(self._delay)
        return self._catalog.get(product_id, default)


def run_warmup(workers: int, sleep_seconds: float) -> None:
    print(f"warmup: {workers} tasks, sleep={sleep_seconds}s each, thread pool")
    started = time.perf_counter()

    def work(task_id: int) -> str:
        name = threading.current_thread().name
        time.sleep(sleep_seconds)
        return f"task {task_id} done on {name}"

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="warmup") as pool:
        futures = [pool.submit(work, i) for i in range(workers)]
        for future in as_completed(futures):
            print(f"  {future.result()}")

    elapsed = time.perf_counter() - started
    print(f"wall time: {elapsed:.3f}s (sequential would be ~{workers * sleep_seconds:.3f}s)")


def run_stampede(
    product_id: int,
    workers: int,
    db_delay: float,
    cache_ttl: int,
    protected: bool,
) -> None:
    catalog = load_catalog()
    slow = SlowCatalogLookup(catalog, db_delay)

    setup = get_client()
    setup.delete(product_key(product_id))
    setup.close()

    mode = "protected" if protected else "unprotected"
    print(
        f"stampede: product_id={product_id}, workers={workers}, "
        f"db_delay={db_delay}s, mode={mode} (cache key deleted first)"
    )

    def fetch(_worker_id: int) -> str:
        client = get_client()
        try:
            fetch_fn = get_product_with_lock if protected else get_product
            _, source = fetch_fn(
                client,
                slow,
                product_id,
                cache_ttl,
                DEFAULT_NEGATIVE_TTL,
                use_negative_cache=False,
            )
            return source
        finally:
            client.close()

    started = time.perf_counter()
    sources: list[str] = []

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stampede") as pool:
        futures = [pool.submit(fetch, i) for i in range(workers)]
        for future in as_completed(futures):
            sources.append(future.result())

    elapsed = time.perf_counter() - started
    db_sources = sum(1 for s in sources if s == "db")
    cache_sources = sum(1 for s in sources if s == "cache")

    print(f"results: db={db_sources}, cache={cache_sources}, total={len(sources)}")
    print(f"SlowCatalogLookup.db_reads (JSON lookups): {slow.db_reads}")
    print(f"wall time: {elapsed:.3f}s")
    if protected:
        if slow.db_reads <= 1:
            print("stampede mitigated: at most one JSON read.")
        else:
            print("unexpected: multiple JSON reads with lock enabled.")
    elif db_sources > 1:
        print("stampede visible: more than one worker reported source=db (or multiple JSON reads).")
    else:
        print("only one db source this run — try more workers or longer db_delay.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 3B threading warmup + stampede demo")
    sub = parser.add_subparsers(dest="command", required=True)

    warmup = sub.add_parser("warmup", help="ThreadPoolExecutor + sleep exercise")
    warmup.add_argument("--workers", type=int, default=10)
    warmup.add_argument("--sleep", type=float, default=0.1, help="Seconds per task")

    stampede = sub.add_parser("stampede", help="Concurrent gets on a cold cache key")
    stampede.add_argument("--product-id", type=int, default=101)
    stampede.add_argument("--workers", type=int, default=30)
    stampede.add_argument("--db-delay", type=float, default=0.05, help="Simulated DB latency")
    stampede.add_argument("--cache-ttl", type=int, default=DEFAULT_CACHE_TTL)
    stampede.add_argument(
        "--protected",
        action="store_true",
        help="Use get_product_with_lock from lab_3a_catalog",
    )

    args = parser.parse_args()

    if args.command == "warmup":
        run_warmup(args.workers, args.sleep)
        return 0

    try:
        run_stampede(
            args.product_id,
            args.workers,
            args.db_delay,
            args.cache_ttl,
            args.protected,
        )
    except redis.ConnectionError:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

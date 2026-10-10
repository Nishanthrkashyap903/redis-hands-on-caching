"""
Lab 3B — Cache stampede: compare unprotected vs lock-protected gets.

  python lab_3b_stampede.py run --product-id 101 --workers 30
  python lab_3b_stampede.py run --product-id 101 --workers 30 --protected

Deletes m3:product:{id} before each run so all workers start cold.
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
    """Counts JSON lookups and sleeps to widen the stampede window."""

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


def run_stampede_test(
    product_id: int,
    workers: int,
    db_delay: float,
    protected: bool,
    cache_ttl: int,
) -> int:
    catalog = load_catalog()
    slow = SlowCatalogLookup(catalog, db_delay)

    setup = get_client()
    setup.delete(product_key(product_id))
    setup.close()

    mode = "protected (SET NX lock)" if protected else "unprotected"
    print(
        f"run: product_id={product_id}, workers={workers}, db_delay={db_delay}s, mode={mode}"
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

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stampede") as pool:
            futures = [pool.submit(fetch, i) for i in range(workers)]
            for future in as_completed(futures):
                sources.append(future.result())
    except TimeoutError as exc:
        print(exc, file=sys.stderr)
        return 1

    elapsed = time.perf_counter() - started
    db_sources = sum(1 for s in sources if s == "db")
    cache_sources = sum(1 for s in sources if s == "cache")

    print(f"results: db={db_sources}, cache={cache_sources}, total={len(sources)}")
    print(f"JSON lookups (SlowCatalogLookup.db_reads): {slow.db_reads}")
    print(f"wall time: {elapsed:.3f}s")

    if protected:
        if slow.db_reads <= 1:
            print("stampede mitigated: at most one JSON load for this product id.")
        else:
            print("unexpected: multiple JSON loads with lock — check lock TTL / max_wait.")
    elif db_sources > 1 or slow.db_reads > 1:
        print("stampede visible: multiple db loads — retry with --protected.")
    else:
        print("no stampede this run — try more workers or higher --db-delay.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 3B: cache stampede comparison")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Concurrent cold-cache fetch")
    run.add_argument("--product-id", type=int, default=101)
    run.add_argument("--workers", type=int, default=30)
    run.add_argument("--db-delay", type=float, default=0.05)
    run.add_argument("--cache-ttl", type=int, default=DEFAULT_CACHE_TTL)
    run.add_argument(
        "--protected",
        action="store_true",
        help="Use get_product_with_lock (SET m3:lock:product:{id} NX EX)",
    )

    args = parser.parse_args()

    try:
        return run_stampede_test(
            args.product_id,
            args.workers,
            args.db_delay,
            args.protected,
            args.cache_ttl,
        )
    except redis.ConnectionError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

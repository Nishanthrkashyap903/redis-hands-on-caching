"""
Lab 2 — Fill Redis toward maxmemory and observe evictions.

Writes m2:fill:{n} keys with large values; alternates TTL vs no TTL.
Reports memory metrics and which tracked keys no longer exist.
"""

import argparse
import os
import sys
import time

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KEY_PREFIX = "m2:fill:"
DEFAULT_VALUE_KB = 80
DEFAULT_TTL_SEC = 3600
MEMORY_FILL_RATIO = 0.95
MAX_ITERATIONS = 10_000


def get_client() -> redis.Redis:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        raise SystemExit(1) from exc
    return client


def snapshot(client: redis.Redis) -> dict[str, int | str]:
    mem = client.info("memory")
    stats = client.info("stats")
    policy = client.config_get("maxmemory-policy")["maxmemory-policy"]
    return {
        "used_memory": int(mem["used_memory"]),
        "used_memory_human": mem.get("used_memory_human", "?"),
        "maxmemory": int(mem["maxmemory"]),
        "evicted_keys": int(stats["evicted_keys"]),
        "dbsize": client.dbsize(),
        "maxmemory_policy": policy,
    }


def print_snapshot(label: str, snap: dict[str, int | str]) -> None:
    maxmem = snap["maxmemory"]
    cap = f"{maxmem} bytes" if maxmem else "no limit"
    print(f"--- {label} ---")
    print(f"  used_memory:      {snap['used_memory_human']} ({snap['used_memory']} bytes)")
    print(f"  maxmemory:        {cap}")
    print(f"  maxmemory-policy: {snap['maxmemory_policy']}")
    print(f"  evicted_keys:     {snap['evicted_keys']}")
    print(f"  DBSIZE:           {snap['dbsize']}")


def fill_blob(size_kb: int, seed: int) -> str:
    unit = f"{seed}:".encode() * (max(size_kb * 1024 // max(len(f"{seed}:"), 1), 1))
    return unit[: size_kb * 1024].decode("latin-1")


def find_missing(client: redis.Redis, keys: list[str]) -> list[str]:
    missing: list[str] = []
    pipe = client.pipeline()
    for key in keys:
        pipe.exists(key)
    results = pipe.execute()
    for key, exists in zip(keys, results):
        if not exists:
            missing.append(key)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 2: fill memory and observe evictions")
    parser.add_argument(
        "--value-kb",
        type=int,
        default=DEFAULT_VALUE_KB,
        help="Payload size per key in KB (default 80)",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=DEFAULT_TTL_SEC,
        help="TTL seconds for alternating keys (default 3600)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=MAX_ITERATIONS,
        help="Safety cap on keys written",
    )
    args = parser.parse_args()

    if args.value_kb < 1:
        print("--value-kb must be >= 1", file=sys.stderr)
        return 1

    client = get_client()
    before = snapshot(client)
    print_snapshot("Before fill", before)

    start_evicted = int(before["evicted_keys"])
    maxmemory = int(before["maxmemory"])
    keys_written: list[str] = []
    evictions_seen = False
    stop_reason = "max iterations"

    for i in range(args.max_iterations):
        key = f"{KEY_PREFIX}{i}"
        value = fill_blob(args.value_kb, i)
        with_ttl = i % 2 == 0

        if with_ttl:
            client.set(key, value, ex=args.ttl)
        else:
            client.set(key, value)

        keys_written.append(key)

        stats = client.info("stats")
        evicted = int(stats["evicted_keys"])
        if evicted > start_evicted:
            evictions_seen = True

        mem = client.info("memory")
        used = int(mem["used_memory"])
        at_cap = maxmemory > 0 and used >= int(maxmemory * MEMORY_FILL_RATIO)

        if at_cap and evictions_seen:
            stop_reason = f"used_memory >= {MEMORY_FILL_RATIO:.0%} of maxmemory and evicted_keys increased"
            break
        if at_cap and i > 0 and (i + 1) % 200 == 0:
            stop_reason = f"used_memory >= {MEMORY_FILL_RATIO:.0%} of maxmemory (no evictions yet)"
            break

    time.sleep(0.2)
    after = snapshot(client)
    print()
    print_snapshot("After fill", after)
    print()
    print(f"Keys written this run: {len(keys_written)}")
    print(f"Stop reason: {stop_reason}")
    print(f"evicted_keys delta: {int(after['evicted_keys']) - start_evicted}")

    missing = find_missing(client, keys_written)
    with_ttl_keys = [k for k in keys_written if int(k.split(":")[-1]) % 2 == 0]
    without_ttl_keys = [k for k in keys_written if int(k.split(":")[-1]) % 2 == 1]
    missing_ttl = [k for k in missing if k in with_ttl_keys]
    missing_no_ttl = [k for k in missing if k in without_ttl_keys]

    print()
    print(f"Missing among keys we wrote: {len(missing)} / {len(keys_written)}")
    print(f"  with TTL:    {len(missing_ttl)} missing / {len(with_ttl_keys)} written")
    print(f"  without TTL: {len(missing_no_ttl)} missing / {len(without_ttl_keys)} written")

    sample = 15
    if missing:
        print(f"\nFirst up to {sample} missing keys:")
        for key in missing[:sample]:
            print(f"  {key}")
        if len(missing) > sample:
            print(f"  ... and {len(missing) - sample} more")

    if keys_written:
        sample_key = keys_written[0]
        try:
            usage = client.memory_usage(sample_key)
            print(f"\nMEMORY USAGE {sample_key}: {usage} bytes (if key still exists)")
        except redis.ResponseError:
            print(f"\n{sample_key} no longer exists (evicted or expired).")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

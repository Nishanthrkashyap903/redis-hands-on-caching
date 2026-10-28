"""
Lab 5 extension — Sliding-window rate limiter (N requests per last W seconds).

Key: m5:rl:slide:{sha256(api_key)[:16]}  (ZSET; score = Redis TIME ms)

Modes (--mode):
  py   — ZREMRANGEBYSCORE → ZCARD → optional ZADD (separate commands; racy under concurrency)
  lua  — same logic atomically in EVAL; TIME read once inside script (recommended)

Only allowed requests are ZADDed (denied attempts are not stored).

Commands:
  python lab_5_sliding_window.py --key demo --limit 5
  python lab_5_sliding_window.py --key demo --limit 5 --mode py --count 7
  python lab_5_sliding_window.py --key demo --limit 5 --mode lua --burst 20
  python lab_5_sliding_window.py --key demo --reset
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Literal

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KEY_PREFIX = "m5:rl:slide:"
DEFAULT_WINDOW_SECONDS = 60
KEY_EXPIRE_BUFFER_SECONDS = 60

Mode = Literal["py", "lua"]

LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local expire_sec = tonumber(ARGV[3])

local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local cutoff = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
local n = redis.call('ZCARD', key)

if n >= limit then
  return {0, n, 0, now_ms}
end

local member = now_ms .. '-' .. tostring(math.random(1000000000))
redis.call('ZADD', key, now_ms, member)
redis.call('EXPIRE', key, expire_sec)

return {1, n + 1, limit - n - 1, now_ms}
"""

_SCRIPT_SHA: dict[str, str] = {}


def get_client() -> redis.Redis:
    """Connect to Redis from REDIS_URL; exit with a hint if the server is down."""
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        raise SystemExit(1) from exc
    return client


def sliding_window_key(api_key: str) -> str:
    """Map an API key to the ZSET key for sliding-window state."""
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return f"{KEY_PREFIX}{digest}"


def redis_time_ms(client: redis.Redis) -> int:
    """Wall-clock milliseconds from Redis TIME (same source as Lua path)."""
    sec, micro = client.time()
    return int(sec) * 1000 + int(micro) // 1000


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be >= 1")


def allow_sliding_py(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> tuple[bool, int, int, int]:
    """
    Sliding window via separate Redis commands (educational; not safe under concurrent load).

    Uses Redis TIME for now_ms. Prune, ZCARD, then ZADD only if under limit.

    Returns:
        allowed, count_in_window, remaining_if_allowed, now_ms
    """
    _validate_limit(limit)
    key = sliding_window_key(api_key)
    window_ms = window_seconds * 1000
    now_ms = redis_time_ms(client)
    cutoff = now_ms - window_ms

    client.zremrangebyscore(key, 0, cutoff)
    count = int(client.zcard(key))

    if count >= limit:
        return False, count, 0, now_ms

    member = f"{now_ms}-{uuid.uuid4().hex[:12]}"
    client.zadd(key, {member: now_ms})
    client.expire(key, window_seconds + KEY_EXPIRE_BUFFER_SECONDS)

    new_count = count + 1
    remaining = max(0, limit - new_count)
    return True, new_count, remaining, now_ms


def allow_sliding_lua(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> tuple[bool, int, int, int]:
    """
    Sliding window in one Lua script: TIME, prune, ZCARD, conditional ZADD, EXPIRE.

    Returns:
        allowed, count_in_window, remaining_if_allowed, now_ms
    """
    _validate_limit(limit)
    key = sliding_window_key(api_key)
    window_ms = window_seconds * 1000
    expire_sec = window_seconds + KEY_EXPIRE_BUFFER_SECONDS

    sha = _SCRIPT_SHA.get("sliding")
    if sha is None:
        sha = client.script_load(LUA_SLIDING_WINDOW)
        _SCRIPT_SHA["sliding"] = sha

    raw = client.evalsha(
        sha,
        1,
        key,
        limit,
        window_ms,
        expire_sec,
    )
    allowed_flag, count, remaining, now_ms = (
        int(raw[0]),
        int(raw[1]),
        int(raw[2]),
        int(raw[3]),
    )
    return allowed_flag == 1, count, remaining, now_ms


_ALLOW_BY_MODE: dict[Mode, Callable[..., tuple[bool, int, int, int]]] = {
    "py": allow_sliding_py,
    "lua": allow_sliding_lua,
}


def allow(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    mode: Mode = "lua",
) -> tuple[bool, int, int, int]:
    """Dispatch sliding-window allow to py or lua implementation."""
    return _ALLOW_BY_MODE[mode](client, api_key, limit, window_seconds)


def format_result(
    api_key: str,
    allowed: bool,
    count: int,
    remaining: int,
    now_ms: int,
    mode: Mode,
) -> str:
    """Format one allow() outcome for CLI logging."""
    status = "allowed" if allowed else "denied"
    return (
        f"mode={mode} key={sliding_window_key(api_key)!r} status={status} "
        f"count={count} remaining={remaining} now_ms={now_ms}"
    )


def cmd_check(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int,
    count: int,
    mode: Mode,
) -> int:
    """Run count sequential allow() calls and print each result."""
    denied = 0
    for i in range(count):
        allowed, n, remaining, now_ms = allow(
            client, api_key, limit, window_seconds, mode=mode
        )
        print(f"request={i + 1} {format_result(api_key, allowed, n, remaining, now_ms, mode)}")
        if not allowed:
            denied += 1
    if count > 1:
        print(f"summary: {count - denied}/{count} allowed, {denied} denied")
    return 0


def cmd_burst(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int,
    workers: int,
    mode: Mode,
) -> int:


    """Concurrent allow() calls; exit 1 if more than limit were allowed."""
    def one_shot(_: int) -> tuple[bool, int, int, int]:
        return allow(client, api_key, limit, window_seconds, mode=mode)

    allowed_n = 0
    denied_n = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one_shot, i) for i in range(workers)]
        for fut in as_completed(futures):
            ok, _, _, _ = fut.result()
            if ok:
                allowed_n += 1
            else:
                denied_n += 1

    zcard = client.zcard(sliding_window_key(api_key))
    print(
        f"burst: mode={mode} workers={workers} limit={limit} allowed={allowed_n} "
        f"denied={denied_n} zcard={zcard}"
    )
    if allowed_n > limit:
        print(
            f"warning: allowed ({allowed_n}) > limit ({limit}) — "
            f"use --mode lua for atomic sliding window",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    """Parse CLI flags and run reset, burst, or sequential checks."""
    parser = argparse.ArgumentParser(description="Lab 5: sliding-window rate limiter")
    parser.add_argument("--key", required=True, help="API key (or IP string) to rate limit")
    parser.add_argument("--limit", type=int, default=5, help="Max requests in sliding window")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_SECONDS, help="Window (seconds)")
    parser.add_argument(
        "--mode",
        choices=("py", "lua"),
        default="lua",
        help="py = separate commands (racy); lua = atomic script (default)",
    )
    parser.add_argument("--count", type=int, default=1, help="Sequential allow() calls")
    parser.add_argument("--burst", type=int, metavar="N", help="Concurrent allow() calls")
    parser.add_argument("--reset", action="store_true", help="DEL sliding ZSET key")
    args = parser.parse_args()
    mode: Mode = args.mode

    client = get_client()
    if args.reset:
        deleted = client.delete(sliding_window_key(args.key))
        print(f"reset key={sliding_window_key(args.key)!r} deleted={deleted}")
        client.close()
        return 0

    if args.burst is not None:
        if args.burst < 1:
            print("--burst must be >= 1", file=sys.stderr)
            return 1
        code = cmd_burst(
            client, args.key, args.limit, args.window, args.burst, mode
        )
        client.close()
        return code

    if args.count < 1:
        print("--count must be >= 1", file=sys.stderr)
        return 1

    code = cmd_check(client, args.key, args.limit, args.window, args.count, mode)
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())

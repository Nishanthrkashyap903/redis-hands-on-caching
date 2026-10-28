"""
Lab 5 — Fixed-window rate limiter (N requests per 60 seconds per API key).

Key: m5:rl:{sha256(api_key)[:16]}  (hash keeps Redis keys safe for arbitrary input)

Modes (--mode):
  a      — Approach A: INCR, EXPIRE on n==1, then compare to limit
  b      — Approach B: TTL==-2 → SET 0 NX EX, INCR, compare (default)
  a-lua  — Approach A in one EVAL (INCR + conditional EXPIRE + allow/deny)
  b-lua  — Approach B in one EVAL (TTL/SET + INCR + allow/deny)

Commands:
  python lab_5_rate_limit.py --key demo --limit 5
  python lab_5_rate_limit.py --key demo --limit 5 --mode a --count 7
  python lab_5_rate_limit.py --key demo --limit 5 --mode a-lua --burst 20
  python lab_5_rate_limit.py --key demo --reset
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Literal

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KEY_PREFIX = "m5:rl:"
DEFAULT_WINDOW_SECONDS = 60

Mode = Literal["a", "b", "a-lua", "b-lua"]

LUA_APPROACH_A = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local limit = tonumber(ARGV[2])
if n > limit then
  return {0, n}
end
return {1, n}
"""

LUA_APPROACH_B = """
if redis.call('TTL', KEYS[1]) == -2 then
  redis.call('SET', KEYS[1], 0, 'NX', 'EX', tonumber(ARGV[1]))
end
local n = redis.call('INCR', KEYS[1])
local limit = tonumber(ARGV[2])
if n > limit then
  return {0, n}
end
return {1, n}
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


def rate_limit_key(api_key: str) -> str:
    """Map an API key or IP string to a namespaced Redis key (hashed for safe key bytes)."""
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return f"{KEY_PREFIX}{digest}"


def _result_from_count(limit: int, count: int) -> tuple[bool, int, int]:
    """Build (allowed, count, remaining) from post-INCR count."""
    allowed = count <= limit
    remaining = max(0, limit - count) if allowed else 0
    return allowed, count, remaining


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be >= 1")


def allow_approach_a(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> tuple[bool, int, int]:
    """
    Approach A: INCR first; on first hit in window (n==1), EXPIRE; then allow if n <= limit.

    Denied requests still increment the counter.
    """
    _validate_limit(limit)
    key = rate_limit_key(api_key)
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, window_seconds)
    return _result_from_count(limit, count)


def allow_approach_b(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> tuple[bool, int, int]:
    """
    Approach B: if TTL==-2, SET 0 NX EX window; INCR; allow if n <= limit.

    Denied requests still increment the counter.
    """
    _validate_limit(limit)
    key = rate_limit_key(api_key)
    if client.ttl(key) == -2:
        client.set(key, 0, nx=True, ex=window_seconds)
    count = int(client.incr(key))
    return _result_from_count(limit, count)


def _eval_allow_script(
    client: redis.Redis,
    script_id: str,
    script_body: str,
    api_key: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int, int]:
    """Run a loaded Lua allow script; returns (allowed, count, remaining)."""
    _validate_limit(limit)
    key = rate_limit_key(api_key)
    sha = _SCRIPT_SHA.get(script_id)
    if sha is None:
        sha = client.script_load(script_body)
        _SCRIPT_SHA[script_id] = sha
    raw = client.evalsha(sha, 1, key, window_seconds, limit)
    allowed_flag, count = int(raw[0]), int(raw[1])
    allowed = allowed_flag == 1
    remaining = max(0, limit - count) if allowed else 0
    return allowed, count, remaining


def allow_approach_a_lua(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> tuple[bool, int, int]:
    """Approach A as atomic Lua: INCR, EXPIRE if n==1, deny if n > limit."""
    return _eval_allow_script(
        client, "approach_a", LUA_APPROACH_A, api_key, limit, window_seconds
    )


def allow_approach_b_lua(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> tuple[bool, int, int]:
    """Approach B as atomic Lua: TTL/SET on miss, INCR, deny if n > limit."""
    return _eval_allow_script(
        client, "approach_b", LUA_APPROACH_B, api_key, limit, window_seconds
    )


_ALLOW_BY_MODE: dict[Mode, Callable[..., tuple[bool, int, int]]] = {
    "a": allow_approach_a,
    "b": allow_approach_b,
    "a-lua": allow_approach_a_lua,
    "b-lua": allow_approach_b_lua,
}


def allow(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    mode: Mode = "b",
) -> tuple[bool, int, int]:
    """
    Dispatch fixed-window rate limiting to the implementation for mode.

    Returns:
        allowed: True if request is within limit after counting.
        count: Redis counter after handling this request.
        remaining: Quota left in window if allowed, else 0.
    """
    handler = _ALLOW_BY_MODE[mode]
    return handler(client, api_key, limit, window_seconds)


def format_result(
    api_key: str,
    allowed: bool,
    count: int,
    remaining: int,
    ttl: int,
    mode: Mode,
) -> str:
    """Format one allow() outcome for CLI logging."""
    status = "allowed" if allowed else "denied"
    return (
        f"mode={mode} key={rate_limit_key(api_key)!r} status={status} count={count} "
        f"remaining={remaining} ttl={ttl}"
    )


def cmd_check(
    client: redis.Redis,
    api_key: str,
    limit: int,
    window_seconds: int,
    count: int,
    mode: Mode,
) -> int:
    """Run count sequential allow() calls and print each result; return process exit code 0."""
    denied = 0
    for i in range(count):
        allowed, n, remaining = allow(client, api_key, limit, window_seconds, mode=mode)
        ttl = client.ttl(rate_limit_key(api_key))
        print(f"request={i + 1} {format_result(api_key, allowed, n, remaining, ttl, mode)}")
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
    """
    Fire workers concurrent allow() calls (one per thread) and print aggregate stats.

    Returns exit code 1 if more than limit calls were allowed (unexpected race).
    """
    def one_shot(_: int) -> tuple[bool, int, int]:
        return allow(client, api_key, limit, window_seconds, mode=mode)

    allowed_n = 0
    denied_n = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one_shot, i) for i in range(workers)]
        for fut in as_completed(futures):
            allowed, _, _ = fut.result()
            if allowed:
                allowed_n += 1
            else:
                denied_n += 1

    ttl = client.ttl(rate_limit_key(api_key))
    value = client.get(rate_limit_key(api_key))
    print(
        f"burst: mode={mode} workers={workers} limit={limit} allowed={allowed_n} "
        f"denied={denied_n} redis_count={value} ttl={ttl}"
    )
    if allowed_n > limit:
        print(
            f"warning: allowed ({allowed_n}) > limit ({limit}) — investigate concurrency",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    """Parse CLI flags, run reset / burst / sequential check, and return an exit code."""
    parser = argparse.ArgumentParser(description="Lab 5: fixed-window rate limiter")
    parser.add_argument("--key", required=True, help="API key (or IP string) to rate limit")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max allowed requests per window (default 5)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW_SECONDS,
        help="Window length in seconds (default 60)",
    )
    parser.add_argument(
        "--mode",
        choices=("a", "b", "a-lua", "b-lua"),
        default="b",
        help="Algorithm: a, b (Python), a-lua, b-lua (default b)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Sequential allow() calls (default 1)",
    )
    parser.add_argument(
        "--burst",
        type=int,
        metavar="N",
        help="Concurrent allow() calls from N threads (one shot each)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DEL rate limit key for --key, then exit",
    )
    args = parser.parse_args()
    mode: Mode = args.mode

    client = get_client()
    if args.reset:
        deleted = client.delete(rate_limit_key(args.key))
        print(f"reset key={rate_limit_key(args.key)!r} deleted={deleted}")
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

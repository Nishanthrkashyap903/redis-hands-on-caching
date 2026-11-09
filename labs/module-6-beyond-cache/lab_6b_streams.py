"""
Module 6 Lab 6B — Streams: metric event log with bounded length.

Stream key: m6:events:stream

Terminal 1 (start first; leave running):
  python lab_6b_streams.py consume

Terminal 2:
  python lab_6b_streams.py produce

Stream vs Pub/Sub: a consumer that joins after metrics were XADDed can still
XREVRANGE the last N entries; Pub/Sub would have missed publishes while offline.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import datetime, timezone

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_STREAM = "m6:events:stream"
DEFAULT_MAXLEN = 10
DEFAULT_CATCH_UP = 10
DEFAULT_READ_COUNT = 10
DEFAULT_BLOCK_MS = 5_000
DEFAULT_PRODUCE_COUNT = 5
DEFAULT_INTERVAL_SEC = 1.5

StreamId = str


def log_entry(entry_id: StreamId, fields: dict[str, str], tag: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    print(
        f"[{ts}] {tag} id={entry_id} "
        f"name={fields.get('name')} value={fields.get('value')}",
    )


def stream_catch_up(client: redis.Redis, stream: str, count: int) -> StreamId:
    """Last N entries (newest window); returns last_id for XREAD tail."""
    entries = client.xrevrange(stream, count=count)
    if not entries:
        print("Catch-up: stream empty — tail will start from id 0")
        return "0"

    for entry_id, fields in reversed(entries):
        log_entry(entry_id, fields, "catch-up")

    last_id = entries[0][0]
    print(f"Catch-up: {len(entries)} entries; last_id={last_id}")
    return last_id


def run_consumer(
    stream: str,
    catch_up_count: int,
    read_count: int,
    block_ms: int,
) -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    print(f"Consuming {stream!r} on {REDIS_URL} (Ctrl+C to stop)")

    last_id = stream_catch_up(client, stream, catch_up_count)

    try:
        while True:
            try:
                result = client.xread(
                    {stream: last_id},
                    count=read_count,
                    block=block_ms,
                )
            except redis.TimeoutError:
                continue
            if not result:
                continue
            for _, messages in result:
                for entry_id, fields in messages:
                    log_entry(entry_id, fields, "live")
                    last_id = entry_id
    except KeyboardInterrupt:
        print("\nStopping consumer…")
    finally:
        client.close()


def run_producer(
    stream: str,
    count: int,
    interval_sec: float,
    maxlen: int,
) -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    print(
        f"Producing {count} event(s) to {stream!r} "
        f"(MAXLEN ~ {maxlen}) every {interval_sec}s",
    )

    for i in range(count):
        value = random.randint(1, 10_000)
        entry_id = client.xadd(
            stream,
            {"name": "requests", "value": str(value)},
            maxlen=maxlen,
            approximate=True,
        )
        length = client.xlen(stream)
        print(
            f"  #{i + 1} id={entry_id} value={value} XLEN={length}",
        )
        if i < count - 1:
            time.sleep(interval_sec)

    client.close()
    print("Producer done.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Module 6 Lab 6B — Streams (produce | consume)",
    )
    parser.add_argument(
        "--stream",
        default=DEFAULT_STREAM,
        help=f"Stream key (default: {DEFAULT_STREAM})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    produce = sub.add_parser("produce", help="XADD metrics with MAXLEN ~ cap")
    produce.add_argument(
        "--count",
        type=int,
        default=DEFAULT_PRODUCE_COUNT,
        help=f"Number of events (default: {DEFAULT_PRODUCE_COUNT})",
    )
    produce.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        help=f"Seconds between events (default: {DEFAULT_INTERVAL_SEC})",
    )
    produce.add_argument(
        "--maxlen",
        type=int,
        default=DEFAULT_MAXLEN,
        help=f"XADD MAXLEN ~ cap (default: {DEFAULT_MAXLEN})",
    )

    consume = sub.add_parser("consume", help="Catch-up last N, then blocking XREAD tail")
    consume.add_argument(
        "--catch-up",
        type=int,
        default=DEFAULT_CATCH_UP,
        help=f"Initial XREVRANGE count (default: {DEFAULT_CATCH_UP})",
    )
    consume.add_argument(
        "--read-count",
        type=int,
        default=DEFAULT_READ_COUNT,
        help=f"XREAD COUNT per call (default: {DEFAULT_READ_COUNT})",
    )
    consume.add_argument(
        "--block-ms",
        type=int,
        default=DEFAULT_BLOCK_MS,
        help=f"XREAD BLOCK milliseconds (default: {DEFAULT_BLOCK_MS})",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "consume":
        run_consumer(
            args.stream,
            args.catch_up,
            args.read_count,
            args.block_ms,
        )
        return 0

    if args.command == "produce":
        if args.count < 1:
            print("--count must be >= 1", file=sys.stderr)
            return 1
        if args.interval < 0:
            print("--interval must be >= 0", file=sys.stderr)
            return 1
        if args.maxlen < 1:
            print("--maxlen must be >= 1", file=sys.stderr)
            return 1
        run_producer(args.stream, args.count, args.interval, args.maxlen)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

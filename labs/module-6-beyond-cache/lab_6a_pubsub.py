"""
Module 6 warm-up B — Pub/Sub publisher and subscriber (separate processes).

Channel: m6:metrics:live

Terminal 1:
  python lab_6a_pubsub.py subscribe

Terminal 2:
  python lab_6a_pubsub.py publish
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_CHANNEL = "m6:metrics:live"
DEFAULT_PUBLISH_COUNT = 5
DEFAULT_PUBLISH_INTERVAL_SEC = 1.5


def run_subscriber(channel: str) -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)
    print(f"Subscribed to {channel!r} on {REDIS_URL} (Ctrl+C to stop)")

    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw
            received_at = datetime.now(timezone.utc).isoformat()
            print(f"[{received_at}] {payload}")
    except KeyboardInterrupt:
        print("\nStopping subscriber…")
    finally:
        pubsub.unsubscribe(channel)
        pubsub.close()
        client.close()


def run_publisher(
    channel: str,
    count: int,
    interval_sec: float,
) -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    print(f"Publishing {count} message(s) to {channel!r} every {interval_sec}s")

    for i in range(count):
        body = json.dumps(
            {"name": "requests", "value": random.randint(1, 10_000)},
        )
        receivers = client.publish(channel, body)
        print(f"  #{i + 1} subscribers={receivers} body={body}")
        if i < count - 1:
            time.sleep(interval_sec)

    client.close()
    print("Publisher done.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Module 6 — Redis Pub/Sub warm-up (subscribe | publish)",
    )
    parser.add_argument(
        "--channel",
        default=DEFAULT_CHANNEL,
        help=f"Pub/Sub channel (default: {DEFAULT_CHANNEL})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("subscribe", help="Listen until Ctrl+C")

    pub = sub.add_parser("publish", help="Send JSON metrics then exit")
    pub.add_argument(
        "--count",
        type=int,
        default=DEFAULT_PUBLISH_COUNT,
        help=f"Number of messages (default: {DEFAULT_PUBLISH_COUNT})",
    )
    pub.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_PUBLISH_INTERVAL_SEC,
        help=f"Seconds between messages (default: {DEFAULT_PUBLISH_INTERVAL_SEC})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "subscribe":
        run_subscriber(args.channel)
        return 0
    if args.command == "publish":
        if args.count < 1:
            print("--count must be >= 1", file=sys.stderr)
            return 1
        if args.interval < 0:
            print("--interval must be >= 0", file=sys.stderr)
            return 1
        run_publisher(args.channel, args.count, args.interval)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

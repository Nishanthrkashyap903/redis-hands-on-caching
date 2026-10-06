"""
Lab 1C — Top-N leaderboard (sorted set).

Cache key: app:leaderboard

Adjust points: ZINCRBY key delta player (new members start at 0).
Minimum score is 0 — if ZINCRBY goes below 0, score is set to 0 with ZADD.

Top N: ZREVRANGE key 0 N-1 WITHSCORES
"""

import argparse
import os
import sys

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
LEADERBOARD_KEY = "app:leaderboard"
DEFAULT_TOP_N = 10
MIN_SCORE = 0


def get_client() -> redis.Redis:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        raise SystemExit(1) from exc
    return client


def adjust_points(client: redis.Redis, player: str, delta: int) -> float:
    if delta == 0:
        raise SystemExit("points must be non-zero.")
    new_score = float(client.zincrby(LEADERBOARD_KEY, delta, player))
    if new_score < MIN_SCORE:
        client.zadd(LEADERBOARD_KEY, {player: MIN_SCORE})
        return float(MIN_SCORE)
    return new_score


def top_n(client: redis.Redis, n: int) -> list[tuple[str, float]]:
    if n <= 0:
        raise SystemExit("N must be positive.")
    rows = client.zrevrange(LEADERBOARD_KEY, 0, n - 1, withscores=True)
    return [(member, float(score)) for member, score in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 1C: leaderboard")
    sub = parser.add_subparsers(dest="command", required=True)

    add_parser = sub.add_parser("add-points", help="Add points to a player")
    add_parser.add_argument("player")
    add_parser.add_argument("points", type=int)

    sub_parser = sub.add_parser("subtract-points", help="Subtract points (score floor is 0)")
    sub_parser.add_argument("player")
    sub_parser.add_argument("points", type=int)

    top_parser = sub.add_parser("top", help="Show top N players by score")
    top_parser.add_argument("-n", type=int, default=DEFAULT_TOP_N, help="Number of ranks (default 10)")

    args = parser.parse_args()
    client = get_client()

    if args.command == "add-points":
        if args.points <= 0:
            raise SystemExit("add-points requires a positive integer.")
        score = adjust_points(client, args.player, args.points)
        print(f"{args.player}: {score}")
    elif args.command == "subtract-points":
        if args.points <= 0:
            raise SystemExit("subtract-points requires a positive integer.")
        score = adjust_points(client, args.player, -args.points)
        print(f"{args.player}: {score}")
    else:
        ranks = top_n(client, args.n)
        if not ranks:
            print("(empty leaderboard)")
        else:
            for rank, (player, score) in enumerate(ranks, start=1):
                print(f"{rank}. {player} — {score}")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

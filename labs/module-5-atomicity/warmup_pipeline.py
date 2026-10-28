"""
Module 5 warm-up B — pipeline (RTT batching) vs MULTI/EXEC (transaction).

Keys:
  m5:lab:pipe  — 10x INCR in one non-transactional pipeline
  m5:lab:multi — 2x INCR inside pipe.multi() / EXEC

Run:
  python warmup_pipeline.py
"""

import os
import sys

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KEY_PIPE = "m5:lab:pipe"
KEY_MULTI = "m5:lab:multi"
PIPE_INCRS = 10


def experiment_pipeline(client: redis.Redis) -> None:
    client.delete(KEY_PIPE)
    pipe = client.pipeline()
    for _ in range(PIPE_INCRS):
        pipe.incr(KEY_PIPE)
    results = pipe.execute()
    last = results[-1]
    value = client.get(KEY_PIPE)
    print("--- Experiment 1: pipeline() (batch RTT, not MULTI/EXEC) ---")
    print(f"  Queued {PIPE_INCRS} INCR on {KEY_PIPE}")
    print(f"  Last INCR reply from execute(): {last}")
    print(f"  GET {KEY_PIPE}: {value}")
    if last != PIPE_INCRS or value != str(PIPE_INCRS):
        print("  Unexpected: expected last reply and GET to be 10.", file=sys.stderr)
        sys.exit(1)


def experiment_multi(client: redis.Redis) -> None:
    client.delete(KEY_MULTI)
    pipe = client.pipeline()
    pipe.multi()
    pipe.incr(KEY_MULTI)
    pipe.incr(KEY_MULTI)
    results = pipe.execute()
    value = client.get(KEY_MULTI)
    print("--- Experiment 2: pipe.multi() + INCR x2 (MULTI/EXEC) ---")
    print(f"  execute() replies: {results}")
    print(f"  GET {KEY_MULTI}: {value}")
    if value != "2":
        print("  Unexpected: both INCRs should apply; GET should be 2.", file=sys.stderr)
        sys.exit(1)
    print("  OK — both increments applied in one transaction block.")


def main() -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    client.ping()
    print(f"Connected to {REDIS_URL}\n")

    experiment_pipeline(client)
    print()
    experiment_multi(client)

    client.delete(KEY_PIPE, KEY_MULTI)
    print(f"\nCleaned up {KEY_PIPE}, {KEY_MULTI}")
    client.close()


if __name__ == "__main__":
    main()

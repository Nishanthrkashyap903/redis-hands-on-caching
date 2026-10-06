"""Mini project: connection, 10 round-trip latency samples, clean shutdown."""

import os
import statistics
import time

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SAMPLES = 10


def main() -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    client.ping()
    print(f"Connected to {REDIS_URL}")

    latencies_ms: list[float] = []
    for i in range(SAMPLES):
        start = time.perf_counter()
        client.set(f"module0:latency:{i}", str(i), ex=60)
        client.get(f"module0:latency:{i}")
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies_ms.append(elapsed_ms)

    print(f"Round-trip (SET+GET) over {SAMPLES} ops:")
    print(f"  min:    {min(latencies_ms):.2f} ms")
    print(f"  median: {statistics.median(latencies_ms):.2f} ms")
    print(f"  max:    {max(latencies_ms):.2f} ms")

    client.close()
    print("Connection closed.")


if __name__ == "__main__":
    main()

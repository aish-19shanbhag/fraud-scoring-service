"""Measures end-to-end latency of POST /score, one request at a time.

    python scripts/benchmark_latency.py --api http://localhost:8000 -n 1000

This is the latency a payment gateway sees for one call (network + features +
model + database write). For throughput under concurrency, use loadtest/.
"""

import argparse
import random
import statistics
import time
import uuid

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("-n", type=int, default=1000)
    args = parser.parse_args()

    timings = []
    with httpx.Client(base_url=args.api, timeout=10) as client:
        for i in range(args.n + 50):
            payload = {
                "transaction_id": f"bench-{uuid.uuid4().hex}",
                "user_id": f"B{random.randint(0, 999):04d}",
                "amount": round(random.lognormvariate(3.7, 0.8), 2),
                "merchant": "Benchmark Store",
                "merchant_category": random.choice(["grocery", "retail", "online_retail", "electronics"]),
                "country": "US",
                "device_id": "D-bench",
                "card_present": False,
            }
            start = time.perf_counter()
            client.post("/api/v1/transactions/score", json=payload).raise_for_status()
            if i >= 50:  # skip warm-up requests
                timings.append((time.perf_counter() - start) * 1000)

    timings.sort()
    pct = lambda p: timings[int(len(timings) * p) - 1]  # noqa: E731
    print(f"requests: {len(timings)}")
    print(f"p50: {pct(0.50):.1f} ms | p95: {pct(0.95):.1f} ms | p99: {pct(0.99):.1f} ms")
    print(f"mean: {statistics.mean(timings):.1f} ms")


if __name__ == "__main__":
    main()

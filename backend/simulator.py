"""Streams realistic transactions (with labelled fraud) to the API.

    python simulator.py                         # 5 transactions/second against localhost
    python simulator.py --rate 20
    python simulator.py --api http://api:8000   # inside docker compose

How it works: it generates a realistic history (normal spending + fraud
attacks), shifted so it ends right now. The first `--warmup-days` are sent as
fast as possible so every user has a spending profile; the remaining days are
then streamed at `--rate` transactions per second, the "live" traffic you see
on the dashboard. When a round finishes, a new round starts with new users.

Replaying generated history (instead of inventing traffic on the fly) keeps
each user's activity realistic: a few purchases a day, not one every second.
"""

import argparse
import itertools
import time
from datetime import UTC, datetime

import httpx

from ml.synthetic import DAY, generate_history

API_FIELDS = (
    "transaction_id", "user_id", "amount", "currency", "merchant",
    "merchant_category", "country", "device_id", "card_present",
)  # fmt: skip


def to_payload(txn: dict) -> dict:
    payload = {k: txn[k] for k in API_FIELDS}
    payload["timestamp"] = datetime.fromtimestamp(txn["timestamp"], tz=UTC).isoformat()
    return payload


def post(client: httpx.Client, txn: dict) -> dict | None:
    for _ in range(5):
        try:
            resp = client.post("/api/v1/transactions/score", json=to_payload(txn))
        except httpx.TransportError as exc:
            print(f"API not reachable ({exc.__class__.__name__}), retrying...")
            time.sleep(2)
            continue
        if resp.status_code == 429:  # rate limited: wait and retry
            time.sleep(float(resp.headers.get("Retry-After", 5)))
            continue
        resp.raise_for_status()
        return resp.json()
    return None


def wait_for_api(client: httpx.Client, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise SystemExit(f"API at {client.base_url} did not become healthy within {timeout}s")


def run_round(client: httpx.Client, args: argparse.Namespace, round_no: int, totals: dict) -> None:
    days = args.warmup_days + args.live_days
    start = time.time() - days * DAY
    history = generate_history(
        args.users, days, start, seed=args.seed + round_no,
        fraud_user_rate=args.fraud_user_rate, id_prefix=f"R{round_no}U",
    )  # fmt: skip
    live_from = start + args.warmup_days * DAY
    warmup = [t for t in history if t["timestamp"] < live_from]
    live = [t for t in history if t["timestamp"] >= live_from]

    print(f"Round {round_no}: warming up {args.users} users with {len(warmup):,} past transactions...")
    for txn in warmup:
        post(client, txn)

    print(f"Round {round_no}: streaming {len(live):,} transactions at ~{args.rate}/s. Ctrl+C to stop.")
    for txn in live:
        tick = time.time()
        result = post(client, txn)
        if result is not None:
            totals["sent"] += 1
            totals["fraud"] += txn["is_fraud"]
            if result["risk_level"] != "GREEN":
                totals["flagged"] += 1
                totals["caught"] += txn["is_fraud"]
                label = "FRAUD" if txn["is_fraud"] else "legit"
                print(
                    f"[{result['risk_level']:5}] {label:5} {txn['user_id']:<10} ${txn['amount']:>8.2f} "
                    f"{txn['merchant_category']:<13} score={result['risk_score']:.3f}  "
                    f"{'; '.join(result['signals'][:2])}"
                )
        time.sleep(max(0.0, 1.0 / args.rate - (time.time() - tick)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--rate", type=float, default=5.0, help="live transactions per second")
    parser.add_argument("--users", type=int, default=300)
    parser.add_argument("--warmup-days", type=int, default=7)
    parser.add_argument("--live-days", type=int, default=3)
    parser.add_argument("--fraud-user-rate", type=float, default=0.4, help="share of users hit by one attack")
    parser.add_argument("--seed", type=int, default=int(time.time()) % 100_000)
    args = parser.parse_args()

    totals = {"sent": 0, "flagged": 0, "fraud": 0, "caught": 0}
    with httpx.Client(base_url=args.api, timeout=10) as client:
        wait_for_api(client)
        try:
            for round_no in itertools.count(1):
                run_round(client, args, round_no, totals)
        except KeyboardInterrupt:
            pass
    print(
        f"\nStopped. Streamed {totals['sent']:,} live transactions: {totals['flagged']:,} flagged; "
        f"caught {totals['caught']:,} of {totals['fraud']:,} fraudulent ones."
    )


if __name__ == "__main__":
    main()

"""Real-time feature store backed by Redis.

For every user we keep, in Redis:

    user:{id}:txns     sorted set of recent transactions (score = unix time)
    user:{id}:profile  hash with running count, total amount, home country, last time
    user:{id}:devices  set of device ids seen before

Reading these takes one round trip (a pipeline), so features are computed in
about a millisecond, fast enough to score a payment before it is approved.
"""

import math
from datetime import UTC, datetime

import redis

from app.features import MERCHANT_CATEGORY_RISK

WINDOW_KEEP_SECONDS = 24 * 3600  # how much transaction history to keep per user
KEY_TTL_SECONDS = 30 * 24 * 3600  # forget users inactive for 30 days
MAX_GAP_SECONDS = 7 * 24 * 3600  # cap for "seconds since last transaction"


class FeatureStore:
    def __init__(self, client: redis.Redis):
        self.r = client

    @staticmethod
    def _keys(user_id: str) -> tuple[str, str, str]:
        return f"user:{user_id}:txns", f"user:{user_id}:profile", f"user:{user_id}:devices"

    def compute_features(self, txn: dict) -> dict[str, float]:
        """Compute features for `txn` using only the user's *previous* activity.

        `txn` needs: user_id, amount, merchant_category, country, device_id,
        card_present, timestamp (unix seconds).
        """
        ts = float(txn["timestamp"])
        k_txns, k_profile, k_devices = self._keys(txn["user_id"])

        pipe = self.r.pipeline()
        pipe.zrangebyscore(k_txns, ts - 3600, ts, withscores=True)
        pipe.hgetall(k_profile)
        pipe.sismember(k_devices, txn["device_id"])
        recent, profile, device_seen = pipe.execute()

        # Recent members look like "<txn_id>|<amount>"
        txn_count_1h = len(recent)
        amount_sum_1h = sum(float(member.split("|")[1]) for member, _ in recent)
        txn_count_10m = sum(1 for _, score in recent if score >= ts - 600)

        history_count = int(profile.get("txn_count", 0))
        amount_total = float(profile.get("amount_sum", 0.0))
        home_country = profile.get("home_country")
        last_ts = float(profile["last_ts"]) if "last_ts" in profile else None

        amount = float(txn["amount"])
        user_avg = amount_total / history_count if history_count else None
        hour = datetime.fromtimestamp(ts, tz=UTC).hour

        return {
            "amount": amount,
            "log_amount": math.log1p(amount),
            "amount_to_user_avg": round(amount / user_avg, 4) if user_avg else 1.0,
            "txn_count_10m": float(txn_count_10m),
            "txn_count_1h": float(txn_count_1h),
            "amount_sum_1h": round(amount_sum_1h, 2),
            "seconds_since_last_txn": (min(max(ts - last_ts, 0.0), MAX_GAP_SECONDS) if last_ts else MAX_GAP_SECONDS),
            "is_new_device": float(history_count > 0 and not device_seen),
            "is_foreign_country": float(home_country is not None and txn["country"] != home_country),
            "is_new_user": float(history_count == 0),
            "user_history_count": float(min(history_count, 500)),
            "hour_of_day": float(hour),
            "is_night": float(hour < 6),
            "merchant_risk": MERCHANT_CATEGORY_RISK.get(txn["merchant_category"], 0.5),
            "card_present": float(bool(txn["card_present"])),
        }

    def update(self, txn: dict) -> None:
        """Record `txn` so it counts toward the user's future features."""
        ts = float(txn["timestamp"])
        k_txns, k_profile, k_devices = self._keys(txn["user_id"])

        pipe = self.r.pipeline()
        pipe.zadd(k_txns, {f"{txn['transaction_id']}|{float(txn['amount'])}": ts})
        pipe.zremrangebyscore(k_txns, "-inf", ts - WINDOW_KEEP_SECONDS)
        pipe.hincrby(k_profile, "txn_count", 1)
        pipe.hincrbyfloat(k_profile, "amount_sum", float(txn["amount"]))
        pipe.hsetnx(k_profile, "home_country", txn["country"])  # first country seen
        pipe.hset(k_profile, "last_ts", ts)
        pipe.sadd(k_devices, txn["device_id"])
        for key in (k_txns, k_profile, k_devices):
            pipe.expire(key, KEY_TTL_SECONDS)
        pipe.execute()

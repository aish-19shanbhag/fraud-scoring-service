"""Feature definitions shared by training and serving.

Keeping these in one place means the model is trained on exactly the same
features it sees in production (no train/serve skew).
"""

# Prior risk per merchant category (0 = low, 1 = high). In a real system this
# would be learned from historical chargeback rates.
MERCHANT_CATEGORY_RISK: dict[str, float] = {
    "grocery": 0.05,
    "fuel": 0.10,
    "restaurant": 0.10,
    "retail": 0.20,
    "entertainment": 0.25,
    "travel": 0.40,
    "online_retail": 0.45,
    "electronics": 0.70,
    "gift_cards": 0.90,
    "crypto": 0.95,
}

# Order matters: the model is trained on columns in this exact order.
FEATURE_NAMES: list[str] = [
    "amount",
    "log_amount",
    "amount_to_user_avg",
    "txn_count_10m",
    "txn_count_1h",
    "amount_sum_1h",
    "seconds_since_last_txn",
    "is_new_device",
    "is_foreign_country",
    "is_new_user",
    "user_history_count",
    "hour_of_day",
    "is_night",
    "merchant_risk",
    "card_present",
]


def explain(features: dict, merchant_category: str) -> list[str]:
    """Human-readable risk signals shown to analysts next to the score.

    These are simple rules that describe *why* a transaction looks unusual.
    They do not change the score; the ML model does the scoring.
    """
    signals: list[str] = []
    has_history = features["user_history_count"] > 0

    if has_history and features["amount_to_user_avg"] >= 5:
        signals.append(f"Amount is {features['amount_to_user_avg']:.1f}x the user's average")
    if features["txn_count_10m"] >= 4:
        signals.append(f"{int(features['txn_count_10m'])} other transactions in the last 10 minutes")
    elif features["txn_count_1h"] >= 8:
        signals.append(f"{int(features['txn_count_1h'])} other transactions in the last hour")
    if features["is_new_device"]:
        signals.append("New device for this user")
    if features["is_foreign_country"]:
        signals.append("Country differs from the user's home country")
    if has_history and features["seconds_since_last_txn"] < 60:
        signals.append("Less than a minute since the previous transaction")
    if features["is_night"]:
        signals.append("Unusual hour (00:00-05:59 UTC)")
    if features["merchant_risk"] >= 0.7:
        signals.append(f"High-risk merchant category ({merchant_category})")
    if features["is_new_user"]:
        signals.append("First transaction seen for this user")
    return signals

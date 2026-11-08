"""Synthetic card-transaction generator with labelled fraud patterns.

Real transaction data is private, so we simulate realistic behaviour:

Normal customers
    Each user has a home country, 1-2 devices, a typical spend level and
    active hours. Legitimate "noise" is included on purpose, so the model
    cannot cheat with one rule: travel abroad, new phones, rare big purchases.

Fraud patterns (the three most common in card fraud)
    account_takeover  new device + foreign country + high-value risky purchases
    card_testing      burst of tiny online charges, then one large charge
    night_spree       several high-value card-not-present purchases at night
    stolen_details    one ordinary-looking online purchase with stolen card details
                      (deliberately hard: it looks like normal spending)

The same generator feeds model training (historical data) and the live
simulator (streaming data).
"""

from dataclasses import dataclass, field

import numpy as np

HOME_COUNTRIES = ["US"] * 14 + ["CA", "GB", "IN", "MX", "DE", "FR"]
TRAVEL_COUNTRIES = ["CA", "MX", "GB", "FR", "DE", "IT", "ES", "JP", "IN", "AE"]
RISKY_COUNTRIES = ["NG", "RU", "BR", "RO", "VN", "UA", "PH", "ID"]

NORMAL_CATEGORIES = {
    "grocery": 0.24,
    "restaurant": 0.20,
    "fuel": 0.10,
    "retail": 0.14,
    "online_retail": 0.14,
    "entertainment": 0.07,
    "travel": 0.04,
    "electronics": 0.05,
    "gift_cards": 0.015,
    "crypto": 0.005,
}
CATEGORY_AMOUNT_SCALE = {
    "grocery": 1.0,
    "restaurant": 0.8,
    "fuel": 0.9,
    "retail": 1.3,
    "online_retail": 1.1,
    "entertainment": 0.7,
    "travel": 4.0,
    "electronics": 3.5,
    "gift_cards": 1.5,
    "crypto": 3.0,
}
MERCHANTS = {
    "grocery": ["Whole Foods", "Safeway", "Trader Joe's", "Costco", "Walmart Grocery"],
    "restaurant": ["Chipotle", "Starbucks", "Olive Garden", "Panera", "Local Diner"],
    "fuel": ["Shell", "Chevron", "76", "Arco"],
    "retail": ["Target", "Macy's", "Nordstrom", "IKEA", "Home Depot"],
    "online_retail": ["Amazon", "eBay", "Etsy", "Shein", "Wayfair"],
    "entertainment": ["Netflix", "AMC Theatres", "Spotify", "Ticketmaster"],
    "travel": ["United Airlines", "Delta", "Marriott", "Airbnb", "Expedia"],
    "electronics": ["Best Buy", "Apple Store", "Newegg", "B&H Photo"],
    "gift_cards": ["GiftCardMall", "Raise", "CardCash"],
    "crypto": ["Coinbase", "Binance", "Kraken"],
}
DAY = 24 * 3600


@dataclass
class User:
    user_id: str
    home_country: str
    devices: list[str]
    avg_amount: float
    active_start: float  # hour of day (UTC)
    active_end: float
    txns_per_day: float
    traveling_until: float = 0.0
    travel_country: str | None = None
    extra: dict = field(default_factory=dict)


def _device(rng: np.random.Generator) -> str:
    return f"D-{rng.integers(0, 16**8):08x}"


def make_users(n: int, rng: np.random.Generator, id_prefix: str = "U") -> list[User]:
    users = []
    for i in range(n):
        if rng.random() < 0.12:  # night owls: legit activity late at night
            start, length = float(rng.uniform(16, 22)), float(rng.uniform(8, 12))
        else:
            start, length = float(rng.uniform(5, 13)), float(rng.uniform(10, 16))
        users.append(
            User(
                user_id=f"{id_prefix}{i:05d}",
                home_country=str(rng.choice(HOME_COUNTRIES)),
                devices=[_device(rng) for _ in range(int(rng.integers(1, 3)))],
                avg_amount=float(rng.lognormal(mean=3.6, sigma=0.5)),  # typical spend ~ $35-$60
                active_start=start,
                active_end=start + length,  # may exceed 24: wraps past midnight
                txns_per_day=float(rng.uniform(0.5, 4.0)),
            )
        )
    return users


def _txn(
    user: User,
    ts: float,
    category: str,
    amount: float,
    country: str,
    device: str,
    card_present: bool,
    rng: np.random.Generator,
    is_fraud: int,
    pattern: str,
) -> dict:
    return {
        "transaction_id": f"T-{int(rng.integers(0, 2**62)):016x}",
        "user_id": user.user_id,
        "amount": round(max(amount, 0.5), 2),
        "currency": "USD",
        "merchant": str(rng.choice(MERCHANTS[category])),
        "merchant_category": category,
        "country": country,
        "device_id": device,
        "card_present": bool(card_present),
        "timestamp": float(ts),
        "is_fraud": is_fraud,
        "pattern": pattern,
    }


def normal_txn(user: User, ts: float, rng: np.random.Generator) -> dict:
    """A legitimate transaction, including realistic 'unusual but fine' noise."""
    categories = list(NORMAL_CATEGORIES)
    category = str(rng.choice(categories, p=list(NORMAL_CATEGORIES.values())))
    amount = user.avg_amount * CATEGORY_AMOUNT_SCALE[category] * float(rng.lognormal(0, 0.45))

    # Legit noise: a rare big purchase (new laptop, flights)
    if rng.random() < 0.02:
        category = str(rng.choice(["electronics", "travel", "gift_cards"]))
        amount = user.avg_amount * float(rng.uniform(4, 15))

    # Legit noise: the user starts a trip abroad
    if user.traveling_until < ts and rng.random() < 0.006:
        user.traveling_until = ts + float(rng.uniform(2, 7)) * DAY
        user.travel_country = str(rng.choice([c for c in TRAVEL_COUNTRIES if c != user.home_country]))
    country = user.travel_country if user.traveling_until >= ts else user.home_country

    # Legit noise: the user gets a new phone or uses a new browser
    if rng.random() < 0.01:
        user.devices.append(_device(rng))
        device = user.devices[-1]
    else:
        device = str(rng.choice(user.devices))

    card_present = category in {"grocery", "fuel", "restaurant", "retail"} and rng.random() < 0.8
    return _txn(user, ts, category, amount, country, device, card_present, rng, 0, "normal")


def legit_burst(user: User, start_ts: float, rng: np.random.Generator) -> list[dict]:
    """Legit noise that looks like card testing: several small app/game purchases."""
    txns, ts, device = [], start_ts, str(rng.choice(user.devices))
    for _ in range(int(rng.integers(3, 8))):
        txns.append(
            _txn(
                user,
                ts,
                "entertainment",
                float(rng.uniform(0.99, 9.99)),
                user.home_country,
                device,
                False,
                rng,
                0,
                "normal",
            )
        )
        ts += float(rng.uniform(20, 240))
    return txns


def fraud_pattern(user: User, start_ts: float, rng: np.random.Generator, kind: str | None = None) -> list[dict]:
    """A labelled fraud incident: a short sequence of fraudulent transactions."""
    kind = kind or str(
        rng.choice(["account_takeover", "card_testing", "night_spree", "stolen_details"], p=[0.35, 0.25, 0.15, 0.25])
    )
    txns: list[dict] = []
    ts = start_ts

    if kind == "account_takeover":
        device = _device(rng)
        # Fraudsters often use a VPN, so the country is the user's own ~40% of the time
        country = user.home_country if rng.random() < 0.4 else str(rng.choice(RISKY_COUNTRIES + TRAVEL_COUNTRIES[:3]))
        for _ in range(int(rng.integers(1, 4))):
            category = str(
                rng.choice(
                    ["electronics", "gift_cards", "crypto", "online_retail", "retail"], p=[0.35, 0.25, 0.1, 0.2, 0.1]
                )
            )
            amount = user.avg_amount * float(rng.uniform(1.5, 15))
            txns.append(_txn(user, ts, category, amount, country, device, False, rng, 1, kind))
            ts += float(rng.uniform(30, 600))

    elif kind == "card_testing":
        device = _device(rng) if rng.random() < 0.7 else str(rng.choice(user.devices))
        country = user.home_country if rng.random() < 0.5 else str(rng.choice(RISKY_COUNTRIES))
        for _ in range(int(rng.integers(4, 11))):
            category = str(rng.choice(["online_retail", "gift_cards", "entertainment"]))
            txns.append(_txn(user, ts, category, float(rng.uniform(0.5, 5)), country, device, False, rng, 1, kind))
            ts += float(rng.uniform(5, 50)) if rng.random() < 0.6 else float(rng.uniform(60, 400))
        category = str(rng.choice(["electronics", "gift_cards"]))
        amount = user.avg_amount * float(rng.uniform(5, 25))
        txns.append(_txn(user, ts, category, amount, country, device, False, rng, 1, kind))

    elif kind == "night_spree":
        device = str(rng.choice(user.devices)) if rng.random() < 0.6 else _device(rng)
        day_start = start_ts - (start_ts % DAY)
        ts = day_start + float(rng.uniform(1, 4.5)) * 3600
        for _ in range(int(rng.integers(2, 5))):
            category = str(rng.choice(["electronics", "online_retail", "gift_cards", "travel"]))
            amount = user.avg_amount * float(rng.uniform(1.5, 10))
            txns.append(_txn(user, ts, category, amount, user.home_country, device, False, rng, 1, kind))
            ts += float(rng.uniform(60, 1200))

    elif kind == "stolen_details":
        category = str(rng.choice(["online_retail", "electronics", "retail"]))
        amount = user.avg_amount * float(rng.uniform(1, 4))
        device = _device(rng) if rng.random() < 0.5 else str(rng.choice(user.devices))
        txns.append(_txn(user, ts, category, amount, user.home_country, device, False, rng, 1, kind))
    else:
        raise ValueError(f"unknown fraud pattern {kind}")
    return txns


def generate_history(
    n_users: int, days: int, start_ts: float, seed: int = 42, fraud_user_rate: float = 0.25, id_prefix: str = "U"
) -> list[dict]:
    """Generate `days` of transactions for `n_users`, sorted by time.

    About `fraud_user_rate` of users suffer one fraud incident, giving an
    overall fraud rate of roughly 1-2% of transactions.
    """
    rng = np.random.default_rng(seed)
    users = make_users(n_users, rng, id_prefix)
    events: list[dict] = []

    for user in users:
        for day in range(days):
            day_start = start_ts + day * DAY
            for _ in range(int(rng.poisson(user.txns_per_day))):
                hour = float(rng.uniform(user.active_start, user.active_end)) % 24
                events.append((day_start + hour * 3600, user, None))
            if rng.random() < 0.02:
                events.append((day_start + float(rng.uniform(8, 23)) * 3600, user, "burst"))
        # One fraud incident for some users, never in the first 3 days (users need history)
        if rng.random() < fraud_user_rate and days > 4:
            events.append((start_ts + float(rng.uniform(3, days - 0.5)) * DAY, user, "fraud"))

    events.sort(key=lambda e: e[0])
    txns: list[dict] = []
    for ts, user, kind in events:
        if kind == "fraud":
            txns.extend(fraud_pattern(user, ts, rng))
        elif kind == "burst":
            txns.extend(legit_burst(user, ts, rng))
        else:
            txns.append(normal_txn(user, ts, rng))
    txns.sort(key=lambda t: t["timestamp"])
    return txns

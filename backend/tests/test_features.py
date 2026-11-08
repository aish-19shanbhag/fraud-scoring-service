import fakeredis
import pytest

from app.feature_store import FeatureStore
from app.features import FEATURE_NAMES, explain
from ml.synthetic import generate_history

T0 = 1_772_000_000.0  # a fixed unix time


def txn(i, ts, **kw):
    base = dict(
        transaction_id=f"T{i}",
        user_id="U1",
        amount=50.0,
        merchant_category="grocery",
        country="US",
        device_id="D1",
        card_present=True,
        timestamp=ts,
    )
    base.update(kw)
    return base


@pytest.fixture
def store():
    return FeatureStore(fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True))


def test_new_user_has_neutral_features(store):
    f = store.compute_features(txn(1, T0))
    assert set(f) == set(FEATURE_NAMES)
    assert f["is_new_user"] == 1 and f["is_new_device"] == 0 and f["is_foreign_country"] == 0
    assert f["amount_to_user_avg"] == 1.0


def test_velocity_windows(store):
    for i, offset in enumerate([-7200, -1800, -300, -60]):  # 2h, 30m, 5m, 1m ago
        store.update(txn(i, T0 + offset))
    f = store.compute_features(txn(9, T0))
    assert f["txn_count_10m"] == 2
    assert f["txn_count_1h"] == 3
    assert f["seconds_since_last_txn"] == 60


def test_device_country_and_amount_signals(store):
    for i in range(5):
        store.update(txn(i, T0 - 86400 + i * 600, amount=40.0))
    f = store.compute_features(txn(9, T0, amount=400.0, device_id="D-new", country="NG"))
    assert f["is_new_device"] == 1 and f["is_foreign_country"] == 1
    assert f["amount_to_user_avg"] == pytest.approx(10.0)
    signals = explain(f, "grocery")
    assert any("10.0x" in s for s in signals) and "New device for this user" in signals


def test_features_only_use_past_data(store):
    store.update(txn(1, T0 + 100))  # a *later* transaction must not leak into an earlier one
    assert store.compute_features(txn(2, T0))["txn_count_1h"] == 0


def test_synthetic_history_is_sorted_and_labelled():
    txns = generate_history(n_users=50, days=10, start_ts=T0, seed=1)
    times = [t["timestamp"] for t in txns]
    assert times == sorted(times)
    assert {t["is_fraud"] for t in txns} <= {0, 1}
    assert any(t["is_fraud"] for t in txns)

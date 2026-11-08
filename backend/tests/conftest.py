from datetime import UTC, datetime, timedelta
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from ml.train import train

BASE_TIME = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)  # a Monday afternoon


@pytest.fixture(scope="session")
def model_path(tmp_path_factory) -> Path:
    """Train a small model once for the whole test session (~10 seconds)."""
    path = tmp_path_factory.mktemp("model") / "fraud_model.joblib"
    train(users=400, days=21, seed=7, model_path=path, reports_dir=None)
    return path


@pytest.fixture
def make_client(tmp_path, model_path):
    def _make(**overrides) -> TestClient:
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            model_path=model_path,
            rate_limit_per_minute=overrides.pop("rate_limit_per_minute", 0),
            stats_cache_seconds=overrides.pop("stats_cache_seconds", 0),
            **overrides,
        )
        redis_client = fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
        return TestClient(create_app(settings, redis_client))

    return _make


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c


def make_txn(n: int, user: str = "U1", minutes: float = 0, **fields) -> dict:
    """A normal-looking grocery purchase; override any field."""
    txn = {
        "transaction_id": f"T-{user}-{n}",
        "user_id": user,
        "amount": 42.0,
        "merchant": "Safeway",
        "merchant_category": "grocery",
        "country": "US",
        "device_id": "D-home",
        "card_present": True,
        "timestamp": (BASE_TIME + timedelta(minutes=minutes)).isoformat(),
    }
    txn.update(fields)
    return txn


def seed_history(client: TestClient, user: str = "U1", n: int = 25) -> None:
    """Give a user ~2 weeks of normal daytime spending."""
    for i in range(n):
        resp = client.post(
            "/api/v1/transactions/score",
            json=make_txn(i, user, minutes=-60 * 14 * (n - i), amount=30 + (i % 5) * 6),
        )
        assert resp.status_code == 201, resp.text

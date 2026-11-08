from tests.conftest import make_txn, seed_history

SCORE = "/api/v1/transactions/score"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok" and body["database"] == "ok" and body["redis"] == "ok"


def test_score_returns_decision(client):
    resp = client.post(SCORE, json=make_txn(1))
    assert resp.status_code == 201
    body = resp.json()
    assert 0.0 <= body["risk_score"] <= 1.0
    assert body["risk_level"] in {"GREEN", "AMBER", "RED"}
    assert body["recommended_action"] in {"APPROVE", "REVIEW", "BLOCK"}
    assert body["latency_ms"] >= 0


def test_scoring_is_idempotent(client):
    first = client.post(SCORE, json=make_txn(1))
    again = client.post(SCORE, json=make_txn(1, amount=9999))  # same id, different body
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["risk_score"] == first.json()["risk_score"]
    assert client.get("/api/v1/transactions").json()["total"] == 1


def test_invalid_payloads_rejected(client):
    assert client.post(SCORE, json=make_txn(1, amount=-5)).status_code == 422
    assert client.post(SCORE, json=make_txn(2, merchant_category="weapons")).status_code == 422
    assert client.post(SCORE, json=make_txn(3, country="usa")).status_code == 422


def test_normal_purchase_is_low_risk(client):
    seed_history(client)
    body = client.post(SCORE, json=make_txn(100, minutes=10, amount=38)).json()
    assert body["risk_level"] == "GREEN"
    assert body["recommended_action"] == "APPROVE"


def test_card_testing_attack_is_flagged(client):
    seed_history(client)
    normal = client.post(SCORE, json=make_txn(100, amount=40)).json()

    # Burst of tiny online charges from a new device abroad, then a big one
    attack = dict(device_id="D-attacker", country="RO", card_present=False)
    first = None
    for i in range(8):
        resp = client.post(
            SCORE,
            json=make_txn(
                200 + i, minutes=1 + i * 0.5, amount=1.5, merchant_category="gift_cards", merchant="CardCash", **attack
            ),
        )
        first = first or resp.json()
    final = client.post(
        SCORE, json=make_txn(300, minutes=6, amount=650, merchant_category="electronics", merchant="Best Buy", **attack)
    ).json()

    assert final["risk_level"] in {"AMBER", "RED"}
    assert final["risk_score"] > normal["risk_score"]
    assert "New device for this user" in first["signals"]
    assert any("last 10 minutes" in s for s in final["signals"])
    assert final["review_status"] == "PENDING"


def test_list_and_filter(client):
    seed_history(client, n=5)
    page = client.get("/api/v1/transactions", params={"limit": 2}).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    assert client.get("/api/v1/transactions", params={"user_id": "nobody"}).json()["total"] == 0
    assert client.get("/api/v1/transactions", params={"risk_level": "PURPLE"}).status_code == 422


def test_get_one_and_404(client):
    client.post(SCORE, json=make_txn(1))
    assert client.get("/api/v1/transactions/T-U1-1").json()["user_id"] == "U1"
    assert client.get("/api/v1/transactions/missing").status_code == 404


def test_review_workflow(client):
    client.post(SCORE, json=make_txn(1))
    resp = client.patch("/api/v1/transactions/T-U1-1/review", json={"status": "FALSE_POSITIVE"})
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "FALSE_POSITIVE" and resp.json()["reviewed_at"]
    assert client.patch("/api/v1/transactions/T-U1-1/review", json={"status": "MAYBE"}).status_code == 422
    assert client.patch("/api/v1/transactions/missing/review", json={"status": "CONFIRMED_FRAUD"}).status_code == 404


def test_stats(client):
    seed_history(client, n=6)
    client.patch("/api/v1/transactions/T-U1-0/review", json={"status": "CONFIRMED_FRAUD"})
    stats = client.get("/api/v1/stats").json()
    assert stats["total_transactions"] == 6
    assert sum(stats["by_risk_level"].values()) == 6
    assert stats["confirmed_fraud"] == 1 and stats["review_precision"] == 1.0
    assert stats["p95_latency_ms"] is not None


def test_stats_are_cached_in_redis(make_client):
    with make_client(stats_cache_seconds=60) as c:
        assert c.get("/api/v1/stats").json()["total_transactions"] == 0
        c.post(SCORE, json=make_txn(1))
        assert c.get("/api/v1/stats").json()["total_transactions"] == 0  # served from cache


def test_rate_limit(make_client):
    with make_client(rate_limit_per_minute=3) as c:
        codes = [c.post(SCORE, json=make_txn(i)).status_code for i in range(4)]
    assert codes == [201, 201, 201, 429]


def test_model_info(client):
    info = client.get("/api/v1/model").json()
    assert info["amber_threshold"] < info["red_threshold"]
    assert "pr_auc" in info["metrics"]["test"]


def test_websocket_streams_scored_transactions(client):
    with client.websocket_connect("/ws/transactions") as ws:
        client.post(SCORE, json=make_txn(1))
        message = ws.receive_json()
    assert message["type"] == "transaction.scored"
    assert message["data"]["transaction_id"] == "T-U1-1"

"""Load test for the scoring endpoint.

    cd loadtest
    locust -f locustfile.py --host http://localhost:8000 --headless -u 50 -r 10 -t 60s

Set RATE_LIMIT_PER_MINUTE=0 on the API first, otherwise you are load testing
the rate limiter (which returns 429s by design).
"""

import random
import uuid

from locust import HttpUser, between, task

CATEGORIES = ["grocery", "restaurant", "fuel", "retail", "online_retail", "electronics", "gift_cards"]
COUNTRIES = ["US"] * 8 + ["CA", "GB", "NG", "RO"]


class PaymentGateway(HttpUser):
    wait_time = between(0.01, 0.05)

    def on_start(self):
        self.users = [f"LT{n:05d}" for n in range(500)]
        self.devices = {u: f"D-{u}" for u in self.users}

    @task(20)
    def score_transaction(self):
        user = random.choice(self.users)
        self.client.post(
            "/api/v1/transactions/score",
            name="POST /score",
            json={
                "transaction_id": uuid.uuid4().hex,
                "user_id": user,
                "amount": round(random.lognormvariate(3.7, 0.9), 2),
                "merchant": "Load Test Merchant",
                "merchant_category": random.choice(CATEGORIES),
                "country": random.choice(COUNTRIES),
                "device_id": self.devices[user] if random.random() < 0.95 else uuid.uuid4().hex[:12],
                "card_present": random.random() < 0.5,
            },
        )

    @task(1)
    def dashboard_stats(self):
        self.client.get("/api/v1/stats", name="GET /stats")

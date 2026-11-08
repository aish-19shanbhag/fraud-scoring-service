"""Dashboard metrics, model info and health checks."""

import numpy as np
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Transaction
from app.schemas import ModelInfo, StatsOut

router = APIRouter(tags=["monitoring"])

STATS_CACHE_KEY = "cache:stats:v1"


@router.get("/api/v1/stats", response_model=StatsOut, summary="Live dashboard metrics")
def get_stats(request: Request, db: Session = Depends(get_db)) -> StatsOut:
    redis_client = request.app.state.redis
    ttl = request.app.state.settings.stats_cache_seconds

    # Dashboards poll this endpoint every few seconds; a short Redis cache
    # keeps those polls from hitting the database each time.
    if ttl > 0 and (cached := redis_client.get(STATS_CACHE_KEY)):
        return StatsOut.model_validate_json(cached)

    by_level = dict(db.execute(select(Transaction.risk_level, func.count()).group_by(Transaction.risk_level)).all())
    by_review = dict(
        db.execute(select(Transaction.review_status, func.count()).group_by(Transaction.review_status)).all()
    )
    total = sum(by_level.values())
    amount_blocked = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0.0)).where(Transaction.risk_level == "RED")
    )
    latencies = db.scalars(select(Transaction.latency_ms).order_by(Transaction.id.desc()).limit(1000)).all()

    confirmed = by_review.get("CONFIRMED_FRAUD", 0)
    false_pos = by_review.get("FALSE_POSITIVE", 0)
    reviewed = confirmed + false_pos
    flagged = by_level.get("AMBER", 0) + by_level.get("RED", 0)

    stats = StatsOut(
        total_transactions=total,
        by_risk_level={level: by_level.get(level, 0) for level in ("GREEN", "AMBER", "RED")},
        flag_rate=round(flagged / total, 4) if total else 0.0,
        pending_reviews=by_review.get("PENDING", 0),
        confirmed_fraud=confirmed,
        false_positives=false_pos,
        review_precision=round(confirmed / reviewed, 4) if reviewed else None,
        amount_blocked=round(float(amount_blocked), 2),
        avg_latency_ms=round(float(np.mean(latencies)), 3) if latencies else None,
        p95_latency_ms=round(float(np.percentile(latencies, 95)), 3) if latencies else None,
        model_version=request.app.state.model.version,
    )
    if ttl > 0:
        redis_client.set(STATS_CACHE_KEY, stats.model_dump_json(), ex=ttl)
    return stats


@router.get("/api/v1/model", response_model=ModelInfo, summary="Deployed model details")
def get_model(request: Request) -> ModelInfo:
    model = request.app.state.model
    return ModelInfo(
        version=model.version,
        feature_names=model.feature_names,
        amber_threshold=model.amber_threshold,
        red_threshold=model.red_threshold,
        metrics=model.metrics,
    )


@router.get("/health", summary="Liveness and dependency check")
def health(request: Request, response: Response) -> dict:
    checks = {}
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - only when the DB is down
        checks["database"] = f"error: {exc.__class__.__name__}"
    try:
        request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # pragma: no cover - only when Redis is down
        checks["redis"] = f"error: {exc.__class__.__name__}"

    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", **checks, "model_version": request.app.state.model.version}

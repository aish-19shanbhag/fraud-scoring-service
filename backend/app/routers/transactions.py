"""Transaction scoring and analyst review endpoints."""

import time
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.features import explain
from app.models import Transaction
from app.rate_limit import rate_limit
from app.schemas import (
    ReviewIn,
    ReviewStatus,
    RiskLevel,
    ScoreOut,
    TransactionIn,
    TransactionOut,
    TransactionPage,
)
from app.scoring import RISK_ACTIONS

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


def _score_out(row: Transaction) -> ScoreOut:
    return ScoreOut(
        transaction_id=row.transaction_id,
        risk_score=row.risk_score,
        risk_level=row.risk_level,
        recommended_action=row.recommended_action,
        signals=row.signals,
        model_version=row.model_version,
        latency_ms=row.latency_ms,
        review_status=row.review_status,
    )


def _event(kind: str, row: Transaction) -> dict:
    return {"type": kind, "data": TransactionOut.model_validate(row).model_dump(mode="json")}


def _get_or_404(db: Session, transaction_id: str) -> Transaction:
    row = db.scalar(select(Transaction).where(Transaction.transaction_id == transaction_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transaction {transaction_id} not found")
    return row


@router.post(
    "/score",
    response_model=ScoreOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit)],
    summary="Score a transaction in real time",
)
def score_transaction(
    payload: TransactionIn,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScoreOut:
    # Idempotency: re-sending the same transaction returns the original decision.
    existing = db.scalar(select(Transaction).where(Transaction.transaction_id == payload.transaction_id))
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _score_out(existing)

    store = request.app.state.feature_store
    model = request.app.state.model

    started = time.perf_counter()
    event_time = payload.timestamp or datetime.now(UTC)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    txn = payload.model_dump()
    txn["timestamp"] = event_time.timestamp()

    features = store.compute_features(txn)
    score = model.predict(features)
    level = model.risk_level(score)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)

    row = Transaction(
        transaction_id=payload.transaction_id,
        user_id=payload.user_id,
        amount=payload.amount,
        currency=payload.currency,
        merchant=payload.merchant,
        merchant_category=payload.merchant_category,
        country=payload.country,
        device_id=payload.device_id,
        card_present=payload.card_present,
        event_time=event_time,
        risk_score=round(score, 6),
        risk_level=level,
        recommended_action=RISK_ACTIONS[level],
        signals=explain(features, payload.merchant_category),
        features=features,
        model_version=model.version,
        latency_ms=latency_ms,
        review_status="NOT_REQUIRED" if level == "GREEN" else "PENDING",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # same transaction_id arrived twice at the same moment
        db.rollback()
        response.status_code = status.HTTP_200_OK
        return _score_out(_get_or_404(db, payload.transaction_id))

    # Only count the transaction in the user's history once it is safely stored.
    store.update(txn)
    background.add_task(request.app.state.ws_manager.broadcast, _event("transaction.scored", row))
    return _score_out(row)


@router.get("", response_model=TransactionPage, summary="List scored transactions")
def list_transactions(
    db: Session = Depends(get_db),
    risk_level: RiskLevel | None = None,
    review_status: ReviewStatus | None = None,
    user_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TransactionPage:
    query = select(Transaction)
    if risk_level:
        query = query.where(Transaction.risk_level == risk_level)
    if review_status:
        query = query.where(Transaction.review_status == review_status)
    if user_id:
        query = query.where(Transaction.user_id == user_id)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(limit).offset(offset)
    ).all()
    return TransactionPage(
        items=[TransactionOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{transaction_id}", response_model=TransactionOut, summary="Get one transaction")
def get_transaction(transaction_id: str, db: Session = Depends(get_db)) -> TransactionOut:
    return TransactionOut.model_validate(_get_or_404(db, transaction_id))


@router.patch(
    "/{transaction_id}/review",
    response_model=TransactionOut,
    summary="Record an analyst decision on an alert",
)
def review_transaction(
    transaction_id: str,
    review: ReviewIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TransactionOut:
    row = _get_or_404(db, transaction_id)
    row.review_status = review.status
    row.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    background.add_task(request.app.state.ws_manager.broadcast, _event("transaction.reviewed", row))
    return TransactionOut.model_validate(row)

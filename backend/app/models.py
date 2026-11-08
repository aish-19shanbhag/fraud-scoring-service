"""Database tables."""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Transaction(Base):
    """One scored transaction, plus the analyst's review decision."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    amount: Mapped[float]
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    merchant: Mapped[str] = mapped_column(String(128))
    merchant_category: Mapped[str] = mapped_column(String(32))
    country: Mapped[str] = mapped_column(String(2))
    device_id: Mapped[str] = mapped_column(String(64))
    card_present: Mapped[bool]
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Model output
    risk_score: Mapped[float]
    risk_level: Mapped[str] = mapped_column(String(8), index=True)  # GREEN / AMBER / RED
    recommended_action: Mapped[str] = mapped_column(String(8))  # APPROVE / REVIEW / BLOCK
    signals: Mapped[list] = mapped_column(JSON, default=list)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[float]

    # Analyst workflow: NOT_REQUIRED (green), PENDING, CONFIRMED_FRAUD, FALSE_POSITIVE
    review_status: Mapped[str] = mapped_column(String(20), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_transactions_created_at_id", "created_at", "id"),)

"""Request and response models (validated by Pydantic)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features import MERCHANT_CATEGORY_RISK

RiskLevel = Literal["GREEN", "AMBER", "RED"]
ReviewStatus = Literal["NOT_REQUIRED", "PENDING", "CONFIRMED_FRAUD", "FALSE_POSITIVE"]


class TransactionIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=64, examples=["T-000123"])
    user_id: str = Field(min_length=1, max_length=64, examples=["U00042"])
    amount: float = Field(gt=0, le=1_000_000, examples=[54.20])
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    merchant: str = Field(min_length=1, max_length=128, examples=["Whole Foods"])
    merchant_category: str = Field(examples=["grocery"])
    country: str = Field(pattern=r"^[A-Z]{2}$", examples=["US"])
    device_id: str = Field(min_length=1, max_length=64, examples=["D-9f2a"])
    card_present: bool = False
    timestamp: datetime | None = Field(
        default=None, description="Event time. Defaults to the time the request is received."
    )

    @field_validator("merchant_category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in MERCHANT_CATEGORY_RISK:
            allowed = ", ".join(sorted(MERCHANT_CATEGORY_RISK))
            raise ValueError(f"unknown merchant_category; allowed: {allowed}")
        return value


class ScoreOut(BaseModel):
    transaction_id: str
    risk_score: float
    risk_level: RiskLevel
    recommended_action: Literal["APPROVE", "REVIEW", "BLOCK"]
    signals: list[str]
    model_version: str
    latency_ms: float
    review_status: ReviewStatus


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    user_id: str
    amount: float
    currency: str
    merchant: str
    merchant_category: str
    country: str
    device_id: str
    card_present: bool
    event_time: datetime
    risk_score: float
    risk_level: RiskLevel
    recommended_action: str
    signals: list[str]
    model_version: str
    latency_ms: float
    review_status: ReviewStatus
    reviewed_at: datetime | None
    created_at: datetime


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class ReviewIn(BaseModel):
    status: Literal["CONFIRMED_FRAUD", "FALSE_POSITIVE"]


class StatsOut(BaseModel):
    total_transactions: int
    by_risk_level: dict[str, int]
    flag_rate: float = Field(description="Share of transactions scored AMBER or RED")
    pending_reviews: int
    confirmed_fraud: int
    false_positives: int
    review_precision: float | None = Field(
        description="Confirmed fraud / all reviewed alerts (None until something is reviewed)"
    )
    amount_blocked: float
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    model_version: str


class ModelInfo(BaseModel):
    version: str
    feature_names: list[str]
    amber_threshold: float
    red_threshold: float
    metrics: dict

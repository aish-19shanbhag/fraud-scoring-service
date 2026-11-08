"""Application settings, read from environment variables.

Every setting has a sensible default so the service runs locally with no
configuration at all (SQLite + in-memory Redis). In Docker / production the
values come from docker-compose.yml or the host environment.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _optional_float(name: str) -> float | None:
    value = _env(name)
    return float(value) if value is not None else None


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'fraud.db'}"))
    # If REDIS_URL is not set, the app falls back to an in-memory fake Redis
    # (handy for local development and tests).
    redis_url: str | None = field(default_factory=lambda: _env("REDIS_URL"))
    model_path: Path = field(
        default_factory=lambda: Path(_env("MODEL_PATH", str(BASE_DIR / "models" / "fraud_model.joblib")))
    )
    # Optional overrides. If unset, the thresholds chosen during training
    # (stored inside the model file) are used.
    amber_threshold: float | None = field(default_factory=lambda: _optional_float("AMBER_THRESHOLD"))
    red_threshold: float | None = field(default_factory=lambda: _optional_float("RED_THRESHOLD"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_env("RATE_LIMIT_PER_MINUTE", "1200")))
    stats_cache_seconds: int = field(default_factory=lambda: int(_env("STATS_CACHE_SECONDS", "2")))
    cors_origins: list[str] = field(
        default_factory=lambda: _env(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:4173,http://localhost:3000"
        ).split(",")
    )

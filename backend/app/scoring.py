"""Loads the trained model and turns features into a risk decision."""

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

RISK_ACTIONS = {"GREEN": "APPROVE", "AMBER": "REVIEW", "RED": "BLOCK"}


@dataclass
class FraudModel:
    estimator: object
    feature_names: list[str]
    version: str
    amber_threshold: float
    red_threshold: float
    metrics: dict

    @classmethod
    def load(
        cls,
        path: Path,
        amber_override: float | None = None,
        red_override: float | None = None,
    ) -> "FraudModel":
        if not Path(path).exists():
            raise FileNotFoundError(f"Model file not found at {path}. Train it first with: python -m ml.train")
        bundle = joblib.load(path)
        return cls(
            estimator=bundle["model"],
            feature_names=bundle["feature_names"],
            version=bundle["version"],
            amber_threshold=amber_override if amber_override is not None else bundle["thresholds"]["amber"],
            red_threshold=red_override if red_override is not None else bundle["thresholds"]["red"],
            metrics=bundle["metrics"],
        )

    def predict(self, features: dict[str, float]) -> float:
        row = np.array([[features[name] for name in self.feature_names]], dtype=float)
        return float(self.estimator.predict_proba(row)[0, 1])

    def risk_level(self, score: float) -> str:
        if score >= self.red_threshold:
            return "RED"
        if score >= self.amber_threshold:
            return "AMBER"
        return "GREEN"

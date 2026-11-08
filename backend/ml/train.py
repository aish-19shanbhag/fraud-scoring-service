"""Train the fraud model.

    python -m ml.train                  # full run (~1 min), writes models/ and ../reports/
    python -m ml.train --users 300 --days 10 --no-reports   # quick run (used by tests)

Steps
 1. Generate synthetic transaction history (ml/synthetic.py).
 2. Replay it in time order through the *same* Redis feature store the API
    uses, so training features match serving features exactly.
 3. Split by time: first 70% train, next 10% validation, last 20% test.
    (A random split would leak future behaviour into training.)
 4. Train a logistic regression baseline and a gradient-boosted tree model.
 5. Pick decision thresholds on validation data:
      RED   (auto-block):  lowest score where >= 90% of blocks are real fraud
      AMBER (review):      lowest score where >= 35% of reviews are real fraud
                           (about 1 in 3 alerts; a typical analyst-queue target)
 6. Evaluate once on the untouched test set and save the model + metrics.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import fakeredis
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.feature_store import FeatureStore
from app.features import FEATURE_NAMES
from ml.synthetic import generate_history

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = BACKEND_DIR / "models" / "fraud_model.joblib"
DEFAULT_REPORTS_DIR = BACKEND_DIR.parent / "reports"
TARGET_RED_PRECISION = 0.90
TARGET_AMBER_PRECISION = 0.35


def build_dataset(txns: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    store = FeatureStore(fakeredis.FakeRedis(decode_responses=True))
    rows, labels, patterns = [], [], []
    for txn in txns:  # already sorted by time
        features = store.compute_features(txn)
        store.update(txn)
        rows.append([features[name] for name in FEATURE_NAMES])
        labels.append(txn["is_fraud"])
        patterns.append(txn["pattern"])
    return np.array(rows, dtype=float), np.array(labels), patterns


def choose_thresholds(y_val: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    precision, recall, thresholds = precision_recall_curve(y_val, scores)
    precision, recall = precision[:-1], recall[:-1]  # align with thresholds

    ok_red = np.where(precision >= TARGET_RED_PRECISION)[0]
    red = float(thresholds[ok_red[0]]) if len(ok_red) else 0.70

    ok_amber = np.where(precision >= TARGET_AMBER_PRECISION)[0]
    amber = float(thresholds[ok_amber[0]]) if len(ok_amber) else 0.30
    amber = min(amber, red * 0.9)  # keep AMBER strictly below RED
    return {"amber": round(amber, 4), "red": round(red, 4)}


def metrics_at(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    pred = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "threshold": round(threshold, 4),
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "false_positive_rate": round(fp / (fp + tn), 5) if fp + tn else 0.0,
        "flag_rate": round(float(pred.mean()), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def train(
    users: int = 1500,
    days: int = 30,
    seed: int = 42,
    model_path: Path = DEFAULT_MODEL_PATH,
    reports_dir: Path | None = DEFAULT_REPORTS_DIR,
) -> dict:
    t0 = time.perf_counter()
    start_ts = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    txns = generate_history(users, days, start_ts, seed=seed)
    X, y, patterns = build_dataset(txns)
    patterns = np.array(patterns)
    print(f"Generated {len(y):,} transactions for {users:,} users, fraud rate {y.mean():.2%}")

    n = len(y)
    i_val, i_test = int(n * 0.70), int(n * 0.80)
    X_tr, y_tr = X[:i_val], y[:i_val]
    X_val, y_val = X[i_val:i_test], y[i_val:i_test]
    X_te, y_te, pat_te = X[i_test:], y[i_test:], patterns[i_test:]

    baseline = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    baseline.fit(X_tr, y_tr)

    model = HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.06,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=seed,
    )
    model.fit(X_tr, y_tr)

    thresholds = choose_thresholds(y_val, model.predict_proba(X_val)[:, 1])
    scores_te = model.predict_proba(X_te)[:, 1]
    base_te = baseline.predict_proba(X_te)[:, 1]

    red, amber = metrics_at(y_te, scores_te, thresholds["red"]), metrics_at(y_te, scores_te, thresholds["amber"])
    recall_by_pattern = {
        p: round(float((scores_te[pat_te == p] >= thresholds["amber"]).mean()), 4)
        for p in sorted(set(pat_te) - {"normal"})
    }

    version = f"hgb-{datetime.now(UTC):%Y%m%d%H%M}"
    metrics = {
        "model_version": version,
        "data": {
            "users": users,
            "days": days,
            "transactions": int(n),
            "fraud_rate": round(float(y.mean()), 4),
            "train": int(len(y_tr)),
            "validation": int(len(y_val)),
            "test": int(len(y_te)),
            "split": "chronological 70/10/20",
        },
        "test": {
            "roc_auc": round(float(roc_auc_score(y_te, scores_te)), 4),
            "pr_auc": round(float(average_precision_score(y_te, scores_te)), 4),
            "baseline_logreg_roc_auc": round(float(roc_auc_score(y_te, base_te)), 4),
            "baseline_logreg_pr_auc": round(float(average_precision_score(y_te, base_te)), 4),
            "red_block": red,
            "amber_or_red_review": amber,
            "recall_by_pattern_at_amber": recall_by_pattern,
        },
        "thresholds": thresholds,
    }

    importance = None
    if reports_dir is not None:
        sample = np.random.default_rng(seed).choice(len(y_te), size=min(8000, len(y_te)), replace=False)
        result = permutation_importance(
            model, X_te[sample], y_te[sample], scoring="average_precision", n_repeats=5, random_state=seed
        )
        importance = {
            FEATURE_NAMES[i]: round(float(result.importances_mean[i]), 4)
            for i in np.argsort(result.importances_mean)[::-1]
        }
        metrics["feature_importance_pr_auc_drop"] = importance

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "feature_names": FEATURE_NAMES,
            "version": version,
            "thresholds": thresholds,
            "metrics": metrics,
        },
        model_path,
    )
    print(f"Saved model to {model_path}")

    if reports_dir is not None:
        metrics_dir = reports_dir / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        (metrics_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
        from ml.plots import save_training_figures

        save_training_figures(reports_dir / "figures", y_te, scores_te, base_te, thresholds, importance)
        print(f"Wrote metrics and figures to {reports_dir}")

    print(json.dumps(metrics["test"], indent=2))
    print(f"Done in {time.perf_counter() - t0:.1f}s")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the fraud scoring model")
    parser.add_argument("--users", type=int, default=1500)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--no-reports", action="store_true", help="skip metrics.json and charts")
    args = parser.parse_args()
    train(args.users, args.days, args.seed, args.model_path, None if args.no_reports else DEFAULT_REPORTS_DIR)


if __name__ == "__main__":
    main()

"""Charts saved to reports/figures/ and embedded in the README."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import confusion_matrix, precision_recall_curve  # noqa: E402

BLUE, GREY, AMBER, RED, GREEN = "#2563eb", "#9ca3af", "#f59e0b", "#dc2626", "#16a34a"


def _style(ax, title: str) -> None:
    ax.set_title(title, fontsize=12, fontweight="bold", loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.25)


def save_training_figures(
    out_dir: Path, y: np.ndarray, scores: np.ndarray, baseline: np.ndarray, thresholds: dict, importance: dict | None
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Precision-recall curve: model vs baseline, with the two operating points
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for s, label, color in ((scores, "Gradient boosting", BLUE), (baseline, "Logistic regression", GREY)):
        p, r, _ = precision_recall_curve(y, s)
        ax.plot(r, p, label=label, color=color, lw=2)
    for name, color in (("amber", AMBER), ("red", RED)):
        pred = scores >= thresholds[name]
        tp = (pred & (y == 1)).sum()
        ax.scatter(
            tp / max(y.sum(), 1),
            tp / max(pred.sum(), 1),
            s=80,
            color=color,
            zorder=3,
            label=f"{name.upper()} threshold ({thresholds[name]:.3f})",
        )
    ax.set_xlabel("Recall (share of fraud caught)")
    ax.set_ylabel("Precision (share of alerts that are fraud)")
    ax.legend(loc="lower left", fontsize=9)
    _style(ax, "Precision-recall on the time-based test set")
    fig.tight_layout()
    fig.savefig(out_dir / "pr_curve.png", dpi=150)
    plt.close(fig)

    # 2. Score distribution with the risk bands
    fig, ax = plt.subplots(figsize=(6.5, 4))
    bins = np.linspace(0, 1, 41)
    ax.hist(scores[y == 0], bins=bins, color=GREEN, alpha=0.7, label="Legitimate")
    ax.hist(scores[y == 1], bins=bins, color=RED, alpha=0.7, label="Fraud")
    ax.axvline(thresholds["amber"], color=AMBER, ls="--", lw=2, label="AMBER")
    ax.axvline(thresholds["red"], color=RED, ls="--", lw=2, label="RED")
    ax.set_yscale("log")
    ax.set_xlabel("Risk score")
    ax.set_ylabel("Transactions (log scale)")
    ax.legend(fontsize=9)
    _style(ax, "Risk score distribution")
    fig.tight_layout()
    fig.savefig(out_dir / "score_distribution.png", dpi=150)
    plt.close(fig)

    # 3. Confusion matrix at the RED (auto-block) threshold
    cm = confusion_matrix(y, scores >= thresholds["red"], labels=[0, 1])
    fig, ax = plt.subplots(figsize=(4.6, 4))
    ax.imshow(cm, cmap="Blues")
    for (i, j), v in np.ndenumerate(cm):
        ax.text(j, i, f"{v:,}", ha="center", va="center", fontsize=13, color="white" if v > cm.max() / 2 else "black")
    ax.set_xticks([0, 1], ["Approved", "Blocked"])
    ax.set_yticks([0, 1], ["Legitimate", "Fraud"])
    ax.set_title("Confusion matrix at RED threshold", fontsize=12, fontweight="bold", loc="left")
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrix.png", dpi=150)
    plt.close(fig)

    # 4. Permutation feature importance
    if importance:
        items = list(importance.items())[:10][::-1]
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        ax.barh([k for k, _ in items], [v for _, v in items], color=BLUE)
        ax.set_xlabel("Drop in PR-AUC when the feature is shuffled")
        _style(ax, "Top 10 features (permutation importance)")
        fig.tight_layout()
        fig.savefig(out_dir / "feature_importance.png", dpi=150)
        plt.close(fig)

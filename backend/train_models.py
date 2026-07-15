"""
train_models.py  —  Step 2

Trains TWO anomaly detectors and saves a side-by-side comparison:
  1. Isolation Forest  — fast, tree-based, no assumptions about data distribution
  2. Autoencoder       — neural net trained to reconstruct normal transactions;
                         high reconstruction error = suspicious

Also saves reference statistics used by the drift detector.

Run:
    python train_models.py --contamination 0.0017
"""

import argparse
import json
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import MinMaxScaler

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DATA = PROJECT_ROOT / "data"   / "processed"
DEFAULT_IF   = PROJECT_ROOT / "models" / "isolation_forest.pkl"
DEFAULT_AE   = PROJECT_ROOT / "models" / "autoencoder.pkl"
DEFAULT_AES  = PROJECT_ROOT / "models" / "ae_scaler.pkl"
DEFAULT_META = PROJECT_ROOT / "models" / "comparison_metrics.json"
DEFAULT_REF  = PROJECT_ROOT / "models" / "reference_stats.json"

FEATURE_COLUMNS = [f"V{i}" for i in range(1, 29)] + ["Time", "Amount"]


# ── helpers ──────────────────────────────────────────────────────────────────

def load_processed(data_dir):
    d = str(data_dir)
    return (
        np.load(os.path.join(d, "X_train.npy")),
        np.load(os.path.join(d, "X_test.npy")),
        np.load(os.path.join(d, "y_train.npy")),
        np.load(os.path.join(d, "y_test.npy")),
    )


def compute_metrics(y_true, y_pred, y_scores, label: str) -> dict:
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    pr_auc  = average_precision_score(y_true, y_scores)
    roc_auc = roc_auc_score(y_true, y_scores)
    print(f"\n{'─'*40}")
    print(f"  {label}")
    print(f"{'─'*40}")
    print(classification_report(y_true, y_pred, digits=4))
    print(f"  PR-AUC  : {pr_auc:.4f}  (key metric for imbalanced data)")
    print(f"  ROC-AUC : {roc_auc:.4f}")
    return {
        "precision": round(float(p),      4),
        "recall":    round(float(r),      4),
        "f1":        round(float(f),      4),
        "pr_auc":    round(float(pr_auc), 4),
        "roc_auc":   round(float(roc_auc),4),
    }


# ── Isolation Forest ─────────────────────────────────────────────────────────

def train_isolation_forest(X_train, contamination, random_state=42):
    print("\nTraining Isolation Forest ...")
    model = IsolationForest(
        n_estimators=200,
        max_samples="auto",
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train)
    return model


def score_if(model, X):
    """Higher = more anomalous."""
    return -model.decision_function(X)


# ── Autoencoder (MLPRegressor) ────────────────────────────────────────────────

def train_autoencoder(X_normal, ae_samples=50_000, random_state=42):
    """
    Train a neural autoencoder on normal transactions only.
    Architecture: 30 → 20 → 10 → 20 → 30
    Anomaly score = reconstruction MSE (high = suspicious).
    """
    print(f"\nTraining Autoencoder on {min(len(X_normal), ae_samples):,} normal samples ...")
    if len(X_normal) > ae_samples:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(len(X_normal), ae_samples, replace=False)
        X_normal = X_normal[idx]

    # Scale to [0,1] — MLPRegressor works better on this range
    ae_scaler = MinMaxScaler()
    X_scaled = ae_scaler.fit_transform(X_normal)

    ae = MLPRegressor(
        hidden_layer_sizes=(20, 10, 20),
        activation="relu",
        max_iter=100,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=random_state,
        verbose=False,
    )
    ae.fit(X_scaled, X_scaled)
    return ae, ae_scaler


def score_ae(ae, ae_scaler, X):
    """Reconstruction MSE per sample. Higher = more anomalous."""
    X_scaled = ae_scaler.transform(X)
    X_recon  = ae.predict(X_scaled)
    return np.mean((X_scaled - X_recon) ** 2, axis=1)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir",      default=str(DEFAULT_DATA))
    parser.add_argument("--if-out",        default=str(DEFAULT_IF))
    parser.add_argument("--ae-out",        default=str(DEFAULT_AE))
    parser.add_argument("--ae-scaler-out", default=str(DEFAULT_AES))
    parser.add_argument("--metrics-out",   default=str(DEFAULT_META))
    parser.add_argument("--ref-stats-out", default=str(DEFAULT_REF))
    parser.add_argument("--contamination", default="auto",
                        help="Fraud fraction for IF. Use 0.0017 for Kaggle dataset.")
    parser.add_argument("--ae-samples",    type=int, default=50_000,
                        help="Max normal samples used to train autoencoder (default 50000).")
    args = parser.parse_args()

    if not os.path.exists(os.path.join(args.data_dir, "X_train.npy")):
        raise FileNotFoundError(
            f"\nNo processed data in: {os.path.abspath(args.data_dir)}\n"
            f"Run preprocess.py first."
        )

    contamination = args.contamination
    if contamination != "auto":
        contamination = float(contamination)

    os.makedirs(PROJECT_ROOT / "models", exist_ok=True)

    X_train, X_test, y_train, y_test = load_processed(args.data_dir)
    print(f"Train: {X_train.shape}  |  Test: {X_test.shape}")

    X_normal = X_train[y_train == 0]

    # ── 1. Isolation Forest ──
    if_model   = train_isolation_forest(X_train, contamination)
    if_scores  = score_if(if_model, X_test)
    if_pred    = np.where(if_model.predict(X_test) == -1, 1, 0)
    if_metrics = compute_metrics(y_test, if_pred, if_scores, "Isolation Forest")

    # ── 2. Autoencoder ──
    ae_model, ae_scaler = train_autoencoder(X_normal, args.ae_samples)
    ae_scores  = score_ae(ae_model, ae_scaler, X_test)

    # Threshold = 95th percentile of normal reconstruction errors
    ae_normal_errors = score_ae(ae_model, ae_scaler, X_normal[:10_000])
    ae_threshold = float(np.percentile(ae_normal_errors, 95))
    ae_pred      = (ae_scores > ae_threshold).astype(int)
    ae_metrics   = compute_metrics(y_test, ae_pred, ae_scores, "Autoencoder")

    # ── Save models ──
    joblib.dump(if_model,  args.if_out)
    joblib.dump(ae_model,  args.ae_out)
    joblib.dump(ae_scaler, args.ae_scaler_out)
    print(f"\nSaved Isolation Forest  → {args.if_out}")
    print(f"Saved Autoencoder       → {args.ae_out}")

    # ── Save comparison metrics ──
    comparison = {
        "isolation_forest": if_metrics,
        "autoencoder":      {**ae_metrics, "threshold": round(ae_threshold, 6)},
    }
    with open(args.metrics_out, "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"Saved comparison metrics → {args.metrics_out}")

    # ── Save reference stats for drift detection ──
    ref_stats = {
        "features": FEATURE_COLUMNS,
        "mean":     X_normal.mean(axis=0).tolist(),
        "std":      (X_normal.std(axis=0) + 1e-8).tolist(),
    }
    with open(args.ref_stats_out, "w") as f:
        json.dump(ref_stats, f, indent=2)
    print(f"Saved reference stats    → {args.ref_stats_out}")

    print("\nAll models trained and saved.")


if __name__ == "__main__":
    main()

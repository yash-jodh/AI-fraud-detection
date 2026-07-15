"""
drift_detector.py

Detects feature distribution drift in incoming transactions by comparing
a sliding window of recent transactions against reference statistics
computed from the training data.

Method: Z-score test on window mean vs reference mean.
  z = |mean(window) - mean(ref)| / (std(ref) / sqrt(window_size))
If z > threshold (default 3.0) for any feature, drift is flagged.
"""

import json
from collections import deque
from pathlib import Path

import numpy as np

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_REF  = PROJECT_ROOT / "models" / "reference_stats.json"


class DriftDetector:
    def __init__(
        self,
        reference_stats: dict,
        window_size: int   = 100,
        z_threshold: float = 3.0,
    ):
        self.ref_mean     = np.array(reference_stats["mean"])
        self.ref_std      = np.array(reference_stats["std"])
        self.feature_names = reference_stats["features"]
        self.window_size  = window_size
        self.z_threshold  = z_threshold
        self.window       = deque(maxlen=window_size)
        self.total_seen   = 0
        self.drift_events = 0

    def add(self, features: np.ndarray):
        """Add one transaction's feature vector to the sliding window."""
        self.window.append(features)
        self.total_seen += 1

    def check(self) -> dict:
        """
        Run the drift test on the current window.
        Returns a dict safe to include in every API response.
        """
        n = len(self.window)
        if n < max(10, self.window_size // 4):
            return {
                "drift_detected":    False,
                "reason":            f"Warming up ({n}/{self.window_size} samples)",
                "drifted_features":  [],
                "window_size":       n,
                "max_z_score":       0.0,
            }

        window_arr  = np.array(list(self.window))
        window_mean = window_arr.mean(axis=0)

        # Standard error of the mean
        se      = self.ref_std / np.sqrt(n)
        z_scores = np.abs(window_mean - self.ref_mean) / (se + 1e-8)

        drifted_idx      = np.where(z_scores > self.z_threshold)[0]
        drifted_features = [
            {
                "feature": self.feature_names[i],
                "z_score": round(float(z_scores[i]), 2),
            }
            for i in drifted_idx
        ]

        drift_detected = len(drifted_features) > 0
        if drift_detected:
            self.drift_events += 1

        return {
            "drift_detected":   drift_detected,
            "drifted_features": drifted_features,
            "window_size":      n,
            "max_z_score":      round(float(z_scores.max()), 2),
            "drift_events":     self.drift_events,
        }

    @classmethod
    def from_file(
        cls,
        path: str | Path = DEFAULT_REF,
        window_size: int = 100,
        z_threshold: float = 3.0,
    ) -> "DriftDetector":
        with open(path) as f:
            ref = json.load(f)
        return cls(ref, window_size=window_size, z_threshold=z_threshold)

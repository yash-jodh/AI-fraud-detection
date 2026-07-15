"""
test_drift_detector.py

Basic unit tests for DriftDetector. Run from the project root:

    pytest tests/ -v

(requires backend/ on the Python path — see conftest.py)
"""

import numpy as np

from drift_detector import DriftDetector


def _make_detector(n_features=3, window_size=10, z_threshold=3.0):
    reference_stats = {
        "features": [f"f{i}" for i in range(n_features)],
        "mean": [0.0] * n_features,
        "std": [1.0] * n_features,
    }
    return DriftDetector(reference_stats, window_size=window_size, z_threshold=z_threshold)


def test_warming_up_before_enough_samples():
    det = _make_detector(window_size=20)
    det.add(np.array([0.0, 0.0, 0.0]))
    result = det.check()
    assert result["drift_detected"] is False
    assert "Warming up" in result["reason"]


def test_no_drift_when_matching_reference():
    det = _make_detector(window_size=10)
    rng = np.random.default_rng(42)
    for _ in range(10):
        det.add(rng.normal(loc=0.0, scale=1.0, size=3))
    result = det.check()
    assert result["drift_detected"] is False


def test_drift_detected_on_large_mean_shift():
    det = _make_detector(window_size=10, z_threshold=3.0)
    for _ in range(10):
        det.add(np.array([50.0, 50.0, 50.0]))  # far from reference mean of 0
    result = det.check()
    assert result["drift_detected"] is True
    assert result["max_z_score"] > 3.0
    assert len(result["drifted_features"]) == 3


def test_drift_events_counter_increments():
    det = _make_detector(window_size=10, z_threshold=1.0)
    for _ in range(10):
        det.add(np.array([10.0, 10.0, 10.0]))
    first = det.check()
    second = det.check()
    assert first["drift_events"] == 1
    assert second["drift_events"] == 2

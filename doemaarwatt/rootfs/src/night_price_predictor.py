"""
predictor.py
------------
Initialization and inference for the hourly and 15-minute electricity price models.

Usage:
    from predictor import init, predict

    init()  # loads both models
    result = predict(date(2025, 11, 15), prev_day_hourly_prices, resolution="15min")
"""

import math
import os
from datetime import date

import joblib

from logger import Logger

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

# Keyed by resolution string: {"model": ..., "scaler": ...}
_artifacts: dict = {}

MODEL_FILES = {
    "1hour": "night_price_model.pkl",
    "15min": "night_price_model_15min.pkl",
}

# Output slots per resolution
SLOTS = {
    "1hour": [(h, 0)  for h in range(12)],
    "15min": [(h, m)  for h in range(12) for m in range(0, 60, 15)],
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_night_price_predictor(log: Logger) -> None:
    """Load both models (1hour and 15min) into memory."""
    base = os.path.dirname(__file__)
    for resolution, filename in MODEL_FILES.items():
        p = os.path.join(base, filename)
        log.debug(f'trying to load night price prediction model {p}')
        _artifacts[resolution] = joblib.load(p)


def predict_night_price(prediction_date: date, prev_day_hourly_prices: list[float], resolution: str) -> list[dict]:
    """
    Predict electricity prices for the first 12 hours of prediction_date.

    Args:
        prediction_date:        The day to predict prices for.
        prev_day_hourly_prices: 24 floats — one price per hour for the preceding day.
        resolution:             "1hour" (4 results) or "15min" (16 results).

    Returns:
        List of dicts with keys "time" (str, e.g. "00:15") and "price" (float, €/kWh).
    """
    if not _artifacts:
        raise RuntimeError("Call init() before predict().")
    if resolution not in _artifacts:
        raise ValueError(f"Unknown resolution '{resolution}'. Choose '1hour' or '15min'.")
    if len(prev_day_hourly_prices) != 24:
        raise ValueError(f"Expected 24 hourly prices, got {len(prev_day_hourly_prices)}.")

    model, scaler = _artifacts[resolution]["model"], _artifacts[resolution]["scaler"]
    features = _build_features(prediction_date, prev_day_hourly_prices)
    raw      = model.predict(scaler.transform([features]))[0]

    return [
        {"time": f"{h:02d}:{m:02d}", "price": float(raw[i])}
        for i, (h, m) in enumerate(SLOTS[resolution])
    ]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cyclic(val: float, period: float) -> tuple[float, float]:
    angle = 2 * math.pi * val / period
    return math.sin(angle), math.cos(angle)


def _build_features(prediction_date: date, prev_hourly: list[float]) -> list[float]:
    dow_sin, dow_cos = _cyclic(prediction_date.weekday(), 7)
    mon_sin, mon_cos = _cyclic(prediction_date.month - 1, 12)
    return list(prev_hourly) + [dow_sin, dow_cos, mon_sin, mon_cos]

"""Soft limiter: transparent below the knee, smoothly saturates towards +-1 above it."""
from __future__ import annotations

import numpy as np


def soft_limit(x: np.ndarray, knee: float = 0.8) -> np.ndarray:
    a = np.abs(x)
    if a.max(initial=0.0) <= knee:
        return x
    over = knee + (1 - knee) * np.tanh((a - knee) / (1 - knee))
    return np.where(a > knee, np.sign(x) * over, x).astype(np.float32)

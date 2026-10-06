"""Lock-free level history for the UI (written by the audio thread, read by the UI thread)."""
import numpy as np


class WaveHistory:
    """Fixed-size ring of per-block (min, max) sample values. Torn reads are harmless for a display."""

    def __init__(self, size: int = 512):
        self.size = size
        self._buf = np.zeros((size, 2), np.float32)
        self._i = 0

    def push(self, lo: float, hi: float) -> None:
        i = self._i
        self._buf[i % self.size] = (lo, hi)
        self._i = i + 1

    def latest(self, n: int) -> np.ndarray:
        """Last n entries, oldest first, shape (n, 2). Zero-padded at the start."""
        n = min(n, self.size)
        i = self._i
        idx = (np.arange(i - n, i)) % self.size
        out = self._buf[idx].copy()
        if i < n:
            out[: n - i] = 0
        return out

    def recent_peak(self, n: int = 300) -> float:
        a = self.latest(n)
        return float(max(abs(a[:, 0]).max(initial=0.0), abs(a[:, 1]).max(initial=0.0)))

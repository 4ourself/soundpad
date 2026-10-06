import threading

import numpy as np


class RingBuffer:
    """Thread-safe float32 ring buffer. Overflow drops the OLDEST audio (keeps latency bounded)."""

    def __init__(self, capacity: int, channels: int):
        self.capacity = int(capacity)
        self.channels = channels
        self._buf = np.zeros((self.capacity, channels), np.float32)
        self._r = 0
        self._count = 0
        self._lock = threading.Lock()

    @property
    def available(self) -> int:
        return self._count

    @property
    def free(self) -> int:
        return self.capacity - self._count

    def clear(self) -> None:
        with self._lock:
            self._r = self._count = 0

    def write(self, x: np.ndarray) -> None:
        x = np.asarray(x, np.float32)
        if x.ndim == 1:
            x = x[:, None]
        n = len(x)
        cap = self.capacity
        with self._lock:
            if n >= cap:
                x, n = x[-cap:], cap
                self._r = self._count = 0
            overflow = self._count + n - cap
            if overflow > 0:
                self._r = (self._r + overflow) % cap
                self._count -= overflow
            w = (self._r + self._count) % cap
            first = min(n, cap - w)
            self._buf[w:w + first] = x[:first]
            if first < n:
                self._buf[:n - first] = x[first:]
            self._count += n

    def read(self, n: int):
        """Returns (block[n, channels] zero-padded, frames_actually_read)."""
        out = np.zeros((n, self.channels), np.float32)
        cap = self.capacity
        with self._lock:
            m = min(n, self._count)
            first = min(m, cap - self._r)
            out[:first] = self._buf[self._r:self._r + first]
            if first < m:
                out[first:m] = self._buf[:m - first]
            self._r = (self._r + m) % cap
            self._count -= m
        return out, m

    def drop(self, n: int) -> None:
        with self._lock:
            n = min(n, self._count)
            self._r = (self._r + n) % self.capacity
            self._count -= n


class JitterReader:
    """Reads fixed blocks from a ring that is filled by a *different* audio clock.

    Keeps ~`jitter_blocks` of safety margin: on underrun it outputs silence and re-primes;
    if the producer runs ahead it drops the excess so latency never grows.
    """

    def __init__(self, ring: RingBuffer, jitter_blocks: int = 2):
        self.ring = ring
        self.jitter_blocks = max(1, jitter_blocks)
        self.primed = False
        self.underruns = 0
        self.overruns = 0

    def read(self, frames: int) -> np.ndarray:
        ring = self.ring
        avail = ring.available
        target = frames * self.jitter_blocks
        if not self.primed:
            if avail < target:
                return np.zeros((frames, ring.channels), np.float32)
            self.primed = True
        if avail < frames:
            self.underruns += 1
            self.primed = False
            return np.zeros((frames, ring.channels), np.float32)
        if avail > target + frames * 2:
            ring.drop(avail - target)
            self.overruns += 1
        return ring.read(frames)[0]

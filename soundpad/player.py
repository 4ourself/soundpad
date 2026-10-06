"""Soundpad playback mixer: many simultaneous voices summed into one stereo stream."""
from __future__ import annotations

import threading

import numpy as np

FADE_SAMPLES = 240  # 5 ms fade-out when a voice is stopped (avoids clicks)


class Voice:
    def __init__(self, sound_id: str, name: str, gain: float, audio=None, stream=None, total: int = 0):
        self.sound_id, self.name, self.gain = sound_id, name, float(gain)
        self.audio, self.stream = audio, stream
        self.pos = 0
        self.total = len(audio) if audio is not None else int(total)
        self.fading = False
        self._fade_gain = 1.0

    def stop(self):
        self.fading = True

    @property
    def progress(self) -> float:
        return min(1.0, self.pos / self.total) if self.total else 0.0

    def close(self):
        if self.stream is not None:
            self.stream.close()

    def render(self, n: int):
        if self.audio is not None:
            chunk = self.audio[self.pos:self.pos + n]
            self.pos += len(chunk)
            ended = self.pos >= len(self.audio)
        else:
            chunk, ended = self.stream.read(n)
            self.pos += n
        out = np.zeros((n, 2), np.float32)
        out[:len(chunk)] = chunk * np.float32(self.gain)
        if self.fading:
            g = np.maximum(self._fade_gain - np.arange(1, n + 1) / FADE_SAMPLES, 0.0).astype(np.float32)
            out *= g[:, None]
            self._fade_gain = float(g[-1])
            ended = ended or self._fade_gain <= 0.0
        return out, ended


class SoundPlayer:
    """Never touches the microphone path. render() is called from the output audio callback."""

    def __init__(self, max_simultaneous: int = 8, allow_overlap: bool = True):
        self.max_simultaneous = max_simultaneous
        self.allow_overlap = allow_overlap
        self._voices: list[Voice] = []
        self._lock = threading.Lock()

    def play(self, sound_id: str, name: str, gain: float, audio=None, stream=None, total: int = 0) -> None:
        v = Voice(sound_id, name, gain, audio=audio, stream=stream, total=total)
        with self._lock:
            if not self.allow_overlap:
                for o in self._voices:
                    o.stop()
            active = [o for o in self._voices if not o.fading]
            while len(active) >= max(1, self.max_simultaneous):
                active.pop(0).stop()      # drop the oldest
            self._voices.append(v)

    def stop_all(self) -> None:
        with self._lock:
            for v in self._voices:
                v.stop()

    def stop_sound(self, sound_id: str) -> None:
        with self._lock:
            for v in self._voices:
                if v.sound_id == sound_id:
                    v.stop()

    def snapshot(self) -> list[dict]:
        """Playing voices for the UI: [{id, name, progress, fading}]."""
        with self._lock:
            return [{"id": v.sound_id, "name": v.name, "progress": v.progress, "fading": v.fading}
                    for v in self._voices]

    def active_ids(self) -> set[str]:
        with self._lock:
            return {v.sound_id for v in self._voices if not v.fading}

    def active_names(self) -> list[str]:
        with self._lock:
            return [v.name for v in self._voices if not v.fading]

    def render(self, n: int) -> np.ndarray:
        out = np.zeros((n, 2), np.float32)
        with self._lock:
            if not self._voices:
                return out
            alive = []
            for v in self._voices:
                block, ended = v.render(n)
                out += block
                if ended:
                    v.close()
                else:
                    alive.append(v)
            self._voices = alive
        return out

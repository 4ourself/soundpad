"""Reusable drawing widgets. Pure drawing + tiny state holders; no backend knowledge."""
from __future__ import annotations

import glob
import math
import os

from .canvas import Canvas, Rect, fit


# ------------------------------------------------------------------ small helpers
def db(level: float) -> float:
    return 20.0 * math.log10(max(level, 1e-5))


def db_text(level: float) -> str:
    return "-inf dB" if level < 1e-4 else f"{db(level):5.1f} dB"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def fmt_value(v: float, unit: str, step: float = 1) -> str:
    dec = 0 if abs(step - round(step)) < 1e-9 else 1
    sign = "+" if unit.strip() in ("dB", "st") and v > 0 else ""
    return f"{sign}{v:.{dec}f}{unit}"


# ------------------------------------------------------------------ drawing
def slider(cv: Canvas, th, x: int, y: int, w: int, frac: float, focused=False, enabled=True) -> None:
    """━━━━━●─────  (filled part accent, thumb white, rest faint)."""
    if w < 3:
        return
    g = th.g
    pos = int(round(clamp(frac, 0, 1) * (w - 1)))
    fill_st = (th.accent_b if focused else th.accent_s) if enabled else th.dim
    cv.put(x, y, g.slider * pos, fill_st)
    cv.put(x + pos, y, g.thumb, th.thumb if enabled else th.dim)
    cv.put(x + pos + 1, y, g.track * (w - pos - 1), th.faint)


def meter(cv: Canvas, th, x: int, y: int, w: int, level: float, peak: float = 0.0, floor_db: float = -60.0) -> None:
    """dB-scaled bar: green / yellow (> -18 dB) / red (> -6 dB), with a peak-hold tick."""
    if w < 2:
        return
    g = th.g
    frac = clamp((db(level) - floor_db) / -floor_db, 0, 1)
    n = int(round(frac * w))
    for i in range(w):
        f = (i + 0.5) / w
        if i < n:
            st = th.graph_style(f, f)
            cv.put(x + i, y, g.full, st)
        else:
            cv.put(x + i, y, g.empty, th.m_empty)
    if peak > level:
        pf = clamp((db(peak) - floor_db) / -floor_db, 0, 1)
        pi = min(w - 1, int(pf * w))
        if pi >= n:
            cv.put(x + pi, y, g.peak, th.thumb)


def toggle(cv: Canvas, th, x: int, y: int, on: bool, label_on="ON", label_off="OFF") -> int:
    g = th.g
    if on:
        return cv.put(x, y, f"{g.dot} {label_on}", th.on)
    return cv.put(x, y, f"{g.ring} {label_off}", th.off)


def dot(cv: Canvas, th, x: int, y: int, state: str) -> None:
    """state: ok | warn | bad | off"""
    g = th.g
    cv.put(x, y, g.ring if state == "off" else g.dot,
           {"ok": th.ok, "warn": th.warn, "bad": th.err, "off": th.off}[state])


def button(cv: Canvas, th, x: int, y: int, label: str, focused: bool) -> int:
    return cv.put(x, y, f"[ {label} ]", th.sel if focused else th.accent_s)


def row_highlight(cv: Canvas, th, r: Rect, y: int, focused: bool) -> None:
    """Solid accent bar behind a focused row + left marker. Content is drawn on top by the caller."""
    if focused:
        cv.fill(Rect(r.x, y, r.w, 1), " ", th.sel)


def legend(cv: Canvas, th, x: int, y: int, w: int, items: list[tuple[str, str]]) -> None:
    """[(key, description)] -> 'key desc  key desc' truncated to fit (drops trailing items)."""
    cx = x
    for k, d in items:
        need = len(k) + 1 + len(d) + 2
        if cx + need - 2 > x + w:
            break
        cx += cv.put(cx, y, k, th.key) + 1
        cx += cv.put(cx, y, d, th.dim) + 2


def waveform(cv: Canvas, th, r: Rect, hist) -> None:
    """Mirrored min/max waveform. hist: (n,2) array of per-block (min,max). Uses the last r.w columns."""
    if r.w < 4 or r.h < 1:
        return
    import numpy as np
    n = len(hist)
    cols = r.w
    if n >= cols:
        seg = hist[-cols * (n // cols):] if n // cols else hist[-cols:]
        k = max(1, len(seg) // cols)
        seg = seg[: cols * k].reshape(cols, k, 2)
        lo, hi = seg[:, :, 0].min(axis=1), seg[:, :, 1].max(axis=1)
    else:
        lo = np.zeros(cols, np.float32); hi = np.zeros(cols, np.float32)
        lo[-n:], hi[-n:] = hist[:, 0], hist[:, 1]
    amp = np.maximum(np.abs(lo), np.abs(hi))
    # perceptual boost so quiet speech is visible
    amp = np.clip(amp ** 0.6, 0, 1)
    g = th.g
    mid = r.h // 2
    half = max(1, mid if r.h % 2 else r.h // 2)
    blocks = g.blocks
    for i in range(cols):
        total = amp[i] * half * 8
        full, part = int(total // 8), int(total % 8)
        st = th.graph_style(float(amp[i]), i / max(1, cols - 1))
        if r.h % 2:
            cv.put(r.x + i, r.y + mid, g.h if total < 0.5 else g.full, th.faint if total < 0.5 else st)
        for j in range(half):
            yu = r.y + (mid - 1 - j) if r.h % 2 else r.y + half - 1 - j
            yd = r.y + (mid + 1 + j) if r.h % 2 else r.y + half + j
            if j < full:
                cu = cd = g.full
            elif j == full and part > 0:
                cu = blocks[part - 1]
                cd = g.top if part >= 4 else " "
            else:
                continue
            cv.put(r.x + i, yu, cu, st)
            cv.put(r.x + i, yd, cd, st)


def sparkline(cv: Canvas, th, x: int, y: int, w: int, values, st=None) -> None:
    blocks = th.g.blocks
    vals = list(values)[-w:]
    pad = w - len(vals)
    for i, v in enumerate(vals):
        idx = int(clamp(v, 0, 1) ** 0.6 * (len(blocks) - 1))
        cv.put(x + pad + i, y, blocks[idx], st if st is not None else th.accent_s)


# ------------------------------------------------------------------ state holders
class ListState:
    """Selection + scroll window for a vertical list."""

    def __init__(self):
        self.idx = 0
        self.top = 0

    def move(self, delta: int, n: int, wrap: bool = False) -> None:
        if n <= 0:
            self.idx = 0
            return
        self.idx = (self.idx + delta) % n if wrap else clamp(self.idx + delta, 0, n - 1)

    def clamp(self, n: int) -> None:
        self.idx = clamp(self.idx, 0, max(0, n - 1))

    def window(self, n: int, height: int) -> tuple[int, int]:
        """(first, last_exclusive) visible indices keeping idx in view."""
        height = max(1, height)
        if self.idx < self.top:
            self.top = self.idx
        elif self.idx >= self.top + height:
            self.top = self.idx - height + 1
        self.top = clamp(self.top, 0, max(0, n - height))
        return self.top, min(n, self.top + height)


def scrollbar(cv: Canvas, th, x: int, y: int, h: int, first: int, last: int, n: int) -> None:
    if n <= h or h < 3:
        return
    size = max(1, h * h // n)
    pos = int((h - size) * first / max(1, n - h))
    for i in range(h):
        cv.put(x, y + i, th.g.bar if pos <= i < pos + size else th.g.v, th.accent_s if pos <= i < pos + size else th.faint)


class TextInput:
    """Single-line editor with cursor, Home/End/Delete and optional filesystem Tab-completion."""

    def __init__(self, value: str = "", path: bool = False, max_len: int = 400):
        self.value = value
        self.cursor = len(value)
        self.path = path
        self.max_len = max_len
        self._offset = 0
        self._completions: list[str] = []
        self._ci = 0

    def set(self, v: str) -> None:
        self.value, self.cursor = v, len(v)

    def handle(self, key) -> bool:
        n = key.name
        if key.printable:
            if len(self.value) < self.max_len:
                self.value = self.value[: self.cursor] + key.char + self.value[self.cursor:]
                self.cursor += 1
            self._completions = []
            return True
        if n == "backspace":
            if self.cursor:
                self.value = self.value[: self.cursor - 1] + self.value[self.cursor:]
                self.cursor -= 1
        elif n == "delete":
            self.value = self.value[: self.cursor] + self.value[self.cursor + 1:]
        elif n == "left":
            self.cursor = max(0, self.cursor - 1)
        elif n == "right":
            self.cursor = min(len(self.value), self.cursor + 1)
        elif n == "home":
            self.cursor = 0
        elif n == "end":
            self.cursor = len(self.value)
        elif n == "ctrl+u":
            self.value, self.cursor = "", 0
        elif n == "tab" and self.path:
            self._complete()
        else:
            return False
        if n != "tab":
            self._completions = []
        return True

    def _complete(self) -> None:
        if not self._completions:
            raw = self.value.strip('"')
            base = os.path.expanduser(raw)
            matches = sorted(glob.glob(glob.escape(base) + "*"))
            self._completions = [m + (os.sep if os.path.isdir(m) else "") for m in matches]
            self._ci = 0
        if self._completions:
            self.set(self._completions[self._ci % len(self._completions)])
            self._ci += 1

    def draw(self, cv: Canvas, th, x: int, y: int, w: int, focused: bool) -> None:
        if w < 3:
            return
        view = w - 1
        if self.cursor < self._offset:
            self._offset = self.cursor
        elif self.cursor > self._offset + view - 1:
            self._offset = self.cursor - view + 1
        text = self.value[self._offset:self._offset + view]
        cv.fill(Rect(x, y, w, 1), " ", th.faint if not focused else th.accent_s)
        cv.fill(Rect(x, y, w, 1), th.g.track if not text and not focused else " ", th.faint)
        cv.put(x, y, text, th.text if text else th.faint)
        if focused:
            cx = x + self.cursor - self._offset
            ch = self.value[self.cursor] if self.cursor < len(self.value) else " "
            cv.put(cx, y, ch, th.sel)

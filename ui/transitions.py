"""Tab-switch animations. Pure canvas post-processing: the previous frame is snapshotted when the screen changes
and mixed with the freshly drawn frame for a short time. Nothing here touches audio or blocks input."""
from __future__ import annotations

import random
import time

KINDS = ("none", "fade", "line", "slide", "wipe", "dissolve", "curtain", "blinds", "random")
SPEEDS = {"fast": 0.18, "normal": 0.32, "slow": 0.60}
TOP, BOTTOM = 1, 2          # rows kept static: header on top, notification + status bar at the bottom


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


class Snapshot:
    __slots__ = ("ch", "st", "w", "h")

    def __init__(self, cv, blank: bool = False):
        self.w, self.h = cv.w, cv.h
        if blank:
            self.ch = [[" "] * cv.w for _ in range(cv.h)]
            self.st = [[0] * cv.w for _ in range(cv.h)]
        else:
            self.ch = [row[:] for row in cv.ch]
            self.st = [row[:] for row in cv.st]


class Transition:
    def __init__(self, kind: str, old: Snapshot, duration: float = 0.32, direction: int = 1,
                 src: tuple = (1, 6), dst: tuple = (1, 6), now: float | None = None, seed: int | None = None):
        self.kind = kind
        self.old = old
        self.duration = max(0.05, duration)
        self.dir = 1 if direction >= 0 else -1
        self.src, self.dst = src, dst                  # (x, width) of the old / new tab label
        self.t0 = time.monotonic() if now is None else now
        self.rng = random.Random(seed)
        self._thr = None

    def progress(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return (now - self.t0) / self.duration

    # -------------------------------------------------------------- compose
    def apply(self, cv, th, now: float | None = None, t: float | None = None) -> bool:
        """Mix the snapshot into `cv` (which holds the new frame). Returns False once finished."""
        p = self.progress(now) if t is None else t
        old = self.old
        if p >= 1.0:
            return False
        if (cv.w, cv.h) != (old.w, old.h) or cv.h < TOP + BOTTOM + 3 or cv.w < 10:
            return False                                   # resized mid-animation: just stop
        kind = self.kind
        if kind == "fade" and th.depth in ("16", "mono"):
            kind = "dissolve"                              # can't dim smoothly with 16 colours
        e = ease(p)
        y0, y1 = TOP, cv.h - BOTTOM
        getattr(self, "_" + kind, self._none)(cv, th, y0, y1, p, e)
        return True

    def _none(self, cv, th, y0, y1, p, e):
        return

    def _fade(self, cv, th, y0, y1, p, e):
        old = self.old
        if p < 0.5:
            lvl = 1.0 - ease(p * 2)
            for y in range(y0, y1):
                cv.ch[y] = old.ch[y][:]
                cv.st[y] = [th.fade_style(s, lvl) for s in old.st[y]]
        else:
            lvl = ease((p - 0.5) * 2)
            for y in range(y0, y1):
                cv.st[y] = [th.fade_style(s, lvl) for s in cv.st[y]]

    def _line(self, cv, th, y0, y1, p, e):
        old = self.old
        if p < 0.5:
            for y in range(y0, y1):
                cv.ch[y] = old.ch[y][:]
                cv.st[y] = old.st[y][:]
        x0, w0 = self.src
        x1, w1 = self.dst
        x = int(round(x0 + (x1 - x0) * e))
        w = max(2, int(round(w0 + (w1 - w0) * e)))
        mark = th.g.slider
        for i in range(w):
            if 0 <= x + i < cv.w:
                cv.ch[y0][x + i] = mark
                cv.st[y0][x + i] = th.accent_b
        # a soft trail behind the head
        for k in range(1, 4):
            tx = x - k * self.dir * 2
            for i in range(w):
                if 0 <= tx + i < cv.w and cv.ch[y0][tx + i] != mark and k < 3:
                    cv.ch[y0][tx + i] = th.g.h
                    cv.st[y0][tx + i] = th.accent_s

    def _slide(self, cv, th, y0, y1, p, e):
        old, w = self.old, cv.w
        off = int(round(w * e))
        for y in range(y0, y1):
            if self.dir > 0:      # new content enters from the right
                cv.ch[y] = old.ch[y][off:] + cv.ch[y][:off]
                cv.st[y] = old.st[y][off:] + cv.st[y][:off]
            else:
                cv.ch[y] = cv.ch[y][w - off:] + old.ch[y][:w - off]
                cv.st[y] = cv.st[y][w - off:] + old.st[y][:w - off]

    def _wipe(self, cv, th, y0, y1, p, e):
        old, w = self.old, cv.w
        edge = int(round(w * e))
        for y in range(y0, y1):
            if self.dir > 0:
                cv.ch[y][edge:] = old.ch[y][edge:]
                cv.st[y][edge:] = old.st[y][edge:]
                if edge < w:
                    cv.ch[y][edge], cv.st[y][edge] = th.g.bar, th.accent_b
            else:
                k = w - edge
                cv.ch[y][:k] = old.ch[y][:k]
                cv.st[y][:k] = old.st[y][:k]
                if k > 0:
                    cv.ch[y][k - 1], cv.st[y][k - 1] = th.g.bar, th.accent_b

    def _curtain(self, cv, th, y0, y1, p, e):
        old, w = self.old, cv.w
        half = int(round(w / 2 * e))
        lo, hi = w // 2 - half, w // 2 + half
        for y in range(y0, y1):
            cv.ch[y][:lo], cv.st[y][:lo] = old.ch[y][:lo], old.st[y][:lo]
            cv.ch[y][hi:], cv.st[y][hi:] = old.ch[y][hi:], old.st[y][hi:]
            if lo > 0:
                cv.ch[y][lo], cv.st[y][lo] = th.g.bar, th.accent_b
            if hi < w:
                cv.ch[y][hi - 1], cv.st[y][hi - 1] = th.g.bar, th.accent_b

    def _blinds(self, cv, th, y0, y1, p, e):
        old = self.old
        for y in range(y0, y1):
            if p < (y % 4) * 0.22 + 0.04:
                cv.ch[y] = old.ch[y][:]
                cv.st[y] = old.st[y][:]

    def _dissolve(self, cv, th, y0, y1, p, e):
        if self._thr is None:
            self._thr = [[self.rng.random() for _ in range(cv.w)] for _ in range(cv.h)]
        old = self.old
        for y in range(y0, y1):
            thr, och, ost, nch, nst = self._thr[y], old.ch[y], old.st[y], cv.ch[y], cv.st[y]
            for x in range(cv.w):
                if thr[x] >= e:
                    nch[x], nst[x] = och[x], ost[x]


CONCRETE = tuple(k for k in KINDS if k not in ("none", "random"))


def make(kind: str, snapshot: Snapshot, speed: str = "normal", direction: int = 1, src=(1, 6), dst=(1, 6),
         now: float | None = None, seed: int | None = None) -> Transition | None:
    if kind == "random":
        kind = random.Random(seed).choice(CONCRETE)
    if kind not in CONCRETE:
        return None
    return Transition(kind, snapshot, SPEEDS.get(speed, SPEEDS["normal"]), direction, src, dst, now, seed)

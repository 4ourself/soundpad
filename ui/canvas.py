"""Cell buffer + diff renderer: only changed cells are written to the terminal (no flicker, tiny output)."""
from __future__ import annotations

import unicodedata
from typing import NamedTuple


class Rect(NamedTuple):
    x: int
    y: int
    w: int
    h: int

    def inset(self, dx: int = 1, dy: int = 1) -> "Rect":
        return Rect(self.x + dx, self.y + dy, max(0, self.w - 2 * dx), max(0, self.h - 2 * dy))

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


def clean(text: str) -> str:
    """Make arbitrary user text single-cell-safe (wide/emoji/combining/control chars would break alignment)."""
    out = []
    for ch in text:
        o = ord(ch)
        if o < 32 or 0x7F <= o < 0xA0:
            out.append(" ")
            continue
        if o >= 0x1F000 or unicodedata.east_asian_width(ch) in ("W", "F"):
            out.append("?")
            continue
        if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            continue
        out.append(ch)
    return "".join(out)


def fit(text: str, width: int, ell: str = "…") -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= len(ell):
        return text[:width]
    return text[: width - len(ell)] + ell


class Canvas:
    def __init__(self, w: int, h: int):
        self.ascii = False          # ASCII fallback: anything non-ASCII (e.g. the ellipsis) is substituted
        self.resize(w, h)

    def resize(self, w: int, h: int) -> None:
        self.w, self.h = max(1, w), max(1, h)
        self.ch = [[" "] * self.w for _ in range(self.h)]
        self.st = [[0] * self.w for _ in range(self.h)]

    def clear(self) -> None:
        for y in range(self.h):
            self.ch[y] = [" "] * self.w
            self.st[y] = [0] * self.w

    # ------------------------------------------------------------ drawing primitives
    def put(self, x: int, y: int, text: str, st: int = 0, maxw: int | None = None) -> int:
        """Write text at (x,y), clipped to the canvas (and to maxw). Returns cells written."""
        if y < 0 or y >= self.h or x >= self.w or not text:
            return 0
        if not text.isascii():
            text = clean(text)
            if self.ascii:
                text = text.replace("…", "~").encode("ascii", "replace").decode()
        if x < 0:
            text, x = text[-x:], 0
        n = min(len(text), self.w - x)
        if maxw is not None:
            n = min(n, maxw)
        if n <= 0:
            return 0
        self.ch[y][x:x + n] = text[:n]
        self.st[y][x:x + n] = [st] * n
        return n

    def fill(self, r: Rect, ch: str = " ", st: int = 0) -> None:
        for y in range(max(0, r.y), min(self.h, r.bottom)):
            x0, x1 = max(0, r.x), min(self.w, r.right)
            if x1 > x0:
                self.ch[y][x0:x1] = ch * (x1 - x0)
                self.st[y][x0:x1] = [st] * (x1 - x0)

    def restyle(self, x: int, y: int, w: int, st: int) -> None:
        if 0 <= y < self.h:
            x0, x1 = max(0, x), min(self.w, x + w)
            if x1 > x0:
                self.st[y][x0:x1] = [st] * (x1 - x0)

    def hline(self, x: int, y: int, w: int, ch: str, st: int = 0) -> None:
        self.put(x, y, ch * max(0, w), st)

    def vline(self, x: int, y: int, h: int, ch: str, style: int) -> None:
        for yy in range(y, y + h):
            self.put(x, yy, ch, style)

    def box(self, r: Rect, theme, title: str = "", focused: bool = False, double: bool = False,
            right_title: str = "") -> Rect:
        """Bordered panel. Returns the inner rect."""
        if r.w < 2 or r.h < 2:
            return Rect(r.x, r.y, 0, 0)
        g = theme.g
        st = theme.border_focus if focused else theme.border
        h, v = (g.th, g.tv) if double else (g.h, g.v)
        tl, tr, bl, br = ((g.ttl, g.ttr, g.tbl, g.tbr) if double else (g.tl, g.tr, g.bl, g.br))
        self.put(r.x, r.y, tl + h * (r.w - 2) + tr, st)
        self.put(r.x, r.bottom - 1, bl + h * (r.w - 2) + br, st)
        for y in range(r.y + 1, r.bottom - 1):
            self.put(r.x, y, v, st)
            self.put(r.right - 1, y, v, st)
        if title and r.w > 6:
            t = fit(title, r.w - 6)
            self.put(r.x + 2, r.y, " " + t + " ", theme.title if focused else theme.bold)
        if right_title and r.w > len(right_title) + 8:
            self.put(r.right - 3 - len(right_title), r.y, " " + right_title + " ", theme.dim)
        return r.inset()

    def text_lines(self) -> list[str]:
        """Plain-text dump (tests / debugging)."""
        return ["".join(row) for row in self.ch]


class Screen:
    """Front buffer + diff flush."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.front_ch: list[list[str]] = []
        self.front_st: list[list[int]] = []
        self.force = True

    def resize(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.force = True

    def flush(self, cv: Canvas, theme) -> str:
        """Return the escape-sequence string that turns the terminal's current content into `cv`."""
        out: list[str] = []
        if self.force or len(self.front_ch) != cv.h or (self.front_ch and len(self.front_ch[0]) != cv.w):
            out.append("\x1b[0m\x1b[2J")
            self.front_ch = [[None] * cv.w for _ in range(cv.h)]     # None never equals a real cell
            self.front_st = [[-1] * cv.w for _ in range(cv.h)]
            self.force = False
        cur = -2
        for y in range(cv.h):
            bc, bs = cv.ch[y], cv.st[y]
            fc, fs = self.front_ch[y], self.front_st[y]
            if bc == fc and bs == fs:
                continue
            x, w = 0, cv.w
            while x < w:
                if bc[x] == fc[x] and bs[x] == fs[x]:
                    x += 1
                    continue
                start, last, gap = x, x, 0                  # extend the run across small unchanged gaps
                while x < w and gap <= 3:
                    if bc[x] == fc[x] and bs[x] == fs[x]:
                        gap += 1
                    else:
                        gap, last = 0, x
                    x += 1
                out.append(f"\x1b[{y + 1};{start + 1}H")
                for i in range(start, last + 1):
                    s = bs[i]
                    if s != cur:
                        out.append(theme.sgr(s))
                        cur = s
                    out.append(bc[i])
                fc[start:last + 1] = bc[start:last + 1]
                fs[start:last + 1] = bs[start:last + 1]
                x = last + 1
        if out:
            out.append("\x1b[0m")
        return "".join(out)

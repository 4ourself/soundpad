"""Colour maths and the `Paint` model (solid / zones / gradient / rainbow, with per-colour alpha).

Everything here is pure (no terminal, no theme): colours are (r, g, b) tuples of ints 0..255.
Alpha is 0..100 and is composited over black ("transparency = mix with black").
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass, field

RGB = tuple


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ------------------------------------------------------------------ conversions
def hex_to_rgb(text: str) -> RGB:
    """'#00d7ff', '00D7FF' or '#0df' -> (0, 215, 255). Raises ValueError."""
    t = (text or "").strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        raise ValueError("use 6 hex digits, e.g. #00D7FF")
    try:
        return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    except ValueError:
        raise ValueError("use 6 hex digits, e.g. #00D7FF") from None


def rgb_to_hex(c: RGB) -> str:
    return "#%02X%02X%02X" % tuple(int(clamp(round(v), 0, 255)) for v in c)


def rgb_to_hsv(c: RGB) -> tuple[float, float, float]:
    """-> (hue 0..360, saturation 0..100, value 0..100)"""
    h, s, v = colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)
    return h * 360.0, s * 100.0, v * 100.0


def hsv_to_rgb(h: float, s: float, v: float) -> RGB:
    r, g, b = colorsys.hsv_to_rgb((h % 360.0) / 360.0, clamp(s, 0, 100) / 100, clamp(v, 0, 100) / 100)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


TERMINAL_BG = (12, 12, 12)       # what we assume the terminal background is when the backdrop is not painted


def with_alpha(c: RGB, alpha: float, base: RGB = (0, 0, 0)) -> RGB:
    """Composite colour `c` at `alpha` % over `base` (the backdrop colour)."""
    a = clamp(alpha, 0, 100) / 100.0
    return tuple(int(round(base[i] + (c[i] - base[i]) * a)) for i in range(3))


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    t = clamp(t, 0.0, 1.0)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def luminance(c: RGB) -> float:
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255.0


def contrast(c: RGB) -> RGB:
    """Readable text colour on top of background `c`."""
    return (14, 14, 18) if luminance(c) > 0.42 else (245, 245, 245)


# ------------------------------------------------------------------ xterm palettes
_LV = (0, 95, 135, 175, 215, 255)


def xterm_rgb(i: int) -> RGB:
    if i < 16:
        base = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205),
                (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255),
                (255, 0, 255), (0, 255, 255), (255, 255, 255)]
        return base[i]
    if i >= 232:
        v = 8 + (i - 232) * 10
        return v, v, v
    i -= 16
    return _LV[i // 36], _LV[(i // 6) % 6], _LV[i % 6]


def _near_level(v: int) -> int:
    return min(range(6), key=lambda k: abs(_LV[k] - v))


def xterm_index(c: RGB) -> int:
    """Nearest colour of the 6x6x6 cube / grey ramp of the 256-colour palette."""
    r, g, b = (int(clamp(v, 0, 255)) for v in c)
    ri, gi, bi = _near_level(r), _near_level(g), _near_level(b)
    cube = 16 + 36 * ri + 6 * gi + bi
    cr = _LV[ri], _LV[gi], _LV[bi]
    grey = int(clamp(round((sum(c) / 3 - 8) / 10), 0, 23))
    gv = 8 + grey * 10
    d_cube = sum((cr[i] - (r, g, b)[i]) ** 2 for i in range(3))
    d_grey = sum((gv - v) ** 2 for v in (r, g, b))
    return 232 + grey if d_grey < d_cube else cube


_SGR16 = [(0, 0, 0, 30), (205, 0, 0, 31), (0, 205, 0, 32), (205, 205, 0, 33), (0, 0, 238, 34), (205, 0, 205, 35),
          (0, 205, 205, 36), (229, 229, 229, 37), (127, 127, 127, 90), (255, 0, 0, 91), (0, 255, 0, 92),
          (255, 255, 0, 93), (92, 92, 255, 94), (255, 0, 255, 95), (0, 255, 255, 96), (255, 255, 255, 97)]


def sgr16_fg(c: RGB) -> int:
    """Nearest of the 16 ANSI colours (SGR foreground code; add 10 for a background)."""
    return min(_SGR16, key=lambda e: (e[0] - c[0]) ** 2 + (e[1] - c[1]) ** 2 + (e[2] - c[2]) ** 2)[3]


# ------------------------------------------------------------------ Paint
MODES = ("solid", "zones", "gradient", "rainbow")
MAX_STOPS = 4
# where one colour ends and the next begins in 'zones' mode, by number of colours (level 0..1)
ZONES = {1: (), 2: (0.80,), 3: (0.70, 0.90), 4: (0.50, 0.75, 0.90)}


@dataclass
class Paint:
    """A fill: one colour, hard zones, a smooth gradient, or an animated rainbow.

    stops: [[hex, alpha 0..100], ...] (1..4).  speed 1..100 (rainbow: full cycles per second = speed / 250).
    Rainbow uses the saturation / brightness / alpha of the FIRST colour.
    Alpha = how much of the colour is mixed over `base` (the backdrop colour; set by the app, not saved).
    """
    mode: str = "solid"
    stops: list = field(default_factory=lambda: [["#00D7FF", 100]])
    speed: int = 50
    base: tuple = field(default=TERMINAL_BG, compare=False, repr=False)

    # ---- (de)serialisation, tolerant of damaged config
    @classmethod
    def from_dict(cls, d, default: "Paint") -> "Paint":
        try:
            mode = d.get("mode", default.mode)
            if mode not in MODES:
                raise ValueError(mode)
            stops = []
            for s in d.get("stops", [])[:MAX_STOPS]:
                hx, al = (s[0], s[1]) if isinstance(s, (list, tuple)) and len(s) > 1 else (s, 100)
                hex_to_rgb(str(hx))
                stops.append([rgb_to_hex(hex_to_rgb(str(hx))), int(clamp(int(al), 0, 100))])
            if not stops:
                raise ValueError("no colours")
            return cls(mode, stops, int(clamp(int(d.get("speed", 50)), 1, 100)), default.base)
        except (AttributeError, TypeError, ValueError, IndexError):
            return cls(default.mode, [list(s) for s in default.stops], default.speed, default.base)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "stops": [[h, int(a)] for h, a in self.stops], "speed": int(self.speed)}

    def rgba_at(self, pos: float) -> tuple:
        """Raw colour and alpha (0..100) at pos 0..1 of a solid / gradient paint, NOT mixed with any base.
        The 'glass' backdrop uses it: the alpha becomes how much of the cell is covered."""
        cols = [hex_to_rgb(h) for h, _ in self.stops]
        als = [float(a) for _, a in self.stops]
        if self.effective_mode() != "gradient" or len(cols) < 2:
            return cols[0], als[0]
        x = clamp(pos, 0.0, 1.0) * (len(cols) - 1)
        i = min(int(x), len(cols) - 2)
        f = x - i
        return lerp(cols[i], cols[i + 1], f), als[i] + (als[i + 1] - als[i]) * f

    def copy(self) -> "Paint":
        return Paint(self.mode, [list(s) for s in self.stops], self.speed, self.base)

    # ---- colours
    def stop_rgb(self, i: int) -> RGB:
        """Colour of stop i with its alpha applied."""
        hx, al = self.stops[i]
        return with_alpha(hex_to_rgb(hx), al, self.base)

    def colors(self) -> list[RGB]:
        return [self.stop_rgb(i) for i in range(len(self.stops))]

    @property
    def animated(self) -> bool:
        return self.mode == "rainbow"

    def effective_mode(self) -> str:
        if self.mode in ("zones", "gradient") and len(self.stops) < 2:
            return "solid"
        return self.mode

    def color_at(self, pos: float, level: float | None = None, phase: float = 0.0) -> RGB:
        """pos 0..1: position along the fill. level 0..1: signal level (zones / gradient on a meter).
        phase 0..1: rainbow rotation."""
        mode = self.effective_mode()
        cols = self.colors()
        if mode == "solid":
            return cols[0]
        if mode == "rainbow":
            hx, al = self.stops[0]
            _, s, v = rgb_to_hsv(hex_to_rgb(hx))
            return with_alpha(hsv_to_rgb(((pos + phase) % 1.0) * 360.0, s, v), al, self.base)
        x = clamp(pos if level is None else level, 0.0, 1.0)
        if mode == "zones":
            for i, edge in enumerate(ZONES[len(cols)]):
                if x < edge:
                    return cols[i]
            return cols[-1]
        seg = x * (len(cols) - 1)                       # gradient
        i = min(int(seg), len(cols) - 2)
        return lerp(cols[i], cols[i + 1], seg - i)

    def phase_at(self, t: float) -> float:
        return (t * self.speed / 250.0) % 1.0 if self.mode == "rainbow" else 0.0


# ------------------------------------------------------------------ presets
PRESET_ACCENTS = {          # same colours the 256-colour palette used before
    "cyan": "#00D7FF", "green": "#00D787", "magenta": "#D75FFF", "amber": "#FFAF00", "blue": "#5FAFFF",
}
DEFAULT_BACKDROP = Paint("solid", [["#171A22", 100]], 50)
DEFAULT_GRAPH = Paint("zones", [["#00D787", 100], ["#FFD700", 100], ["#FF5F5F", 100]], 50)


def preset_paint(name: str) -> Paint:
    return Paint("solid", [[PRESET_ACCENTS.get(name, PRESET_ACCENTS["cyan"]), 100]], 50)

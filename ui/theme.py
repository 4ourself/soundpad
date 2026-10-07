"""Colours, glyphs and the style registry. Degrades: truecolor -> 256 colours -> 16 colours -> mono; Unicode -> ASCII."""
from __future__ import annotations

import os
import sys

from .colors import (DEFAULT_GRAPH, PRESET_ACCENTS, ZONES, Paint, contrast, preset_paint, sgr16_fg, xterm_index, xterm_rgb,
                     with_alpha)

# name -> (xterm-256 index, 16-colour SGR fg code)
PALETTE = {
    "text": (252, 37), "dim": (245, 90), "faint": (240, 90), "white": (255, 97), "black": (16, 30),
    "green": (42, 92), "red": (203, 91), "yellow": (220, 93), "blue": (75, 94),
    "magenta": (171, 95), "cyan": (45, 96), "amber": (214, 33), "orange": (209, 33),
}
ACCENTS = ("cyan", "green", "magenta", "amber", "blue")

UNICODE = dict(
    h="─", v="│", tl="┌", tr="┐", bl="└", br="┘", lt="├", rt="┤",
    th="═", tv="║", ttl="╔", ttr="╗", tbl="╚", tbr="╝", tlt="╠", trt="╣",
    dot="●", ring="○", cur="▶", bar="▌", full="█", empty="░", slider="━", track="─", thumb="●",
    up="↑", down="↓", left="←", right="→", blocks="▁▂▃▄▅▆▇█", top="▀", ell="…", peak="▏", sep="│",
    sound="♪",
)
ASCII = dict(
    h="-", v="|", tl="+", tr="+", bl="+", br="+", lt="+", rt="+",
    th="=", tv="|", ttl="+", ttr="+", tbl="+", tbr="+", tlt="+", trt="+",
    dot="*", ring="o", cur=">", bar="|", full="#", empty=".", slider="=", track="-", thumb="O",
    up="^", down="v", left="<", right=">", blocks=".:-=+*#@", top="'", ell="~", peak="|", sep="|",
    sound="*",
)


ROUND = dict(tl="╭", tr="╮", bl="╰", br="╯", ttl="╭", ttr="╮", tbl="╰", tbr="╯", th="─", tv="│")   # curvy borders


class Glyphs:
    def __init__(self, table: dict):
        self.__dict__.update(table)


def detect_unicode(setting: str = "auto") -> bool:
    if setting == "unicode":
        return True
    if setting == "ascii":
        return False
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" not in enc and os.name != "nt":
        return False
    return os.environ.get("TERM") != "linux"


def _windows_truecolor() -> bool:
    """Every Windows 10 console since build 15063 (and Windows Terminal) draws 24-bit colour once VT is on."""
    if os.name != "nt":
        return False
    return getattr(getattr(sys, "getwindowsversion", lambda: None)(), "build", 0) >= 15063


def detect_depth(setting: str = "auto") -> str:
    if setting in ("true", "256", "16", "mono"):
        return setting
    if os.environ.get("NO_COLOR"):
        return "mono"
    ct = os.environ.get("COLORTERM", "").lower()
    if ct in ("truecolor", "24bit") or os.environ.get("WT_SESSION") or _windows_truecolor():   # WT sets WT_SESSION
        return "true"
    if os.name == "nt" or "256" in os.environ.get("TERM", "") or ct:
        return "256"
    return "16"


ACC, ON_ACC = "@accent", "@onaccent"        # placeholders in accent-class style templates
STEPS = 48                                  # colour quantisation for gradients / rainbow / fades (bounded style count)
FADE_LEVELS = 8
DEFAULT_FG = (204, 204, 204)                # what "no colour" means when a fade needs a number


class Theme:
    """Style registry. Styles are small ints stored in the canvas; sgr(id) renders the escape code.

    Colours in a style are None, a PALETTE name, or an (r, g, b) tuple. Styles are never mutated or removed,
    so changing the accent / graph paint live only registers new ids (no full-screen repaint needed).
    """

    def __init__(self, accent="cyan", depth: str = "256", unicode_ok: bool = True, graph: Paint | None = None,
                 backdrop: Paint | None = None, rounded: bool = True, glass: bool = False):
        self.depth = depth
        self.rounded = rounded and unicode_ok
        self.g = Glyphs({**UNICODE, **ROUND} if self.rounded else UNICODE if unicode_ok else ASCII)
        self.unicode = unicode_ok
        self.t = 0.0                                      # animation clock (App sets it every frame)
        self._styles: list[tuple] = [(None, None, False, False, False, False)]
        self._index: dict[tuple, int] = {self._styles[0]: 0}
        self._sgr: dict[int, str] = {}
        self._fade: dict[tuple, int] = {}
        self.configure(accent, graph, backdrop, glass)

    # ------------------------------------------------------------ paints
    def configure(self, accent, graph: Paint | None = None, backdrop: Paint | None = None,
                  glass: bool = False) -> None:
        """(Re)build the named styles from the accent + graph (+ optional painted backdrop) paints.
        Safe to call while running."""
        self.backdrop_paint = backdrop
        self.glass = bool(glass and backdrop is not None)      # translucent: shade glyphs, terminal bg stays
        self._glass_sid: dict[int, int] = {}
        self._bgvar: dict[tuple, int] = {}
        if isinstance(accent, str):
            accent = preset_paint(accent if accent in PRESET_ACCENTS else "cyan")
        self.accent_paint: Paint = accent
        self.graph_paint: Paint = graph or DEFAULT_GRAPH.copy()
        self.accent = accent_name(accent)
        self.accent_rgb = accent.color_at(0.0)
        self._tpl: dict[int, tuple] = {}                  # sid -> template with ACC placeholders (recolour pass)
        self._variants: dict[tuple, int] = {}
        self._gcache: dict[tuple, int] = {}
        mono = self.depth == "mono"
        S = self.style

        def A(fg=None, bg=None, **fl):
            sid = S(self._sub(fg), self._sub(bg), **fl)
            if ACC in (fg, bg) or ON_ACC in (fg, bg):
                self._tpl[sid] = (fg, bg, fl)
            return sid

        self.text = 0
        self.dim = S("dim")
        self.faint = S("faint")
        self.bold = S("white", bold=True)
        self.title = A(ACC, bold=True)
        self.border = S("faint")
        self.border_focus = A(ACC)
        self.sel = A(ON_ACC, ACC, bold=True, reverse=mono)    # focused row: solid accent bar
        self.sel_dim = S("white", None, bold=True)
        self.accent_s = A(ACC)
        self.accent_b = A(ACC, bold=True)
        self.key = A(ACC, bold=True)
        self.on = S("green", bold=True)
        self.off = S("dim")
        self.ok = S("green")
        self.warn = S("yellow", bold=True)
        self.err = S("red", bold=True)
        self.info = S("blue")
        self.sound = S("magenta", bold=True)
        self.m_empty = S("faint")
        self.thumb = S("white", bold=True)
        self.tab_on = A(ON_ACC, ACC, bold=True, reverse=mono)
        self.tab_off = S("dim")
        self.header = S("white", bold=True)
        self.m_green, self.m_yellow, self.m_red = self.graph_style(0.0), self.graph_style(0.8), self.graph_style(1.0)

    def _sub(self, c, rgb=None):
        if c == ACC:
            return rgb or self.accent_rgb
        if c == ON_ACC:
            return contrast(rgb or self.accent_rgb)
        return c

    # ------------------------------------------------------------ dynamic styles
    def graph_style(self, level: float, pos: float | None = None) -> int:
        """Style for a meter / waveform cell. level: signal level 0..1; pos: position 0..1 along the graph."""
        p = self.graph_paint
        mode = p.effective_mode()
        pos = level if pos is None else pos
        if mode == "solid":
            key = ("s",)
        elif mode == "zones":
            n = len(p.stops)
            key = ("z", sum(1 for e in ZONES[n] if level >= e))
        elif mode == "gradient":
            key = ("g", int(max(0.0, min(1.0, level)) * (STEPS - 1)))
        else:
            key = ("r", (int((pos % 1.0) * STEPS) + int(p.phase_at(self.t) * STEPS)) % STEPS)
        sid = self._gcache.get(key)
        if sid is None:
            if mode in ("solid", "zones"):
                rgb = p.color_at(0.0, level)
            elif mode == "gradient":
                rgb = p.color_at(key[1] / (STEPS - 1))
            else:
                rgb = p.color_at(key[1] / STEPS)
            sid = self._gcache[key] = self.style(rgb)
        return sid

    @property
    def accent_moves(self) -> bool:
        return self.accent_paint.effective_mode() in ("gradient", "rainbow") and self.depth != "mono"

    @property
    def recolors(self) -> bool:
        return self.accent_moves or (self.backdrop_paint is not None and self.depth != "mono")

    def recolor(self, cv) -> None:
        """Post-process a drawn frame: accent gradient / rainbow (left -> right) for accent-class cells, and the
        painted backdrop (solid, or top -> bottom gradient) behind every cell that has no background."""
        if not self.recolors:
            return
        p, bd = self.accent_paint, self.backdrop_paint
        w, h = cv.w, cv.h
        acc = self.accent_moves and w >= 2
        glass = self.glass and self.depth != "mono" and self.unicode
        bd = bd if (self.depth != "mono" and not self.glass) else None
        gl = self._glass_rows(h) if glass else None
        shift = int(p.phase_at(self.t) * STEPS) if p.mode == "rainbow" else 0
        qs = [((x * STEPS) // w + shift) % STEPS if p.mode == "rainbow" else (x * (STEPS - 1)) // (w - 1)
              for x in range(w)] if acc else None
        rq = [0] * h
        if bd is not None and bd.effective_mode() == "gradient" and h > 1:
            rq = [(y * (STEPS - 1)) // (h - 1) for y in range(h)]
        tpl, var, bgv = self._tpl, self._variants, self._bgvar
        styles = self._styles
        for y, row in enumerate(cv.st):
            bq = rq[y]
            if gl is not None and gl[y][0]:
                glyph, gsid = gl[y]
                chrow = cv.ch[y]
                orig = chrow[:]                      # cells next to text stay clear, so words stay easy to read
                for x in range(w):
                    if orig[x] == " " and (x == 0 or orig[x - 1] == " ") and (x == w - 1 or orig[x + 1] == " "):
                        st = styles[row[x]]
                        if st[1] is None and not st[4]:
                            chrow[x] = glyph
                            row[x] = gsid
            for x in range(w):
                s = row[x]
                if acc and s in tpl:
                    key = (s, qs[x])
                    v = var.get(key)
                    if v is None:
                        v = var[key] = self._variant(s, qs[x])
                    s = row[x] = v
                if bd is not None:
                    key = (s, bq)
                    v = bgv.get(key)
                    if v is None:
                        v = bgv[key] = self._with_bg(s, bq)
                    row[x] = v

    GLASS_GLYPHS = ((88, "\u2588"), (62, "\u2593"), (37, "\u2592"), (8, "\u2591"))      # alpha >= x -> glyph (coverage)

    def _glass_rows(self, h: int) -> list:
        """Per row: (shade glyph, style) so that the cell is covered by `alpha` percent of the backdrop colour and
        the rest stays the terminal's own (blurred) background. Only blank cells are touched."""
        bd = self.backdrop_paint
        grad = bd.effective_mode() == "gradient" and h > 1
        out = []
        for y in range(h):
            q = (y * (STEPS - 1)) // (h - 1) if grad else 0
            rgb, a = bd.rgba_at(q / (STEPS - 1) if grad else 0.0)
            glyph = next((g for lim, g in self.GLASS_GLYPHS if a >= lim), "")
            key = (rgb, glyph)
            sid = self._glass_sid.get(key) if glyph else 0
            if glyph and sid is None:
                sid = self._glass_sid[key] = self.style(rgb)
            out.append((glyph, sid))
        return out

    def backdrop_rgb(self, q: int = 0):
        bd = self.backdrop_paint
        if bd is None:
            return None
        return bd.color_at(q / (STEPS - 1)) if bd.effective_mode() == "gradient" else bd.color_at(0.0)

    def _with_bg(self, sid: int, q: int) -> int:
        fg, bg, bold, dim, rev, ul = self._styles[sid]
        if bg is not None or rev:
            return sid
        return self.style(fg, self.backdrop_rgb(q), bold, dim, rev, ul)

    def _variant(self, sid: int, q: int) -> int:
        fg, bg, fl = self._tpl[sid]
        p = self.accent_paint
        rgb = p.color_at(q / STEPS) if p.mode == "rainbow" else p.color_at(q / (STEPS - 1))
        if fg == ON_ACC and bg == ACC:
            f, b = contrast(rgb), rgb
        else:
            f, b = self._sub(fg, rgb), self._sub(bg, rgb)
        return self.style(f, b, **fl)

    # ------------------------------------------------------------ colour resolution
    def to_rgb(self, c, default=None):
        if c is None:
            return default
        if isinstance(c, tuple):
            return c
        return xterm_rgb(PALETTE[c][0])

    def style_rgb(self, sid: int):
        """-> (fg rgb|None, bg rgb|None, bold, dim, reverse, underline) with palette names resolved."""
        fg, bg, bold, dim, rev, ul = self._styles[sid]
        return self.to_rgb(fg), self.to_rgb(bg), bold, dim, rev, ul

    def fade_style(self, sid: int, level: float) -> int:
        """The style `sid` mixed with black. level 1 = unchanged, 0 = black (quantised to a few steps)."""
        q = int(round(max(0.0, min(1.0, level)) * (FADE_LEVELS - 1)))
        if q >= FADE_LEVELS - 1:
            return sid
        key = (sid, q)
        r = self._fade.get(key)
        if r is None:
            fg, bg, bold, dim, rev, ul = self._styles[sid]
            a = q / (FADE_LEVELS - 1) * 100
            f = with_alpha(self.to_rgb(fg, DEFAULT_FG), a)
            b = with_alpha(self.to_rgb(bg), a) if bg else None
            r = self._fade[key] = self.style(f, b, bold, dim, rev, ul)
        return r

    def style(self, fg=None, bg=None, bold=False, dim=False, reverse=False, underline=False) -> int:
        t = (fg, bg, bold, dim, reverse, underline)
        if t not in self._index:
            self._index[t] = len(self._styles)
            self._styles.append(t)
        return self._index[t]

    def _code(self, c, bg: bool) -> str:
        d = self.depth
        if isinstance(c, tuple):
            if d == "true":
                return f"{48 if bg else 38};2;{c[0]};{c[1]};{c[2]}"
            if d == "256":
                return f"{48 if bg else 38};5;{xterm_index(c)}"
            return str(sgr16_fg(c) + (10 if bg else 0))
        if d in ("true", "256"):
            return f"{48 if bg else 38};5;{PALETTE[c][0]}"
        return str(PALETTE[c][1] + (10 if bg else 0))

    def sgr(self, sid: int) -> str:
        s = self._sgr.get(sid)
        if s is None:
            fg, bg, bold, dim, reverse, underline = self._styles[sid]
            codes = ["0"]
            if bold:
                codes.append("1")
            if dim:
                codes.append("2")
            if underline:
                codes.append("4")
            if reverse:
                codes.append("7")
            if self.depth != "mono":
                if fg:
                    codes.append(self._code(fg, False))
                if bg:
                    codes.append(self._code(bg, True))
            elif bg and not reverse:      # mono: a background means "highlight"
                codes.append("7")
            s = self._sgr[sid] = "\x1b[" + ";".join(codes) + "m"
        return s


def accent_name(p: Paint) -> str:
    """Preset name when the accent is exactly a preset, else 'custom'."""
    if p.mode == "solid" and p.stops[0][1] == 100:
        for k, v in PRESET_ACCENTS.items():
            if v == p.stops[0][0]:
                return k
    return "custom"

"""Colour editor. Left: grouped controls (style, hue / saturation / brightness, RGB + hex, alpha).
Centre: a colour field (saturation x brightness), the hue bar and the gradient strip with its colour markers.
Right: a live example of what you are editing (UI window, volume graph or backdrop).
Every change is live and saved at once. Controls: Up/Down = row, Left/Right = change, Enter = activate."""
from __future__ import annotations

import math

from ..canvas import Rect, fit
from ..colors import (MAX_STOPS, Paint, contrast, hex_to_rgb, hsv_to_rgb, lerp, rgb_to_hex, rgb_to_hsv, with_alpha)
from ..modals import Prompt
from ..widgets import ListState, meter, waveform
from .base import BaseScreen

MODE_NAMES = {"solid": "Solid", "zones": "Zones", "gradient": "Gradient", "rainbow": "Rainbow"}
MODES_FOR = {"accent": ("solid", "gradient", "rainbow"), "graph": ("zones", "solid", "gradient", "rainbow"),
             "backdrop": ("solid", "gradient")}
TITLES = {"accent": "MAIN COLOR", "graph": "VOLUME GRAPH COLORS", "backdrop": "BACKDROP"}
DARK = (18, 18, 22)
SECTION = {"mode": "STYLE", "stop": "STYLE", "add": "STYLE", "del": "STYLE", "speed": "STYLE",
           "hue": "COLOR", "sat": "COLOR", "val": "COLOR", "red": "RGB", "green": "RGB", "blue": "RGB",
           "hex": "RGB", "alpha": "OPACITY", "reset": ""}
LABEL = {"mode": "Mode", "stop": "Colour", "add": "+ Add", "del": "- Remove", "speed": "Speed", "hue": "Hue",
         "sat": "Saturation", "val": "Brightness", "red": "Red", "green": "Green", "blue": "Blue", "hex": "Hex",
         "alpha": "Alpha", "reset": "Reset"}


class ColorEditor(BaseScreen):
    def __init__(self, app, target: str = "accent"):
        super().__init__(app)
        self.target = target
        self.sel = ListState()
        self.paint: Paint = app.paint_of(target).copy()
        self.si = 0
        self._hsv = None            # (h, s, v) cache so hue / saturation survive grey and black

    # ------------------------------------------------------------------ model
    @property
    def rainbow(self) -> bool:
        return self.paint.mode == "rainbow"

    @property
    def multi(self) -> bool:
        return self.paint.mode in ("zones", "gradient")

    def _rgb(self) -> tuple:
        return hex_to_rgb(self.paint.stops[self.si][0])

    def hsv(self) -> tuple:
        rgb = self._rgb()
        if self._hsv is None or hsv_to_rgb(*self._hsv) != rgb:
            h, s, v = rgb_to_hsv(rgb)
            if self._hsv is not None:
                if s < 0.5 or v < 0.5:
                    h = self._hsv[0]
                if v < 0.5:
                    s = self._hsv[1]
            self._hsv = (h, s, v)
        return self._hsv

    def _store(self, rgb) -> None:
        self.paint.stops[self.si][0] = rgb_to_hex(rgb)
        self._commit()

    def _commit(self) -> None:
        if self.target == "backdrop":
            for s in self.paint.stops:
                s[1] = 100
        self.app.apply_paint(self.target, self.paint)

    def set_hsv(self, h=None, s=None, v=None) -> None:
        ch, cs, cv_ = self.hsv()
        nh = ch if h is None else h % 360
        ns = cs if s is None else max(0, min(100, s))
        nv = cv_ if v is None else max(0, min(100, v))
        self._hsv = (nh, ns, nv)
        self._store(hsv_to_rgb(nh, ns, nv))

    def set_channel(self, i: int, value: int) -> None:
        rgb = list(self._rgb())
        rgb[i] = max(0, min(255, int(value)))
        self._store(tuple(rgb))

    def set_alpha(self, a: int) -> None:
        self.paint.stops[self.si][1] = max(0, min(100, int(a)))
        self._commit()

    def set_mode(self, mode: str) -> None:
        p = self.paint
        p.mode = mode
        want = {"zones": 3 if len(p.stops) < 3 else len(p.stops), "gradient": 2}.get(mode, 1)
        while len(p.stops) < want:
            h, s, v = rgb_to_hsv(hex_to_rgb(p.stops[-1][0]))
            p.stops.append([rgb_to_hex(hsv_to_rgb(h + 70, max(s, 60), max(v, 70))), p.stops[-1][1]])
        if mode == "rainbow":
            self.si = 0
            h, s, v = rgb_to_hsv(hex_to_rgb(p.stops[0][0]))
            if s < 40 or v < 40:
                p.stops[0][0] = rgb_to_hex(hsv_to_rgb(h, max(s, 85), max(v, 100)))
        self.si = min(self.si, len(p.stops) - 1)
        self._hsv = None
        self._commit()

    def add_stop(self) -> None:
        p = self.paint
        if len(p.stops) >= MAX_STOPS:
            self.app.notify("info", f"At most {MAX_STOPS} colours")
            return
        h, s, v = rgb_to_hsv(hex_to_rgb(p.stops[-1][0]))
        p.stops.append([rgb_to_hex(hsv_to_rgb(h + 50, max(s, 60), max(v, 70))), p.stops[-1][1]])
        self.si = len(p.stops) - 1
        self._hsv = None
        self._commit()

    def del_stop(self) -> None:
        p = self.paint
        if len(p.stops) <= 2:
            self.app.notify("info", "Need at least 2 colours for this mode")
            return
        del p.stops[self.si]
        self.si = min(self.si, len(p.stops) - 1)
        self._hsv = None
        self._commit()

    def reset(self) -> None:
        self.paint = (self.app.default_paint(self.target)).copy()
        self.si = 0
        self._hsv = None
        self._commit()

    # ------------------------------------------------------------------ rows
    def rows(self) -> list[str]:
        r = ["mode"]
        if self.rainbow:
            r += ["speed", "sat", "val"]
        else:
            if self.multi:
                r += ["stop", "add", "del"]
            r += ["hue", "sat", "val", "red", "green", "blue", "hex"]
        if self.target != "backdrop":
            r.append("alpha")
        r.append("reset")
        return r

    # ------------------------------------------------------------------ keys
    def on_key(self, key) -> bool:
        n = key.name
        rows = self.rows()
        self.sel.clamp(len(rows))
        row = rows[self.sel.idx]
        if n in ("up", "down"):
            self.sel.move(-1 if n == "up" else 1, len(rows), wrap=True)
            return True
        if n in ("left", "right", "enter"):
            sign = -1 if n == "left" else 1
            self._act(row, sign, enter=(n == "enter"))
            return True
        return False

    def _act(self, row: str, sign: int, enter: bool) -> None:
        p, app = self.paint, self.app
        k = app.accel(100)
        if row == "mode":
            modes = MODES_FOR[self.target]
            i = modes.index(p.mode) if p.mode in modes else 0
            self.set_mode(modes[(i + sign) % len(modes)])
        elif row == "stop":
            self.si = (self.si + sign) % len(p.stops)
            self._hsv = None
        elif row == "hue" and not enter:
            self.set_hsv(h=self.hsv()[0] + sign * 3 * k)
        elif row == "sat" and not enter:
            self.set_hsv(s=self.hsv()[1] + sign * k)
        elif row == "val" and not enter:
            self.set_hsv(v=self.hsv()[2] + sign * k)
        elif row in ("red", "green", "blue") and not enter:
            i = ("red", "green", "blue").index(row)
            self.set_channel(i, self._rgb()[i] + sign * k * 2)
        elif row == "alpha" and not enter:
            self.set_alpha(p.stops[self.si][1] + sign * k)
        elif row == "speed" and not enter:
            p.speed = max(1, min(100, p.speed + sign * k))
            self._commit()
        elif row == "hex" and enter:
            def ok(text):
                self._hsv = None
                self._store(hex_to_rgb(text))

            def check(text):
                try:
                    hex_to_rgb(text)
                    return ""
                except ValueError as e:
                    return str(e)
            app.open_modal(Prompt("HEX COLOR", "Type 6 hex digits, e.g. #FF8800", rgb_to_hex(self._rgb()), ok, check))
        elif row == "add" and enter:
            self.add_stop()
        elif row == "del" and enter:
            self.del_stop()
        elif row == "reset" and enter:
            self.reset()
            app.notify("ok", "Colour reset")

    # ------------------------------------------------------------------ drawing
    def draw(self, cv, r: Rect):
        th = self.th
        inner = cv.box(r, th, TITLES[self.target], True)
        if inner.h < 5 or inner.w < 30:
            return
        wide = inner.w >= 70
        mid = inner.w >= 50
        lw = 32 if wide else 30 if mid else inner.w
        left = Rect(inner.x, inner.y, lw, inner.h)
        self._controls(cv, th, left)
        x = inner.x + lw
        if wide:
            cw = 24
            cv.vline(x, inner.y, inner.h, th.g.v, th.faint)
            self._picker(cv, th, Rect(x + 2, inner.y, cw, inner.h))
            x += cw + 2
        if mid:
            cv.vline(x, inner.y, inner.h, th.g.v, th.faint)
            self._example(cv, th, Rect(x + 2, inner.y, inner.right - x - 3, inner.h))

    # ---- left column
    def _display(self, rows, room):
        out, last = [], None
        for i, name in enumerate(rows):
            sec = SECTION[name]
            if sec and sec != last and room >= len(rows) + 4:
                out.append(("head", sec))
            if sec:
                last = sec
            elif room >= len(rows) + 5 and name == "reset":
                out.append(("head", ""))
            out.append(("row", i))
        return out

    def _controls(self, cv, th, r: Rect) -> None:
        rows = self.rows()
        self.sel.clamp(len(rows))
        disp = self._display(rows, r.h)
        if len(disp) > r.h:
            disp = [d for d in disp if d[0] == "row"]
        fi = next(k for k, d in enumerate(disp) if d == ("row", self.sel.idx))
        tmp = ListState()
        tmp.idx, tmp.top = fi, getattr(self, "_top", 0)
        first, last = tmp.window(len(disp), r.h)
        self._top = tmp.top
        for ri, d in enumerate(disp[first:last]):
            y = r.y + ri
            if d[0] == "head":
                if d[1]:
                    cv.put(r.x + 1, y, d[1], th.dim)
                    cv.hline(r.x + 2 + len(d[1]), y, r.w - 4 - len(d[1]), th.g.h, th.faint)
                continue
            i = d[1]
            foc = i == self.sel.idx
            base = th.sel if foc else th.text
            if foc:
                cv.fill(Rect(r.x, y, r.w - 1, 1), " ", th.sel)
            cv.put(r.x + 1, y, th.g.cur if foc else " ", base)
            name = rows[i]
            lab = LABEL[name]
            if name == "speed" and self.rainbow:
                lab = "Speed"
            lw = 11 if r.w >= 32 else 9
            cv.put(r.x + 3, y, fit(lab, lw - 1), base)
            self._control(cv, th, name, r.x + 3 + lw, y, r.w - 3 - lw - 1, foc)

    def _control(self, cv, th, row: str, x: int, y: int, w: int, foc: bool) -> None:
        p, g = self.paint, th.g
        base = th.sel if foc else th.text
        if row == "mode":
            txt = MODE_NAMES[p.mode]
            cv.put(x, y, f"{g.left} {txt} {g.right}" if foc else f"  {txt}", base)
            return
        if row == "stop":
            cv.put(x, y, fit(f"{self.si + 1} of {len(p.stops)}" + (f" {g.right}" if foc else ""), w), base)
            return
        if row in ("add", "del", "reset"):
            return
        if row == "hex":
            rgb = with_alpha(self._rgb(), p.stops[self.si][1], p.base)
            cv.put(x, y, g.full * 2, th.style(rgb, DARK))
            cv.put(x + 3, y, fit(rgb_to_hex(self._rgb()), w - 3), base)
            return
        h, s, v = self.hsv()
        rgb = self._rgb()
        if row == "speed":
            frac, txt = (p.speed - 1) / 99, f"{p.speed}"
            colour = lambda f: hsv_to_rgb(f * 360, 80, 100)   # noqa: E731
        elif row == "hue":
            frac, txt = h / 360, f"{h:.0f}"
            colour = lambda f: hsv_to_rgb(f * 359, max(s, 35), max(v, 55))   # noqa: E731
        elif row == "sat":
            frac, txt = s / 100, f"{s:.0f}"
            colour = lambda f: hsv_to_rgb(h, f * 100, max(v, 40))             # noqa: E731
        elif row == "val":
            frac, txt = v / 100, f"{v:.0f}"
            colour = lambda f: hsv_to_rgb(h, s, f * 100)                       # noqa: E731
        elif row in ("red", "green", "blue"):
            i = ("red", "green", "blue").index(row)
            frac, txt = rgb[i] / 255, f"{rgb[i]}"

            def colour(f, i=i):
                c = list(rgb)
                c[i] = int(f * 255)
                return tuple(c)
        else:   # alpha
            a = p.stops[self.si][1]
            frac, txt = a / 100, f"{a}%"
            colour = lambda f: with_alpha(rgb, f * 100, p.base)                # noqa: E731
        sw = max(5, w - len(txt) - 2)
        pos = int(round(max(0.0, min(1.0, frac)) * (sw - 1)))
        bg = DARK if foc else None
        for i in range(sw):
            f = i / (sw - 1)
            if i == pos:
                cv.put(x + i, y, g.thumb, th.style((255, 255, 255), bg, True))
            else:
                cv.put(x + i, y, g.slider if i < pos else g.track, th.style(colour(f), bg))
        cv.put(x + sw + 1, y, txt, base)

    # ---- centre column: the colour field
    def _picker(self, cv, th, r: Rect) -> None:
        p, g = self.paint, th.g
        cv.put(r.x, r.y, "COLOR FIELD", th.dim)
        if p.mode == "rainbow":
            cv.put(r.x + 12, r.y, "(rainbow)", th.faint)
        h, s, v = self.hsv()
        fh = max(4, min(12, r.h - 8 - (3 if self.multi else 0)))
        fw = r.w
        top = r.y + 1
        # saturation (left -> right) x brightness (bottom -> top); two samples per cell with the half block
        for cy in range(fh):
            for cx in range(fw):
                sa = cx / (fw - 1) * 100
                if th.unicode:
                    v1 = 100 - (cy * 2) / (fh * 2 - 1) * 100
                    v2 = 100 - (cy * 2 + 1) / (fh * 2 - 1) * 100
                    cv.put(r.x + cx, top + cy, "▀", th.style(hsv_to_rgb(h, sa, v1), hsv_to_rgb(h, sa, v2)))
                else:
                    vm = 100 - (cy + 0.5) / fh * 100
                    cv.put(r.x + cx, top + cy, " ", th.style(None, hsv_to_rgb(h, sa, vm)))
        mx = int(round(s / 100 * (fw - 1)))
        my = int(round((100 - v) / 100 * (fh - 1)))
        under = hsv_to_rgb(h, s, v)
        cv.put(r.x + mx, top + my, "+" if not th.unicode else "◆", th.style(contrast(under), under, True))
        y = top + fh
        cv.put(r.x, y, "HUE", th.dim)
        y += 1
        for cx in range(fw):
            cv.put(r.x + cx, y, g.full if th.unicode else "#", th.style(hsv_to_rgb(cx / (fw - 1) * 359, 100, 100)))
        hx = int(round(h / 359 * (fw - 1)))
        cv.put(r.x + hx, y + 1, "▲" if th.unicode else "^", th.style((255, 255, 255), None, True))
        y += 3
        if self.multi and y + 3 <= r.bottom:
            cv.put(r.x, y, "ZONES" if p.mode == "zones" else "GRADIENT", th.dim)
            y += 1
            pa = p.copy()
            for cx in range(fw):
                pos = cx / (fw - 1)
                cv.put(r.x + cx, y, g.full if th.unicode else "#", th.style(pa.color_at(pos, pos)))
            n = len(p.stops)
            for i in range(n):
                mxp = int(round(i / (n - 1) * (fw - 1)))
                on = i == self.si
                cv.put(min(r.x + fw - 1, r.x + mxp), y + 1, str(i + 1), th.sel if on else th.dim)
        elif p.mode == "rainbow" and y + 2 <= r.bottom:
            cv.put(r.x, y, "RAINBOW", th.dim)
            ph = p.phase_at(th.t)
            for cx in range(fw):
                cv.put(r.x + cx, y + 1, g.full if th.unicode else "#", th.style(p.color_at(cx / (fw - 1), phase=ph)))

    # ---- right column: live example
    def _example(self, cv, th, r: Rect) -> None:
        g = th.g
        cv.put(r.x, r.y, "EXAMPLE", th.dim)
        cv.put(r.x + 8, r.y, "(live)", th.faint)
        if r.w < 16 or r.h < 7:
            return
        y = r.y + 1
        if self.target == "graph":
            self._graph_example(cv, th, Rect(r.x, y, r.w, r.h - 1))
            return
        # a miniature window drawn with the real theme
        bh = min(9, r.h - 1 - (5 if r.h >= 17 else 0))
        box = Rect(r.x, y, r.w, bh)
        inner = cv.box(box, th, "SOUNDS", True)
        rows = (("Airhorn", "ALT", False), ("Bass Drop", "F8", True), ("Vine Boom", "F7", False),
                ("Donation", "-", False))
        for i, (nm, kb, foc) in enumerate(rows[:max(0, inner.h - 2)]):
            yy = inner.y + i
            if foc:
                cv.fill(Rect(inner.x, yy, inner.w, 1), " ", th.sel)
            cv.put(inner.x + 1, yy, g.cur if foc else " ", th.sel if foc else th.text)
            cv.put(inner.x + 3, yy, fit(nm, inner.w - 9), th.sel if foc else th.text)
            cv.put(inner.right - 5, yy, fit(kb, 4), th.sel if foc else th.accent_s)
        yy = inner.bottom - 1
        if inner.h >= 3:
            cv.put(inner.x + 1, yy, " TAB ", th.tab_on)
            cv.put(inner.x + 7, yy, "[ OK ]", th.accent_s)
            cv.put(inner.x + 14, yy, g.slider * 2 + g.thumb, th.accent_b)
        y += bh + 1
        if r.h >= 17 and y + 4 <= r.bottom:
            self._see_through(cv, th, Rect(r.x, y, r.w, 4))

    def _see_through(self, cv, th, r: Rect) -> None:
        """Alpha demo over a checkerboard: left = opaque, right = at the current alpha."""
        p = self.paint
        base_rgb = self._rgb()
        a = p.stops[self.si][1]
        cv.put(r.x, r.y, "OPACITY", th.dim)
        cv.put(r.x + 8, r.y, f"{a}%", th.bold)
        for ry in range(2):
            for cx in range(r.w):
                chk = (200, 200, 205) if ((cx // 2) + ry) % 2 == 0 else (70, 70, 78)
                half = cx < r.w // 2
                col = lerp(chk, base_rgb, 1.0 if half else a / 100)
                cv.put(r.x + cx, r.y + 1 + ry, " ", th.style(None, col))
        cv.put(r.x, r.y + 3, "solid", th.faint)
        cv.put(r.x + r.w // 2, r.y + 3, fit("see-through", r.w - r.w // 2), th.faint)

    def _graph_example(self, cv, th, r: Rect) -> None:
        import numpy as np
        t = th.t
        cv.put(r.x, r.y, "OUT", th.dim)
        w = max(6, r.w - 4)
        lv = [0.9, 0.35 + 0.3 * math.sin(t * 1.4), 0.08]
        y = r.y
        for i, l in enumerate(lv):
            if y + i >= r.bottom:
                return
            cv.put(r.x, y + i, ("OUT", "SPK", "MIC")[i], th.dim)
            meter(cv, th, r.x + 4, y + i, w, max(0.001, l) ** 1.6, 0.0)
        n = 96
        k = np.arange(n)
        env = np.abs(np.sin(k / 9.0 + t * 0.8)) * (0.35 + 0.65 * np.abs(np.sin(k / 31.0)))
        hist = np.stack([-env, env], 1).astype(np.float32)
        wy = y + 4
        if wy + 3 <= r.bottom:
            waveform(cv, th, Rect(r.x, wy, r.w, min(7, r.bottom - wy)), hist)

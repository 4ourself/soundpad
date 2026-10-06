"""Boot / home screen: live startup status + main menu."""
from __future__ import annotations

from ..canvas import Rect, fit
from ..logo import TAGLINES, draw_logo, logo_size
from ..widgets import ListState, dot
from .base import BaseScreen

MENU = (("Sounds", "sounds"), ("Customize", "customize"), ("Settings", "settings"),
        ("Help & diagnostics", "help"), ("Exit", None))
SPIN = "|/-\\"
NAME = "soundpad"


class HomeScreen(BaseScreen):
    def __init__(self, app):
        super().__init__(app)
        self.sel = ListState()

    def _rows(self):
        """[(label, state, text, detail)] state: ok|warn|bad|off|run|wait"""
        b, eng = self.app.boot, self.ctl.engine
        t = {"ok": "READY", "warn": "ATTENTION", "bad": "ERROR", "off": "OFF"}

        def gen(key, label, ok_text):
            s = b.status[key]
            if s == "pending":
                return (label, "wait", "WAITING", "")
            if s == "run":
                return (label, "run", "STARTING", "")
            return (label, s, ok_text if s == "ok" else t[s], b.detail[key])
        rows = [gen("config", "Configuration", "LOADED"), gen("devices", "Audio devices", "DETECTED"),
                gen("engine", "Audio engine", "READY")]
        if b.status["engine"] in ("ok", "bad") or eng.state != "STARTING":
            names = {"output": "Output", "speaker": "Speaker"}
            for role in ("output", "speaker"):
                h = eng.health[role]
                st = {"ok": ("ok", "DETECTED"), "disconnected": ("bad", "DISCONNECTED"),
                      "disabled": ("off", "DISABLED"), "init": ("off", "-")}[h["state"]]
                rows.append((names[role], st[0], st[1], h["name"] or h["error"]))
        rows += [gen("sounds", "Sound library", "LOADED"), gen("keyboard", "Global keyboard", "ACTIVE")]
        return rows

    def on_show(self) -> None:
        self._t0 = None                       # restart the logo reveal

    # ------------------------------------------------------------------ title screen
    def _draw_splash(self, cv, r) -> None:
        th, app = self.th, self.app
        t = th.t
        if getattr(self, "_t0", None) is None:
            self._t0 = t
        reveal = (t - self._t0) / 0.9
        lw, lh = logo_size(NAME)
        full = r.w >= lw + 2 and r.h >= lh + 8
        mode = app.cfg.get("ui.logo_glow") or "sometimes"
        block = (lh if full else 1) + 6
        y = r.y + max(0, (r.h - block) // 2)
        if full:
            draw_logo(cv, th, NAME, r.x + (r.w - lw) // 2, y, t, mode, reveal)
            y += lh + 1
        else:
            word = " ".join(NAME.upper())
            shown = word[: int(len(word) * max(0.0, min(1.0, reveal))) + 1]
            cv.put(r.x + (r.w - len(word)) // 2, y, shown, th.title)
            y += 2
        tag = TAGLINES[NAME]
        cv.put(r.x + (r.w - len(tag)) // 2, y, tag, th.dim)
        y += 2
        pulse = 0.5 + 0.5 * __import__("math").sin(t * 3.0)
        txt = "PRESS ENTER"
        cv.put(r.x + (r.w - len(txt)) // 2, y, txt, th.accent_b if pulse > 0.35 else th.accent_s)
        y += 2
        b = app.boot
        if not b.done:
            st, sty = "starting...", th.warn
        elif any(v in ("bad", "warn") for v in b.status.values()):
            st, sty = "attention - details in the menu", th.warn
        else:
            st, sty = "ready", th.ok
        line = f"{th.g.dot} {st}"
        cv.put(r.x + (r.w - len(line)) // 2, y, line, sty)

    def draw(self, cv, r):
        th = self.th
        if self.app.splash:
            self._draw_splash(cv, r)
            return
        W = min(64, r.w - 2)
        rows = self._rows()
        need_menu = len(MENU) + 2
        avail = r.h - 2 - need_menu - 1
        if avail < len(rows):                   # compact: drop the least important rows first
            drop = [l for l in ("Configuration", "Audio devices") if avail < len(rows)]
            rows = [x for x in rows if x[0] not in drop][:max(0, avail)]
        H = min(r.h, len(rows) + need_menu + 4 + (1 if rows else 0))
        pos = self.app.menu_position()
        bx = r.x + 1 if pos == "left" else r.right - W - 1 if pos == "right" else r.x + (r.w - W) // 2
        box = Rect(max(r.x, bx), r.y + max(0, (r.h - H) // 2), W, H)
        inner = cv.box(box, th, "soundpad  -  background soundboard", True, double=True)
        y = inner.y
        if rows:
            y += 1
        for label, state, text, detail in rows:
            if y >= inner.bottom - need_menu - 1:
                break
            cv.put(inner.x + 2, y, label, th.text)
            x = inner.x + 22
            if state in ("run", "wait"):
                cv.put(x, y, SPIN[self.app.frame // 3 % 4] if state == "run" else th.g.ring,
                       th.warn if state == "run" else th.off)
            else:
                dot(cv, th, x, y, state)
            st = {"ok": th.ok, "warn": th.warn, "bad": th.err, "off": th.off, "run": th.warn,
                  "wait": th.off}[state]
            cv.put(x + 2, y, text, st)
            cv.put(x + 16, y, fit(detail, inner.right - x - 17), th.dim)
            y += 1
        y = inner.bottom - need_menu
        cv.hline(inner.x + 1, y, inner.w - 2, th.g.h, th.faint)
        y += 1
        ready = self.app.boot.done
        self.sel.clamp(len(MENU))
        for i, (label, _) in enumerate(MENU):
            foc = i == self.sel.idx
            if foc:
                cv.fill(Rect(inner.x + 1, y, inner.w - 2, 1), " ", th.sel)
            enabled = ready or label == "Exit"
            cv.put(inner.x + 3, y, (th.g.cur + " " if foc else "  ") + label,
                   th.sel if foc else (th.text if enabled else th.faint))
            y += 1

    def on_key(self, key) -> bool:
        n = key.name
        if self.app.splash:                   # title screen: Enter continues (Backspace = quit dialog)
            if n == "enter":
                self.app.enter_menu()
                return True
            return False
        if n in ("up", "down"):
            self.sel.move(-1 if n == "up" else 1, len(MENU), wrap=True)
        elif n == "enter":
            label, page = MENU[self.sel.idx]
            if page is None:
                self.app.confirm_quit()
            elif self.app.boot.done:
                self.app.goto(page)
        else:
            return False
        return True

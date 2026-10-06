"""Sounds screen: the sound list, a live KEYS recorder panel and playback.

Only CONTROLS the Soundpad: the sound worker and the global key hook keep running while this screen
is not visible (and while the terminal is minimized)."""
from __future__ import annotations

import time

from ..canvas import Rect, fit
from ..modals import Prompt
from ..widgets import ListState, db_text, meter, scrollbar, slider, waveform
from .base import BaseScreen


def mid_trunc(s: str, w: int) -> str:
    if len(s) <= w:
        return s
    keep = max(1, w - 1)
    return s[: keep // 3] + "…" + s[-(keep - keep // 3):]


class SoundsScreen(BaseScreen):
    ACTIONS = 2                    # list rows before the sounds: [+ Load folder or file] [Stop all]

    def __init__(self, app):
        super().__init__(app)
        self.sel = ListState()
        self.loading = ""

    def sounds(self):
        return self.ctl.sounds()

    def selected(self):
        s = self.sounds()
        i = self.sel.idx - self.ACTIONS
        return s[i] if s and 0 <= i < len(s) else None

    # ------------------------------------------------------------------ draw
    def draw(self, cv, r: Rect):
        pos = self.app.graph_position()               # where the LEVELS graph sits: left | center | right
        if r.w >= 92:
            sel_h = 9 if r.h >= 22 else 8
            pb_h = 5 if r.h >= 22 else 4
            if pos == "center" and r.w >= 112:        # list | levels + playback | selected + keys
                gw, iw = 34, 38
                lw = r.w - gw - iw - 2
                gx, ix = r.x + lw + 1, r.x + lw + gw + 2
                self._list(cv, Rect(r.x, r.y, lw, r.h), meters=False)
                self._levels(cv, Rect(gx, r.y, gw, r.h - pb_h))
                self._playback(cv, Rect(gx, r.bottom - pb_h, gw, pb_h))
                self._selected(cv, Rect(ix, r.y, iw, sel_h))
                self._keys(cv, Rect(ix, r.y + sel_h, iw, r.h - sel_h))
                return
            rw = 42
            gh = 8 if r.h >= 26 else 7 if r.h >= 22 else 0     # no room on a 24-row screen: meters stay in the list
            lx, sx = (r.x + rw + 1, r.x) if pos == "left" else (r.x, r.right - rw)
            self._list(cv, Rect(lx, r.y, r.w - rw - 1, r.h), meters=gh == 0)
            y = r.y
            self._selected(cv, Rect(sx, y, rw, sel_h))
            y += sel_h
            self._keys(cv, Rect(sx, y, rw, max(0, r.h - sel_h - pb_h - gh)))
            y += max(0, r.h - sel_h - pb_h - gh)
            if gh:
                self._levels(cv, Rect(sx, y, rw, gh))
            self._playback(cv, Rect(sx, r.bottom - pb_h, rw, pb_h))
        else:
            kh = 7 if r.h >= 18 else 6 if r.h >= 15 else 0
            self._list(cv, Rect(r.x, r.y, r.w, r.h - kh))
            if kh:
                self._keys(cv, Rect(r.x, r.bottom - kh, r.w, kh))

    def _status(self, s, playing):
        th = self.th
        if s.id in playing:
            return "PLAYING", th.sound
        if s.state == "error":
            return "ERROR", th.err
        if s.state in ("loading", "unloaded"):
            return "LOADING", th.warn
        return ("STREAM" if s.streaming else "READY"), th.ok

    def _list(self, cv, rect: Rect, meters: bool = True):
        th, ctl = self.th, self.ctl
        inner = cv.box(rect, th, "SOUNDS", True, right_title=f"{len(self.sounds())} sounds")
        foot = 3 if inner.h >= 8 else 0
        listh = inner.h - foot
        sounds = self.sounds()
        playing = ctl.soundpad.player.active_ids()
        total = len(sounds) + self.ACTIONS
        self.sel.clamp(total)
        first, last = self.sel.window(total, listh)
        showstat = inner.w >= 52
        cols = (inner.w - 2) - 2 - 2 - 16 - 6 - (9 if showstat else 0)
        for row, i in enumerate(range(first, last)):
            y, foc = inner.y + row, i == self.sel.idx
            base = th.sel if foc else th.text
            if foc:
                cv.fill(Rect(inner.x, y, inner.w, 1), " ", th.sel)
            cv.put(inner.x + 1, y, th.g.cur if foc else " ", base)
            if i < self.ACTIONS:
                if i == 0:
                    label = "+ Load folder or file" + (f"   {self.loading}" if self.loading else "")
                else:
                    label = ("■" if th.unicode else "#") + " Stop all sounds"
                cv.put(inner.x + 3, y, fit(label, inner.w - 5), th.sel if foc else th.accent_b)
                continue
            s = sounds[i - self.ACTIONS]
            if s.id in playing:
                cv.put(inner.x + 3, y, th.g.sound, th.sel if foc else th.sound)
            x = inner.x + 5
            cv.put(x, y, fit(s.name, max(4, cols)), base)
            x += max(4, cols) + 1
            cv.put(x, y, fit(s.keybind or "-", 15), th.sel if foc else (th.accent_s if s.keybind else th.faint))
            x += 16
            cv.put(x, y, f"{s.volume * 100:>4.0f}%", base)
            x += 6
            if showstat:
                txt, st = self._status(s, playing)
                cv.put(x, y, txt, th.sel if foc else st)
        if not sounds and listh > self.ACTIONS + 2:
            cv.put(inner.x + 3, inner.y + self.ACTIONS + 1, "No sounds yet - load a folder to begin.", th.faint)
        scrollbar(cv, th, inner.right - 1, inner.y, listh, first, last, total)
        if foot:
            eng, y = ctl.engine, inner.bottom - 3
            cv.hline(inner.x + 1, y, inner.w - 2, th.g.h, th.faint)
            half = (inner.w - 2) // 2
            for k, (label, role) in enumerate((("Output", "output"), ("Speaker", "speaker"))):
                h = eng.health[role]
                x = inner.x + 1 + k * half
                x += cv.put(x, y + 1, label + ": ", th.dim)
                name = h["name"] or ("off" if h["state"] == "disabled" else "DISCONNECTED")
                ok = h["state"] in ("ok", "disabled")
                cv.put(x, y + 1, fit(name, max(4, half - len(label) - 4)), th.text if ok else th.err)
            if meters:
                m = self.app.meters
                mw = max(4, half - 8)
                for k, (label, key) in enumerate((("OUT", "out"), ("SPK", "spk"))):
                    x = inner.x + 1 + k * half
                    cv.put(x, y + 2, label, th.dim)
                    meter(cv, th, x + 4, y + 2, mw, m.level(key), m.peak(key))
            else:
                cv.put(inner.x + 1, y + 2, fit("Levels: see the LEVELS panel", inner.w - 2), th.faint)

    def _levels(self, cv, rect: Rect):
        """Volume graph: Output + Speaker meters and the output waveform (colours: Settings > Colors)."""
        th, ctl, m = self.th, self.ctl, self.app.meters
        inner = cv.box(rect, th, "LEVELS")
        if inner.h < 1:
            return
        hs = ctl.engine.health
        lab = 5
        bw = max(4, inner.w - lab - 10)
        y = inner.y
        for label, key, role in (("OUT", "out", "output"), ("SPK", "spk", "speaker")):
            if y >= inner.bottom:
                return
            cv.put(inner.x + 1, y, label, th.dim)
            on = hs[role]["state"] == "ok" and (key != "spk" or ctl.engine.hear)
            if on:
                meter(cv, th, inner.x + lab, y, bw, m.level(key), m.peak(key))
                cv.put(inner.x + lab + bw + 1, y, db_text(m.level(key)), th.text)
            else:
                cv.put(inner.x + lab, y, "DISCONNECTED" if hs[role]["state"] == "disconnected"
                       else "OFF", th.err if hs[role]["state"] == "disconnected" else th.off)
            y += 1
        wh = inner.bottom - y
        if wh >= 2:
            waveform(cv, th, Rect(inner.x + 1, y, inner.w - 2, wh), ctl.engine.wave_out.latest(max(64, inner.w * 6)))

    def _selected(self, cv, rect: Rect):
        th = self.th
        inner = cv.box(rect, th, "SELECTED")
        s = self.selected()
        if s is None:
            return
        y = inner.y

        def line(label, value, st=None):
            nonlocal y
            if y < inner.bottom:
                cv.put(inner.x + 1, y, f"{label:<9}", th.dim)
                cv.put(inner.x + 10, y, fit(value, inner.w - 11), st if st is not None else th.text)
                y += 1
        line("Name", s.name, th.bold)
        line("File", mid_trunc(s.file, inner.w - 11))
        line("Key", s.keybind or "(none)", th.accent_b if s.keybind else th.faint)
        if y < inner.bottom:
            cv.put(inner.x + 1, y, "Volume", th.dim)
            sw = inner.w - 10 - 6
            slider(cv, th, inner.x + 10, y, sw, s.volume / 2.0, True)
            cv.put(inner.x + 11 + sw, y, f"{s.volume * 100:.0f}%", th.bold)
            y += 1
        cd = s.cooldown_ms if s.cooldown_ms is not None else self.app.cfg.get("soundpad.cooldown_ms")
        line("Cooldown", f"{cd} ms" + ("" if s.cooldown_ms is not None else " (default)"))
        line("Length", f"{s.duration:.1f} s" + ("  (streamed)" if s.streaming else "") if s.duration else "-")
        txt, st = self._status(s, self.ctl.soundpad.player.active_ids())
        line("Status", txt if s.state != "error" else f"{txt}: {s.error}", st)

    # ------------------------------------------------------------------ live key recorder
    def _keys(self, cv, rect: Rect):
        """What the global hook sees RIGHT NOW: held keys + the last presses, matched sounds highlighted."""
        th, ctl = self.th, self.ctl
        ok = ctl.listener_ok
        inner = cv.box(rect, th, "KEYS", False, right_title="recording" if ok else "no hook")
        if inner.h < 1:
            return
        if not ok:
            cv.put(inner.x + 1, inner.y, fit("Global keyboard hook unavailable - see Help", inner.w - 2), th.err)
            return
        held = ctl.held_keys()
        x = inner.x + 1
        x += cv.put(x, inner.y, "HELD ", th.dim)
        if held:
            for k in held.split("+"):
                x += cv.put(x, inner.y, f" {k} ", th.sel) + 1
        else:
            cv.put(x, inner.y, "-", th.faint)
        now = time.time()
        rows = inner.h - 1
        for i, (t, combo, names) in enumerate(ctl.recent_keys()[:max(0, rows)]):
            y = inner.y + 1 + i
            age = now - t
            hit = bool(names)
            kst = th.accent_b if hit else (th.text if age < 4 else th.faint)
            cv.put(inner.x + 1, y, th.g.dot if hit else " ", th.sound if hit else th.faint)
            cv.put(inner.x + 3, y, fit(combo, 18), kst)
            if hit:
                cv.put(inner.x + 22, y, fit(th.g.right + " " + ", ".join(names), inner.w - 24), th.sound)
            if inner.w > 40:
                cv.put(inner.right - 5, y, f"{min(age, 99):>3.0f}s" if age >= 1 else "  now", th.faint)

    def _playback(self, cv, rect: Rect):
        th, ctl = self.th, self.ctl
        voices = ctl.playing()
        mx = ctl.soundpad.player.max_simultaneous
        inner = cv.box(rect, th, "PLAYBACK", right_title=f"{len([v for v in voices if not v['fading']])}/{mx}")
        if not voices:
            cv.put(inner.x + 1, inner.y, "Nothing playing", th.faint)
            return
        for i, v in enumerate(voices[: inner.h]):
            y = inner.y + i
            cv.put(inner.x + 1, y, th.g.dot if not v["fading"] else th.g.ring, th.sound if not v["fading"] else th.off)
            nw = min(16, max(6, inner.w // 3))
            cv.put(inner.x + 3, y, fit(v["name"], nw), th.text)
            bw = inner.w - 3 - nw - 1 - 5
            if bw >= 4:
                n = int(round(v["progress"] * bw))
                cv.put(inner.x + 4 + nw, y, th.g.full * n, th.sound)
                cv.put(inner.x + 4 + nw + n, y, th.g.empty * (bw - n), th.faint)
                cv.put(inner.right - 5, y, f"{v['progress'] * 100:3.0f}%", th.dim)

    # ------------------------------------------------------------------ loading
    def open_load(self) -> None:
        self.app.open_modal(Prompt("LOAD SOUNDS", "Paste a folder path (or a single audio file):",
                                   on_ok=self._load, path=True, ok="LOAD", width=74,
                                   validator=lambda v: "" if v.strip() else "Paste a path first"))

    def _load(self, text: str) -> None:
        app, ctl = self.app, self.ctl

        def work():
            self.loading = "scanning..."
            try:
                res = ctl.soundpad.load_path(text)
            finally:
                self.loading = ""
            app.notify("ok" if res.added else "warn", res.summary(), 6.0)
            if res.sounds:                                  # jump to the first new sound
                ids = [s.id for s in ctl.sounds()]
                if res.sounds[0].id in ids:
                    self.sel.idx = ids.index(res.sounds[0].id) + self.ACTIONS
        app.bg(work)

    # ------------------------------------------------------------------ keys
    def on_key(self, key) -> bool:
        """Up/Down move. Enter: load / stop-all rows, or play (stop, if already playing) the focused sound.
        Right opens the focused sound's editor (key, volume, cooldown, remove)."""
        n = key.name
        ctl, app = self.ctl, self.app
        s = self.selected()
        total = len(self.sounds()) + self.ACTIONS
        if n in ("up", "down"):
            self.sel.move(-1 if n == "up" else 1, total, wrap=True)
        elif n in ("pgup", "pgdn"):
            self.sel.idx = max(0, min(total - 1, self.sel.idx + (10 if n == "pgdn" else -10)))
        elif n in ("home", "end"):
            self.sel.idx = 0 if n == "home" else total - 1
        elif n == "enter":
            if self.sel.idx == 0:
                self.open_load()
            elif self.sel.idx == 1:
                ctl.stop_all_sounds()
                app.notify("info", "All sounds stopped")
            elif s:
                if s.id in ctl.soundpad.player.active_ids():
                    ctl.soundpad.player.stop_sound(s.id)
                else:
                    ctl.play(s.id)
        elif n == "right" and s:
            from .sound_form import SoundForm
            app.push(SoundForm(app, s))
        else:
            return False
        return True

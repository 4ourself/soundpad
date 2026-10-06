"""Edit one sound: name, key (recorded by pressing it), volume, cooldown, remove."""
from __future__ import annotations

from ..canvas import Rect, fit
from ..modals import Capture, Confirm
from ..widgets import TextInput, button, slider
from .base import BaseScreen
from .sounds import mid_trunc

F_NAME, F_KEY, F_VOL, F_CD, F_SAVE, F_CANCEL, F_REMOVE = range(7)


class SoundForm(BaseScreen):
    def __init__(self, app, sound):
        super().__init__(app)
        self.sound = sound
        cfg_cd = int(app.cfg.get("soundpad.cooldown_ms"))
        self.name = TextInput(sound.name, max_len=40)
        self.keybind = sound.keybind
        self.volume = sound.volume
        self.cooldown = sound.cooldown_ms if sound.cooldown_ms is not None else cfg_cd
        self.focus = F_KEY
        self.error = ""

    def captures_text(self) -> bool:
        return self.focus == F_NAME

    # ------------------------------------------------------------------ draw
    def draw(self, cv, r: Rect):
        th = self.th
        W, H = min(76, r.w), min(19, r.h)
        box = Rect(r.x + (r.w - W) // 2, r.y + max(0, (r.h - H) // 2), W, H)
        inner = cv.box(box, th, "EDIT SOUND", True, double=True)
        x, w = inner.x + 3, inner.w - 6
        y = inner.y + (1 if inner.h > 14 else 0)

        def label(i, text, yy):
            foc = self.focus == i
            cv.put(inner.x + 1, yy, th.g.cur if foc else " ", th.accent_b)
            cv.put(x, yy, text, th.accent_b if foc else th.dim)

        cv.put(x, y, "File", th.dim)
        cv.put(x + 10, y, mid_trunc(self.sound.file, w - 10), th.faint)
        y += 2
        label(F_NAME, "Name", y)
        self.name.draw(cv, th, x + 10, y, w - 10, self.focus == F_NAME)
        y += 2
        label(F_KEY, "Key", y)
        foc = self.focus == F_KEY
        kb = f"[ {self.keybind} ]" if self.keybind else "[ none ]"
        cv.put(x + 10, y, kb, th.sel if foc else (th.accent_b if self.keybind else th.faint))
        y += 2
        label(F_VOL, "Volume", y)
        sw = w - 10 - 8
        slider(cv, th, x + 10, y, sw, self.volume / 2.0, self.focus == F_VOL)
        cv.put(x + 11 + sw, y, f"{self.volume * 100:.0f}%", th.bold)
        y += 2
        label(F_CD, "Cooldown", y)
        slider(cv, th, x + 10, y, sw, self.cooldown / 5000.0, self.focus == F_CD)
        cv.put(x + 11 + sw, y, f"{self.cooldown} ms", th.bold)
        y += 2
        by = min(inner.bottom - 1, y)
        button(cv, th, x + 10, by, "SAVE", self.focus == F_SAVE)
        button(cv, th, x + 20, by, "CANCEL", self.focus == F_CANCEL)
        button(cv, th, x + 32, by, "REMOVE", self.focus == F_REMOVE)
        if self.error:
            cv.put(inner.x + 1, inner.bottom - 1, fit(self.error, inner.w - 2), th.err)

    # ------------------------------------------------------------------ keys
    def _next(self, d):
        self.focus = (self.focus + d) % 7
        self.error = ""

    def on_key(self, key) -> bool:
        """Name: type; Up/Down/Enter change field. Other rows: Up/Down move, Left/Right adjust a slider
        (Left clears the key), Enter activates (record key / Save / Cancel / Remove). Backspace = cancel."""
        n = key.name
        app, f = self.app, self.focus
        if f == F_NAME:
            if n in ("down", "enter"):
                self._next(1)
            elif n == "up":
                self._next(-1)
            else:
                self.name.handle(key)
            return True
        if n == "up":
            self._next(-1)
        elif n == "down":
            self._next(1)
        elif n in ("left", "right") and f in (F_VOL, F_CD):
            sign = 1 if n == "right" else -1
            if f == F_VOL:
                self.volume = round(max(0.0, min(2.0, self.volume + sign * 0.05 * app.accel(40))) * 20) / 20
            else:
                self.cooldown = int(max(0, min(5000, self.cooldown + sign * 50 * app.accel(100))))
        elif n == "left" and f == F_KEY:
            self.keybind = ""
        elif n == "enter":
            if f == F_KEY:
                app.open_modal(Capture("PRESS THE KEY", self._set_key))
            elif f == F_SAVE:
                self._save()
            elif f == F_CANCEL:
                app.pop()
            elif f == F_REMOVE:
                s = self.sound
                app.open_modal(Confirm("REMOVE SOUND", f"Remove '{s.name}' from the list?\n(The file is not deleted.)",
                                       "REMOVE", "KEEP", on_yes=lambda: self._remove(s)))
        else:
            return False                      # Backspace falls through to the global "back"
        return True

    def _remove(self, s) -> None:
        self.ctl.soundpad.remove_sound(s.id)
        self.app.pop()
        self.app.notify("ok", f"Removed {s.name}")

    def _set_key(self, kb: str) -> None:
        self.keybind = kb

    def _save(self) -> None:
        stop_key = self.app.cfg.get("soundpad.stop_all_keybind")
        if self.keybind and stop_key and self.keybind == stop_key:
            self.error, self.focus = f"{self.keybind} is the Stop-all key", F_KEY
            return
        other = self.ctl.keybind_conflict(self.keybind, self.sound.id)
        if other:
            self.app.open_modal(Confirm(
                "KEY ALREADY USED", f"{self.keybind} is assigned to:\n  {other.name}\n\n"
                "Replace removes it from that sound.", "REPLACE", "CANCEL", on_yes=lambda: self._commit(other)))
            return
        self._commit(None)

    def _commit(self, steal_from) -> None:
        sp, app = self.ctl.soundpad, self.app
        name = self.name.value.strip() or self.sound.name
        try:
            if steal_from is not None:
                sp.update_sound(steal_from.id, keybind="")
            default_cd = int(app.cfg.get("soundpad.cooldown_ms"))
            keep_default = self.sound.cooldown_ms is None and self.cooldown == default_cd
            sp.update_sound(self.sound.id, name=name, keybind=self.keybind, volume=self.volume,
                            cooldown_ms=None if keep_default else self.cooldown)
        except (OSError, ValueError, KeyError) as e:
            self.error = str(e)[:80]
            return
        app.pop()
        app.notify("ok", f"Saved '{name}'" + (f"  [{self.keybind}]" if self.keybind else ""))

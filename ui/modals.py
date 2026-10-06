"""Modal dialogs drawn over the current screen. A modal receives ALL keys while it is open."""
from __future__ import annotations

from .canvas import Canvas, Rect, fit
from .widgets import TextInput, button


class Modal:
    title = ""
    width = 56

    def lines(self, th) -> list[tuple[str, int]]:
        return []

    def height(self) -> int:
        return len(self.lines_cache) + 4

    # --- lifecycle
    def on_key(self, app, key) -> None:
        pass

    def tick(self, app) -> None:
        pass

    def draw_extra(self, app, cv: Canvas, inner: Rect) -> None:
        pass

    def draw(self, app, cv: Canvas, area: Rect) -> None:
        th = app.theme
        w = min(self.width, area.w - 2)
        self.lines_cache = self.lines(th)
        h = min(area.h, self.height() + self.extra_rows)
        r = Rect(area.x + (area.w - w) // 2, area.y + max(0, (area.h - h) // 2), w, h)
        cv.fill(r, " ", 0)
        inner = cv.box(r, th, self.title, focused=True, double=True)
        y = inner.y
        for text, st in self.lines_cache:
            cv.put(inner.x + 1, y, fit(text, inner.w - 2), st)
            y += 1
        self.draw_extra(app, cv, Rect(inner.x, y, inner.w, inner.bottom - y))

    extra_rows = 0
    lines_cache: list = []


class Confirm(Modal):
    """Two-button dialog (Replace/Cancel, Delete/Keep, Quit/Stay ...). Backspace = no."""

    def __init__(self, title, message, yes="YES", no="NO", on_yes=None, on_no=None, default_yes=False, warn=False):
        self.title, self.message = title, message.split("\n")
        self.yes, self.no, self.on_yes, self.on_no = yes, no, on_yes, on_no
        self.sel = 0 if default_yes else 1
        self.warn = warn
        self.extra_rows = 2

    def lines(self, th):
        return [("", 0)] + [(m, th.warn if self.warn else th.text) for m in self.message]

    def draw_extra(self, app, cv, inner):
        th = app.theme
        y = inner.bottom - 1
        wy, wn = len(self.yes) + 4, len(self.no) + 4
        x = inner.x + (inner.w - (wy + wn + 3)) // 2
        button(cv, th, x, y, self.yes, self.sel == 0)
        button(cv, th, x + wy + 3, y, self.no, self.sel == 1)

    def on_key(self, app, key):
        if key.name in ("left", "right", "up", "down"):
            self.sel = 1 - self.sel
        elif key.name == "enter":
            app.close_modal()
            cb = self.on_yes if self.sel == 0 else self.on_no
            if cb:
                cb()
        elif key.name == "backspace":
            app.close_modal()
            if self.on_no:
                self.on_no()


class Message(Modal):
    def __init__(self, title, message, level="info"):
        self.title, self.message, self.level = title, message.split("\n"), level
        self.extra_rows = 1

    def lines(self, th):
        st = {"error": th.err, "warn": th.warn}.get(self.level, th.text)
        return [("", 0)] + [(m, st) for m in self.message]

    def draw_extra(self, app, cv, inner):
        button(cv, app.theme, inner.x + (inner.w - 6) // 2, inner.bottom - 1, "OK", True)

    def on_key(self, app, key):
        if key.name in ("enter", "backspace"):
            app.close_modal()


class Prompt(Modal):
    """Single text field with OK / CANCEL buttons below it (up/down to move).
    path=True: a long field for pasted file-system paths with a live FOLDER / FILE / NOT FOUND check."""

    def __init__(self, title, label, initial="", on_ok=None, validator=None, path=False, ok="OK", width=56, new_ok=False):
        self.title, self.label, self.on_ok, self.validator = title, label, on_ok, validator
        self.path, self.ok_label, self.width = path, ok, width
        self.new_ok = new_ok                # path may be a new file (export): NOT FOUND is fine
        self.inp = TextInput(initial, path=path, max_len=400 if path else 40)
        self.error = ""
        self.focus = 0                      # 0 text, 1 OK, 2 CANCEL
        self.extra_rows = 5 if path else 4
        self._probe: tuple[str, str] = ("", "")

    def lines(self, th):
        return [("", 0), (self.label, th.dim)]

    def _kind(self, text: str) -> str:
        """Cached (the field changes rarely; the check must not run 30x per second)."""
        if self._probe[0] != text:
            import os

            from configfile import clean_path
            p = clean_path(text)
            kind = "" if not p else "FOLDER" if os.path.isdir(p) else "FILE" if os.path.isfile(p) else "NOT FOUND"
            self._probe = (text, kind)
        return self._probe[1]

    def draw_extra(self, app, cv, inner):
        th = app.theme
        self.inp.draw(cv, th, inner.x + 1, inner.y, inner.w - 2, self.focus == 0)
        if self.error:
            cv.put(inner.x + 1, inner.y + 1, fit(self.error, inner.w - 2), th.err)
        elif self.path:
            kind = self._kind(self.inp.value)
            st = th.ok if kind in ("FOLDER", "FILE") or (self.new_ok and kind) else th.warn
            if self.new_ok:
                kind = {"NOT FOUND": "NEW FILE", "FILE": "REPLACES EXISTING FILE"}.get(kind, kind)
            if kind:
                cv.put(inner.x + 1, inner.y + 1, kind, st)
        by = inner.bottom - 1
        bx = inner.x + (inner.w - (len(self.ok_label) + 4 + 3 + 10)) // 2
        button(cv, th, bx, by, self.ok_label, self.focus == 1)
        button(cv, th, bx + len(self.ok_label) + 7, by, "CANCEL", self.focus == 2)

    def _submit(self, app):
        err = self.validator(self.inp.value) if self.validator else ""
        if err:
            self.error = err
            return
        app.close_modal()
        if self.on_ok:
            self.on_ok(self.inp.value.strip())

    def on_key(self, app, key):
        n = key.name
        if n == "down" or (n == "right" and self.focus > 0):
            self.focus = min(2, self.focus + 1)
        elif n == "up" or (n == "left" and self.focus > 0):
            self.focus = max(0, self.focus - 1)
        elif n == "enter":
            if self.focus == 2:
                app.close_modal()
            else:
                self._submit(app)
        elif self.focus == 0:
            if n == "backspace" and not self.inp.value:
                app.close_modal()
            else:
                self.inp.handle(key)
                self.error = ""
        elif n == "backspace":
            app.close_modal()


class Capture(Modal):
    """'WAITING FOR KEY...' - captures the next key/combination through the GLOBAL hook, so the terminal's
    own copy of those keystrokes is ignored (and flushed afterwards). ESC alone cancels."""

    def __init__(self, title, on_result, timeout=15.0):
        import time
        self.title, self.on_result = title, on_result
        self.t0, self.timeout = time.monotonic(), timeout
        self.started = False
        self.fallback = None
        self.extra_rows = 4

    def lines(self, th):
        return [("", 0)]

    def _begin(self, app):
        self.started = True
        if app.ctl.listener_ok:
            app.ctl.soundpad.keybinds.begin_capture()
        else:                                       # no global hook: type the name instead
            self.fallback = TextInput("", max_len=30)

    def draw_extra(self, app, cv, inner):
        th = app.theme
        if not self.started:
            self._begin(app)
        y = inner.y
        if self.fallback is not None:
            cv.put(inner.x + 1, y, "No global hook - type it (e.g. CTRL+F6):", th.warn)
            self.fallback.draw(cv, th, inner.x + 1, y + 1, inner.w - 2, True)
        else:
            live, _ = app.ctl.soundpad.keybinds.capture_state()
            text = live or "WAITING FOR KEY..."
            cv.put(inner.x + (inner.w - len(text) - 4) // 2, y, f"[ {text} ]", th.sel if live else th.accent_b)

    def _finish(self, app, result):
        kb = app.ctl.soundpad.keybinds
        if self.fallback is None:
            kb.end_capture()
        app.close_modal()
        app.term.drain_input()
        app.ignore_keys_until = app.now() + 0.25
        if result and result != "ESC":
            self.on_result(result)

    def tick(self, app):
        import time
        if not self.started:
            return
        if self.fallback is None:
            _, res = app.ctl.soundpad.keybinds.capture_state()
            if res:
                self._finish(app, res)
            elif time.monotonic() - self.t0 > self.timeout:
                self._finish(app, None)
                app.notify("warn", "Key capture timed out")

    def on_key(self, app, key):
        if self.fallback is None:
            return                                      # terminal copies of the captured keys are ignored
        if key.name == "backspace" and not self.fallback.value:
            self._finish(app, None)
        elif key.name == "enter":
            from soundpad.keybinds import format_keybind, parse_keybind
            try:
                self._finish(app, format_keybind(parse_keybind(self.fallback.value)))
            except ValueError as e:
                app.notify("error", str(e))
        else:
            self.fallback.handle(key)

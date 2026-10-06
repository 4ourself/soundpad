"""Device management: pick the Output (virtual microphone cable) and the Speaker. Also the first-run setup."""
from __future__ import annotations

from ..canvas import Rect, fit
from ..widgets import ListState, button, dot, scrollbar
from .base import BaseScreen

ROLES = (("output", "OUTPUT", "Output = your virtual microphone (Discord / game hears this)"),
         ("speaker", "SPEAKER", "Speaker = what YOU hear"))


class DevicesScreen(BaseScreen):
    def __init__(self, app, first_run: bool = False):
        super().__init__(app)
        self.first_run = first_run
        self.role = 0
        self.lists = {r[0]: ListState() for r in ROLES}
        self.choices: dict[str, list] = {}
        self._applied = False

    def on_show(self):
        self.reload()
        if self.first_run and not self._applied:
            self._applied = True
            for role, setting in self.ctl.first_run_defaults().items():
                self.ctl.config.set(self.ctl.ROLE_KEY[role], setting)
            self.reload()

    def reload(self):
        for role, *_ in ROLES:
            self.choices[role] = self.ctl.device_choices(role)
            ls = self.lists[role]
            cur = next((i for i, c in enumerate(self.choices[role]) if c.current), 0)
            ls.idx = cur
        self.app.dirty = True

    # ------------------------------------------------------------------ draw
    def _rows_count(self, role):
        return len(self.choices.get(role, [])) + 1          # + [FINISH SETUP] / [REFRESH]

    def draw(self, cv, r: Rect):
        th, ctl = self.th, self.ctl
        status_h = 5 if self.first_run else 4
        title = "FIRST RUN SETUP" if self.first_run else "DEVICE STATUS"
        inner = cv.box(Rect(r.x, r.y, r.w, min(status_h, r.h)), th, title, False)
        y = inner.y
        if self.first_run and inner.h >= 4:
            cv.put(inner.x + 1, y, fit("Output: the virtual cable that acts as your microphone ('CABLE Input'). "
                                       "Speaker: your headphones.", inner.w - 2), th.dim)
            y += 1
        for i, (role, label, _) in enumerate(ROLES):
            if y >= inner.bottom:
                break
            h = ctl.engine.health[role]
            foc = i == self.role
            cfg = ctl.config.get(ctl.ROLE_KEY[role])
            if foc:
                cv.fill(Rect(inner.x, y, inner.w, 1), " ", th.sel)
            cv.put(inner.x + 1, y, (th.g.cur if foc else " ") + " " + label, th.sel if foc else th.dim)
            if self.first_run and not self.app.ctl.engine.running and h["state"] == "init":
                st, txt = ("ok", "default device" if cfg == "default" else "none (disabled)" if cfg == "none" else cfg)
            else:
                st = {"ok": "ok", "disconnected": "bad", "disabled": "off", "init": "off"}[h["state"]]
                txt = h["name"] or ("DISCONNECTED" if st == "bad" else "disabled")
                if st == "bad":
                    txt = f"DISCONNECTED  {h['error']}"
                elif h["index"] is not None:
                    txt += f"   #{h['index']}"
            if foc:
                cv.put(inner.x + 11, y, fit(txt, inner.w - 13), th.sel)
            else:
                dot(cv, th, inner.x + 11, y, st)
                cv.put(inner.x + 13, y, fit(txt, inner.w - 15), th.err if st == "bad" else th.text)
            y += 1
        # list for the active role
        role, label, long = ROLES[self.role]
        lr = Rect(r.x, r.y + min(status_h, r.h), r.w, max(0, r.h - status_h))
        if lr.h < 4:
            return
        inner = cv.box(lr, th, f"SELECT {label}  -  {long}", True)
        items = self.choices[role]
        ls = self.lists[role]
        n = self._rows_count(role)
        ls.clamp(n)
        first, last = ls.window(n, inner.h)
        for row, i in enumerate(range(first, last)):
            y = inner.y + row
            foc = i == ls.idx
            if foc:
                cv.fill(Rect(inner.x, y, inner.w, 1), " ", th.sel)
            if i >= len(items):
                button(cv, th, inner.x + 3, y, "FINISH SETUP  -  START AUDIO" if self.first_run
                       else "REFRESH DEVICES", foc)
                continue
            c = items[i]
            cv.put(inner.x + 1, y, th.g.cur if foc else " ", th.sel if foc else th.text)
            if foc:
                cv.put(inner.x + 3, y, th.g.dot if c.current else th.g.ring, th.sel)
            else:
                cv.put(inner.x + 3, y, th.g.dot if c.current else th.g.ring, th.on if c.current else th.off)
            extra = ""
            if c.index is not None:
                extra = f"#{c.index}"
                if c.samplerate:
                    extra += f"  {c.samplerate:.0f} Hz"
            if c.virtual:
                extra += "  [virtual cable]"
            namew = inner.w - 6 - len(extra) - 2
            cv.put(inner.x + 5, y, fit(c.label, namew), th.sel if foc else (th.text if c.current else th.dim))
            cv.put(inner.right - len(extra) - 1, y, extra, th.sel if foc else (th.accent_s if c.virtual else th.faint))
        scrollbar(cv, th, inner.right - 1, inner.y, inner.h, first, last, n)

    # ------------------------------------------------------------------ keys
    def on_key(self, key) -> bool:
        """Up/Down pick a device (last row = Finish / Refresh), Left/Right switch output/speaker,
        Enter applies, Backspace goes back (during first-run setup it finishes the setup)."""
        n = key.name
        role = ROLES[self.role][0]
        ls = self.lists[role]
        if n in ("up", "down"):
            ls.move(-1 if n == "up" else 1, self._rows_count(role), wrap=True)
        elif n == "right":
            self.role = (self.role + 1) % 2
        elif n == "left":
            self.role = (self.role - 1) % 2
        elif n == "enter":
            items = self.choices[role]
            if ls.idx >= len(items):
                if self.first_run:
                    self._finish()
                else:
                    self.app.notify("info", "Refreshing devices...")
                    self.app.bg(lambda: (self.ctl.refresh_devices(), self.reload()))
            else:
                self._choose(role, items[ls.idx])
        elif n == "backspace" and self.first_run:
            self._finish()
        else:
            return False
        return True

    def _choose(self, role: str, choice) -> None:
        ctl, app = self.ctl, self.app
        if self.first_run:
            ctl.config.set(ctl.ROLE_KEY[role], choice.setting)
            self.reload()
            return
        if role == "output" and not choice.virtual and choice.setting != "none":
            app.notify("warn", "Not a virtual cable - other apps cannot use it as a microphone")
        ctl.config.set(ctl.ROLE_KEY[role], choice.setting)

        def apply():
            ok = ctl.select_device(role, choice.setting)
            self.reload()
            if not ok:
                h = ctl.engine.health[role]
                raise RuntimeError(f"{role.upper()}: {h['error'] or 'could not open device'}")
        app.bg(apply, ok=f"{role.upper()} set to {choice.label}")
        self.reload()

    def _finish(self) -> None:
        app = self.app
        app.pop()
        app.notify("info", "Starting audio...")

        def go():
            self.ctl.config.first_run = False
            self.ctl.config.save()
            self.ctl.engine.start()
            if self.ctl.engine.running:
                app.notify("ok", "Audio engine running")
            else:
                app.notify("error", "Output device could not be opened - see Settings > Devices")
        app.bg(go)

    def captures_text(self) -> bool:
        return False

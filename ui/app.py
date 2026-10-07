"""TUI application shell: one persistent event loop, screen/page navigation, modals, notifications.

Threads
-------
UI thread (this loop)  : input -> state -> draw, ~30 fps, never touches audio buffers.
backend start thread   : runs the boot steps once (so the boot screen animates).
Everything else (audio callbacks, watchdog, sound worker, global key hook) lives in the backend;
the UI only calls Controller methods and reads plain attributes.
"""
from __future__ import annotations

import time
import traceback
from collections import deque
from dataclasses import dataclass

from .canvas import Canvas, Rect, Screen, fit
from . import transitions
from .colors import DEFAULT_BACKDROP, DEFAULT_GRAPH, PRESET_ACCENTS, TERMINAL_BG, Paint, preset_paint
from .keys import Key
from .theme import ACCENTS, Theme, detect_depth, detect_unicode
from .widgets import clamp, dot

PAGES = (("sounds", "SOUNDS"), ("customize", "CUSTOMIZE"), ("settings", "SETTINGS"), ("help", "HELP"))
MIN_W, MIN_H = 40, 12


@dataclass
class Note:
    level: str
    text: str
    expires: float


class Meters:
    """UI-side smoothing + peak hold of the engine's levels."""

    def __init__(self):
        self.v = {k: [0.0, 0.0, 0.0] for k in ("out", "spk")}

    def update(self, engine, now: float) -> None:
        h = engine.health
        raw = {"out": engine.out_level if h["output"]["state"] == "ok" else 0.0,
               "spk": engine.spk_level if h["speaker"]["state"] == "ok" and engine.hear else 0.0}
        for k, new in raw.items():
            lvl, peak, pt = self.v[k]
            lvl = max(new, lvl * 0.80)
            if lvl >= peak:
                peak, pt = lvl, now
            elif now - pt > 1.0:
                peak *= 0.93
            self.v[k] = [lvl, peak, pt]

    def level(self, k):
        return self.v[k][0]

    def peak(self, k):
        return self.v[k][1]


class BootState:
    ORDER = ("config", "devices", "engine", "sounds", "keyboard")

    def __init__(self):
        self.status = {k: "pending" for k in self.ORDER}     # pending | run | ok | warn | bad | off
        self.detail = {k: "" for k in self.ORDER}
        self.done = False


class App:
    def __init__(self, ctl, terminal):
        self.ctl, self.term = ctl, terminal
        self.cfg = ctl.config
        self.theme = self._make_theme()
        w, h = terminal.size()
        self.cv = Canvas(w, h)
        self.cv.ascii = not self.theme.unicode
        self.scr = Screen(w, h)
        self.size = (w, h)
        self.page = "home"
        self.stack: list = []
        self.modal = None
        self.notes: deque[Note] = deque(maxlen=8)
        self.log: deque[tuple[float, str, str]] = deque(maxlen=60)
        self.meters = Meters()
        self.boot = BootState()
        self.quit_requested = False
        self.shutting_down = False
        self.ignore_keys_until = 0.0
        self._last_key = ("", 0.0)
        self.hold = 0
        self.frame = 0
        self.dirty = True
        self.screens: dict = {}
        self.fatal: str | None = None
        self.starter = None
        self.pending_setup = False                      # first-run device setup, waits for the title screen
        self.splash = bool(self.cfg.get("ui.splash"))   # title screen (logo) until Enter is pressed
        self.trans = None                       # running tab animation (transitions.Transition)
        self.tab_rects: dict[str, tuple] = {}   # page -> (x, width) of its header label (for the 'line' animation)
        self._build_screens()

    # ------------------------------------------------------------------ setup
    def _make_theme(self) -> Theme:
        c = self.cfg
        return Theme(self.paint_of("accent"), detect_depth(c.get("ui.colors")), detect_unicode(c.get("ui.charset")),
                     self.paint_of("graph"), self.backdrop_paint(), c.get("ui.borders") != "square",
                     self.backdrop_mode() == "glass")

    def default_paint(self, target: str) -> Paint:
        if target == "graph":
            return DEFAULT_GRAPH.copy()
        if target == "backdrop":
            return DEFAULT_BACKDROP.copy()
        from config import DEFAULTS
        return preset_paint(DEFAULTS["ui"]["accent"])

    def backdrop_mode(self) -> str:
        """terminal = nothing painted (the terminal's blur / acrylic stays) | glass = translucent colour over it |
        custom = opaque painted background."""
        v = self.cfg.get("ui.backdrop")
        return v if v in ("glass", "custom") else "terminal"

    def backdrop_paint(self) -> Paint | None:
        """The painted backdrop (Paint) or None = leave the terminal's own background alone."""
        mode = self.backdrop_mode()
        if mode == "terminal":
            return None
        p = Paint.from_dict(self.cfg.get("ui.backdrop_paint") or {}, DEFAULT_BACKDROP)
        if mode == "custom":
            for st in p.stops:
                st[1] = 100
        return p

    def base_rgb(self) -> tuple:
        """Colour that 'alpha' mixes with: the backdrop if painted, else the terminal background."""
        bd = self.backdrop_paint()
        if self.backdrop_mode() != "custom" or bd is None or not bd.colors():
            return TERMINAL_BG
        cols = bd.colors()
        return tuple(sum(c[i] for c in cols) // len(cols) for i in range(3))

    def paint_of(self, target: str) -> Paint:
        """Current Paint for 'accent' (main UI colour), 'graph' (meters / waveform) or 'backdrop'."""
        c = self.cfg
        if target == "backdrop":
            p = Paint.from_dict(c.get("ui.backdrop_paint") or {}, DEFAULT_BACKDROP)
            if self.backdrop_mode() != "glass":
                for st in p.stops:
                    st[1] = 100
            return p
        if target == "graph":
            p = Paint.from_dict(c.get("ui.graph_paint") or {}, DEFAULT_GRAPH)
        else:
            name = c.get("ui.accent")
            if name in PRESET_ACCENTS:
                p = preset_paint(name)
            else:
                p = Paint.from_dict(c.get("ui.accent_paint") or {}, self.default_paint("accent"))
        p.base = self.base_rgb()
        return p

    def apply_paint(self, target: str, paint: Paint) -> None:
        """Save + apply a colour change live (new style ids only: no full repaint, no flicker)."""
        if target == "graph":
            self.cfg.set("ui.graph_paint", paint.to_dict())
        elif target == "backdrop":
            self.cfg.set("ui.backdrop", "glass" if self.backdrop_mode() == "glass" else "custom")
            self.cfg.set("ui.backdrop_paint", paint.to_dict())
        else:
            self.cfg.set("ui.accent", "custom")
            self.cfg.set("ui.accent_paint", paint.to_dict())
        self.refresh_paints()

    def refresh_paints(self) -> None:
        self.theme.configure(self.paint_of("accent"), self.paint_of("graph"), self.backdrop_paint(),
                             self.backdrop_mode() == "glass")
        self.dirty = True

    def rebuild_theme(self) -> None:
        self.theme = self._make_theme()
        self.cv.ascii = not self.theme.unicode
        self.scr.force = True
        self.trans = None

    def open_colors(self, target: str) -> None:
        from .screens.color_editor import ColorEditor
        self.push(ColorEditor(self, target))

    def enter_menu(self) -> None:
        """Title screen -> main menu."""
        snap = self._snap()
        self.splash = False
        self.dirty = True
        self._begin_transition(snap, 1)

    def mark_dirty(self) -> None:
        self.dirty = True

    def graph_position(self) -> str:
        v = self.cfg.get("ui.graph_position")
        return v if v in ("left", "center", "right") else "right"

    def menu_position(self) -> str:
        v = self.cfg.get("ui.menu_position")
        return v if v in ("left", "center", "right") else "center"

    def _build_screens(self) -> None:
        from .screens.customize import CustomizeScreen
        from .screens.help import HelpScreen
        from .screens.home import HomeScreen
        from .screens.settings import SettingsScreen
        from .screens.sounds import SoundsScreen
        self.screens = {"home": HomeScreen(self), "sounds": SoundsScreen(self),
                        "settings": SettingsScreen(self), "customize": CustomizeScreen(self),
                        "help": HelpScreen(self)}

    # ------------------------------------------------------------------ helpers used by screens
    def now(self) -> float:
        return time.monotonic()

    def accel(self, span_steps: float = 1000) -> int:
        """Step multiplier while an arrow key is held (bounded by the control's range)."""
        mult = 1 if self.hold < 6 else 2 if self.hold < 14 else 4 if self.hold < 28 else 8
        return int(max(1, min(mult, span_steps / 12)))

    def notify(self, level: str, text: str, ttl: float = 4.0) -> None:
        self.notes.append(Note(level, text, self.now() + ttl))
        self.log.append((time.time(), level, text))
        self.dirty = True

    # ---- tab animation: snapshot the last drawn frame, change screen, mix old/new for a moment
    def _snap(self):
        if self.cfg.get("ui.animation") in (None, "none") or not self.boot.done or self.modal is not None:
            return None
        if self.cv.w < MIN_W or self.cv.h < MIN_H or (self.cv.w, self.cv.h) != self.size:
            return None
        return transitions.Snapshot(self.cv), self.page

    def _begin_transition(self, snap, direction: int, new_page: str | None = None) -> None:
        if snap is None:
            return
        shot, old_page = snap
        r = self.tab_rects
        src = r.get(old_page, (1, 8))
        dst = r.get(new_page or self.page, (1, 8))
        self.trans = transitions.make(self.cfg.get("ui.animation"), shot, self.cfg.get("ui.animation_speed"),
                                      direction, src, dst, self.now())

    def play_transition(self) -> None:
        """Settings preview: reveal the current screen with the chosen animation (from an empty screen)."""
        kind = self.cfg.get("ui.animation")
        if kind in (None, "none") or self.cv.w < MIN_W or self.cv.h < MIN_H or (self.cv.w, self.cv.h) != self.size:
            return
        r = self.tab_rects
        blank = transitions.Snapshot(self.cv, blank=True)
        self.theme.recolor(blank)
        self.trans = transitions.make(kind, blank, self.cfg.get("ui.animation_speed"),
                                      1, r.get("home", (1, 8)), r.get(self.page, (1, 8)), self.now())
        self.dirty = True

    def _tab_order(self, page: str) -> int:
        keys = ["home"] + [p for p, _ in PAGES]
        return keys.index(page) if page in keys else 0

    def goto(self, page: str) -> None:
        snap = self._snap() if page != self.page or self.stack else None
        old = self.page
        self.stack.clear()
        self.page = page
        self.screens[page].on_show()
        self.dirty = True
        self._begin_transition(snap, 1 if self._tab_order(page) >= self._tab_order(old) else -1)

    def push(self, screen) -> None:
        snap = self._snap()
        self.stack.append(screen)
        screen.on_show()
        self.dirty = True
        self._begin_transition(snap, 1)

    def pop(self) -> None:
        if self.stack:
            snap = self._snap()
            self.stack.pop()
            self.current.on_show()
            self._begin_transition(snap, -1)
        self.dirty = True

    def open_modal(self, modal) -> None:
        self.modal = modal
        self.dirty = True

    def close_modal(self) -> None:
        self.modal = None
        self.dirty = True

    def bg(self, fn, ok: str | None = None) -> None:
        """Run a slow backend call (device open ...) off the UI thread; report errors compactly."""
        import threading

        def run():
            try:
                fn()
                if ok:
                    self.notify("ok", ok)
            except Exception as e:  # noqa: BLE001
                self.notify("error", str(e)[:120])
        threading.Thread(target=run, daemon=True, name="ui-bg").start()

    @property
    def current(self):
        return self.stack[-1] if self.stack else self.screens[self.page]

    @property
    def state(self) -> str:
        if self.shutting_down:
            return "SHUTTING DOWN"
        if not self.boot.done:
            return "STARTING"
        es = self.ctl.engine.state
        if es == "DEVICE ERROR":
            return es
        return "READY" if self.page == "home" else "RUNNING"

    def confirm_quit(self) -> None:
        from .modals import Confirm
        if isinstance(self.modal, Confirm):
            return
        self.open_modal(Confirm("QUIT", "Stop Soundpad?\n(Your sounds will stop playing.)",
                                "QUIT", "STAY", on_yes=self.request_quit, warn=True))

    def request_quit(self) -> None:
        self.quit_requested = True

    # ------------------------------------------------------------------ input
    def handle_key(self, key: Key) -> None:
        now = self.now()
        if key.name == "ctrl+c":
            self.request_quit()
            return
        if now < self.ignore_keys_until:
            return
        # hold detection for slider acceleration
        last, t = self._last_key
        self.hold = self.hold + 1 if (key.name == last and now - t < 0.18) else 0
        self._last_key = (key.name, now)
        self.dirty = True
        if self.modal is not None:
            self.modal.on_key(self, key)
            return
        scr = self.current
        if scr.captures_text():
            scr.on_key(key)
            return
        if scr.on_key(key):
            return
        self._global_key(key)

    def _global_key(self, key: Key) -> None:
        """The only global key: BACKSPACE = one level back (pop screen -> home -> quit dialog)."""
        if key.name != "backspace":
            return
        if self.stack:
            self.pop()
        elif self.page != "home":
            self.goto("home")
        else:
            self.confirm_quit()

    # ------------------------------------------------------------------ actions shared by screens
    def toggle_hear(self) -> None:
        eng = self.ctl.engine
        eng.set_hear(not eng.hear)
        self.notify("ok", f"Speaker {'ON' if eng.hear else 'OFF'}")

    def open_devices(self) -> None:
        from .screens.devices import DevicesScreen
        self.push(DevicesScreen(self))

    # ------------------------------------------------------------------ per-frame update
    def update(self) -> None:
        self.frame += 1
        now = self.now()
        self.theme.t = now
        self.meters.update(self.ctl.engine, now)
        for level, text in self.ctl.drain_notifications():
            self.notify(level, text, 3.0 if level == "sound" else 5.0)
        while self.notes and self.notes[0].expires < now:
            self.notes.popleft()
        if self.modal is not None:
            self.modal.tick(self)
        self.current.tick()
        self.ctl.tick()
        if self.pending_setup and self.boot.done and not self.splash and self.modal is None:
            self.pending_setup = False
            from .screens.devices import DevicesScreen
            self.push(DevicesScreen(self, first_run=True))

    # ------------------------------------------------------------------ drawing
    def draw(self) -> None:
        cv, th = self.cv, self.theme
        cv.clear()
        w, h = cv.w, cv.h
        if w < MIN_W or h < MIN_H:
            cv.put(0, 0, fit("Terminal too small", w), th.warn)
            cv.put(0, 1, fit(f"need {MIN_W}x{MIN_H}, have {w}x{h}", w), th.dim)
            return
        self._draw_header(w)
        footer = 2
        body = Rect(0, 1, w, h - 1 - footer)
        try:
            self.current.draw(cv, body)
        except Exception:  # noqa: BLE001 - a broken widget must not kill the app
            self._log_exception("draw")
            cv.put(1, 2, "Internal UI error (see data/ui_error.log)", th.err)
        self._draw_footer(w, h, footer)
        if self.modal is not None:
            self.modal.draw(self, cv, body)
        th.recolor(cv)                      # accent gradient / rainbow (no-op for a solid accent)

    def _draw_header(self, w: int) -> None:
        cv, th = self.cv, self.theme
        cv.fill(Rect(0, 0, w, 1), " ", th.header)
        x = cv.put(1, 0, "soundpad", th.title) + 3
        self.tab_rects["home"] = (1, len("soundpad"))
        for page, label in PAGES:
            txt = f" {label} "
            active = self.page == page and self.page != "home"
            self.tab_rects[page] = (x, len(txt))
            x += cv.put(x, 0, txt, th.tab_on if active else th.tab_off) + 1
        st = self.state
        col = {"RUNNING": th.ok, "READY": th.ok, "STARTING": th.warn, "DEVICE ERROR": th.err,
               "SHUTTING DOWN": th.warn}[st]
        if w - x > len(st) + 3:
            cv.put(w - len(st) - 2, 0, st, col)

    def _draw_footer(self, w: int, h: int, footer: int) -> None:
        """Notification line + status bar. (No key hints anywhere: the controls are arrows / Enter / Backspace.)"""
        cv, th = self.cv, self.theme
        note = self.notes[-1] if self.notes else None
        ny = h - 2
        if note is not None:
            tag, st = {"error": ("ERROR", th.err), "warn": ("WARNING", th.warn), "ok": ("OK", th.ok),
                       "sound": ("PLAYED", th.sound), "info": ("INFO", th.info)}.get(note.level, ("", th.text))
            text = note.text
            cv.fill(Rect(0, ny, w, 1), " ", 0)
            x = cv.put(1, ny, f" {tag} ", th.sel if note.level != "sound" else th.sound) + 2
            cv.put(x, ny, fit(text, w - x - 1), st)
        self._draw_status(w, h - 1)

    def _draw_status(self, w: int, y: int) -> None:
        cv, th, ctl = self.cv, self.theme, self.ctl
        cv.fill(Rect(0, y, w, 1), " ", 0)
        eng = ctl.engine
        hs = eng.health
        long = w >= 86

        def st(role):
            s = hs[role]["state"]
            return "ok" if s == "ok" else "off" if s in ("disabled", "init") else "bad"
        x = 1
        spk = st("speaker")
        if spk == "ok" and not eng.hear:
            spk = "warn"          # speaker open but 'Hear sounds' is OFF
        n = len(ctl.sounds())
        items = (("OUTPUT" if long else "OUT", st("output")), ("SPEAKER" if long else "SPK", spk),
                 ("KEYBOARD" if long else "KEY", "ok" if ctl.listener_ok else "bad"))
        for label, state in items:
            x += cv.put(x, y, label + " ", th.dim)
            dot(cv, th, x, y, state)
            x += 3
        rest = []
        if w >= 60:
            rest.append(f"{n} SOUND{'S' if n != 1 else ''}")
        if w >= 72:
            rest.append(f"CPU {ctl.cpu_percent():.1f}%")
        if rest:
            cv.put(x + 1, y, "  ".join(rest), th.dim)

    # ------------------------------------------------------------------ errors
    def _log_exception(self, where: str) -> None:
        tb = traceback.format_exc()
        self.log.append((time.time(), "error", f"{where}: {tb.splitlines()[-1]}"))
        try:
            from config import DATA_DIR
            with open(DATA_DIR / "ui_error.log", "a", encoding="utf-8") as f:
                f.write(f"--- {time.ctime()} ({where})\n{tb}\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ main loop
    def render(self) -> None:
        """Draw + flush one frame (also used by tests with a fake terminal)."""
        w, h = self.term.size()
        if (w, h) != self.size:
            self.size = (w, h)
            self.cv.resize(w, h)
            self.scr.resize(w, h)
        self.draw()
        if self.trans is not None:
            try:
                if not self.trans.apply(self.cv, self.theme, self.now()):
                    self.trans = None
            except Exception:  # noqa: BLE001 - an animation bug must never break the UI
                self._log_exception("transition")
                self.trans = None
        out = self.scr.flush(self.cv, self.theme)
        if out:
            self.term.write(out)

    def run(self) -> None:
        import threading
        fps = int(clamp(self.cfg.get("ui.fps") or 30, 10, 60))
        frame_dt = 1.0 / fps
        if self.starter:
            threading.Thread(target=self._run_starter, daemon=True, name="backend-start").start()
        last = 0.0
        while not self.quit_requested:
            now = self.now()
            timeout = max(0.0, last + frame_dt - now)
            try:
                keys = self.term.read_keys(timeout)
            except KeyboardInterrupt:
                break
            for k in keys:
                try:
                    self.handle_key(k)
                except Exception:  # noqa: BLE001
                    self._log_exception("key")
                    self.notify("error", "Internal error handling key (see data/ui_error.log)")
                if self.quit_requested:
                    break
            now = self.now()
            if keys or now - last >= frame_dt:
                last = now
                try:
                    self.update()
                    self.render()
                except Exception:  # noqa: BLE001
                    self._log_exception("frame")

    def _run_starter(self) -> None:
        try:
            self.starter(self)
        except Exception as e:  # noqa: BLE001
            self.notify("error", f"Startup problem: {e}")
        finally:
            self.boot.done = True
            self.dirty = True

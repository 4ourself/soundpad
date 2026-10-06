"""Global keybind manager.

Matching rule (one rule covers both modes):
    on every key-DOWN transition (UP -> DOWN, auto-repeat ignored unless allowed), fire each binding
    whose key set is a subset of the currently held keys AND contains the key just pressed.

    * "ALT"          -> fires the instant ALT goes down, so a later ALT+F4 has already triggered it.
    * "CTRL+ALT+S"   -> fires when S (the last missing key) goes down while CTRL and ALT are held.
Keys are never swallowed, so Windows still receives ALT+F4 etc.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

MODIFIERS = ("CTRL", "ALT", "SHIFT", "WIN")
_ALIASES = {
    "CONTROL": "CTRL", "CTL": "CTRL", "LCTRL": "CTRL", "RCTRL": "CTRL",
    "OPTION": "ALT", "LALT": "ALT", "RALT": "ALT", "ALTGR": "ALT",
    "LSHIFT": "SHIFT", "RSHIFT": "SHIFT",
    "CMD": "WIN", "WINDOWS": "WIN", "SUPER": "WIN", "META": "WIN", "LWIN": "WIN", "RWIN": "WIN",
    "RETURN": "ENTER", "ESCAPE": "ESC", "SPACEBAR": "SPACE", "BKSP": "BACKSPACE",
    "DEL": "DELETE", "INS": "INSERT", "PGUP": "PAGEUP", "PAGE_UP": "PAGEUP",
    "PGDN": "PAGEDOWN", "PAGE_DOWN": "PAGEDOWN", "CAPS": "CAPSLOCK", "CAPS_LOCK": "CAPSLOCK",
    "PRTSC": "PRINTSCREEN", "PRINT_SCREEN": "PRINTSCREEN", "NUM_LOCK": "NUMLOCK",
    "SCROLL_LOCK": "SCROLLLOCK", "PLUS": "+",
}
_NAMED = {"SPACE", "ENTER", "TAB", "ESC", "BACKSPACE", "DELETE", "INSERT", "HOME", "END", "PAGEUP",
          "PAGEDOWN", "UP", "DOWN", "LEFT", "RIGHT", "CAPSLOCK", "NUMLOCK", "SCROLLLOCK",
          "PRINTSCREEN", "PAUSE", "MENU"}
_VALID = (set(MODIFIERS) | _NAMED | {chr(c) for c in range(ord("A"), ord("Z") + 1)}
          | set("0123456789") | {f"F{i}" for i in range(1, 25)} | {f"NUM{i}" for i in range(10)}
          | set("`-=[];',./\\+"))
_OEM_VK = {0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
           0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
REPEAT_GAP = 1.2  # seconds; a "down" for an already-held key within this gap is auto-repeat


def parse_keybind(spec: str) -> tuple[str, ...]:
    """'ctrl+alt+s' -> ('CTRL', 'ALT', 'S'). Modifiers first. Raises ValueError."""
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("empty keybind")
    parts = [p.strip() for p in spec.split("+")]
    if spec == "+" or spec.endswith("++"):
        parts = parts[:-2] + ["+"]
    names: list[str] = []
    for p in parts:
        p = _ALIASES.get(p.upper(), p.upper())
        if p not in _VALID:
            raise ValueError(f"unknown key '{p}'")
        if p not in names:
            names.append(p)
    mods = [m for m in MODIFIERS if m in names]
    rest = [k for k in names if k not in MODIFIERS]
    return tuple(mods + rest)


def _ordered(names) -> tuple[str, ...]:
    names = list(names)
    return tuple([m for m in MODIFIERS if m in names] + sorted(n for n in names if n not in MODIFIERS))


def format_keybind(keys) -> str:
    return "+".join(keys)


def normalize_pynput_key(key) -> str | None:
    """pynput Key/KeyCode -> canonical name (left/right variants collapse), or None to ignore."""
    name = getattr(key, "name", None)
    if name:
        n = name.lower()
        if n.startswith("ctrl"):
            return "CTRL"
        if n.startswith("alt"):
            return "ALT"
        if n.startswith("shift"):
            return "SHIFT"
        if n.startswith("cmd"):
            return "WIN"
        n = n.replace("_", "").upper()
        return n if n in _VALID else None
    vk = getattr(key, "vk", None)
    char = getattr(key, "char", None)
    if vk is not None:
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk)
        if sys.platform == "win32":
            if 0x60 <= vk <= 0x69:
                return f"NUM{vk - 0x60}"
            if vk in _OEM_VK:
                return _OEM_VK[vk]
        elif 0x61 <= vk <= 0x7A:
            return chr(vk).upper()
    if char and char.isprintable():
        up = char.upper()
        return up if up in _VALID else None
    return None


def _raw_id(key):
    return getattr(key, "name", None) or getattr(key, "vk", None) or getattr(key, "char", None)


def _windows_key_down(vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


@dataclass
class Binding:
    id: int
    keys: frozenset
    spec: str
    callback: Callable[[], None]
    tag: object = None

    @property
    def kind(self) -> str:
        return "single" if len(self.keys) == 1 else "combo"


class KeybindManager:
    def __init__(self, allow_repeat: bool = False, exact_single_keys: bool = False,
                 key_state_fn: Callable[[int], bool] | None = None):
        self.allow_repeat = allow_repeat
        self.exact_single_keys = exact_single_keys
        self._bindings: list[Binding] = []
        self._next_id = 1
        self._held: dict = {}      # raw key -> (name, vk, last_event_time)
        self.history: deque = deque(maxlen=12)   # (wall time, "CTRL+F4", [tags of fired bindings]) - for the UI
        self._lock = threading.RLock()
        self._listener = None
        self.error = ""
        self._key_state = key_state_fn or (_windows_key_down if sys.platform == "win32" else None)
        self._capture_evt: threading.Event | None = None
        self._capture_keys: list[str] = []
        self._capture_result: tuple | None = None

    # ------------------------------------------------------------ bindings
    def bind(self, spec: str, callback: Callable[[], None], tag=None) -> Binding:
        keys = parse_keybind(spec)
        with self._lock:
            b = Binding(self._next_id, frozenset(keys), format_keybind(keys), callback, tag)
            self._next_id += 1
            self._bindings.append(b)
            return b

    def unbind_tag(self, tag) -> None:
        with self._lock:
            self._bindings = [b for b in self._bindings if b.tag != tag]

    def clear(self) -> None:
        with self._lock:
            self._bindings = []

    @property
    def bindings(self) -> list[Binding]:
        with self._lock:
            return list(self._bindings)

    @property
    def pressed(self) -> set[str]:
        with self._lock:
            return {name for name, _, _ in self._held.values()}

    def held_text(self) -> str:
        """Keys held right now, e.g. 'ALT+F4' (empty when nothing is down)."""
        with self._lock:
            self._drop_stuck(None)
            return format_keybind(_ordered({name for name, _, _ in self._held.values()}))

    def recent(self) -> list:
        """Newest-first [(time, combo, [fired tags])] of key-down events seen by the global hook."""
        with self._lock:
            return list(reversed(self.history))

    # ------------------------------------------------------------ event handling (listener thread)
    def _drop_stuck(self, current_raw) -> None:
        """Windows can swallow key-ups (Alt+Tab, Win+L...). Verify held keys against real state."""
        if self._key_state is None:
            return
        for raw, (name, vk, _) in list(self._held.items()):
            if raw != current_raw and vk and not self._key_state(vk):
                del self._held[raw]

    def handle_press(self, name: str, raw=None, vk: int | None = None, now: float | None = None) -> list[Binding]:
        raw = raw if raw is not None else name
        now = time.monotonic() if now is None else now
        fire: list[Binding] = []
        with self._lock:
            self._drop_stuck(raw)
            prev = self._held.get(raw)
            is_repeat = prev is not None and (now - prev[2]) < REPEAT_GAP
            self._held[raw] = (name, vk, now)
            if self._capture_evt is not None:
                if not is_repeat and name not in self._capture_keys:
                    self._capture_keys.append(name)
                return []
            if is_repeat and not self.allow_repeat:
                return []
            held = {n for n, _, _ in self._held.values()}
            for b in self._bindings:
                if name in b.keys and b.keys <= held:
                    if self.exact_single_keys and b.kind == "single" and len(held) > 1:
                        continue
                    fire.append(b)
            self.history.append((time.time(), format_keybind(_ordered(held)), [b.tag for b in fire]))
        for b in fire:                      # outside the lock; callbacks must be quick
            try:
                b.callback()
            except Exception:  # noqa: BLE001
                pass
        return fire

    def handle_release(self, raw) -> None:
        with self._lock:
            self._held.pop(raw, None)
            if self._capture_evt is not None and not self._held and self._capture_keys:
                keys = self._capture_keys
                mods = [m for m in MODIFIERS if m in keys]
                self._capture_result = tuple(mods + [k for k in keys if k not in MODIFIERS])
                self._capture_evt.set()

    # ------------------------------------------------------------ pynput glue
    @property
    def available(self) -> bool:
        return self._listener is not None

    def start(self) -> bool:
        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001 - ImportError, or no display server on Linux
            self.error = f"global keyboard hook unavailable: {e}"
            return False

        def on_press(key):
            name = normalize_pynput_key(key)
            if name:
                vk = getattr(key, "vk", None) or getattr(getattr(key, "value", None), "vk", None)
                self.handle_press(name, raw=_raw_id(key), vk=vk)

        def on_release(key):
            self.handle_release(_raw_id(key))

        try:
            self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:  # noqa: BLE001
            self._listener = None
            self.error = f"global keyboard hook failed: {e}"
            return False
        return True

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # -- non-blocking capture API (used by the TUI) ---------------------------------
    def begin_capture(self) -> None:
        with self._lock:
            self._capture_keys, self._capture_result = [], None
            self._capture_evt = threading.Event()

    def capture_state(self) -> tuple[str, str | None]:
        """(live text of keys pressed so far, final combo or None while still waiting)."""
        with self._lock:
            keys = list(self._capture_keys)
            mods = [m for m in MODIFIERS if m in keys]
            live = format_keybind(mods + [k for k in keys if k not in MODIFIERS])
            res = format_keybind(self._capture_result) if self._capture_result else None
            return live, res

    def end_capture(self) -> None:
        with self._lock:
            self._capture_evt = None
            self._capture_keys, self._capture_result = [], None
            self._held.clear()   # forget keys held during capture (their key-ups may arrive late)

    def capture(self, timeout: float = 10.0) -> str | None:
        """Block until the user presses and releases a key combination. Returns e.g. 'CTRL+F6'."""
        if not self.available:
            return None
        evt = threading.Event()
        with self._lock:
            self._capture_keys, self._capture_result, self._capture_evt = [], None, evt
        evt.wait(timeout)
        with self._lock:
            self._capture_evt = None
            res = self._capture_result
        return format_keybind(res) if res else None

"""Terminal control: raw/non-blocking keyboard input, alternate screen, VT output, safe restore.

Windows 10/11: msvcrt for input (no Enter needed), VT sequences enabled on the console for output.
POSIX (used for development/tests): termios cbreak + select.
The terminal is ALWAYS restored (context manager + atexit + signal handlers).
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import sys
import time

from .keys import Key, decode_windows, parse_ansi

IS_WIN = os.name == "nt"
ENTER_SEQ = "\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J\x1b[H"      # alt screen, hide cursor, no autowrap
LEAVE_SEQ = "\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l"


class Terminal:
    def __init__(self, out=None, fd_in=None):
        self.out = out or sys.stdout
        self._active = False
        self._old_attr = None
        self._old_win_mode = None
        self._buf = ""
        self._esc_since = 0.0
        self.fd = fd_in if fd_in is not None else (None if IS_WIN else sys.stdin.fileno())
        self.vt_ok = True

    # -------------------------------------------------------------- lifecycle
    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, *exc):
        self.restore()
        return False

    def enter(self) -> None:
        if self._active:
            return
        try:
            self.out.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        if IS_WIN:
            self.vt_ok = self._enable_windows_vt()
        else:
            import termios
            import tty
            self._old_attr = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        self._active = True
        atexit.register(self.restore)
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
            if sig is not None:
                try:
                    signal.signal(sig, lambda *_: (self.restore(), os._exit(1)))
                except (ValueError, OSError):
                    pass
        self.write(ENTER_SEQ)

    def restore(self) -> None:
        if not self._active:
            return
        self._active = False
        try:
            self.write(LEAVE_SEQ)
        except Exception:  # noqa: BLE001
            pass
        if IS_WIN:
            try:
                import ctypes
                k32 = ctypes.windll.kernel32
                if self._old_win_mode is not None:
                    k32.SetConsoleMode(k32.GetStdHandle(-11), self._old_win_mode)
            except Exception:  # noqa: BLE001
                pass
        elif self._old_attr is not None:
            import termios
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._old_attr)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _enable_windows_vt_static():
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return None, False
        ok = k32.SetConsoleMode(h, mode.value | 0x0001 | 0x0004)     # PROCESSED_OUTPUT | VT_PROCESSING
        return mode.value, bool(ok)

    def _enable_windows_vt(self) -> bool:
        try:
            self._old_win_mode, ok = self._enable_windows_vt_static()
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            return ok
        except Exception:  # noqa: BLE001
            return False

    # -------------------------------------------------------------- output / size
    def write(self, s: str) -> None:
        self.out.write(s)
        self.out.flush()

    def size(self) -> tuple[int, int]:
        sz = shutil.get_terminal_size((80, 24))
        return max(1, sz.columns), max(1, sz.lines)

    # -------------------------------------------------------------- input
    def read_keys(self, timeout: float = 0.0) -> list[Key]:
        """Return all pending keys; wait up to `timeout` seconds for the first one."""
        return self._read_windows(timeout) if IS_WIN else self._read_posix(timeout)

    def _read_windows(self, timeout: float) -> list[Key]:
        import msvcrt
        end = time.monotonic() + timeout
        while True:
            keys = decode_windows(msvcrt.getwch, msvcrt.kbhit)
            if keys or time.monotonic() >= end:
                return keys
            time.sleep(0.004)

    def _read_posix(self, timeout: float) -> list[Key]:
        import select
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            data = os.read(self.fd, 4096)
            self._buf += data.decode("utf-8", errors="ignore")
        if not self._buf:
            return []
        keys, rest = parse_ansi(self._buf, final=False)
        if rest == "\x1b":                    # maybe the start of an escape sequence: wait ~30 ms
            if self._esc_since == 0.0:
                self._esc_since = time.monotonic()
            elif time.monotonic() - self._esc_since > 0.03:
                keys.append(Key("esc"))
                rest, self._esc_since = "", 0.0
        else:
            self._esc_since = 0.0
        self._buf = rest
        return keys

    def drain_input(self) -> None:
        """Discard buffered keystrokes (e.g. those typed while a global key capture was active)."""
        self._buf, self._esc_since = "", 0.0
        try:
            if IS_WIN:
                import msvcrt
                while msvcrt.kbhit():
                    msvcrt.getwch()
            else:
                import termios
                termios.tcflush(self.fd, termios.TCIFLUSH)
        except Exception:  # noqa: BLE001
            pass

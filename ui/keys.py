"""Key model + decoders for Windows (msvcrt) and ANSI terminals. Pure functions => unit-testable."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    name: str            # 'char' | 'up' 'down' 'left' 'right' 'enter' 'esc' 'space' 'tab' 'backtab'
    char: str = ""       # 'backspace' 'delete' 'home' 'end' 'pgup' 'pgdn' 'insert' 'f1'..'f12' 'ctrl+x'

    @property
    def printable(self) -> bool:
        return self.name in ("char", "space") and bool(self.char)

    @property
    def lower(self) -> str:
        return self.char.lower() if self.printable else ""

    def __str__(self) -> str:
        return self.char if self.name == "char" else self.name


def decode_char(ch: str) -> Key | None:
    o = ord(ch)
    if ch in ("\r", "\n"):
        return Key("enter")
    if ch == "\t":
        return Key("tab")
    if ch in ("\x08", "\x7f"):
        return Key("backspace")
    if ch == "\x1b":
        return Key("esc")
    if ch == " ":
        return Key("space", " ")
    if ch == "\x03":
        return Key("ctrl+c")
    if 1 <= o <= 26:
        return Key(f"ctrl+{chr(o + 96)}")
    if ch.isprintable():
        return Key("char", ch)
    return None


# ---------------------------------------------------------------- Windows console (msvcrt.getwch)
_WIN = {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end",
        "I": "pgup", "Q": "pgdn", "S": "delete", "R": "insert"}
_WIN_F = {chr(59 + i): f"f{i + 1}" for i in range(10)}          # '\x00;' .. '\x00D'  = F1..F10
_WIN_F.update({"\x85": "f11", "\x86": "f12"})                    # '\xe0\x85' / '\xe0\x86'


def decode_windows(getch, kbhit) -> list[Key]:
    """Drain every pending key from the Windows console (arrows arrive as 2-char sequences)."""
    keys: list[Key] = []
    while kbhit():
        ch = getch()
        if ch in ("\x00", "\xe0"):
            code = getch()
            if ch == "\x00" and code == "\x0f":
                keys.append(Key("backtab"))
            elif code in _WIN_F:
                keys.append(Key(_WIN_F[code]))
            elif code in _WIN:
                keys.append(Key(_WIN[code]))
            continue
        k = decode_char(ch)
        if k:
            keys.append(k)
    return keys


# ---------------------------------------------------------------- ANSI / VT input (Linux, macOS, tests)
_CSI_TILDE = {1: "home", 2: "insert", 3: "delete", 4: "end", 5: "pgup", 6: "pgdn", 7: "home", 8: "end",
              11: "f1", 12: "f2", 13: "f3", 14: "f4", 15: "f5", 17: "f6", 18: "f7", 19: "f8", 20: "f9",
              21: "f10", 23: "f11", 24: "f12"}
_CSI_FINAL = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end", "Z": "backtab",
              "P": "f1", "Q": "f2", "R": "f3", "S": "f4"}


def parse_ansi(buf: str, final: bool = False) -> tuple[list[Key], str]:
    """Parse as many keys as possible. Returns (keys, unconsumed). A lone ESC is only emitted when
    `final` (caller decided no more bytes are coming)."""
    keys: list[Key] = []
    i, n = 0, len(buf)
    while i < n:
        ch = buf[i]
        if ch != "\x1b":
            k = decode_char(ch)
            if k:
                keys.append(k)
            i += 1
            continue
        if i + 1 >= n:                       # ESC at end of buffer
            if final:
                keys.append(Key("esc"))
                i += 1
            break
        nxt = buf[i + 1]
        if nxt in "[O":
            j = i + 2
            while j < n and not ("@" <= buf[j] <= "~"):
                j += 1
            if j >= n:                       # incomplete sequence
                if final:
                    i = n
                break
            params, f = buf[i + 2:j], buf[j]
            if f == "~":
                try:
                    code = int(params.split(";")[0])
                except ValueError:
                    code = -1
                if code in _CSI_TILDE:
                    keys.append(Key(_CSI_TILDE[code]))
            elif f in _CSI_FINAL:
                keys.append(Key(_CSI_FINAL[f]))
            i = j + 1
            continue
        keys.append(Key("esc"))              # ESC <char> (Alt+char): report ESC, then re-read the char
        i += 1
    return keys, buf[i:]

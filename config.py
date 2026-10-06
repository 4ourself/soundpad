"""Configuration manager (data/config.json). Thread-safe, atomic saves."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SOUNDPAD_DATA", APP_DIR / "data"))

DEFAULTS: dict = {
    "audio": {
        "sample_rate": 48000,
        "block_size": 480,           # 10 ms @ 48 kHz
        "jitter_blocks": 2,          # safety buffer between the Output and Speaker clocks
        "host_api": "auto",          # "auto" -> WASAPI on Windows
        "output_device": "default",  # "default" | device name  (the virtual cable, e.g. "CABLE Input")
        "speaker_device": "default",  # "default" | "none" | device name  (your headphones / speakers)
        "hear_sounds": True,         # also play sounds on the speaker
    },
    "mixer": {
        "master_volume": 1.0,
        "speaker_volume": 1.0,
    },
    "soundpad": {
        "max_simultaneous": 8,
        "allow_overlap": True,
        "allow_repeat": False,       # hold a key => retrigger (limited by cooldown)
        "cooldown_ms": 250,
        "exact_single_keys": False,  # False: a sound bound to "ALT" also fires on ALT+F4
        "stop_all_keybind": "",
        "stream_threshold_seconds": 120,  # longer files are streamed, not preloaded
        "preload": True,             # decode all sounds into RAM at startup
        "scan_subfolders": True,     # loading a folder also reads the folders inside it
        "folders": [],               # loaded folders; re-scanned at every start (new files appear)
    },
    "ui": {
        "charset": "auto",           # auto | unicode | ascii
        "colors": "auto",            # auto | true | 256 | 16 | mono
        "accent": "amber",
        "fps": 30,
        "accent_paint": {"mode": "solid", "stops": [["#00D7FF", 100]], "speed": 50},   # used when accent = "custom"
        "graph_paint": {"mode": "zones", "stops": [["#00D787", 100], ["#FFD700", 100], ["#FF5F5F", 100]], "speed": 50},
        "backdrop": "terminal",      # terminal (leave the background alone) | custom (paint ui.backdrop_paint)
        "backdrop_paint": {"mode": "solid", "stops": [["#171A22", 100]], "speed": 50},
        "borders": "rounded",        # rounded | square
        "splash": True,              # show the logo title screen at start
        "logo_glow": "sometimes",    # off | sometimes | always
        "graph_position": "right",   # left | center | right
        "menu_position": "center",   # left | center | right
        "animation": "none",         # none | fade | line | slide | wipe | dissolve | curtain | blinds | random
        "animation_speed": "normal",  # fast | normal | slow
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)


class ConfigManager:
    def __init__(self, path: Path | None = None, autosave: bool = True):
        self.path = Path(path) if path else DATA_DIR / "config.json"
        self.autosave = autosave
        self._lock = threading.RLock()
        self.dirty = False
        self._data = copy.deepcopy(DEFAULTS)
        self.first_run = not self.path.exists()
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = _merge(DEFAULTS, json.load(f))
            except (json.JSONDecodeError, OSError):
                try:
                    os.replace(self.path, self.path.with_suffix(".json.bak"))
                except OSError:
                    pass
                self._data = copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.path, self._data)
            self.dirty = False

    def save_if_dirty(self) -> None:
        """Debounced persistence for the TUI (sliders change 30x/second)."""
        if self.dirty:
            self.save()

    def get(self, dotted: str, default=None):
        with self._lock:
            cur = self._data
            for part in dotted.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return default
                cur = cur[part]
            return copy.deepcopy(cur)

    def set(self, dotted: str, value) -> None:
        with self._lock:
            parts = dotted.split(".")
            cur = self._data
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = value
            self.dirty = True
            if self.autosave:
                self.save()

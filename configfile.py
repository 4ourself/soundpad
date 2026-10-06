"""Import / export of settings ("config files") - IDENTICAL in Voicer and Soundpad, so a file exported by one
can be imported by the other. Colours, layout, animation, title screen, buffer sizes and the app's own tuning
travel; devices (input / output / speaker / monitor), the audio API, loaded folders, sounds and voice presets
do not. Keys the other app does not know are ignored; every value is validated before it is applied.
Pure functions (no UI): the screens only call export_file / import_file / apply_changes."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

FORMAT = "voicer-soundpad-config"
VERSION = 1
DEFAULT_NAME = "voicer-soundpad-config.json"

NEVER = {"audio.sample_rate", "audio.host_api", "soundpad.folders"}          # machine / setup specific
NEVER_SECTIONS = {"effects", "presets"}                                        # voice chain and presets

CHOICES = {
    "ui.charset": ("auto", "unicode", "ascii"),
    "ui.colors": ("auto", "true", "256", "16", "mono"),
    "ui.backdrop": ("terminal", "custom"),
    "ui.borders": ("rounded", "square"),
    "ui.logo_glow": ("off", "sometimes", "always"),
    "ui.graph_position": ("left", "center", "right"),
    "ui.menu_position": ("left", "center", "right"),
    "ui.animation_speed": ("fast", "normal", "slow"),
    "ui.fps": (20, 30, 60),
    "audio.jitter_blocks": (1, 2, 3, 4),
}
RANGES = {"audio.block_size": (120, 1920), "soundpad.max_simultaneous": (1, 32), "soundpad.cooldown_ms": (0, 2000),
          "soundpad.stream_threshold_seconds": (5, 3600)}


class ConfigFileError(Exception):
    """Compact, user-presentable message."""


class Report:
    def __init__(self):
        self.changed: dict[str, object] = {}     # key -> new value (really different from the current one)
        self.same = 0                            # valid but already set
        self.ignored: list[str] = []             # not used by this app / never imported (devices ...)
        self.rejected: list[str] = []            # invalid value

    @property
    def applied(self) -> int:
        return len(self.changed) + self.same

    def summary(self, app_name: str = "") -> str:
        s = f"Imported {self.applied} settings ({len(self.changed)} changed)"
        if self.ignored:
            s += f", {len(self.ignored)} not used here"
        if self.rejected:
            s += f", {len(self.rejected)} invalid skipped"
        return s


# ------------------------------------------------------------------ paths
def clean_path(text: str) -> str:
    t = (text or "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return os.path.expandvars(os.path.expanduser(t)) if t else ""


def default_path() -> str:
    """Same default for both apps: exporting in one and importing in the other is just Enter, Enter."""
    return str(Path.home() / DEFAULT_NAME)


# ------------------------------------------------------------------ export
def exportable(key: str) -> bool:
    sec = key.split(".")[0]
    return not (key in NEVER or key.endswith("_device") or sec in NEVER_SECTIONS)


def export_dict(cfg, defaults: dict, app: str) -> dict:
    settings: dict = {}
    for sec, body in defaults.items():
        if sec in NEVER_SECTIONS or not isinstance(body, dict):
            continue
        for k in body:
            key = f"{sec}.{k}"
            if exportable(key):
                settings.setdefault(sec, {})[k] = cfg.get(key)
    return {"format": FORMAT, "version": VERSION, "app": app,
            "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "Colors and settings only. Audio devices are never stored here.",
            "settings": settings}


def export_file(cfg, defaults: dict, app: str, path: str) -> tuple[str, int]:
    p = Path(clean_path(path))
    if not str(p) or str(p) == ".":
        raise ConfigFileError("Type a file name")
    if p.is_dir():
        p = p / DEFAULT_NAME
    if p.suffix == "":
        p = p.with_suffix(".json")
    data = export_dict(cfg, defaults, app)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError as e:
        raise ConfigFileError(f"Cannot write: {e.strerror or e}") from e
    return str(p), sum(len(v) for v in data["settings"].values())


# ------------------------------------------------------------------ import
def read_file(path: str) -> dict:
    p = Path(clean_path(path))
    if p.is_dir():
        p = p / DEFAULT_NAME
    if not p.is_file():
        raise ConfigFileError("File not found")
    try:
        if p.stat().st_size > 1_000_000:
            raise ConfigFileError("Too big to be a config file")
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ConfigFileError("Not a valid config file (bad JSON)") from e
    if not isinstance(data, dict):
        raise ConfigFileError("Not a config file")
    if data.get("format") == FORMAT and isinstance(data.get("settings"), dict):
        return data["settings"]
    if data.get("format") not in (None, FORMAT):
        raise ConfigFileError("Not a Voicer / Soundpad config file")
    if isinstance(data.get("ui"), dict) or isinstance(data.get("audio"), dict):      # a plain data/config.json
        return data
    raise ConfigFileError("Not a Voicer / Soundpad config file")


def _clean_paint(v):
    from ui.colors import MAX_STOPS, MODES, hex_to_rgb, rgb_to_hex
    if not isinstance(v, dict) or v.get("mode") not in MODES:
        raise ValueError("paint")
    stops = v.get("stops")
    if not isinstance(stops, list) or not 1 <= len(stops) <= MAX_STOPS:
        raise ValueError("stops")
    out = []
    for s in stops:
        if not isinstance(s, (list, tuple)) or len(s) < 2 or isinstance(s[1], bool) or not isinstance(s[1], (int, float)):
            raise ValueError("stop")
        out.append([rgb_to_hex(hex_to_rgb(str(s[0]))), int(max(0, min(100, s[1])))])
    sp = v.get("speed", 50)
    if isinstance(sp, bool) or not isinstance(sp, (int, float)):
        raise ValueError("speed")
    return {"mode": v["mode"], "stops": out, "speed": int(max(1, min(100, sp)))}


def _clean(key: str, value, default):
    """Return the validated value or raise ValueError."""
    if key == "ui.accent":
        from ui.colors import PRESET_ACCENTS
        if value in list(PRESET_ACCENTS) + ["custom"]:
            return value
        raise ValueError(key)
    if key == "ui.animation":
        from ui import transitions
        if value in transitions.KINDS:
            return value
        raise ValueError(key)
    if key.endswith("_paint"):
        return _clean_paint(value)
    if key == "soundpad.stop_all_keybind":
        if not isinstance(value, str):
            raise ValueError(key)
        if value:
            from soundpad.keybinds import format_keybind, parse_keybind
            return format_keybind(parse_keybind(value))
        return ""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        raise ValueError(key)
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(key)
        if key in CHOICES:
            if value in CHOICES[key]:
                return type(CHOICES[key][0])(value)
            raise ValueError(key)
        lo, hi = RANGES.get(key, (0.0, 2.0) if isinstance(default, float) else (None, None))
        if lo is not None:
            value = max(lo, min(hi, value))
        return int(value) if isinstance(default, int) else float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(key)
        if key in CHOICES and value not in CHOICES[key]:
            raise ValueError(key)
        return value
    raise ValueError(key)                                   # lists / unknown shapes are never imported


def import_settings(cfg, defaults: dict, settings: dict) -> Report:
    """Validate and store. Nothing is written for a key that is invalid or unknown to this app."""
    rep = Report()
    for sec, body in settings.items():
        if not isinstance(body, dict):
            continue
        for k, v in body.items():
            key = f"{sec}.{k}"
            if (not isinstance(defaults.get(sec), dict) or k not in defaults[sec] or not exportable(key)):
                rep.ignored.append(key)
                continue
            try:
                new = _clean(key, v, defaults[sec][k])
            except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                rep.rejected.append(key)
                continue
            if cfg.get(key) == new:
                rep.same += 1
            else:
                rep.changed[key] = new
    for key, new in rep.changed.items():
        cfg.set(key, new)
    return rep


def import_file(cfg, defaults: dict, path: str) -> Report:
    rep = import_settings(cfg, defaults, read_file(path))
    if not rep.applied and not rep.rejected:
        raise ConfigFileError("Nothing in this file applies here")
    return rep


# ------------------------------------------------------------------ make it live (UI thread)
def apply_changes(app, changed: dict) -> None:
    """Push imported values into the running app. Works for both apps (duck typed)."""
    keys = set(changed)
    eng = app.ctl.engine
    if any(k.startswith("ui.") for k in keys):
        app.rebuild_theme()
        app.refresh_paints()
        if "ui.animation" not in keys:
            app.trans = None
    if "audio.hear_sounds" in keys and hasattr(eng, "set_hear"):
        eng.set_hear(changed["audio.hear_sounds"])
    if "audio.hear_output" in keys and hasattr(eng, "set_hear_output"):
        eng.set_hear_output(changed["audio.hear_output"])
    if "audio.output_mono" in keys and hasattr(eng, "set_output_mono"):
        eng.set_output_mono(changed["audio.output_mono"])
    if "audio.bypass" in keys and hasattr(eng, "set_bypass"):
        eng.set_bypass(changed["audio.bypass"])
    for key, which in (("mixer.master_volume", "master"), ("mixer.speaker_volume", "speaker"),
                       ("mixer.voice_volume", "voice"), ("mixer.monitor_volume", "monitor")):
        if key in keys:
            try:
                eng.set_volume(which, changed[key])
            except KeyError:
                pass
    sp = getattr(app.ctl, "soundpad", None)
    if sp is not None and any(k.startswith("soundpad.") for k in keys):
        sp.apply_settings()
    if keys & {"audio.block_size", "audio.jitter_blocks"}:
        app.notify("info", "Restarting audio...")
        app.bg(eng.start)
    app.dirty = True

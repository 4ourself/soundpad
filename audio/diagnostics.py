"""Live signal-path checks (pure function of backend state) shown on the Help page."""
from __future__ import annotations

from .devices import is_virtual


def verdict(engine, soundpad=None) -> list[tuple[str, str]]:
    """[(level, message)] with level in ok | warn | bad. Explains where a sound would stop."""
    out: list[tuple[str, str]] = []
    o, s = engine.health["output"], engine.health["speaker"]
    if o["state"] != "ok":
        out.append(("bad", f"OUTPUT not open ({o['error'] or 'no device'}) - nothing reaches Discord / the game."))
    elif is_virtual(o["name"]):
        out.append(("ok", f"Output is a virtual cable ({o['name']}). In Discord / the game choose its recording "
                          "side as microphone (VB-Cable: 'CABLE Output')."))
    else:
        out.append(("bad", f"Output is '{o['name']}', a NORMAL device. Other apps cannot use it as a microphone - "
                           "select the virtual cable ('CABLE Input')."))
    if s["state"] == "disconnected":
        out.append(("warn", f"SPEAKER not open ({s['error']}). You will not hear your sounds."))
    elif s["state"] == "disabled" and s["error"]:
        out.append(("warn", f"Speaker is off: {s['error']}."))
    elif not engine.hear and s["state"] == "ok":
        out.append(("warn", "'Hear sounds' is off (Settings > Audio): sounds are sent to Output only."))
    if soundpad is not None:
        if not soundpad.listener_ok:
            out.append(("bad", "Global keyboard hook is not running - key presses are not detected "
                               f"({soundpad.keybinds.error[:60] or 'pynput missing'})."))
        else:
            out.append(("ok", "Keyboard hook is active in every window."))
        sounds = soundpad.library.sounds
        if not sounds:
            out.append(("warn", "No sounds loaded yet. Open Sounds > Load folder and paste a folder path."))
        elif not any(x.keybind for x in sounds):
            out.append(("warn", "No sound has a key yet. Open a sound and assign one."))
        bad = [x for x in sounds if x.state == "error"]
        if bad:
            out.append(("warn", f"{len(bad)} sound(s) cannot be decoded, e.g. {bad[0].name}: {bad[0].error[:50]}"))
    if engine.master_volume == 0:
        out.append(("warn", "Master volume is 0% (Settings > Audio)."))
    if engine.stats()["underruns"] > 5:
        out.append(("warn", "Buffer underruns detected - raise the audio buffer in Settings > Performance."))
    return out

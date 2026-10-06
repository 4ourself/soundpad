"""End-to-end with a fake backend: real-time streams + a (simulated) global key press -> sound at the
Output and on the Speaker."""
import sys
import threading
import time
import wave

import numpy as np

from tests import fake_sd

SR = 48000


def _peaks(x):
    seg = x[SR // 10:SR // 2]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    return sorted(f[np.argsort(spec)[-30:]])


def test_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setenv("SOUNDPAD_DATA", str(tmp_path))
    from audio.engine import SoundEngine
    from config import ConfigManager
    from soundpad.manager import SoundpadManager

    t = np.arange(SR) / SR
    with wave.open(str(tmp_path / "horn.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((0.5 * np.sin(2 * np.pi * 1000 * t) * 32767).astype(np.int16).tobytes())

    cfg = ConfigManager(tmp_path / "config.json")
    cfg.set("audio.output_device", "Fake Cable")
    cfg.set("audio.speaker_device", "Fake Speakers")
    sp = SoundpadManager(cfg, tmp_path / "sounds.json")
    sp._running = True
    threading.Thread(target=sp._work, daemon=True).start()
    sp.load_path(str(tmp_path))                            # paste the directory
    s = sp.library.sounds[0]
    sp.update_sound(s.id, keybind="ALT")
    eng = SoundEngine(cfg, sp.player)
    assert eng.start() == []
    assert eng.has_output and eng.has_speaker and eng.state == "RUNNING"
    time.sleep(0.5)
    n0, m0 = len(fake_sd.CAPTURED), len(fake_sd.MONITORED)
    sp.keybinds.handle_press("ALT", now=0)                 # global key event (simulated)
    sp.keybinds.handle_press("F4", now=0.05)               # ...then F4 of ALT+F4: nothing is swallowed or blocked
    time.sleep(1.2)
    out = np.concatenate(fake_sd.CAPTURED[n0:])[:, 0]
    spk = np.concatenate(fake_sd.MONITORED[m0:])[:, 0]
    eng.stop(); sp.stop()
    assert any(abs(f - 1000) < 30 for f in _peaks(out))    # the sound is at the Output (the "microphone")
    assert any(abs(f - 1000) < 30 for f in _peaks(spk))    # ...and on the speaker
    assert eng.stats()["underruns"] <= 3


def test_output_default_prefers_virtual_cable(tmp_path, monkeypatch):
    """With nothing chosen, Output picks an installed virtual cable instead of the normal speakers."""
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    from audio.engine import SoundEngine
    from config import ConfigManager
    from soundpad.player import SoundPlayer
    cfg = ConfigManager(tmp_path / "config.json")          # default = "default"; the system default is the speakers
    eng = SoundEngine(cfg, SoundPlayer())
    eng.start()
    assert eng.health["output"]["name"] == "Fake Cable"
    assert eng.health["speaker"]["name"] == "Fake Speakers"
    eng.stop()


def test_speaker_same_as_output_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    from audio.engine import SoundEngine
    from config import ConfigManager
    from soundpad.player import SoundPlayer
    cfg = ConfigManager(tmp_path / "config.json")
    cfg.set("audio.output_device", "Fake Cable")
    cfg.set("audio.speaker_device", "Fake Cable")
    eng = SoundEngine(cfg, SoundPlayer())
    eng.start()
    assert eng.health["output"]["state"] == "ok"
    assert eng.health["speaker"]["state"] == "disabled" and "same device" in eng.health["speaker"]["error"]
    eng.stop()

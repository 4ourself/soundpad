import time
import wave

import numpy as np
import pytest

from audio.engine import SoundEngine
from config import ConfigManager
from soundpad.manager import SoundpadManager

SR = 48000


def write_wav(path, freq=1000, seconds=0.5, sr=44100, channels=1, amp=0.5):
    t = np.arange(int(sr * seconds)) / sr
    x = (amp * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    if channels == 2:
        x = np.repeat(x[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(x.tobytes())


@pytest.fixture
def env(tmp_path):
    cfg = ConfigManager(tmp_path / "config.json")
    sp = SoundpadManager(cfg, tmp_path / "sounds.json")
    sp._running = True
    import threading
    sp._worker = threading.Thread(target=sp._work, daemon=True); sp._worker.start()
    sp.library.load()
    yield cfg, sp, tmp_path
    sp.stop()


def wait_ready(sp, s):
    t = time.time()
    while s.state != "ready" and time.time() - t < 5:
        time.sleep(0.01)
    assert s.state == "ready", s.error


def test_loader_converts_to_internal_format(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", sr=44100, channels=1, seconds=0.5)
    s = sp.add_sound(str(tmp / "a.wav"), "F6", 0.8)
    wait_ready(sp, s)
    assert s.audio.dtype == np.float32 and s.audio.shape[1] == 2
    assert abs(len(s.audio) - 24000) < 50          # resampled 44.1k -> 48k
    assert s.keybind == "F6"


def test_library_persistence(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav")
    sp.add_sound(str(tmp / "a.wav"), "alt", 0.5, name="Boom")
    import json
    data = json.loads((tmp / "sounds.json").read_text())
    assert data["sounds"][0]["name"] == "Boom" and data["sounds"][0]["keybind"] == "ALT"
    assert data["sounds"][0]["volume"] == 0.5


def test_add_validation(env):
    cfg, sp, tmp = env
    with pytest.raises(FileNotFoundError):
        sp.add_sound(str(tmp / "nope.wav"))
    (tmp / "x.txt").write_text("hi")
    with pytest.raises(ValueError):
        sp.add_sound(str(tmp / "x.txt"))
    (tmp / "junk.xyz").write_bytes(b"\x00" * 64)
    with pytest.raises(ValueError):
        sp.add_sound(str(tmp / "junk.xyz"))
    write_wav(tmp / "a.wav")
    with pytest.raises(ValueError):
        sp.add_sound(str(tmp / "a.wav"), "notakey")


def test_key_triggers_playback_and_per_sound_volume(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", amp=0.5, sr=48000)
    s = sp.add_sound(str(tmp / "a.wav"), "ALT", 0.5)
    wait_ready(sp, s)
    sp.keybinds.handle_press("ALT", now=0)
    time.sleep(0.2)
    block = sp.player.render(480)
    assert abs(np.abs(block).max() - 0.25) < 0.01      # 0.5 amp * 0.5 volume


def test_cooldown(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", sr=48000)
    s = sp.add_sound(str(tmp / "a.wav"), "F1")
    wait_ready(sp, s)
    for _ in range(3):
        sp.request_play(s.id)
    time.sleep(0.2)
    assert len(sp.player._voices) == 1


def test_max_simultaneous_and_overlap(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", sr=48000, seconds=2)
    s = sp.add_sound(str(tmp / "a.wav"), "F1")
    wait_ready(sp, s)
    sp.player.max_simultaneous = 3
    for _ in range(5):
        sp.player.play(s.id, s.name, 1.0, audio=s.audio)
    assert len(sp.player.active_names()) == 3
    sp.player.allow_overlap = False
    sp.player.play(s.id, s.name, 1.0, audio=s.audio)
    assert len(sp.player.active_names()) == 1


def test_sound_finishes_and_is_removed(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", sr=48000, seconds=0.05)
    s = sp.add_sound(str(tmp / "a.wav"), "F1"); wait_ready(sp, s)
    sp.player.play(s.id, s.name, 1.0, audio=s.audio)
    for _ in range(10):
        sp.player.render(480)
    assert sp.player._voices == []


def test_streaming_long_file(env):
    cfg, sp, tmp = env
    sp.library.stream_threshold = 1.0
    write_wav(tmp / "long.wav", sr=44100, seconds=3, freq=500)
    s = sp.add_sound(str(tmp / "long.wav"), "F2"); wait_ready(sp, s)
    assert s.streaming and s.audio is None
    sp.play_now(s.id)
    time.sleep(0.3)
    total, peak = 0, 0.0
    for _ in range(400):
        b = sp.player.render(480); peak = max(peak, float(np.abs(b).max())); total += 480
        time.sleep(0.0005)
        if not sp.player._voices:
            break
    assert peak > 0.4 and 2.9 * SR < total < 3.2 * SR


def test_engine_renders_player_to_output_and_speaker(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", amp=0.4, sr=48000, freq=1000, seconds=1)
    s = sp.add_sound(str(tmp / "a.wav"), "F1", 1.0)
    wait_ready(sp, s)
    eng = SoundEngine(cfg, sp.player)
    eng.has_output = eng.has_speaker = True
    sp.player.play(s.id, s.name, 1.0, audio=s.audio)
    outs, spk = [], []
    for _ in range(40):
        outs.append(eng._fill_output(480))
        spk.append(eng._fill_speaker(480))
    out, spk = np.concatenate(outs), np.concatenate(spk)
    spec = np.abs(np.fft.rfft(out[4800:, 0] * np.hanning(len(out) - 4800)))
    assert abs(np.argmax(spec) * SR / (len(out) - 4800) - 1000) < 30
    assert abs(np.abs(out).max() - 0.4) < 0.02                      # no voice effects, no extra gain
    assert abs(np.abs(spk).max() - 0.4) < 0.02                      # the speaker gets the same mix
    eng.set_volume("speaker", 0.5)
    for _ in range(10):
        eng._fill_output(480)
    assert abs(np.abs(eng._fill_speaker(480)).max() - 0.2) < 0.03


def test_engine_hear_off_keeps_output(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", amp=0.4, sr=48000, seconds=1)
    s = sp.add_sound(str(tmp / "a.wav"), "F1"); wait_ready(sp, s)
    eng = SoundEngine(cfg, sp.player)
    eng.has_output = eng.has_speaker = True
    eng.set_hear(False)
    sp.player.play(s.id, s.name, 1.0, audio=s.audio)
    assert np.abs(eng._fill_output(480)).max() > 0.3
    assert np.abs(eng._fill_speaker(480)).max() == 0


def test_engine_speaker_alone_still_plays(env):
    """No Output device: the Speaker callback becomes the clock, so the pad works on speakers only."""
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", amp=0.4, sr=48000, seconds=1)
    s = sp.add_sound(str(tmp / "a.wav"), "F1"); wait_ready(sp, s)
    eng = SoundEngine(cfg, sp.player)
    eng.has_output, eng.has_speaker = False, True
    sp.player.play(s.id, s.name, 1.0, audio=s.audio)
    assert abs(np.abs(eng._fill_speaker(480)).max() - 0.4) < 0.02


def test_engine_latency_is_bounded_when_output_runs_fast(env):
    cfg, sp, tmp = env
    eng = SoundEngine(cfg, sp.player)
    eng.has_output = eng.has_speaker = True
    for _ in range(100):               # output renders, speaker never pulls -> ring overflows safely
        eng._fill_output(480)
    for _ in range(3):
        eng._fill_output(480); eng._fill_output(480)       # producer twice as fast
        eng._fill_speaker(480)
    assert eng._ring.available <= 480 * 6


def test_master_volume_and_limiter(env):
    cfg, sp, tmp = env
    write_wav(tmp / "a.wav", amp=0.9, sr=48000, seconds=1)
    s = sp.add_sound(str(tmp / "a.wav"), "F1"); wait_ready(sp, s)
    eng = SoundEngine(cfg, sp.player)
    eng.set_volume("master", 2.0)
    for _ in range(3):
        sp.player.play(s.id, s.name, 2.0, audio=s.audio)     # wildly too loud
    assert np.abs(eng._render(480)).max() <= 1.0


def test_soft_limiter_never_exceeds_one():
    from audio.limiter import soft_limit
    x = np.linspace(-5, 5, 1000).astype(np.float32)
    assert np.abs(soft_limit(x)).max() <= 1.0
    y = np.linspace(-0.5, 0.5, 100).astype(np.float32)
    assert np.array_equal(soft_limit(y), y)

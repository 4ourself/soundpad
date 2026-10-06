"""Loading by pasted path: folders, single files, every audio format, saved folders, re-scan."""
import json
import time
import wave

import numpy as np
import pytest

from config import ConfigManager
from soundpad.manager import SoundpadManager

SR = 48000


def tone(seconds=0.2, freq=440, sr=SR):
    return (0.3 * np.sin(2 * np.pi * freq * np.arange(int(sr * seconds)) / sr)).astype(np.float32)


@pytest.fixture
def sp(tmp_path):
    cfg = ConfigManager(tmp_path / "config.json")
    m = SoundpadManager(cfg, tmp_path / "sounds.json")
    m.library.load()
    yield m
    m.stop()


def wait_ready(m, timeout=8):
    t = time.time()
    while time.time() - t < timeout:
        if all(s.state in ("ready", "error") for s in m.library.sounds):
            return
        time.sleep(0.02)


def test_folder_with_every_format(sp, tmp_path):
    import soundfile as sf
    d = tmp_path / "pack"
    d.mkdir()
    sf.write(d / "a.wav", tone(), SR)
    sf.write(d / "b.ogg", tone(), SR)
    sf.write(d / "c.flac", tone(), SR)
    sf.write(d / "d.mp3", tone(), SR)                       # libsndfile >= 1.1 writes mp3
    (d / "notes.txt").write_text("hello")
    (d / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    res = sp.load_path(str(d))
    assert res.kind == "folder" and res.added >= 4
    names = sorted(s.name for s in sp.library.sounds)
    assert {"a", "b", "c", "d"} <= set(names) and "notes" not in names and "cover" not in names
    wait_ready(sp)
    assert all(s.state == "ready" for s in sp.library.sounds), [(s.name, s.error) for s in sp.library.sounds]
    for s in sp.library.sounds:
        assert s.audio.dtype == np.float32 and s.audio.shape[1] == 2
        assert abs(len(s.audio) - 0.2 * SR) < 0.02 * SR


def test_m4a_and_aac_via_pyav(sp, tmp_path):
    av = pytest.importorskip("av")
    d = tmp_path / "pack"
    d.mkdir()
    for name, fmt, codec in (("x.m4a", "ipod", "aac"), ("y.wma", "asf", "wmav2"), ("z.webm", "webm", "libopus")):
        try:
            with av.open(str(d / name), "w", format=fmt) as c:
                st = c.add_stream(codec, rate=SR)
                st.layout = "stereo"
                frame = av.AudioFrame.from_ndarray(np.stack([tone(0.5, 330)] * 2, 1).reshape(1, -1),
                                                   format="flt", layout="stereo")
                frame.sample_rate = SR
                frame.pts = 0
                for pkt in st.encode(frame):
                    c.mux(pkt)
                for pkt in st.encode(None):
                    c.mux(pkt)
        except Exception:  # noqa: BLE001 - this ffmpeg build lacks the encoder
            (d / name).unlink(missing_ok=True)
    made = [p.name for p in d.iterdir()]
    print("encoded:", made)
    if not made:
        pytest.skip("no encoder available")
    res = sp.load_path(str(d))
    assert res.added == len(made)
    wait_ready(sp)
    for s in sp.library.sounds:
        assert s.state == "ready", (s.name, s.error)
        assert 0.3 * SR < len(s.audio) < 0.8 * SR


def test_unknown_extension_is_probed(sp, tmp_path):
    d = tmp_path / "pack"
    d.mkdir()
    import soundfile as sf
    sf.write(d / "weird.sound", tone(), SR, format="WAV")        # audio under an unknown extension
    (d / "junk.dat").write_bytes(b"not audio at all" * 10)
    res = sp.load_path(str(d))
    assert [s.name for s in sp.library.sounds] == ["weird"] and res.added == 1
    wait_ready(sp)
    assert sp.library.sounds[0].state == "ready"


def test_subfolders_flag(sp, tmp_path):
    import soundfile as sf
    d = tmp_path / "pack"
    (d / "deep" / "deeper").mkdir(parents=True)
    sf.write(d / "top.wav", tone(), SR)
    sf.write(d / "deep" / "deeper" / "low.wav", tone(), SR)
    sp.cfg.set("soundpad.scan_subfolders", False)
    assert sp.load_path(str(d)).added == 1
    sp.cfg.set("soundpad.scan_subfolders", True)
    assert sp.load_path(str(d)).added == 1                       # only the deep one is new
    assert sorted(s.name for s in sp.library.sounds) == ["low", "top"]


def test_paste_forms_and_single_file(sp, tmp_path):
    import soundfile as sf
    d = tmp_path / "my sounds"
    d.mkdir()
    sf.write(d / "one.wav", tone(), SR)
    for text in (f'"{d}"', f"'{d}'", f"  {d}{'/'}  ", f"file:///{d}"):
        sp.library._sounds.clear()
        sp.library.removed.clear()
        assert sp.load_path(text).added == 1, text
    res = sp.load_path(str(d / "one.wav"))                       # a single file that is already known
    assert res.kind == "file" and res.added == 0 and "already" in res.summary()
    sp.library._sounds.clear()
    assert sp.load_path(f'"{d / "one.wav"}"').added == 1


def test_errors(sp, tmp_path):
    with pytest.raises(FileNotFoundError):
        sp.load_path(str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        sp.load_path("   ")
    (tmp_path / "x.txt").write_text("hi")
    with pytest.raises(ValueError):
        sp.load_path(str(tmp_path / "x.txt"))
    empty = tmp_path / "empty"
    empty.mkdir()
    res = sp.load_path(str(empty))
    assert res.added == 0 and "No audio files" in res.summary()


def test_dedupe_and_rescan_keep_bindings(sp, tmp_path):
    import soundfile as sf
    d = tmp_path / "pack"
    d.mkdir()
    sf.write(d / "a.wav", tone(), SR)
    sp.load_path(str(d))
    a = sp.library.sounds[0]
    sp.update_sound(a.id, keybind="ctrl+1", volume=0.7, name="Alpha")
    assert sp.load_path(str(d)).added == 0                       # loading twice adds nothing
    sf.write(d / "b.wav", tone(), SR)                            # the folder gains a file
    assert sp.rescan_folders() == 1
    got = {s.file.split("/")[-1].split("\\")[-1]: s for s in sp.library.sounds}
    assert got["a.wav"].keybind == "CTRL+1" and got["a.wav"].volume == 0.7 and got["a.wav"].name == "Alpha"
    assert got["b.wav"].keybind == ""                            # new file: no key
    assert [b.spec for b in sp.keybinds.bindings] == ["CTRL+1"]  # existing binding still registered
    assert sp.rescan_folders() == 0


def test_saved_folders_rescanned_at_start_and_removed_stay_removed(tmp_path):
    import soundfile as sf
    d = tmp_path / "pack"
    d.mkdir()
    sf.write(d / "a.wav", tone(), SR)
    sf.write(d / "b.wav", tone(), SR)
    cfg = ConfigManager(tmp_path / "config.json")
    m = SoundpadManager(cfg, tmp_path / "sounds.json")
    m.start(listener=False)
    m.load_path(str(d))
    b = next(s for s in m.library.sounds if s.name == "b")
    m.remove_sound(b.id)                                         # user removes b
    m.stop()
    sf.write(d / "c.wav", tone(), SR)                            # while closed, c appears
    cfg2 = ConfigManager(tmp_path / "config.json")
    m2 = SoundpadManager(cfg2, tmp_path / "sounds.json")
    m2.start(listener=False)
    t = time.time()
    while len(m2.library.sounds) < 2 and time.time() - t < 5:
        time.sleep(0.05)
    assert sorted(s.name for s in m2.library.sounds) == ["a", "c"]      # c picked up, b stays gone
    m2.load_path(str(d))                                         # an explicit load brings b back
    assert sorted(s.name for s in m2.library.sounds) == ["a", "b", "c"]
    m2.stop()
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["soundpad"]["folders"] == [str(d)]


def test_long_file_streams_via_pyav(sp, tmp_path):
    av = pytest.importorskip("av")
    sp.library.stream_threshold = 0.5
    p = tmp_path / "long.m4a"
    try:
        with av.open(str(p), "w", format="ipod") as c:
            st = c.add_stream("aac", rate=SR)
            st.layout = "stereo"
            frame = av.AudioFrame.from_ndarray(np.stack([tone(1.5)] * 2, 1).reshape(1, -1), format="flt", layout="stereo")
            frame.sample_rate = SR
            frame.pts = 0
            for pkt in st.encode(frame):
                c.mux(pkt)
            for pkt in st.encode(None):
                c.mux(pkt)
    except Exception:  # noqa: BLE001
        pytest.skip("no aac encoder")
    sp.load_path(str(p))
    wait_ready(sp)
    s = sp.library.sounds[0]
    assert s.state == "ready" and s.streaming
    sp.start(listener=False)
    sp.play_now(s.id)
    time.sleep(0.3)
    total, peak = 0, 0.0
    for _ in range(500):
        b = sp.player.render(480)
        peak, total = max(peak, float(np.abs(b).max())), total + 480
        time.sleep(0.0005)
        if not sp.player._voices:
            break
    assert peak > 0.2 and 1.3 * SR < total < 1.9 * SR

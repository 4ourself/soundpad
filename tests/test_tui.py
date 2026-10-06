"""Terminal UI tests: diff-render correctness (pyte), key flows, sounds playing independent of the visible
screen, loading by pasted path, the live KEYS panel, Windows key decoding (fake msvcrt) and a real pty run."""
import io
import os
import sys
import time
import wave

import numpy as np
import pytest

from tests import fake_sd

SR = 48000
pyte = pytest.importorskip("pyte")


class FakeTerm:
    def __init__(self, w, h):
        self.w, self.h = w, h

    def size(self):
        return self.w, self.h

    def write(self, s):
        pass

    def read_keys(self, t=0):
        return []

    def drain_input(self):
        pass


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setenv("SOUNDPAD_DATA", str(tmp_path))
    from audio.engine import SoundEngine
    from config import ConfigManager
    from controller import Controller
    from soundpad.manager import SoundpadManager
    from ui.app import App

    t = np.arange(SR * 3) / SR
    wav = tmp_path / "horn.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((0.5 * np.sin(2 * np.pi * 1000 * t) * 32767).astype(np.int16).tobytes())
    cfg = ConfigManager(tmp_path / "config.json")
    cfg.first_run = False
    cfg.set("audio.output_device", "Fake Cable")
    cfg.set("audio.speaker_device", "Fake Speakers")
    sp = SoundpadManager(cfg, tmp_path / "sounds.json")
    eng = SoundEngine(cfg, sp.player)
    ctl = Controller(cfg, eng, sp)
    term = FakeTerm(80, 24)
    app = App(ctl, term)
    app.boot.done = True
    app.splash = False                 # tests start on the menu, not the title screen
    eng.start()
    sp.start(listener=False)
    sp.add_sound(str(wav), "ALT", 1.0, "Horn", 0)
    app.wav = wav
    app.dir = tmp_path
    yield app
    ctl.shutdown()


def press(app, *names):
    from ui.keys import Key
    app.ignore_keys_until = 0
    for n in names:
        key = Key("char", n) if len(n) == 1 else (Key("space", " ") if n == "space" else Key(n))
        app.handle_key(key)
    app.update()


def frame(app):
    app.update()
    app.render()
    return app.cv.text_lines()


# ------------------------------------------------------------------ diff renderer
def test_diff_render_matches_canvas(rig):
    """The incremental escape sequences written by App.render(), fed to a real terminal emulator,
    must reproduce the canvas exactly - across page changes and a resize."""
    app = rig
    screen = pyte.Screen(80, 24)
    stream = pyte.Stream(screen)
    written = []
    app.term.write = lambda s: (written.append(s), stream.feed(s))
    sizes = []
    for step in range(40):
        if step == 5:
            app.goto("sounds"); press(app, "down", "down")
        if step == 10:
            app.goto("settings"); press(app, "enter", "down")
        if step == 15:
            app.goto("help")
        if step == 20:
            app.goto("sounds"); press(app, "right")
        if step == 25:
            press(app, "backspace"); app.goto("home")
        if step == 30:
            app.term.w, app.term.h = 100, 30      # resize -> forced full repaint
            screen.resize(30, 100)
        n = sum(map(len, written))
        app.update()
        app.render()
        sizes.append(sum(map(len, written)) - n)
        got = [l.rstrip() for l in screen.display]
        want = [l.rstrip() for l in app.cv.text_lines()]
        assert got == want, f"step {step}\n" + "\n".join(got) + "\n---\n" + "\n".join(want)
    # steady state frames are tiny (diff), not full repaints
    assert min(sizes[1:5]) < 300


def test_unchanged_frame_emits_nothing(rig):
    app = rig
    app.term.write = lambda s: None
    app.goto("settings")
    app.update(); app.render()
    app.draw()
    assert app.scr.flush(app.cv, app.theme) == ""


def test_no_key_hints_on_screen(rig):
    """The UI shows no key legend anywhere (controls: arrows / Enter / Backspace)."""
    app = rig
    banned = ("ESC", "SPACE", "ENTER", "BACKSPACE", "F1", "Navigate", "Select  ", "Toggle")
    for page in ["home", "sounds", "settings", "help"]:
        app.goto(page)
        text = "\n".join(frame(app))
        assert not any(b in text for b in banned), (page, text)


def test_backspace_navigation_and_quit(rig):
    app = rig
    app.goto("sounds")
    press(app, "backspace")
    assert app.page == "home"
    press(app, "backspace")
    assert app.modal is not None                      # quit confirmation
    press(app, "backspace")                           # = No
    assert app.modal is None and not app.quit_requested
    press(app, "backspace", "left", "enter")
    assert app.quit_requested


def test_load_folder_by_pasting_path(rig):
    """Sounds > '+ Load folder or file' > paste a directory > Enter: every audio file is added."""
    import soundfile as sf
    app = rig
    folder = app.dir / "pack"
    (folder / "sub").mkdir(parents=True)
    tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(4800) / SR)).astype(np.float32)
    sf.write(folder / "a.ogg", tone, SR)
    sf.write(folder / "b.flac", tone, SR)
    sf.write(folder / "sub" / "c.wav", tone, SR)
    (folder / "readme.txt").write_text("not audio")
    app.goto("sounds")
    press(app, "enter")                                  # first row: load
    assert app.modal is not None
    assert "LOAD SOUNDS" in "\n".join(frame(app))
    for ch in f'"{folder}"':                             # a pasted, quoted path
        press(app, ch)
    assert "FOLDER" in "\n".join(frame(app))             # live check of what was pasted
    press(app, "enter")
    deadline = time.time() + 5
    while len(app.ctl.sounds()) < 4 and time.time() < deadline:
        time.sleep(0.05)
    names = sorted(s.name for s in app.ctl.sounds())
    assert names == ["Horn", "a", "b", "c"]
    app.update()
    assert any("Loaded 3 sounds" in n.text for n in app.notes)


def test_edit_sound_form_with_conflict(rig):
    app = rig
    wav2 = app.dir / "two.wav"
    import shutil
    shutil.copy(app.wav, wav2)
    s2 = app.ctl.soundpad.add_sound(str(wav2), "", 1.0, "Two")
    app.goto("sounds")
    press(app, "down", "down", "down")                   # actions x2 -> Horn -> Two
    assert app.current.selected().name == "Two"
    press(app, "right")                                  # editor of "Two", focus on Key
    assert type(app.current).__name__ == "SoundForm"
    press(app, "enter")                                  # record key
    frame(app)                                           # (no global hook in tests -> typed fallback)
    for ch in "ALT":
        press(app, ch)
    press(app, "enter")
    assert app.modal is None
    press(app, "down", "down", "down", "enter")          # volume, cooldown, SAVE -> conflict dialog
    assert app.modal is not None
    assert "ALREADY" in "\n".join(frame(app))
    press(app, "enter")                                  # default button is the safe one: CANCEL
    assert [s.keybind for s in app.ctl.sounds() if s.name == "Horn"] == ["ALT"]
    press(app, "enter")                                  # SAVE again -> dialog
    press(app, "left", "enter")                          # REPLACE
    assert {s.name: s.keybind for s in app.ctl.sounds()} == {"Horn": "", "Two": "ALT"}


def test_keys_panel_shows_held_and_matches(rig):
    app = rig
    app.goto("sounds")
    kb = app.ctl.soundpad.keybinds
    app.ctl.soundpad.keybinds._listener = object()          # pretend the hook is running
    kb.handle_press("ALT", raw="alt", now=1.0)
    kb.handle_press("F4", raw="f4", now=1.1)
    text = "\n".join(frame(app))
    assert "KEYS" in text and "HELD" in text
    assert " ALT " in text and " F4 " in text
    assert "ALT+F4" in text
    kb.handle_release("f4"); kb.handle_release("alt")
    text = "\n".join(frame(app))
    assert "Horn" in text.split("KEYS")[1]                   # ALT press shows the sound it fired
    kb._listener = None


# ------------------------------------------------------------------ critical: soundpad vs UI
def _out_peak(n0, seconds=0.5):
    time.sleep(seconds)
    blocks = fake_sd.CAPTURED[n0:]
    return float(np.abs(np.concatenate(blocks)).max()) if blocks else 0.0


@pytest.mark.parametrize("page", ["home", "sounds", "settings", "help"])
def test_alt_triggers_on_every_tab(rig, page):
    app = rig
    app.goto(page)
    frame(app)
    sp = app.ctl.soundpad
    n0 = len(fake_sd.CAPTURED)
    sp.keybinds.handle_press("ALT", now=0)
    time.sleep(0.4)
    assert sp.player.active_ids()
    notes = app.ctl.drain_notifications()
    assert any("Horn" in t and "ALT" in t for _, t in notes)
    assert _out_peak(n0, 0.2) > 0.2


def test_alt_f4_with_single_alt_bind(rig):
    """No hardcoded F4 exception: pressing ALT first fires the bind, F4 afterwards is just another key."""
    sp = rig.ctl.soundpad
    sp.keybinds.handle_press("ALT", now=0)
    time.sleep(0.3)
    assert sp.player.active_ids()


def test_tab_switching_keeps_sound_and_listener(rig):
    app = rig
    sp = app.ctl.soundpad
    sp.keybinds.handle_press("ALT", now=0)
    time.sleep(0.3)
    sid = next(iter(sp.player.active_ids()))
    for page in ["sounds", "settings", "help", "home", "sounds"]:
        app.goto(page)
        frame(app)
        time.sleep(0.1)
        assert sid in sp.player.active_ids()          # 3 s sound keeps playing through every tab change
    assert sp._running
    sp.keybinds.handle_press("ALT", now=10)           # ...and the key hook path still triggers afterwards


def test_master_volume_and_hear_toggle(rig):
    app = rig
    eng = app.ctl.engine
    eng.set_volume("master", 0.5)
    n0, m0 = len(fake_sd.CAPTURED), len(fake_sd.MONITORED)
    app.ctl.soundpad.keybinds.handle_press("ALT", now=0)
    assert abs(_out_peak(n0, 0.6) - 0.25) < 0.03            # 0.5 horn * 0.5 master
    assert np.abs(np.concatenate(fake_sd.MONITORED[m0:])).max() > 0.2    # the speaker hears it too
    app.ctl.stop_all_sounds()
    time.sleep(0.2)
    eng.set_hear(False)
    time.sleep(0.2)
    m1 = len(fake_sd.MONITORED)
    app.ctl.play(app.ctl.sounds()[0].id)
    time.sleep(0.4)
    assert np.abs(np.concatenate(fake_sd.MONITORED[m1:])).max() < 1e-6   # speaker silent, Output unaffected


def test_stop_all_key(rig):
    app = rig
    app.ctl.soundpad.keybinds.handle_press("ALT", now=0)
    time.sleep(0.3)
    app.goto("sounds")
    press(app, "down", "enter")                       # "Stop all sounds" row
    time.sleep(0.5)
    assert not [v for v in app.ctl.playing() if not v["fading"]]


# ------------------------------------------------------------------ rendering robustness
@pytest.mark.parametrize("size", [(80, 24), (120, 40), (60, 20), (40, 12), (30, 8)])
def test_every_screen_renders_at_every_size(rig, size):
    from ui.screens.devices import DevicesScreen
    from ui.screens.sound_form import SoundForm
    app = rig
    app.term.w, app.term.h = size
    for page in ["home", "sounds", "settings", "help"]:
        app.goto(page)
        for keys in [(), ("down",), ("enter",), ("right",), ("backspace",)]:
            press(app, *keys)
            lines = frame(app)
            assert len(lines) == size[1] and all(len(l) == size[0] for l in lines)
            if app.modal:
                press(app, "backspace")
    for scr in (DevicesScreen(app), DevicesScreen(app, True), SoundForm(app, app.ctl.sounds()[0])):
        app.goto("sounds"); app.push(scr); frame(app)
    app.goto("sounds"); press(app, "enter"); frame(app)       # the load prompt, too


def test_ascii_fallback_has_no_non_ascii(rig):
    app = rig
    app.cfg.set("ui.charset", "ascii")
    app.cfg.set("ui.colors", "mono")
    app.rebuild_theme()
    for page in ["home", "sounds", "settings", "help"]:
        app.goto(page)
        text = "\n".join(frame(app))
        assert all(ord(c) < 128 for c in text), page


# ------------------------------------------------------------------ Windows input decoding (fake msvcrt)
def test_decode_windows_keys():
    from ui.keys import decode_windows

    def run(seq):
        q = list(seq)
        return [str(k) for k in decode_windows(lambda: q.pop(0), lambda: bool(q))]
    assert run("\xe0H\xe0P\xe0K\xe0M") == ["up", "down", "left", "right"]
    assert run("\x00;\x00<") == ["f1", "f2"]
    assert run("a \r\x1b\t\x08") == ["a", "space", "enter", "esc", "tab", "backspace"]
    assert run("\x00\x0f") == ["backtab"]
    assert run("\xe0S\xe0I\xe0Q") == ["delete", "pgup", "pgdn"]
    assert run("\x03") == ["ctrl+c"]


def test_parse_ansi():
    from ui.keys import parse_ansi
    keys, rest = parse_ansi("\x1b[A\x1b[B\x1b[1;5C\x1bOQ x\x1b[3~")
    assert [str(k) for k in keys][:2] == ["up", "down"] and rest == ""
    assert "f2" in [str(k) for k in keys] and "delete" in [str(k) for k in keys]
    assert parse_ansi("\x1b")[1] == "\x1b"


# ------------------------------------------------------------------ real pty run
@pytest.mark.skipif(os.name == "nt", reason="pty is POSIX only")
def test_pty_full_run(tmp_path):
    import pty
    import select
    import struct
    import fcntl
    import termios
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, SOUNDPAD_DATA=str(tmp_path), TERM="xterm-256color", PYTHONPATH=root)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    p = subprocess.Popen([sys.executable, os.path.join(root, "main.py"), "--fake-audio"], cwd=root, env=env,
                         stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    screen = pyte.Screen(80, 24)
    stream = pyte.ByteStream(screen)
    raw = bytearray()

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            r, _, _ = select.select([master], [], [], 0.05)
            if r:
                try:
                    d = os.read(master, 65536)
                except OSError:
                    return
                raw.extend(d)
                stream.feed(d)

    def send(s, wait=0.4):
        os.write(master, s.encode())
        pump(wait)

    try:
        pump(1.5)
        text = "\n".join(screen.display)
        assert "soundpad" in text, text
        assert "PRESS ENTER" in text and "FIRST RUN SETUP" not in text      # the logo waits; no setup yet
        send("\r", 0.8)                                # Enter on the title screen -> first-run setup
        text = "\n".join(screen.display)
        assert "FIRST RUN SETUP" in text, text
        send("\x1b[B", 0.3)                            # down to [FINISH SETUP]
        send("\r", 0.8)                                # Enter: start audio (virtual cable preselected)
        send("\r", 0.6)                                # Sounds from the boot menu
        text = "\n".join(screen.display)
        assert "SOUNDS" in text and "Load folder or file" in text, text
        folder = tmp_path / "pack"
        folder.mkdir()
        import soundfile as sf
        sf.write(folder / "boom.ogg", (0.3 * np.sin(np.arange(4800) / 7)).astype(np.float32), 48000)
        send("\r", 0.5)                                # open the load prompt
        send(str(folder), 0.4)                         # paste the directory
        send("\r", 1.0)                               # Enter: load
        text = "\n".join(screen.display)
        assert "boom" in text and "1 sounds" in text, text
        send("\x7f", 0.5)                             # Backspace -> home
        send("\x1b[B\r", 0.5)                         # Settings
        assert "SETTINGS" in "\n".join(screen.display)
        send("\x7f\x7f", 0.5)                         # back, back -> quit dialog
        assert "QUIT" in "\n".join(screen.display).upper()
        send("\x1b[D\r", 0.3)                         # choose QUIT, Enter
        p.wait(timeout=8)
        pump(0.3)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 0
    assert b"\x1b[?1049l" in raw and b"\x1b[?25h" in raw       # alt screen left, cursor restored
    assert not os.path.exists(tmp_path / "ui_error.log"), "a frame/key handler raised (swallowed by the loop)"
    assert os.path.exists(tmp_path / "config.json")
    import json
    cfg = json.load(open(tmp_path / "config.json"))
    assert cfg["soundpad"]["folders"] == [str(tmp_path / "pack")]      # the loaded folder is remembered
    assert [s["name"] for s in json.load(open(tmp_path / "sounds.json"))["sounds"]] == ["boom"]

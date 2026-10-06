"""Config files: export / import (shared format between Voicer and Soundpad), and the first-run setup that waits
for the title screen."""
import json

import pytest

from tests.test_tui import frame, press, rig  # noqa: F401  (rig is a fixture)

import configfile
from config import DEFAULTS


def app_name(app):
    return "soundpad" if hasattr(app.ctl, "soundpad") else "voicer"


# ------------------------------------------------------------------ first run waits for the logo
def test_first_run_setup_waits_for_title_screen(rig):
    app = rig
    app.splash = True
    app.pending_setup = True                    # what the boot thread sets on a first run
    app.goto("home")
    for _ in range(3):
        frame(app)
    assert "FIRST RUN SETUP" not in "\n".join(frame(app)) and type(app.current).__name__ == "HomeScreen"
    assert "PRESS ENTER" in "\n".join(frame(app))
    press(app, "enter")                         # leave the title screen
    press(app)                                  # next update opens the setup
    assert type(app.current).__name__ == "DevicesScreen" and app.current.first_run
    assert "FIRST RUN SETUP" in "\n".join(frame(app))
    assert app.pending_setup is False


def test_first_run_setup_opens_directly_without_title_screen(rig):
    app = rig
    app.splash = False
    app.pending_setup = True
    press(app)
    assert type(app.current).__name__ == "DevicesScreen"


def test_first_run_setup_not_over_a_dialog(rig):
    app = rig
    app.splash = False
    app.confirm_quit()
    app.pending_setup = True
    press(app)
    assert type(app.current).__name__ == "HomeScreen" and app.pending_setup


# ------------------------------------------------------------------ file format
def test_export_has_settings_but_never_devices(rig, tmp_path):
    app = rig
    app.cfg.set("ui.borders", "square")
    app.cfg.set("audio.block_size", 960)
    path, n = configfile.export_file(app.cfg, DEFAULTS, app_name(app), str(tmp_path / "out" / "mine"))
    assert path.endswith("mine.json") and n > 15
    data = json.load(open(path, encoding="utf-8"))
    assert data["format"] == configfile.FORMAT and data["app"] == app_name(app)
    s = data["settings"]
    assert s["ui"]["borders"] == "square" and s["audio"]["block_size"] == 960
    flat = [f"{a}.{b}" for a, body in s.items() for b in body]
    assert not [k for k in flat if k.endswith("_device")]
    assert "audio.host_api" not in flat and "audio.sample_rate" not in flat and "soundpad.folders" not in flat
    assert "effects" not in s and "presets" not in s
    assert "Fake Cable" not in json.dumps(data)


def test_export_to_directory_and_errors(rig, tmp_path):
    app = rig
    p, _ = configfile.export_file(app.cfg, DEFAULTS, app_name(app), str(tmp_path))
    assert p.endswith(configfile.DEFAULT_NAME)
    p, _ = configfile.export_file(app.cfg, DEFAULTS, app_name(app), f'  "{tmp_path / "q.json"}" ')   # pasted with quotes
    assert p.endswith("q.json")
    with pytest.raises(configfile.ConfigFileError):
        configfile.export_file(app.cfg, DEFAULTS, app_name(app), "")
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    with pytest.raises(configfile.ConfigFileError):
        configfile.export_file(app.cfg, DEFAULTS, app_name(app), str(blocker / "sub" / "a.json"))


def test_round_trip_restores_settings_but_keeps_devices(rig, tmp_path):
    from ui.colors import Paint
    app = rig
    app.apply_paint("accent", Paint("gradient", [["#112233", 80], ["#AABBCC", 100]]))
    app.cfg.set("ui.accent", "custom")
    app.cfg.set("ui.animation", "slide")
    app.cfg.set("ui.menu_position", "left")
    path, _ = configfile.export_file(app.cfg, DEFAULTS, app_name(app), str(tmp_path / "c.json"))
    app.cfg.set("ui.accent", "green")
    app.cfg.set("ui.animation", "none")
    app.cfg.set("ui.menu_position", "right")
    app.cfg.set("audio.output_device", "Other Device")
    rep = configfile.import_file(app.cfg, DEFAULTS, path)
    assert app.cfg.get("ui.accent") == "custom" and app.cfg.get("ui.animation") == "slide"
    assert app.cfg.get("ui.menu_position") == "left"
    assert app.cfg.get("ui.accent_paint")["stops"] == [["#112233", 80], ["#AABBCC", 100]]
    assert app.cfg.get("audio.output_device") == "Other Device"          # devices untouched
    assert {"ui.accent", "ui.animation", "ui.menu_position"} <= set(rep.changed) and not rep.rejected
    assert "changed" in rep.summary()


def test_foreign_file_from_the_other_app(rig, tmp_path):
    """A file exported by the other app: shared keys apply, its own keys are ignored, devices never."""
    app = rig
    voicer = {"format": configfile.FORMAT, "version": 1, "app": "voicer", "settings": {
        "ui": {"accent": "magenta", "borders": "square", "waveform": False, "logo_glow": "always"},
        "audio": {"block_size": 960, "jitter_blocks": 3, "input_device": "Mic X", "output_device": "Cable Y",
                  "monitor_device": "Z", "hear_output": True, "output_mono": True, "bypass": True},
        "mixer": {"voice_volume": 0.5, "monitor_volume": 0.7}}}
    soundpad = {"format": configfile.FORMAT, "version": 1, "app": "soundpad", "settings": {
        "ui": {"accent": "magenta", "borders": "square", "logo_glow": "always"},
        "audio": {"block_size": 960, "jitter_blocks": 3, "output_device": "Cable Y", "speaker_device": "S",
                  "hear_sounds": False},
        "mixer": {"master_volume": 0.5, "speaker_volume": 0.7},
        "soundpad": {"cooldown_ms": 400, "folders": ["/x"], "stop_all_keybind": "F12"}}}
    before = app.cfg.get("audio.output_device")
    for name, data in (("voicer", voicer), ("soundpad", soundpad)):
        f = tmp_path / f"{name}.json"
        f.write_text(json.dumps(data))
        app.cfg.set("ui.accent", "cyan")
        app.cfg.set("audio.block_size", 480)
        rep = configfile.import_settings(app.cfg, DEFAULTS, configfile.read_file(str(f)))
        assert app.cfg.get("ui.accent") == "magenta" and app.cfg.get("ui.borders") == "square"
        assert app.cfg.get("audio.block_size") == 960 and app.cfg.get("audio.jitter_blocks") == 3
        assert app.cfg.get("audio.output_device") == before
        assert "audio.output_device" in rep.ignored
        if name != app_name(app):
            assert "audio.input_device" in rep.ignored or "audio.speaker_device" in rep.ignored
            assert not any(k in rep.changed for k in ("mixer.voice_volume", "mixer.master_volume", "audio.hear_output"))
    assert app.cfg.get("ui.accent") == "magenta"
    if app_name(app) == "soundpad":
        assert app.cfg.get("soundpad.folders") == []              # folders are never imported


def test_plain_config_json_can_be_imported(rig, tmp_path):
    app = rig
    raw = {"ui": {"borders": "square"}, "audio": {"output_device": "Nope"}}
    f = tmp_path / "config_copy.json"
    f.write_text(json.dumps(raw))
    rep = configfile.import_file(app.cfg, DEFAULTS, str(f))
    assert app.cfg.get("ui.borders") == "square" and app.cfg.get("audio.output_device") != "Nope"
    assert "audio.output_device" in rep.ignored


def test_invalid_values_are_rejected_not_stored(rig):
    app = rig
    cfg = app.cfg
    bad = {"ui": {"borders": "triangle", "fps": 45, "splash": "yes", "accent": "purple-ish",
                  "accent_paint": {"mode": "solid", "stops": [["#GG0000", 100]]},
                  "graph_paint": {"mode": "gradient", "stops": []},
                  "backdrop_paint": {"mode": "nope", "stops": [["#000000", 100]]},
                  "animation": "explode", "logo_glow": 3},
           "audio": {"jitter_blocks": True, "block_size": "480"}}
    before = {k: cfg.get(k) for k in ("ui.borders", "ui.fps", "ui.splash", "ui.accent", "ui.accent_paint",
                                       "ui.graph_paint", "ui.backdrop_paint", "ui.animation", "ui.logo_glow",
                                       "audio.jitter_blocks", "audio.block_size")}
    rep = configfile.import_settings(cfg, DEFAULTS, bad)
    assert len(rep.rejected) == 11 and not rep.changed
    assert {k: cfg.get(k) for k in before} == before
    rep = configfile.import_settings(cfg, DEFAULTS, {"audio": {"block_size": 99999}, "ui": {
        "accent_paint": {"mode": "rainbow", "stops": [["#ff0000", 300]], "speed": 900}}})
    assert cfg.get("audio.block_size") == 1920                                # clamped
    assert cfg.get("ui.accent_paint") == {"mode": "rainbow", "stops": [["#FF0000", 100]], "speed": 100}


def test_not_a_config_file(rig, tmp_path):
    app = rig
    for name, text in (("a.json", "{not json"), ("b.json", "[1, 2]"), ("c.json", '{"hello": 1}'),
                       ("d.json", '{"format": "something-else", "settings": {}}'),
                       ("e.json", json.dumps({"format": configfile.FORMAT, "settings": {"foo": {"bar": 1}}}))):
        (tmp_path / name).write_text(text)
        with pytest.raises(configfile.ConfigFileError):
            configfile.import_file(app.cfg, DEFAULTS, str(tmp_path / name))
    with pytest.raises(configfile.ConfigFileError):
        configfile.import_file(app.cfg, DEFAULTS, str(tmp_path / "missing.json"))


# ------------------------------------------------------------------ through the UI
def open_cfg(app, owner):
    app.goto(owner)
    scr = app.screens[owner]
    scr.in_items = False
    scr.cat.idx = scr.CATS.index("Config")
    press(app, "enter")
    return scr


@pytest.mark.parametrize("owner", ["customize", "settings"])
def test_config_page_export_and_import_through_the_ui(rig, tmp_path, monkeypatch, owner):
    app = rig
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    scr = open_cfg(app, owner)
    text = "\n".join(frame(app))
    assert "Export config" in text and "Import config" in text and "Never included" in text
    # export
    out = tmp_path / "share" / "mine.json"
    app.cfg.set("ui.menu_position", "left")
    press(app, "enter")                                         # Export config
    assert type(app.modal).__name__ == "Prompt" and app.modal.path
    assert "EXPORT CONFIG" in "\n".join(frame(app))
    app.modal.inp.set(str(out))
    frame(app)
    assert "NEW FILE" in "\n".join(frame(app))
    press(app, "enter")
    assert app.modal is None and out.is_file()
    assert any("Exported" in n.text for n in app.notes)
    app.modal = None
    # import after changing things
    app.cfg.set("ui.menu_position", "right")
    scr.items_sel.idx = 1
    press(app, "enter")                                         # Import config
    assert type(app.modal).__name__ == "Prompt"
    app.modal.inp.set(str(tmp_path / "nope.json"))
    press(app, "enter")
    assert app.modal is not None and "not found" in app.modal.error.lower()
    app.modal.inp.set(str(out))
    press(app, "enter")
    assert app.modal is None and app.cfg.get("ui.menu_position") == "left"
    assert any("Imported" in n.text for n in app.notes)
    frame(app)


def test_import_applies_live(rig, tmp_path):
    app = rig
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"format": configfile.FORMAT, "settings": {"ui": {
        "borders": "square", "accent": "custom",
        "accent_paint": {"mode": "solid", "stops": [["#FF0000", 100]], "speed": 50}}}}))
    rep = configfile.import_file(app.cfg, DEFAULTS, str(f))
    configfile.apply_changes(app, rep.changed)
    assert app.theme.rounded is False and app.theme.accent_rgb == (255, 0, 0)
    assert "╔" in "\n".join(frame(app)) or "┌" in "\n".join(frame(app))


def test_import_error_shows_compact_message(rig, tmp_path, monkeypatch):
    app = rig
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    scr = open_cfg(app, "customize")
    scr.items_sel.idx = 1
    press(app, "enter")
    app.modal.inp.set(str(bad))
    press(app, "enter")
    assert any("bad JSON" in n.text or "valid" in n.text for n in app.notes)


def test_prompt_is_still_a_plain_text_prompt(rig):
    """Presets / sound names use Prompt without path mode."""
    from ui.modals import Prompt
    app = rig
    got = []
    app.open_modal(Prompt("NAME", "Name:", initial="ab", on_ok=got.append))
    press(app, "c", "enter")
    assert got == ["abc"]

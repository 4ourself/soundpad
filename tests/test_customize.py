"""Customisation: free-form colours (HSV / RGB / alpha / gradient / rainbow), graph colours, truecolor fallbacks,
graph + menu position, and tab animations (default: none)."""
import pytest

from tests.test_tui import frame, press, rig  # noqa: F401  (rig is a fixture)

pyte = pytest.importorskip("pyte")


def page(app):
    return "sounds" if "sounds" in app.screens else "voice"


GRAPH_TITLE = {"sounds": "LEVELS", "voice": "LIVE AUDIO"}
LIST_TITLE = {"sounds": "SOUNDS", "voice": "EFFECTS"}


def resize(app, w, h):
    app.term.w, app.term.h = w, h


def col_of(lines, text):
    for ln in lines:
        i = ln.find(text)
        if i >= 0:
            return i
    return -1


# ------------------------------------------------------------------ colour maths
def test_color_conversions():
    from ui import colors as c
    assert c.hex_to_rgb("#00d7ff") == (0, 215, 255)
    assert c.hex_to_rgb("0df") == (0, 221, 255)
    assert c.rgb_to_hex((0, 215, 255)) == "#00D7FF"
    with pytest.raises(ValueError):
        c.hex_to_rgb("#12345")
    with pytest.raises(ValueError):
        c.hex_to_rgb("zzzzzz")
    for rgb in [(255, 0, 0), (10, 200, 90), (128, 128, 128), (0, 0, 0)]:
        assert c.hsv_to_rgb(*c.rgb_to_hsv(rgb)) == rgb
    assert c.with_alpha((200, 100, 50), 50) == (100, 50, 25)
    assert c.with_alpha((200, 100, 50), 0) == (0, 0, 0)
    assert c.xterm_index((0, 0, 0)) == 16 and c.xterm_index((255, 255, 255)) == 231
    assert 232 <= c.xterm_index((128, 128, 128)) <= 255
    assert c.sgr16_fg((250, 10, 10)) == 91
    assert c.contrast((250, 250, 0)) == (14, 14, 18) and c.contrast((10, 10, 80)) == (245, 245, 245)


def test_paint_modes():
    from ui.colors import DEFAULT_GRAPH, Paint
    z = DEFAULT_GRAPH
    assert z.color_at(0, 0.1) == (0, 215, 135) and z.color_at(0, 0.8) == (255, 215, 0) and z.color_at(0, 0.97) == (255, 95, 95)
    g = Paint("gradient", [["#000000", 100], ["#FFFFFF", 100]])
    assert g.color_at(0.5) == (128, 128, 128) and g.color_at(0) == (0, 0, 0) and g.color_at(1) == (255, 255, 255)
    g3 = Paint("gradient", [["#FF0000", 100], ["#00FF00", 100], ["#0000FF", 100]])
    assert g3.color_at(0.5) == (0, 255, 0)
    r = Paint("rainbow", [["#FF0000", 100]])
    assert r.color_at(0) == (255, 0, 0) and r.color_at(0.0, phase=0.5) != r.color_at(0.0)
    assert Paint("rainbow", [["#FF0000", 50]], base=(0, 0, 0)).color_at(0) == (128, 0, 0)    # alpha mixes with the backdrop
    assert Paint("rainbow", [["#FF0000", 50]], base=(100, 100, 100)).color_at(0) == (178, 50, 50)
    assert Paint("gradient", [["#123456", 100]]).effective_mode() == "solid"    # not enough colours
    assert r.phase_at(1.0) != r.phase_at(0.0) and Paint("solid").phase_at(10.0) == 0.0


def test_paint_from_damaged_config():
    from ui.colors import DEFAULT_GRAPH, Paint
    for bad in ({}, {"mode": "nope"}, {"stops": []}, {"stops": [["xyz", 5]]}, {"stops": 7}, None):
        p = Paint.from_dict(bad if bad is not None else {}, DEFAULT_GRAPH)
        assert p.stops and p.mode in ("zones", "solid", "gradient", "rainbow")
    p = Paint.from_dict({"mode": "gradient", "stops": [["#abc", 150], ["#00ff00", -4]] * 5, "speed": 999}, DEFAULT_GRAPH)
    assert len(p.stops) == 4 and p.stops[0] == ["#AABBCC", 100] and p.stops[1][1] == 0 and p.speed == 100


# ------------------------------------------------------------------ theme
def test_sgr_per_depth():
    from ui.theme import Theme
    rgb = (12, 34, 56)
    for depth, needle in (("true", "38;2;12;34;56"), ("256", "38;5;"), ("16", "3"), ("mono", None)):
        th = Theme("cyan", depth, True)
        code = th.sgr(th.style(rgb, (200, 0, 0)))
        if depth == "true":
            assert needle in code and "48;2;200;0;0" in code
        elif depth == "256":
            assert needle in code and ";2;" not in code
        elif depth == "16":
            assert "38;" not in code and "48;" not in code
        else:
            assert "38;" not in code and "48;" not in code and "\x1b[0m" != code[:0]
    th = Theme("cyan", "true", True)
    assert "38;2;0;215;255" in th.sgr(th.accent_s)


def test_theme_configure_is_live_and_keeps_old_ids():
    from ui.colors import Paint
    from ui.theme import Theme
    th = Theme("cyan", "true", True)
    old = th.sel
    th.configure(Paint("solid", [["#FF8800", 100]]))
    assert th.sel != old and th.accent == "custom"
    assert "48;2;255;136;0" in th.sgr(th.sel)
    assert "48;2;0;215;255" in th.sgr(old)             # old ids keep their colour (no stale cells on screen)
    th.configure("green")
    assert th.accent == "green"


def test_graph_style_modes():
    from ui.colors import Paint
    from ui.theme import Theme
    th = Theme("cyan", "true", True)
    assert len({th.graph_style(x) for x in (0.1, 0.8, 0.97)}) == 3          # default zones
    th.configure("cyan", Paint("solid", [["#AA00FF", 100]]))
    assert len({th.graph_style(x) for x in (0.0, 0.5, 1.0)}) == 1
    assert "38;2;170;0;255" in th.sgr(th.graph_style(0.4))
    th.configure("cyan", Paint("gradient", [["#FFFF00", 100], ["#AA00FF", 100]]))
    assert len({th.graph_style(x / 20) for x in range(21)}) > 10
    th.configure("cyan", Paint("rainbow", [["#FF0000", 100]], 100))
    a = th.graph_style(0.5, 0.0)
    th.t = 1.0
    assert th.graph_style(0.5, 0.0) != a
    n = len(th._styles)
    for k in range(2000):                                                     # bounded style growth
        th.t = k * 0.01
        for x in range(40):
            th.graph_style(0.5, x / 40)
    assert len(th._styles) - n < 100


def test_accent_gradient_and_rainbow_recolor():
    from ui.canvas import Canvas
    from ui.colors import Paint
    from ui.theme import Theme
    th = Theme("cyan", "true", True)
    cv = Canvas(40, 3)
    cv.put(0, 0, " " * 40, th.sel)
    th.recolor(cv)
    assert set(cv.st[0]) == {th.sel}                                          # solid accent: untouched
    th.configure(Paint("gradient", [["#FF0000", 100], ["#0000FF", 100]]))
    cv.put(0, 0, " " * 40, th.sel)
    th.recolor(cv)
    assert cv.st[0][0] != cv.st[0][-1] and len(set(cv.st[0])) > 10
    assert "48;2;255;0;0" in th.sgr(cv.st[0][0]) and "48;2;0;0;255" in th.sgr(cv.st[0][-1])
    cv.put(0, 1, "abc", th.text)
    th.recolor(cv)
    assert cv.st[1][0] == th.text                                             # non-accent styles never change
    th.configure(Paint("rainbow", [["#FF0000", 100]], 100))
    cv.put(0, 0, " " * 40, th.sel)
    th.recolor(cv)
    first = list(cv.st[0])
    th.t = 0.7
    cv.put(0, 0, " " * 40, th.sel)
    th.recolor(cv)
    assert cv.st[0] != first


def test_fade_style():
    from ui.theme import Theme
    th = Theme("cyan", "true", True)
    s = th.style((200, 100, 50), (0, 100, 200))
    assert th.fade_style(s, 1.0) == s
    half = th.sgr(th.fade_style(s, 0.5))
    assert "38;2;" in half and "100;50;25" not in half
    black = th.sgr(th.fade_style(s, 0.0))
    assert "38;2;0;0;0" in black and "48;2;0;0;0" in black
    assert th.sgr(th.fade_style(0, 0.0)).count("38;2;0;0;0") == 1              # default text fades too


def test_detect_depth(monkeypatch):
    from ui.theme import detect_depth
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert detect_depth("auto") == "true"
    monkeypatch.delenv("COLORTERM")
    monkeypatch.setenv("WT_SESSION", "abc")
    assert detect_depth("auto") == "true"
    assert detect_depth("256") == "256" and detect_depth("true") == "true"
    monkeypatch.setenv("NO_COLOR", "1")
    assert detect_depth("auto") == "mono"


# ------------------------------------------------------------------ app wiring + config
def test_apply_paint_saves_and_applies(rig):
    from ui.colors import Paint
    app = rig
    assert app.cfg.get("ui.animation") == "none"
    app.apply_paint("accent", Paint("solid", [["#FF8800", 100]]))
    assert app.cfg.get("ui.accent") == "custom" and app.cfg.get("ui.accent_paint")["stops"][0][0] == "#FF8800"
    assert app.theme.accent_rgb == (255, 136, 0)
    app.apply_paint("graph", Paint("gradient", [["#FFFF00", 100], ["#AA00FF", 100]]))
    assert app.theme.graph_paint.mode == "gradient"
    app.cfg.save() if hasattr(app.cfg, "save") else None
    from config import ConfigManager
    again = ConfigManager(app.cfg.path)
    assert again.get("ui.graph_paint")["mode"] == "gradient" and again.get("ui.accent") == "custom"


def test_first_run_defaults_have_new_keys(rig):
    c = rig.cfg
    assert c.get("ui.graph_position") == "right" and c.get("ui.menu_position") == "center"
    assert c.get("ui.animation") == "none" and c.get("ui.animation_speed") == "normal"
    assert c.get("ui.graph_paint")["mode"] == "zones" and len(c.get("ui.graph_paint")["stops"]) == 3


# ------------------------------------------------------------------ colour editor
def open_editor(app, target="accent"):
    app.goto("settings")
    app.open_colors(target)
    frame(app)
    return app.current


def row(ed, name):
    ed.sel.idx = ed.rows().index(name)


def test_color_editor_flows(rig):
    app = rig
    ed = open_editor(app)
    text = "\n".join(frame(app))
    assert "MAIN COLOR" in text and "Saturation" in text and "Alpha" in text and "Hex" in text
    base = app.theme.accent_rgb
    press(app, "down", "right", "right", "right")                        # arrows move to Hue and change it
    assert ed.rows()[ed.sel.idx] == "hue"
    assert app.cfg.get("ui.accent") == "custom" and app.theme.accent_rgb != base
    # saturation 0 -> grey (the hue is remembered), then back up to 100
    h0 = ed.hsv()[0]
    row(ed, "sat")
    for _ in range(120):
        press(app, "left")
    assert ed.hsv()[1] == 0
    for _ in range(120):
        press(app, "right")
    assert ed.hsv()[1] == 100 and abs(ed.hsv()[0] - h0) < 2
    # RGB sliders
    row(ed, "red")
    for _ in range(200):
        press(app, "right")
    assert ed._rgb()[0] == 255
    # alpha mixes with black
    full = sum(app.theme.accent_rgb)
    row(ed, "alpha")
    for _ in range(80):
        press(app, "left")
    assert ed.paint.stops[0][1] < 60 and sum(app.theme.accent_rgb) < full * 0.7
    # hex prompt
    row(ed, "hex")
    press(app, "enter")
    assert app.modal is not None
    app.modal.inp.value = "#336699"
    app.modal.on_key(app, __import__("ui.keys", fromlist=["Key"]).Key("enter"))       # submit from the text field
    if app.modal is not None:
        press(app, "down", "enter")                                                   # ... or via the OK button
    assert app.modal is None and ed.paint.stops[0][0] == "#336699"
    # invalid hex is refused with a compact error and the modal stays open
    press(app, "enter")
    app.modal.inp.value = "nope"
    press(app, "enter")
    if app.modal is not None and not app.modal.error:
        press(app, "down", "enter")
    assert app.modal is not None and "hex" in app.modal.error.lower()
    app.close_modal()
    # reset -> default colour
    row(ed, "reset")
    press(app, "enter")
    from config import DEFAULTS
    assert app.theme.accent_rgb == app.default_paint("accent").color_at(0)
    press(app, "backspace")
    assert app.current is app.screens["settings"]


def test_color_editor_modes_and_stops(rig):
    app = rig
    ed = open_editor(app, "accent")
    press(app, "right")                                                  # mode -> gradient
    assert ed.paint.mode == "gradient" and len(ed.paint.stops) >= 2
    assert "Colour" in "\n".join(frame(app))
    app.theme.t = 0.0
    frame(app)
    assert len({app.cv.st[0][x] for x in range(app.cv.w)}) > 3           # header recoloured left -> right
    rows = ed.rows()
    assert "add" in rows and "del" in rows
    ed.sel.idx = rows.index("add")
    for _ in range(6):
        press(app, "enter")
    assert len(ed.paint.stops) == 4
    ed.sel.idx = ed.rows().index("del")
    press(app, "enter", "enter", "enter", "enter")
    assert len(ed.paint.stops) == 2                                      # never fewer than 2 for a gradient
    press(app, "up", "up")                                               # to 'add'... back to mode row
    ed.sel.idx = 0
    press(app, "right")                                                  # -> rainbow
    assert ed.paint.mode == "rainbow" and "speed" in ed.rows() and "hue" not in ed.rows()
    assert "Speed" in "\n".join(frame(app))
    ed.sel.idx = 1
    press(app, "right")
    assert ed.paint.speed > 50


def test_graph_editor_zones_default_and_draw(rig):
    app = rig
    ed = open_editor(app, "graph")
    assert ed.paint.mode == "zones" and len(ed.paint.stops) == 3
    text = "\n".join(frame(app))
    assert "VOLUME GRAPH COLORS" in text and "Zones" in text
    press(app, "down")                                                   # Colour (stop) selector
    press(app, "right")
    assert ed.si == 1
    row(ed, "hue")
    press(app, "right", "right")
    assert app.cfg.get("ui.graph_paint")["stops"][1][0] != "#FFD700"
    assert app.cfg.get("ui.accent") != "custom"                          # graph edits never touch the accent


@pytest.mark.parametrize("size", [(80, 24), (120, 40), (60, 20), (40, 12)])
@pytest.mark.parametrize("target", ["accent", "graph"])
def test_color_editor_renders_everywhere(rig, size, target):
    app = rig
    resize(app, *size)
    ed = open_editor(app, target)
    for mode in ed_modes(target):
        ed.set_mode(mode)
        for sel in range(len(ed.rows())):
            ed.sel.idx = sel
            lines = frame(app)
            assert len(lines) == size[1] and all(len(l) == size[0] for l in lines)


def ed_modes(target):
    return ("solid", "gradient", "rainbow") if target == "accent" else ("zones", "solid", "gradient", "rainbow")


# ------------------------------------------------------------------ settings pages
def test_customize_page_and_settings_split(rig):
    app = rig
    c, s = app.screens["customize"], app.screens["settings"]
    assert c.CATS == ("Colors", "Layout", "Animation", "Logo", "Config") and c.TITLE == "CUSTOMIZE"
    for cat in c.CATS:
        assert cat == "Config" or cat not in s.CATS
    app.goto("customize")
    labels = {k: [i.label for i in c._items(k)] for k in c.CATS}
    assert {"Main color", "Volume graph colors", "Backdrop", "Backdrop color", "Reset colors", "Color mode"} <= set(labels["Colors"])
    assert {"Graph position", "Menu position", "Borders"} == set(labels["Layout"])
    assert {"Tab animation", "Animation speed", "Preview animation"} == set(labels["Animation"])
    assert {"Title screen", "Logo glow"} <= set(labels["Logo"])
    text = "\n".join(frame(app))
    assert "CUSTOMIZE" in text and "Main color" not in text.split("COLORS")[0]
    # the header has a CUSTOMIZE tab and the main menu has a Customize entry
    assert "CUSTOMIZE" in frame(app)[0]
    app.goto("home")
    assert "Customize" in "\n".join(frame(app))


def test_customize_items_work(rig):
    app = rig
    c = app.screens["customize"]
    items = {i.label: i for i in c._items("Colors")}
    items["Main color preset"].set("green")
    assert app.theme.accent == "green"
    items["Main color"].press()
    assert app.current.__class__.__name__ == "ColorEditor"
    app.pop()
    items["Backdrop color"].press()
    assert app.current.target == "backdrop"
    app.pop()
    assert app.cfg.get("ui.backdrop") == "custom" or app.cfg.get("ui.backdrop") == "terminal"
    items["Reset colors"].press()
    from config import DEFAULTS
    assert app.cfg.get("ui.accent") == DEFAULTS["ui"]["accent"] and app.cfg.get("ui.graph_paint")["mode"] == "zones"
    assert app.cfg.get("ui.backdrop") == "terminal"
    anim = {i.label: i for i in c._items("Animation")}["Tab animation"]
    assert anim.options[0] == "none" and "fade" in anim.options and "line" in anim.options and len(anim.options) >= 8
    anim.set("slide")
    assert app.cfg.get("ui.animation") == "slide"


# ------------------------------------------------------------------ positions
@pytest.mark.parametrize("pos", ["left", "center", "right"])
def test_graph_position(rig, pos):
    app = rig
    app.cfg.set("ui.graph_position", pos)
    resize(app, 130, 40)
    app.goto(page(app))
    lines = frame(app)
    g, lst = col_of(lines, GRAPH_TITLE[page(app)]), col_of(lines, LIST_TITLE[page(app)])
    assert g >= 0 and lst >= 0, "\n".join(lines)
    if pos == "left":
        assert g < lst
    elif pos == "right":
        assert g > lst
    else:                                            # three columns: list | graph | rest
        other = col_of(lines, "SYSTEM" if page(app) == "voice" else "SELECTED")
        assert lst < g < other


def test_graph_center_falls_back_when_narrow(rig):
    app = rig
    app.cfg.set("ui.graph_position", "center")
    resize(app, 100, 30)
    app.goto(page(app))
    lines = frame(app)
    assert col_of(lines, GRAPH_TITLE[page(app)]) > col_of(lines, LIST_TITLE[page(app)])


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (130, 40), (60, 20), (40, 12)])
@pytest.mark.parametrize("pos", ["left", "center", "right"])
def test_positions_render_at_every_size(rig, size, pos):
    app = rig
    app.cfg.set("ui.graph_position", pos)
    app.cfg.set("ui.menu_position", pos)
    resize(app, *size)
    for pg in ("home", page(app), "settings", "help"):
        app.goto(pg)
        lines = frame(app)
        assert len(lines) == size[1] and all(len(l) == size[0] for l in lines)


def test_menu_position(rig):
    app = rig
    xs = {}
    resize(app, 120, 30)
    for pos in ("left", "center", "right"):
        app.cfg.set("ui.menu_position", pos)
        app.goto("home")
        xs[pos] = col_of(frame(app), "Settings")
    assert xs["left"] < xs["center"] < xs["right"]


# ------------------------------------------------------------------ transitions
def test_default_is_no_animation(rig):
    app = rig
    frame(app)
    app.goto(page(app))
    assert app.trans is None
    app.goto("settings")
    assert app.trans is None


def snap_two(app):
    """Old frame = home, new frame = the app page."""
    app.goto("home")
    frame(app)


@pytest.mark.parametrize("kind", ["fade", "line", "slide", "wipe", "dissolve", "curtain", "blinds", "random"])
def test_each_transition(rig, kind):
    from ui import transitions as T
    app = rig
    app.cfg.set("ui.animation", kind)
    snap_two(app)
    old = [r[:] for r in app.cv.ch]
    app.goto(page(app))
    tr = app.trans
    assert tr is not None
    new_app_frame = None
    app.draw()
    final = [r[:] for r in app.cv.ch]
    seen_mid = False
    for p in (0.05, 0.25, 0.5, 0.75, 0.95):
        app.draw()
        assert tr.apply(app.cv, app.theme, t=p) is True
        assert len(app.cv.ch) == app.cv.h and all(len(r) == app.cv.w and len(s) == app.cv.w
                                                 for r, s in zip(app.cv.ch, app.cv.st))
        if app.cv.ch != final and app.cv.ch != old:
            seen_mid = True
    assert seen_mid or tr.kind == "fade"
    app.draw()
    assert tr.apply(app.cv, app.theme, t=1.0) is False
    assert app.cv.ch == final                                       # finished: exactly the new screen


def test_header_and_status_bar_stay_live_during_animation(rig):
    app = rig
    app.cfg.set("ui.animation", "slide")
    snap_two(app)
    app.goto(page(app))
    app.draw()
    new_head, new_foot = list(app.cv.ch[0]), list(app.cv.ch[-1])
    app.trans.apply(app.cv, app.theme, t=0.5)
    assert app.cv.ch[0] == new_head and app.cv.ch[-1] == new_foot


def test_slide_direction_follows_tab_order(rig):
    from ui import transitions as T
    app = rig
    app.cfg.set("ui.animation", "slide")
    app.goto(page(app))
    app.trans = None
    frame(app)
    app.goto("settings")
    assert app.trans.dir == 1
    app.trans = None
    frame(app)
    app.goto(page(app))
    assert app.trans.dir == -1


def test_line_animation_marker_travels_between_tabs(rig):
    app = rig
    app.cfg.set("ui.animation", "line")
    app.goto(page(app))
    app.trans = None
    frame(app)
    src = app.tab_rects[page(app)]
    app.goto("settings")
    dst = app.tab_rects["settings"]
    tr = app.trans
    assert tr.src == src and tr.dst == dst and dst[0] > src[0]
    xs = []
    mark = app.theme.g.slider
    for p in (0.1, 0.5, 0.9):
        app.draw()
        tr.apply(app.cv, app.theme, t=p)
        row = app.cv.ch[1]
        xs.append(row.index(mark))
    assert xs[0] <= xs[1] <= xs[2] and xs[2] > xs[0]


def test_fade_goes_dark_in_the_middle(rig):
    app = rig
    app.cfg.set("ui.animation", "fade")
    app.theme.depth = "true"
    app.rebuild_theme() if False else None
    snap_two(app)
    app.goto(page(app))
    app.draw()
    tr = app.trans
    if app.theme.depth in ("16", "mono"):
        pytest.skip("fade degrades to dissolve")
    tr.apply(app.cv, app.theme, t=0.49)
    cells = [s for row in app.cv.st[2:-2] for s in row]
    th = app.theme
    lum = [sum(c or 0 for c in (th.style_rgb(s)[0] or (0, 0, 0))) for s in cells]
    assert max(lum) < 150


def test_transition_runs_out_and_stops(rig):
    app = rig
    app.cfg.set("ui.animation", "wipe")
    app.cfg.set("ui.animation_speed", "fast")
    snap_two(app)
    app.goto(page(app))
    assert app.trans is not None
    import time
    time.sleep(0.25)
    frame(app)
    assert app.trans is None


def test_input_works_during_animation(rig):
    app = rig
    app.cfg.set("ui.animation", "dissolve")
    app.cfg.set("ui.animation_speed", "slow")
    snap_two(app)
    app.goto("settings")
    assert app.trans is not None
    press(app, "enter", "down", "down")
    assert app.screens["settings"].in_items or app.screens["settings"].cat.idx >= 0
    press(app, "backspace", "backspace")
    assert app.page == "home"
    frame(app)


def test_modals_and_resize_do_not_animate_or_crash(rig):
    app = rig
    app.cfg.set("ui.animation", "curtain")
    snap_two(app)
    app.goto(page(app))
    assert app.trans is not None
    resize(app, 100, 30)
    frame(app)
    assert app.trans is None                                      # resized mid-animation: dropped, no crash
    app.confirm_quit()
    assert app.trans is None


def test_preview_plays_from_empty_screen(rig):
    app = rig
    frame(app)
    app.play_transition()
    assert app.trans is None                                      # animation is 'none': nothing to preview
    app.cfg.set("ui.animation", "wipe")
    app.play_transition()
    assert app.trans is not None
    app.draw()
    app.trans.apply(app.cv, app.theme, t=0.5)
    assert any(" " * 5 in l for l in app.cv.text_lines()[3:-3])


def test_ascii_fallback_with_animation_and_custom_colors(rig):
    from ui.colors import Paint
    app = rig
    app.cfg.set("ui.charset", "ascii")
    app.rebuild_theme()
    app.apply_paint("accent", Paint("rainbow", [["#FF0000", 100]], 80))
    app.cfg.set("ui.animation", "line")
    snap_two(app)
    app.goto("settings")
    app.draw()
    app.trans.apply(app.cv, app.theme, t=0.5)
    assert all(ord(ch) < 128 for ln in app.cv.text_lines() for ch in ln)


def test_diff_render_with_truecolor_rainbow_and_animation(rig):
    """What App.render() writes (truecolor, rainbow accent, mid-animation) still reproduces the canvas text."""
    from ui.colors import Paint
    app = rig
    app.cfg.set("ui.colors", "true")
    app.rebuild_theme()
    app.apply_paint("accent", Paint("rainbow", [["#FF0000", 100]], 100))
    app.apply_paint("graph", Paint("gradient", [["#FFFF00", 100], ["#AA00FF", 100]]))
    app.cfg.set("ui.animation", "dissolve")
    app.cfg.set("ui.animation_speed", "slow")
    out = []
    app.term.write = out.append
    screen = pyte.Screen(80, 24)
    stream = pyte.Stream(screen)
    app.goto("home")
    for pg in ("home", page(app), "settings", "home", page(app)):
        app.goto(pg)
        for _ in range(4):
            app.theme.t += 0.13
            app.update()
            app.render()
            stream.feed("".join(out))
            out.clear()
            assert screen.display == app.cv.text_lines()
    assert any("38;2;" in x for x in app.theme._sgr.values())


def test_every_screen_renders_with_rainbow_and_every_animation(rig):
    from ui.colors import Paint
    from ui import transitions as T
    app = rig
    app.apply_paint("accent", Paint("rainbow", [["#00FFAA", 80]], 60))
    app.apply_paint("graph", Paint("rainbow", [["#FF0000", 100]], 60))
    for size in ((80, 24), (120, 40), (40, 12)):
        resize(app, size[0], size[1])
        for kind in T.KINDS:
            app.cfg.set("ui.animation", kind)
            for pg in ("home", page(app), "settings", "help"):
                app.goto(pg)
                for _ in range(2):
                    lines = frame(app)
                    assert len(lines) == size[1] and all(len(l) == size[0] for l in lines)


# ------------------------------------------------------------------ title screen / logo / borders / backdrop
def test_title_screen_logo_and_enter(rig):
    from ui.logo import LOGOS
    app = rig
    app.splash = True
    app.goto("home")
    app.screens["home"]._t0 = app.theme.t - 5
    text = "\n".join(frame(app))
    name = "soundpad" if "sounds" in app.screens else "voicer"
    assert "PRESS ENTER" in text
    assert any(ln.strip() in text for ln in LOGOS[name][:2])        # the big ascii logo is on screen
    assert "Load folder" not in text and "Settings" not in text      # menu comes after Enter
    press(app, "down", "up", "right")                                # other keys do nothing
    assert app.splash is True
    press(app, "enter")
    assert app.splash is False
    text = "\n".join(frame(app))
    assert "PRESS ENTER" not in text and "Customize" in text and "Exit" in text
    press(app, "backspace")                                          # menu -> quit dialog
    assert app.modal is not None


def test_logo_matches_requested_art():
    from ui.logo import LOGOS
    v = LOGOS["voicer"]
    assert len(v) == 10 and v[0].strip() == "██▒   █▓ ▒█████   ██▓ ▄████▄  ▓█████  ██▀███"
    assert v[4].strip().startswith("▒▀█░  ░ ████▓▒░░██░▒ ▓███▀")
    assert len(LOGOS["soundpad"]) == 10


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (60, 20), (40, 12), (30, 8)])
@pytest.mark.parametrize("mode", ["off", "sometimes", "always"])
def test_title_screen_every_size_and_glow(rig, size, mode):
    app = rig
    app.cfg.set("ui.logo_glow", mode)
    resize(app, *size)
    app.splash = True
    for t in (0.0, 4.2, 5.0, 9.0):
        app.theme.t = t
        app.goto("home")
        app.render()
        lines = app.cv.text_lines()
        assert len(lines) == size[1] and all(len(l) == size[0] for l in lines)


def test_logo_glows_sometimes_and_style_count_is_bounded(rig):
    from ui.canvas import Canvas
    from ui.logo import draw_logo, glow_amount
    app = rig
    th = app.theme
    assert glow_amount(0.0, "sometimes")[0] == 0.0 and glow_amount(5.0, "sometimes")[0] > 0.5
    assert glow_amount(5.0, "off")[0] == 0.0 and glow_amount(1.3, "always")[2] == 1.0
    name = "voicer" if "voice" in app.screens else "soundpad"
    cv = Canvas(100, 14)
    before = len(th._styles)
    sets = []
    for t in (0.0, 4.5, 5.0, 5.6):
        cv.clear()
        draw_logo(cv, th, name, 2, 1, t, "sometimes", 1.0)
        sets.append([row[:] for row in cv.st])
    assert sets[0] != sets[2]                                       # the glow changes colours
    for k in range(400):
        draw_logo(cv, th, name, 2, 1, k * 0.07, "always", 1.0)
    assert len(th._styles) - before < 1500
    cv.clear()
    draw_logo(cv, th, name, 0, 0, 0.0, "off", 0.3)                  # reveal: only the left part is drawn
    shown = [i for i, ch in enumerate(cv.ch[1]) if ch != " "]
    assert shown and max(shown) < 100 * 0.6


def test_logo_in_ascii_mode(rig):
    app = rig
    app.cfg.set("ui.charset", "ascii")
    app.rebuild_theme()
    app.splash = True
    app.goto("home")
    app.render()
    assert all(ord(c) < 128 for ln in app.cv.text_lines() for c in ln)


def test_borders_rounded_by_default_and_switchable(rig):
    app = rig
    lines = frame(app)
    txt = "\n".join(lines)
    assert "╭" in txt and "╯" in txt and "┌" not in txt and "╔" not in txt
    app.cfg.set("ui.borders", "square")
    app.rebuild_theme()
    txt = "\n".join(frame(app))
    assert "╔" in txt and "╭" not in txt


def test_alpha_mixes_with_backdrop_not_black(rig):
    from ui.colors import Paint
    app = rig
    app.apply_paint("accent", Paint("solid", [["#00D7FF", 50]]))
    on_terminal = app.theme.accent_rgb
    app.apply_paint("backdrop", Paint("solid", [["#802080", 100]]))
    assert app.cfg.get("ui.backdrop") == "custom"
    assert app.base_rgb() == (128, 32, 128)
    assert app.theme.accent_rgb != on_terminal
    assert all(abs(a - b) <= 1 for a, b in zip(app.theme.accent_rgb, (64, 123, 192)))                   # halfway between the colour and the backdrop
    app.cfg.set("ui.backdrop", "terminal")
    app.refresh_paints()
    assert app.theme.accent_rgb == on_terminal


def test_painted_backdrop_fills_background(rig):
    from ui.colors import Paint
    app = rig
    app.cfg.set("ui.colors", "true")
    app.rebuild_theme()
    app.apply_paint("backdrop", Paint("gradient", [["#000000", 100], ["#FF0000", 100]]))
    frame(app)
    th, cv = app.theme, app.cv
    top = th.style_rgb(cv.st[0][cv.w - 1])[1]
    bot = th.style_rgb(cv.st[cv.h - 1][cv.w - 1])[1]
    mid = th.style_rgb(cv.st[cv.h // 2][cv.w // 2 + 3])[1]
    assert top is not None and bot is not None and bot[0] > top[0] + 200 and top[0] < mid[0] < bot[0]
    # cells that already have a background (selection bars) keep it
    app.goto("home")
    frame(app)
    assert all(th.style_rgb(s)[1] is not None for row in cv.st for s in row)
    app.cfg.set("ui.backdrop", "terminal")
    app.refresh_paints()
    frame(app)
    assert any(th.style_rgb(s)[1] is None for s in cv.st[1])


def test_backdrop_diff_render_matches_canvas(rig):
    from ui.colors import Paint
    app = rig
    app.cfg.set("ui.colors", "true")
    app.rebuild_theme()
    app.apply_paint("backdrop", Paint("gradient", [["#101020", 100], ["#301040", 100]]))
    out = []
    app.term.write = out.append
    screen = pyte.Screen(80, 24)
    stream = pyte.Stream(screen)
    for pg in ("home", page(app), "customize", "settings"):
        app.goto(pg)
        app.update()
        app.render()
        stream.feed("".join(out))
        out.clear()
        assert screen.display == app.cv.text_lines()


# ------------------------------------------------------------------ the redesigned colour editor
@pytest.mark.parametrize("target", ["accent", "graph", "backdrop"])
def test_editor_has_controls_field_and_example(rig, target):
    app = rig
    resize(app, 100, 30)
    ed = open_editor(app, target)
    text = "\n".join(frame(app))
    assert "COLOR FIELD" in text and "EXAMPLE" in text and "HUE" in text      # three columns
    assert "STYLE" in text and "COLOR" in text and "RGB" in text
    if target == "backdrop":
        assert "Alpha" not in text and "OPACITY" not in text.split("EXAMPLE")[0]
    cols = {name: "\n".join(frame(app)).find(name) for name in ("Saturation",)}
    lines = frame(app)
    left = next(l.find("Saturation") for l in lines if "Saturation" in l)
    field = next(l.find("COLOR FIELD") for l in lines if "COLOR FIELD" in l)
    example = next(l.find("EXAMPLE") for l in lines if "EXAMPLE" in l)
    assert left < field < example                                       # sliders left, field centre, example right


def test_editor_degrades_on_narrow_screens(rig):
    app = rig
    resize(app, 60, 20)
    open_editor(app, "accent")
    text = "\n".join(frame(app))
    assert "EXAMPLE" in text and "COLOR FIELD" not in text               # two columns
    resize(app, 40, 14)
    text = "\n".join(frame(app))
    assert "Saturation" in text or "Sat" in text                         # controls only


def test_editor_field_marker_follows_hsv(rig):
    app = rig
    resize(app, 100, 30)
    ed = open_editor(app, "accent")
    ed.paint.stops[0][0] = "#FF0000"
    ed._hsv = None
    app.apply_paint("accent", ed.paint)
    frame(app)
    marker = "◆"
    pos1 = [(x, y) for y, row in enumerate(app.cv.ch) for x, c in enumerate(row) if c == marker]
    row_(ed, "sat")
    for _ in range(60):
        press(app, "left")
    frame(app)
    pos2 = [(x, y) for y, row in enumerate(app.cv.ch) for x, c in enumerate(row) if c == marker]
    assert pos1 and pos2 and pos2[0][0] < pos1[0][0]                     # less saturation = further left


def row_(ed, name):
    ed.sel.idx = ed.rows().index(name)


# ------------------------------------------------------------------ glass backdrop (blur / acrylic stays visible)
def _glass(app, stops, mode="glass"):
    from ui.colors import Paint
    app.cfg.set("ui.colors", "true")
    app.cfg.set("ui.backdrop", mode)
    app.cfg.set("ui.backdrop_paint", Paint("gradient" if len(stops) > 1 else "solid", stops).to_dict())
    app.rebuild_theme()


def _bgs(app):
    th = app.theme
    return [th.style_rgb(s)[1] for row in app.cv.st for s in row]


def test_glass_never_paints_a_background_and_alpha_is_coverage(rig):
    app = rig
    for alpha, glyph in ((100, "█"), (70, "▓"), (50, "▒"), (20, "░")):
        _glass(app, [["#102040", alpha]])
        app.splash = False
        frame(app)
        blanks = [c for row in app.cv.ch for c in row]
        assert blanks.count(glyph) > 1000, (alpha, glyph)
        assert (16, 32, 64) not in _bgs(app)                           # the terminal's own (blurred) background stays
        th = app.theme
        fgs = {th.style_rgb(s)[0] for row, srow in zip(app.cv.ch, app.cv.st) for c, s in zip(row, srow) if c == glyph}
        assert fgs == {(16, 32, 64)}
    _glass(app, [["#102040", 3]])                                      # almost nothing: pure terminal background
    frame(app)
    assert not any(c in "░▒▓█" for row in app.cv.ch for c in row)


def test_glass_gradient_fades_to_the_blur(rig):
    app = rig
    _glass(app, [["#8040FF", 80], ["#8040FF", 0]])
    app.splash = False
    lines = frame(app)
    top = sum(c in "░▒▓█" for c in lines[1])
    bottom = sum(c in "░▒▓█" for c in lines[-2])
    assert top > 40 and bottom == 0
    assert any(lines[y].count("▓") > 20 for y in range(1, 6))        # dense at the top, thinner further down
    dens = [sum(c in "▒▓█" for c in ln) for ln in lines[1:-1]]
    assert dens[0] >= dens[len(dens) // 2] >= dens[-1]


def test_glass_leaves_text_and_selection_alone(rig):
    app = rig
    _glass(app, [["#102040", 60]])
    app.splash = False
    app.goto("home")
    lines = frame(app)
    txt = "\n".join(lines)
    assert "Customize" in txt and "Exit" in txt and ("voicer" in txt or "soundpad" in txt)
    th = app.theme
    assert any(b is not None for b in _bgs(app))                        # the focus bar keeps its own colour


def test_glass_is_skipped_in_ascii_and_mono(rig):
    app = rig
    _glass(app, [["#102040", 60]])
    app.cfg.set("ui.charset", "ascii")
    app.rebuild_theme()
    frame(app)
    assert all(ord(c) < 128 for row in app.cv.ch for c in row)
    app.cfg.set("ui.charset", "unicode")
    app.cfg.set("ui.colors", "mono")
    app.rebuild_theme()
    frame(app)
    assert not any(c in "░▒▓█" for row in app.cv.ch for c in row)


def test_terminal_mode_paints_nothing(rig):
    app = rig
    _glass(app, [["#102040", 60]], mode="terminal")
    frame(app)
    assert not any(c in "░▒▓█" for row in app.cv.ch for c in row)
    th = app.theme
    assert all(th.style_rgb(s)[1] is None for row in app.cv.st for s in row[:5])      # no painted background at all
    assert app.theme.backdrop_paint is None and app.base_rgb() == (12, 12, 12)


def test_glass_diff_render_matches_canvas(rig):
    app = rig
    _glass(app, [["#8040FF", 70], ["#10C0FF", 10]])
    out = []
    app.term.write = out.append
    screen = pyte.Screen(80, 24)
    stream = pyte.Stream(screen)
    for pg in ("home", page(app), "customize", "settings"):
        app.goto(pg)
        app.update()
        app.render()
        stream.feed("".join(out))
        out.clear()
        assert screen.display == app.cv.text_lines()


def test_backdrop_choice_switches_modes_and_starts_translucent(rig):
    from ui.colors import Paint
    app = rig
    app.apply_paint("backdrop", Paint("solid", [["#202040", 100]]))            # opaque custom backdrop
    assert app.cfg.get("ui.backdrop") == "custom"
    items = {i.label: i for i in app.screens["customize"]._items("Colors")}
    assert items["Backdrop"].options == ["terminal", "glass", "custom"]
    items["Backdrop"].set("glass")
    assert app.backdrop_mode() == "glass" and app.theme.glass
    assert app.cfg.get("ui.backdrop_paint")["stops"][0][1] == 45               # would hide the blur at 100: made translucent
    assert app.base_rgb() == (12, 12, 12)                                      # accent alpha still mixes with the terminal bg
    items["Backdrop"].set("custom")
    assert app.paint_of("backdrop").stops[0][1] == 100 and not app.theme.glass
    items["Backdrop"].set("terminal")
    assert app.theme.backdrop_paint is None


def test_editor_alpha_row_only_for_glass_backdrop(rig):
    app = rig
    app.cfg.set("ui.backdrop", "custom")
    ed = open_editor(app, "backdrop")
    assert "alpha" not in ed.rows()
    app.pop()
    app.cfg.set("ui.backdrop", "glass")
    ed = open_editor(app, "backdrop")
    assert "alpha" in ed.rows()
    ed.sel.idx = ed.rows().index("alpha")
    before = ed.paint.stops[0][1]
    press(app, "left", "left")
    assert app.cfg.get("ui.backdrop") == "glass" and app.cfg.get("ui.backdrop_paint")["stops"][0][1] < before
    assert "Alpha" in "\n".join(frame(app))


def test_windows_defaults_to_truecolor(monkeypatch):
    from ui import theme
    for k in ("WT_SESSION", "COLORTERM", "NO_COLOR", "TERM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(theme, "_windows_truecolor", lambda: True)
    assert theme.detect_depth("auto") == "true"                              # not 256: no banded gradients
    monkeypatch.setattr(theme, "_windows_truecolor", lambda: False)
    assert theme.detect_depth("auto") != "true"
    assert theme.detect_depth("256") == "256"

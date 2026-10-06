from soundpad.keybinds import KeybindManager, normalize_pynput_key, parse_keybind


def mk(**kw):
    km = KeybindManager(key_state_fn=None, **kw)
    hits = []
    return km, hits


def bind(km, hits, spec):
    km.bind(spec, lambda s=spec: hits.append(s))


def test_parse():
    assert parse_keybind("ctrl+alt+s") == ("CTRL", "ALT", "S")
    assert parse_keybind("f6") == ("F6",)
    assert parse_keybind("shift + f") == ("SHIFT", "F")
    assert parse_keybind("alt+space") == ("ALT", "SPACE")
    assert parse_keybind("CTRL++") == ("CTRL", "+")
    for bad in ("", "ctrl+", "banana", "ctrl+f99"):
        try:
            parse_keybind(bad)
            assert False, bad
        except ValueError:
            pass


def test_single_modifier_fires_before_alt_f4():
    km, hits = mk()
    bind(km, hits, "ALT")
    km.handle_press("ALT", now=0)
    assert hits == ["ALT"]
    km.handle_press("F4", now=0.1)   # ALT+F4 -> nothing extra, ALT already fired
    assert hits == ["ALT"]


def test_alt_f4_fires_f4_single_when_not_exact():
    km, hits = mk()
    bind(km, hits, "F4")
    km.handle_press("ALT", now=0)
    km.handle_press("F4", now=0.1)
    assert hits == ["F4"]


def test_exact_single_keys():
    km, hits = mk(exact_single_keys=True)
    bind(km, hits, "F4")
    km.handle_press("ALT", now=0)
    km.handle_press("F4", now=0.1)
    assert hits == []


def test_combo_requires_all_keys():
    km, hits = mk()
    bind(km, hits, "CTRL+ALT+S")
    km.handle_press("S", now=0)
    km.handle_release("S")
    km.handle_press("CTRL", now=1)
    km.handle_press("S", now=1.1)
    assert hits == []
    km.handle_release("S")
    km.handle_press("ALT", now=2)
    assert hits == []                 # S not held
    km.handle_press("S", now=2.1)
    assert hits == ["CTRL+ALT+S"]


def test_no_repeat_spam_while_held():
    km, hits = mk()
    bind(km, hits, "F6")
    km.handle_press("F6", now=0)
    for i in range(1, 30):
        km.handle_press("F6", now=0.5 + i * 0.03)   # OS auto-repeat
    assert hits == ["F6"]
    km.handle_release("F6")
    km.handle_press("F6", now=3)
    assert hits == ["F6", "F6"]


def test_allow_repeat():
    km, hits = mk(allow_repeat=True)
    bind(km, hits, "F6")
    km.handle_press("F6", now=0)
    km.handle_press("F6", now=0.5)
    assert len(hits) == 2


def test_stuck_modifier_recovers_after_gap():
    km, hits = mk()
    bind(km, hits, "ALT")
    km.handle_press("ALT", now=0)        # Alt+Tab: release never delivered
    km.handle_press("ALT", now=30)       # genuine new press long after
    assert hits == ["ALT", "ALT"]


def test_stuck_keys_dropped_with_os_state():
    state = {}
    km = KeybindManager(key_state_fn=lambda vk: state.get(vk, False))
    hits = []
    km.bind("CTRL+S", lambda: hits.append(1))
    state[17] = True
    km.handle_press("CTRL", raw="ctrl_l", vk=17, now=0)
    km.handle_press("S", now=0.1)
    assert hits == [1]
    km.handle_release("S")
    state[17] = False                    # ctrl released but event lost
    km.handle_press("S", now=0.2)        # plain S: CTRL must be purged
    assert hits == [1]


def test_left_right_modifiers_collapse():
    km, hits = mk()
    bind(km, hits, "CTRL+F1")
    km.handle_press("CTRL", raw="ctrl_r", now=0)
    km.handle_press("F1", now=0.1)
    assert hits == ["CTRL+F1"]


def test_capture_mode_does_not_fire():
    import threading, time
    km, hits = mk()
    bind(km, hits, "F6")
    km._listener = object()              # pretend the hook is active
    out = {}
    t = threading.Thread(target=lambda: out.update(r=km.capture(3)))
    t.start(); time.sleep(0.1)
    km.handle_press("CTRL", now=0); km.handle_press("F6", now=0.1)
    km.handle_release("F6"); km.handle_release("CTRL")
    t.join()
    assert out["r"] == "CTRL+F6" and hits == []


class K:
    def __init__(self, **kw): self.__dict__.update(kw)


def test_normalize_pynput():
    assert normalize_pynput_key(K(name="ctrl_l")) == "CTRL"
    assert normalize_pynput_key(K(name="alt_gr")) == "ALT"
    assert normalize_pynput_key(K(name="f6")) == "F6"
    assert normalize_pynput_key(K(name="page_up")) == "PAGEUP"
    assert normalize_pynput_key(K(name="media_play_pause")) is None
    assert normalize_pynput_key(K(vk=0x53, char="\x13")) == "S"   # Ctrl+S yields a control char
    assert normalize_pynput_key(K(char="a", vk=None)) == "A"


def test_held_keys_and_history_for_the_ui_panel():
    km, hits = mk()
    km.bind("alt", lambda: hits.append("alt"), tag="alt")
    km.handle_press("ALT", raw="alt", now=0.0)
    km.handle_press("F4", raw="f4", now=0.1)
    assert km.held_text() == "ALT+F4"
    rec = km.recent()                                    # newest first
    assert [c for _, c, _ in rec] == ["ALT+F4", "ALT"]
    assert rec[1][2] == ["alt"]                           # ALT alone fired the sound...
    assert rec[0][2] == []                                # ...F4 afterwards is just another key (no wait, no block)
    km.handle_release("f4")
    km.handle_release("alt")
    assert km.held_text() == ""


def test_hook_never_suppresses_keys():
    """The pynput listener is created without suppress=True, so Windows still gets every key (ALT+F4)."""
    import inspect

    from soundpad import keybinds
    src = inspect.getsource(keybinds.KeybindManager.start)
    assert "suppress" not in src

"""Soundpad - background soundboard with a terminal UI (entry point).

Process layout (see README "Architecture"):
  audio threads (PortAudio)  <- own the Output and Speaker streams, never wait on the UI
  key hook + sound worker    <- run from boot until exit, whichever screen is visible
  UI thread (this one)       <- draws ~30 fps and reads keys; a pure view/controller
"""
from __future__ import annotations

import argparse
import sys
import traceback


def list_devices() -> int:
    from audio import devices as dev
    try:
        api = dev.preferred_hostapi("auto")
        print(f"Audio system: {api}\nOUTPUT DEVICES")
        for d in dev.list_devices("output", api):
            print(f"  {d.name}" + ("   <- virtual cable" if dev.is_virtual(d.name) else ""))
    except dev.AudioBackendError as e:
        print(e)
        return 1
    return 0


def run_tui() -> int:
    from audio.engine import SoundEngine
    from config import ConfigManager
    from controller import Controller
    from soundpad.manager import SoundpadManager
    from ui.app import App
    from ui.startup import run_boot
    from ui.terminal import Terminal

    config = ConfigManager()
    soundpad = SoundpadManager(config)
    engine = SoundEngine(config, soundpad.player)
    ctl = Controller(config, engine, soundpad)
    err = None
    try:
        with Terminal() as term:
            app = App(ctl, term)
            app.starter = run_boot
            app.run()
    except Exception:  # noqa: BLE001  - the terminal is already restored by Terminal.__exit__
        err = traceback.format_exc()
    finally:
        ctl.shutdown()           # key hook -> playback -> engine -> save config (in that order)
    if err:
        print("The interface crashed (audio and settings were shut down cleanly):\n" + err, file=sys.stderr)
        return 1
    print("Bye!")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Soundpad - background soundboard for a virtual microphone")
    ap.add_argument("--list-devices", action="store_true", help="print output devices and exit")
    ap.add_argument("--fake-audio", action="store_true", help=argparse.SUPPRESS)   # tests: no hardware
    args = ap.parse_args()
    if args.fake_audio:
        from tests import fake_sd
        sys.modules["sounddevice"] = fake_sd
    if args.list_devices:
        return list_devices()
    return run_tui()


if __name__ == "__main__":
    sys.exit(main())

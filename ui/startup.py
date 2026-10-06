"""Boot sequence run on a background thread so the boot screen can animate.
Order: config -> devices -> audio engine -> sound library -> global keyboard -> READY."""
from __future__ import annotations

from audio import devices as dev


def run_boot(app) -> None:
    ctl, b = app.ctl, app.boot

    def step(name, fn):
        b.status[name] = "run"
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001
            status, detail = "bad", str(e)[:70]
        b.status[name], b.detail[name] = status, detail

    step("config", lambda: ("ok", "first run" if ctl.config.first_run else "loaded"))

    def devices():
        api = dev.preferred_hostapi(ctl.config.get("audio.host_api"))
        return "ok", f"{api}: {len(dev.list_devices('output', api))} outputs"
    step("devices", devices)

    def engine():
        if ctl.config.first_run:
            return "warn", "waiting for first-run setup"
        ctl.engine.start()
        return ("ok", "") if ctl.engine.running else ("bad", "output device unavailable")
    step("engine", engine)

    def sounds():
        ctl.soundpad.start(listener=False)
        n = len(ctl.soundpad.library.sounds)
        return "ok", f"{n} sound{'s' if n != 1 else ''}"
    step("sounds", sounds)
    step("keyboard", lambda: ("ok", "global hook") if ctl.soundpad.start_listener()
         else ("bad", ctl.soundpad.keybinds.error[:60]))
    b.done = True
    if ctl.config.first_run:
        app.pending_setup = True        # the UI thread opens the setup once the title screen has been left

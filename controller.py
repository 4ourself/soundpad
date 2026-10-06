"""UI-facing facade over the backend (config + SoundEngine + SoundpadManager).

The TUI never touches decoding, key hooks or devices directly: it calls these methods and reads state.
All methods are cheap and thread-safe enough to be called from the UI thread at any frequency;
disk writes are debounced (tick()).
"""
from __future__ import annotations

import os
import queue
import time
from dataclasses import dataclass

from audio import devices as dev
from audio.diagnostics import verdict


@dataclass
class DeviceChoice:
    setting: str          # value stored in config: "default" | "none" | device name
    label: str
    index: int | None = None
    samplerate: float | None = None
    virtual: bool = False
    current: bool = False


class Controller:
    SAVE_INTERVAL = 0.5
    ROLE_KEY = {"output": "audio.output_device", "speaker": "audio.speaker_device"}

    def __init__(self, config, engine, soundpad):
        self.config, self.engine, self.soundpad = config, engine, soundpad
        config.autosave = False            # sliders change 30x/s: persist with a debounce instead
        self._last_save = 0.0
        self._cpu_t = (time.perf_counter(), time.process_time())
        self._cpu = 0.0
        self._ncpu = os.cpu_count() or 1

    # ------------------------------------------------------------------ devices
    def hostapi(self) -> str:
        try:
            return dev.preferred_hostapi(self.config.get("audio.host_api"))
        except dev.AudioBackendError:
            return ""

    def device_choices(self, role: str) -> list[DeviceChoice]:
        current = self.config.get(self.ROLE_KEY[role])
        out = [DeviceChoice("default", "Default device" if role == "speaker" else "Automatic (virtual cable if found)",
                            current=current == "default")]
        try:
            for d in dev.list_devices("output", self.hostapi()):
                out.append(DeviceChoice(d.name, d.name, d.index, d.default_samplerate,
                                        dev.is_virtual(d.name), current == d.name))
        except dev.AudioBackendError:
            pass
        if role == "speaker":
            out.append(DeviceChoice("none", "None (do not play on a speaker)", current=current == "none"))
        return out

    def select_device(self, role: str, setting: str) -> bool:
        self.config.set(self.ROLE_KEY[role], setting)
        return self.engine.restart_role(role)

    def refresh_devices(self) -> None:
        self.engine.refresh_devices()

    def first_run_defaults(self) -> dict[str, str]:
        """Sensible first-run picks: a virtual cable as Output when one exists, default speakers."""
        picks = {"output": "default", "speaker": "default"}
        cables = [c for c in self.device_choices("output") if c.virtual]
        best = next((c for c in cables if "input" in c.label.lower()), cables[0] if cables else None)
        if best:
            picks["output"] = best.setting
        return picks

    # ------------------------------------------------------------------ sounds
    def sounds(self):
        return self.soundpad.library.sounds

    def play(self, sound_id: str) -> None:
        self.soundpad.play_now(sound_id)

    def stop_all_sounds(self) -> None:
        self.soundpad.stop_all()

    def playing(self) -> list[dict]:
        return self.soundpad.player.snapshot()

    def keybind_conflict(self, keybind: str, ignore_id: str | None = None):
        if not keybind:
            return None
        others = self.soundpad.conflicts(keybind, ignore_id)
        return others[0] if others else None

    @property
    def listener_ok(self) -> bool:
        return self.soundpad.listener_ok

    # ------------------------------------------------------------------ live key panel
    def held_keys(self) -> str:
        return self.soundpad.keybinds.held_text()

    def recent_keys(self) -> list[tuple[float, str, list[str]]]:
        """[(time, combo, [names of sounds fired])] newest first."""
        out = []
        for t, combo, tags in self.soundpad.keybinds.recent():
            names = []
            for tag in tags:
                if tag == "__stop_all__":
                    names.append("Stop all")
                else:
                    s = self.soundpad.library.get(tag)
                    names.append(s.name if s else "?")
            out.append((t, combo, names))
        return out

    # ------------------------------------------------------------------ status / housekeeping
    def cpu_percent(self) -> float:
        now, cpu = time.perf_counter(), time.process_time()
        t0, c0 = self._cpu_t
        if now - t0 >= 1.0:
            self._cpu = (cpu - c0) / (now - t0) / self._ncpu * 100.0
            self._cpu_t = (now, cpu)
        return self._cpu

    def checks(self):
        return verdict(self.engine, self.soundpad)

    def drain_notifications(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        while True:
            try:
                out.append(self.engine.events.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                _, name, via = self.soundpad.events.get_nowait()
            except queue.Empty:
                break
            if via == "scan":
                out.append(("info", name))
            else:
                out.append(("sound", f"{name}" + (f"  [{via}]" if via else "")))
        if self.soundpad.last_error:
            out.append(("error", self.soundpad.last_error))
            self.soundpad.last_error = ""
        return out

    def tick(self) -> None:
        """Debounced persistence; call from the UI loop."""
        now = time.monotonic()
        if now - self._last_save >= self.SAVE_INTERVAL:
            self._last_save = now
            self.config.save_if_dirty()
            self.soundpad.flush()

    def shutdown(self) -> None:
        """Ordered shutdown: key listener -> playback -> streams -> persist."""
        for step in (self.soundpad.stop, self.engine.stop, self.soundpad.flush, self.config.save):
            try:
                step()
            except Exception:  # noqa: BLE001 - keep going: every device must be released
                pass

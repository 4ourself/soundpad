"""Soundpad audio engine - only two devices.

    SoundPlayer (all playing sounds) -> master volume -> soft limiter -> OUTPUT device (virtual cable = your "mic")
                                                                      '-> ring -> SPEAKER device (hear yourself)

The OUTPUT callback is the clock that renders the sounds. If the Output device is missing, the Speaker
callback renders them instead, so the pad still works on speakers alone.
Threads: PortAudio callbacks do light numpy work only; a watchdog thread detects lost devices and
reconnects them; the UI only reads/writes plain attributes.
"""
from __future__ import annotations

import queue
import threading
import time

import numpy as np

from .devices import (AudioBackendError, default_device, friendly_error, is_virtual, list_devices,
                      preferred_hostapi, refresh_backend, resolve_device)
from .limiter import soft_limit
from .meters import WaveHistory
from .output import OutputSink
from .ringbuffer import JitterReader, RingBuffer

ROLES = ("output", "speaker")


class SoundEngine:
    def __init__(self, config, player):
        self.cfg = config
        self.player = player
        self.sr = int(config.get("audio.sample_rate"))
        self.block = int(config.get("audio.block_size"))
        self.master_volume = float(config.get("mixer.master_volume"))
        self.speaker_volume = float(config.get("mixer.speaker_volume"))
        self.hear = bool(config.get("audio.hear_sounds"))

        self._ring = RingBuffer(self.sr, 2)
        self._reader = JitterReader(self._ring)
        self._output = OutputSink(self._fill_output, "output")
        self._speaker = OutputSink(self._fill_speaker, "speaker")
        self.running = False
        self.has_output = False
        self.has_speaker = False
        self.health = {r: {"state": "init", "name": "", "index": None, "samplerate": None, "error": ""}
                       for r in ROLES}
        self.warnings: list[str] = []
        self.events: queue.SimpleQueue = queue.SimpleQueue()   # (level, text) for the UI
        self.out_level = 0.0
        self.spk_level = 0.0
        self.last_error = ""
        self.wave_out = WaveHistory()
        self._lock = threading.RLock()
        self._epoch = 0
        self._hostapi: str | None = None
        self._stop_evt = threading.Event()
        self._watchdog: threading.Thread | None = None

    # ------------------------------------------------------------ audio callbacks (real-time thread!)
    def _render(self, frames: int) -> np.ndarray:
        block = self.player.render(frames)
        if self.master_volume != 1.0:
            block = block * np.float32(self.master_volume)
        return soft_limit(block)

    def _fill_output(self, frames: int) -> np.ndarray:
        mixed = self._render(frames)
        if self.hear and self.has_speaker:
            self._ring.write(mixed * np.float32(self.speaker_volume))
        lo, hi = float(mixed.min()), float(mixed.max())
        self.wave_out.push(lo, hi)
        self.out_level = max(max(abs(lo), abs(hi)), self.out_level * 0.9)
        return mixed

    def _fill_speaker(self, frames: int) -> np.ndarray:
        if not self.hear:
            self.spk_level *= 0.9
            if not self.has_output:
                self._render(frames)            # keep time moving so sounds still finish
            return np.zeros((frames, 2), np.float32)
        if self.has_output:
            block = self._reader.read(frames)
        else:                                    # no Output device: this stream is the clock
            block = self._render(frames) * np.float32(self.speaker_volume)
            lo, hi = float(block.min()), float(block.max())
            self.wave_out.push(lo, hi)
        self.spk_level = max(float(np.abs(block).max()), self.spk_level * 0.9)
        return block

    # ------------------------------------------------------------ roles
    def _sink(self, role):
        return self._output if role == "output" else self._speaker

    def _set_flag(self, role: str, on: bool) -> None:
        if role == "output":
            self.has_output = on
        else:
            self.has_speaker = on

    def _close_role(self, role: str) -> None:
        self._sink(role).stop()
        self._set_flag(role, False)

    def _open_role(self, role: str) -> bool:
        h = self.health[role]
        setting = self.cfg.get(f"audio.{role}_device")
        h.update(state="disconnected", name="" if setting in ("default", "none") else setting,
                 index=None, samplerate=None, error="")
        self._close_role(role)
        if role == "speaker" and setting == "none":
            h["state"] = "disabled"
            return False
        if self._hostapi is None:
            h["error"] = "audio backend unavailable"
            return False
        try:
            if role == "output" and setting == "default":
                # nothing chosen yet: prefer an installed virtual cable over the normal speakers
                virt = [d for d in list_devices("output", self._hostapi) if is_virtual(d.name)]
                info, note = (virt[0], "") if virt else (default_device("output", self._hostapi), "")
            else:
                info, note = resolve_device("output", setting, self._hostapi, strict=True)
        except Exception as e:  # noqa: BLE001
            h["error"] = friendly_error(str(e))
            return False
        if info is None:
            h["error"] = note or "no default device"
            return False
        if role == "speaker" and self.health["output"]["index"] == info.index and self.has_output:
            h.update(state="disabled", name=info.name, error="same device as Output")
            return False
        try:
            self._sink(role).start(info, self.sr, self.block)
        except Exception as e:  # noqa: BLE001
            h["error"] = friendly_error(str(e))
            return False
        h.update(state="ok", name=info.name, index=info.index, samplerate=info.default_samplerate, error="")
        self._set_flag(role, True)
        return True

    def _recompute(self) -> None:
        self.running = any(self.health[r]["state"] == "ok" for r in ROLES)

    def restart_role(self, role: str) -> bool:
        """Re-open ONE device after the user picked a new one. The other stream is untouched."""
        with self._lock:
            ok = self._open_role(role)
            if role == "output" and ok and self.health["speaker"]["state"] == "disabled":
                self._open_role("speaker")
            self._epoch += 1
            self._recompute()
            return ok

    # ------------------------------------------------------------ lifecycle
    def start(self) -> list[str]:
        """Open both streams. Never raises: failures are reported through `health`/`warnings`/`events`."""
        with self._lock:
            self._close_all()
            self.sr = int(self.cfg.get("audio.sample_rate"))
            self.block = int(self.cfg.get("audio.block_size"))
            self._reader = JitterReader(self._ring, int(self.cfg.get("audio.jitter_blocks")))
            self._ring.clear()
            try:
                self._hostapi = preferred_hostapi(self.cfg.get("audio.host_api"))
            except AudioBackendError as e:
                self._hostapi = None
                self.events.put(("error", str(e)))
            for role in ROLES:                 # output first: the speaker compares against it
                self._open_role(role)
            self._epoch += 1
            self._recompute()
            self.warnings = [f"{r}: {h['error']}" for r, h in self.health.items()
                             if h["state"] == "disconnected" and h["error"]]
            warnings = list(self.warnings)
        self._start_watchdog()
        return warnings

    def _close_all(self) -> None:
        for role in ROLES:
            self._close_role(role)
        self.running = False

    def stop(self) -> None:
        self._stop_evt.set()
        if self._watchdog is not None:
            self._watchdog.join(timeout=1.5)
            self._watchdog = None
        with self._lock:
            self._close_all()

    def refresh_devices(self) -> None:
        """Explicit refresh: close everything, re-enumerate devices, reopen."""
        with self._lock:
            self._close_all()
            try:
                refresh_backend()
            except AudioBackendError:
                pass
        self.start()
        self.events.put(("info", "Devices refreshed"))

    # ------------------------------------------------------------ watchdog / recovery
    def _start_watchdog(self) -> None:
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self._stop_evt.clear()
        self._watchdog = threading.Thread(target=self._watch, daemon=True, name="audio-watchdog")
        self._watchdog.start()

    def _counter(self, role) -> int:
        return self._sink(role).callbacks

    def _lose(self, role: str, msg: str) -> None:
        self._close_role(role)
        h = self.health[role]
        h.update(state="disconnected", error=msg)
        self._recompute()
        self.events.put(("warn", f"{role.upper()} {msg}: {h['name'] or role}"))

    def _watch(self) -> None:
        seen: dict[str, tuple[int, float]] = {}
        retry: dict[str, float] = {}
        epoch = -1
        last_full = time.monotonic()
        while not self._stop_evt.wait(0.5):
            if not self._lock.acquire(timeout=0.3):
                continue
            try:
                now = time.monotonic()
                if epoch != self._epoch:        # streams were (re)opened: restart baselines
                    epoch = self._epoch
                    seen = {r: (self._counter(r), now) for r in ROLES}
                    retry = {}
                for role in ROLES:
                    h = self.health[role]
                    if h["state"] == "ok":
                        cnt = self._counter(role)
                        stream = self._sink(role).stream
                        if cnt != seen[role][0]:
                            seen[role] = (cnt, now)
                        elif now - seen[role][1] > 1.5 or (stream is not None and not getattr(stream, "active", True)):
                            self._lose(role, "disconnected")
                    elif h["state"] == "disconnected" and now >= retry.get(role, 0):
                        if self._open_role(role):
                            seen[role] = (self._counter(role), now)
                            self._recompute()
                            self.events.put(("info", f"{role.upper()} reconnected: {h['name']}"))
                        else:
                            retry[role] = now + 3.0
                lost = any(h["state"] == "disconnected" for h in self.health.values())
                if lost and now - last_full > 15.0:
                    # cheap retries cannot see newly plugged devices (PortAudio caches the list):
                    # every 15 s re-enumerate with all streams closed.
                    last_full = now
                    self._close_all()
                    try:
                        refresh_backend()
                    except AudioBackendError:
                        pass
                    for role in ROLES:
                        self._open_role(role)
                    self._epoch += 1
                    self._recompute()
            except Exception as e:  # noqa: BLE001 - the watchdog must never die
                self.last_error = repr(e)
            finally:
                self._lock.release()

    # ------------------------------------------------------------ live controls (UI thread)
    def set_hear(self, on: bool) -> None:
        self.hear = bool(on)
        if not on:
            self._ring.clear()
        self.cfg.set("audio.hear_sounds", self.hear)

    def set_volume(self, which: str, value: float) -> None:
        value = max(0.0, min(2.0, value))
        if which == "master":
            self.master_volume = value
        elif which == "speaker":
            self.speaker_volume = value
        else:
            raise KeyError(which)
        self.cfg.set(f"mixer.{which}_volume", value)

    # ------------------------------------------------------------ status
    @property
    def state(self) -> str:
        if self._epoch == 0:
            return "STARTING"
        if not self.running or self.health["output"]["state"] == "disconnected":
            return "DEVICE ERROR"
        return "RUNNING"

    def latency_ms(self) -> float:
        """Approximate key -> Output latency: stream latency + one block."""
        st = self._output.stream
        v = getattr(st, "latency", 0.0) if st is not None else 0.0
        v = float(v[0] if isinstance(v, (tuple, list)) else v or 0.0)
        return v * 1000.0 + self.block / self.sr * 1000.0

    def stats(self) -> dict:
        return {"running": self.running, "has_output": self.has_output, "has_speaker": self.has_speaker,
                "out": self.out_level, "speaker": self.spk_level, "underruns": self._reader.underruns,
                "last_error": self.last_error}

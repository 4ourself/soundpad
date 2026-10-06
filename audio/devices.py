"""Device discovery, resolution (by name, per host API) and quick tests."""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import numpy as np


class AudioBackendError(RuntimeError):
    pass


def _sd():
    try:
        import sounddevice as sd
    except (ImportError, OSError) as e:
        raise AudioBackendError(
            f"sounddevice / PortAudio is not available ({e}). Run: pip install sounddevice") from e
    return sd


@dataclass
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    max_input: int
    max_output: int
    default_samplerate: float


VIRTUAL_HINTS = ("cable", "vb-audio", "voicemeeter", "virtual", "vac ", "blackhole", "loopback")


def is_virtual(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in VIRTUAL_HINTS)


def hostapi_names() -> list[str]:
    return [h["name"] for h in _sd().query_hostapis()]


def preferred_hostapi(setting: str = "auto") -> str:
    sd = _sd()
    names = hostapi_names()
    if setting not in (None, "auto") and setting in names:
        return setting
    if sys.platform == "win32":
        for n in names:
            if "WASAPI" in n:
                return n
    try:
        return names[sd.default.hostapi]
    except Exception:
        return names[0]


def list_devices(kind: str, hostapi: str) -> list[DeviceInfo]:
    """kind: 'input' | 'output'."""
    sd = _sd()
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        api = apis[d["hostapi"]]["name"]
        if api != hostapi:
            continue
        if d["max_input_channels" if kind == "input" else "max_output_channels"] <= 0:
            continue
        out.append(DeviceInfo(i, d["name"], api, d["max_input_channels"],
                              d["max_output_channels"], d["default_samplerate"]))
    return out


def default_device(kind: str, hostapi: str) -> DeviceInfo | None:
    sd = _sd()
    for api in sd.query_hostapis():
        if api["name"] == hostapi:
            idx = api["default_input_device" if kind == "input" else "default_output_device"]
            if idx is not None and idx >= 0:
                d = sd.query_devices(idx)
                return DeviceInfo(idx, d["name"], hostapi, d["max_input_channels"],
                                  d["max_output_channels"], d["default_samplerate"])
    return None


def refresh_backend() -> None:
    """Re-enumerate devices (PortAudio caches the list). ONLY call with every stream closed."""
    sd = _sd()
    sd._terminate()
    sd._initialize()


def friendly_error(msg: str) -> str:
    m = msg.lower()
    if "-9985" in m or "unavailable" in m or "busy" in m:
        return "device busy or in use by another app"
    if "-9996" in m or "invalid device" in m:
        return "device not available"
    if "-9997" in m or "sample rate" in m:
        return "unsupported sample rate"
    if "-9998" in m or "channel" in m:
        return "unsupported channel count"
    return msg.replace("\n", " ")[:90]


def resolve_device(kind: str, setting: str, hostapi: str, strict: bool = False):
    """Returns (DeviceInfo | None, note). setting: 'default' | 'none' | device name.
    strict=True: a named device that is missing returns None (no silent fallback to speakers)."""
    if setting == "none":
        return None, "disabled"
    if setting not in (None, "", "default"):
        for d in list_devices(kind, hostapi):
            if d.name == setting:
                return d, ""
        if strict:
            return None, f"'{setting}' not found"
        dflt = default_device(kind, hostapi)
        return dflt, f"'{setting}' not found - using default"
    return default_device(kind, hostapi), ""


def wasapi_settings(hostapi: str):
    if "WASAPI" not in hostapi:
        return None
    sd = _sd()
    try:
        return sd.WasapiSettings(auto_convert=True)  # lets Windows resample to 48 kHz
    except TypeError:
        return sd.WasapiSettings()


# ------------------------------------------------------------------ tests
def test_speaker(info: DeviceInfo, hostapi: str, seconds: float = 1.0, sr: int = 48000) -> None:
    sd = _sd()
    state = {"n": 0}
    channels = 2 if info.max_output >= 2 else 1

    def cb(outdata, frames, t, status):
        k = state["n"] + np.arange(frames)
        tone = (0.2 * np.sin(2 * np.pi * 440 * k / sr)).astype(np.float32)
        tone *= np.minimum(1.0, np.minimum(k, seconds * sr - k) / (0.02 * sr)).clip(0, 1)
        outdata[:] = tone[:, None]
        state["n"] += frames

    with sd.OutputStream(device=info.index, channels=channels, samplerate=sr, dtype="float32",
                         callback=cb, extra_settings=wasapi_settings(hostapi)):
        time.sleep(seconds + 0.1)

"""Output sinks (the 'Voice output' device and the 'Monitor' device)."""
from __future__ import annotations

import numpy as np

from .devices import DeviceInfo, _sd, wasapi_settings


class OutputSink:
    """Wraps an OutputStream. `fill(frames) -> float32 (frames, 2)` is called from the audio thread."""

    def __init__(self, fill, name="output"):
        self.fill = fill
        self.name = name
        self.stream = None
        self.channels = 2
        self.info = None
        self.callbacks = 0
        self.status_events = 0
        self.last_status = ""
        self.last_error = ""

    def _cb(self, outdata, frames, time_info, status):
        self.callbacks += 1
        if status:
            self.status_events += 1
            self.last_status = str(status)
        try:
            block = self.fill(frames)
        except Exception as e:  # noqa: BLE001 - never raise inside the audio callback
            self.last_error = repr(e)
            outdata.fill(0)
            return
        if outdata.shape[1] == 1:
            outdata[:, 0] = block.mean(axis=1)
        else:
            outdata.fill(0)
            outdata[:, :2] = block

    def start(self, info: DeviceInfo, sample_rate: int, block: int) -> None:
        sd = _sd()
        extra = wasapi_settings(info.hostapi)
        self.channels = 2 if info.max_output >= 2 else 1
        try:
            self.stream = sd.OutputStream(
                device=info.index, channels=self.channels, samplerate=sample_rate, blocksize=block,
                dtype="float32", latency="low", extra_settings=extra, callback=self._cb)
            self.stream.start()
            self.info = info
        except Exception as e:  # noqa: BLE001
            self.stream = None
            raise RuntimeError(f"cannot open {self.name} device '{info.name}': {e}") from e

    def stop(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            finally:
                self.stream = None

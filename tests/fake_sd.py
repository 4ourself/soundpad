"""Minimal fake `sounddevice` (real-time threads) so the whole app can run without hardware."""
import threading
import time

import numpy as np

CAPTURED = []          # blocks written to the 'virtual cable' output
MONITORED = []
_apis = [{"name": "Fake API", "default_input_device": 0, "default_output_device": 1}]
_devs = [
    {"name": "Fake Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000.0},
    {"name": "Fake Speakers", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
    {"name": "Fake Cable", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
]


class _D:
    hostapi = 0


default = _D()


def query_hostapis(i=None):
    return _apis if i is None else _apis[i]


def query_devices(i=None):
    return _devs if i is None else _devs[i]


class WasapiSettings:
    def __init__(self, **kw): pass


class _Stream:
    def __init__(self, device, channels, samplerate, blocksize, callback, **kw):
        self.device, self.channels, self.sr, self.bs, self.cb = device, channels, samplerate, blocksize, callback
        self._run = False

    def start(self):
        self._run = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self): self._run = False
    def close(self): self._run = False

    def _loop(self):
        nxt = time.perf_counter()
        while self._run:
            self._tick()
            nxt += self.bs / self.sr
            d = nxt - time.perf_counter()
            if d > 0:
                time.sleep(d)


class InputStream(_Stream):
    def _tick(self):
        self.t = getattr(self, "t", 0)
        k = self.t + np.arange(self.bs)
        data = (0.3 * np.sin(2 * np.pi * 300 * k / self.sr)).astype(np.float32)[:, None]
        self.t += self.bs
        self.cb(data, self.bs, None, None)


class OutputStream(_Stream):
    def _tick(self):
        out = np.zeros((self.bs, self.channels), np.float32)
        self.cb(out, self.bs, None, None)
        (CAPTURED if self.device == 2 else MONITORED).append(out.copy())

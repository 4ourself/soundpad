"""Sound decoding (-> float32 / stereo / engine rate), RAM cache, streaming for long files, library JSON."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from audio.ringbuffer import RingBuffer
from config import DATA_DIR, atomic_write_json

# Extensions that are certainly audio (or audio in a video container). Files with OTHER extensions are
# still accepted when libsndfile / PyAV can open them, so unknown formats work too.
AUDIO_EXTENSIONS = frozenset((
    ".wav", ".wave", ".mp3", ".mp2", ".mp1", ".ogg", ".oga", ".opus", ".spx", ".flac", ".aiff", ".aif", ".aifc",
    ".m4a", ".m4b", ".aac", ".wma", ".webm", ".weba", ".mka", ".mp4", ".m4r", ".3gp", ".amr", ".awb", ".ac3",
    ".eac3", ".dts", ".caf", ".au", ".snd", ".w64", ".rf64", ".voc", ".ape", ".wv", ".tta", ".tak", ".mpc",
    ".mid", ".alac", ".ra", ".ram", ".gsm", ".sf", ".iff", ".svx", ".paf", ".pvf", ".htk", ".sd2", ".sds",
    ".nist", ".sph", ".mat", ".avr", ".xi", ".wve", ".vox", ".mpga", ".mka", ".dsf", ".dff", ".mov", ".mkv",
    ".avi", ".flv",
))
SUPPORTED = tuple(sorted(AUDIO_EXTENSIONS))
_NOT_AUDIO = frozenset((".txt", ".json", ".md", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico", ".exe", ".dll",
                        ".py", ".pyc", ".ini", ".cfg", ".log", ".zip", ".rar", ".7z", ".pdf", ".doc", ".docx",
                        ".lnk", ".db", ".tmp", ".bak", ".html", ".htm", ".css", ".js", ".csv", ".xml", ".url"))
MAX_SCAN_FILES = 5000


def norm_path(p: str | Path) -> str:
    """Case-insensitive on Windows, slash-agnostic key for comparing file paths."""
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(p))))


def to_stereo(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        return np.repeat(data, 2, axis=1)
    return data[:, :2]


def clean_path(text: str) -> str:
    """Pasted paths: strip quotes / whitespace / file:// and a trailing separator, expand ~ and %VARS%."""
    t = (text or "").strip().strip("\"").strip("'").strip()
    if t.lower().startswith("file:///"):
        t = t[8:]
    t = os.path.expandvars(os.path.expanduser(t))
    if len(t) > 3 and t[-1] in "\\/":
        t = t[:-1]
    return t


def _probe(path: str) -> bool:
    """True when libsndfile or PyAV can read an audio stream from the file (header only, fast)."""
    try:
        import soundfile as sf
        sf.info(path)
        return True
    except Exception:  # noqa: BLE001
        pass
    try:
        import av
        with av.open(path) as c:
            return any(s.type == "audio" for s in c.streams)
    except Exception:  # noqa: BLE001
        return False


def is_audio_file(path: str | Path, probe_unknown: bool = True) -> bool:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in AUDIO_EXTENSIONS:
        return True
    if ext in _NOT_AUDIO or not probe_unknown:
        return False
    return _probe(str(p))


def scan_folder(folder: str | Path, recursive: bool = True, limit: int = MAX_SCAN_FILES) -> tuple[list[Path], int]:
    """All audio files in a folder (sorted, natural-ish order). Returns (files, number_of_files_inspected)."""
    root = Path(folder)
    found: list[Path] = []
    seen = 0
    walker = os.walk(root) if recursive else [(str(root), [], [f.name for f in root.iterdir() if f.is_file()])]
    for dirpath, dirs, files in walker:
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$")))
        for name in sorted(files, key=lambda n: n.lower()):
            if name.startswith("."):
                continue
            seen += 1
            if seen > limit:
                return found, seen - 1
            fp = Path(dirpath) / name
            if is_audio_file(fp):
                found.append(fp)
    return found, seen


def _ffmpeg_decode(path: str, sr: int) -> np.ndarray:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("cannot decode this file (install PyAV: pip install av)")
    proc = subprocess.run([exe, "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"],
                          capture_output=True, check=True)
    return np.frombuffer(proc.stdout, np.float32).reshape(-1, 2).copy()


def _av_blocks(path: str, sr: int):
    """Yield float32 stereo blocks at `sr` decoded by PyAV (bundles ffmpeg: m4a/aac/wma/webm/mp4/...)."""
    import av
    with av.open(path) as c:
        stream = next((s for s in c.streams if s.type == "audio"), None)
        if stream is None:
            raise RuntimeError("no audio stream in file")
        rs = av.AudioResampler(format="flt", layout="stereo", rate=sr)
        for frame in c.decode(stream):
            for f in rs.resample(frame):
                yield f.to_ndarray().reshape(-1, 2).copy()
        for f in rs.resample(None):
            yield f.to_ndarray().reshape(-1, 2).copy()


def decode_file(path: str, sr: int) -> np.ndarray:
    """Fully decode to float32 stereo at `sr`: libsndfile first, then PyAV, then an ffmpeg binary."""
    import soundfile as sf
    import soxr
    try:
        data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001 - format unknown to libsndfile (m4a, wma, ...)
        try:
            blocks = list(_av_blocks(path, sr))
            if not blocks:
                raise RuntimeError("file contains no audio")
            return np.ascontiguousarray(np.concatenate(blocks), dtype=np.float32)
        except ImportError:
            return _ffmpeg_decode(path, sr)
    data = to_stereo(data)
    if file_sr != sr:
        data = soxr.resample(data, file_sr, sr, quality="HQ")
    return np.ascontiguousarray(data, dtype=np.float32)


def probe_duration(path: str) -> float | None:
    try:
        import soundfile as sf
        info = sf.info(path)
        return info.frames / float(info.samplerate)
    except Exception:  # noqa: BLE001
        pass
    try:
        import av
        with av.open(path) as c:
            if c.duration:
                return c.duration / 1_000_000.0
    except Exception:  # noqa: BLE001
        pass
    return None


class StreamingSource:
    """Decodes a long file on a background thread into a small ring (no full preload)."""

    def __init__(self, path: str, sr: int):
        self.path, self.sr = path, sr
        self.ring = RingBuffer(sr * 3, 2)
        self.error = ""
        self._done = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="soundpad-stream")
        self._thread.start()
        t0 = time.time()
        while self.ring.available < sr // 4 and not self._done and time.time() - t0 < 0.5:
            time.sleep(0.005)

    def _run(self):
        try:
            try:
                import soundfile as sf
                f = sf.SoundFile(self.path)
            except Exception:  # noqa: BLE001 - not a libsndfile format: decode with PyAV
                for block in _av_blocks(self.path, self.sr):
                    if not self._push(block):
                        return
                return
            import soxr
            with f:
                rs = None
                if f.samplerate != self.sr:
                    rs = soxr.ResampleStream(f.samplerate, self.sr, 2, dtype="float32", quality="HQ")
                for block in f.blocks(blocksize=f.samplerate // 4, dtype="float32", always_2d=True):
                    block = to_stereo(block)
                    if rs is not None:
                        block = rs.resample_chunk(block)
                    if not self._push(block):
                        return
                if rs is not None:
                    tail = rs.resample_chunk(np.zeros((0, 2), np.float32), last=True)
                    if len(tail):
                        self.ring.write(tail)
        except Exception as e:  # noqa: BLE001
            self.error = repr(e)
        finally:
            self._done = True

    def _push(self, block) -> bool:
        """Write a decoded block, waiting while the ring is full. False when closed."""
        while not self._stop.is_set() and self.ring.free < len(block):
            time.sleep(0.01)
        if self._stop.is_set():
            return False
        self.ring.write(block)
        return True

    def read(self, n: int):
        data, _ = self.ring.read(n)
        ended = self._done and self.ring.available == 0
        return data, ended

    def close(self):
        self._stop.set()


@dataclass
class Sound:
    name: str
    file: str
    keybind: str = ""
    volume: float = 1.0
    cooldown_ms: int | None = None      # None -> use the global soundpad cooldown
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    # runtime-only
    audio: np.ndarray | None = field(default=None, repr=False, compare=False)
    duration: float = 0.0
    streaming: bool = False
    state: str = "unloaded"   # unloaded | loading | ready | error
    error: str = ""

    def to_json(self) -> dict:
        d = {"id": self.id, "name": self.name, "file": self.file,
             "keybind": self.keybind, "volume": self.volume}
        if self.cooldown_ms is not None:
            d["cooldown_ms"] = int(self.cooldown_ms)
        return d


class SoundLibrary:
    def __init__(self, sample_rate: int = 48000, stream_threshold: float = 120.0, path: Path | None = None):
        self.sr = sample_rate
        self.stream_threshold = stream_threshold
        self.path = Path(path) if path else DATA_DIR / "sounds.json"
        self._sounds: list[Sound] = []
        self.removed: set[str] = set()      # files the user deleted: folder re-scans must not bring them back
        self._lock = threading.RLock()
        self._load_lock = threading.Lock()
        self.dirty = False

    # -- persistence
    def load(self) -> None:
        import json
        with self._lock:
            self._sounds = []
            self.removed = set()
            if not self.path.exists():
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            self.removed = {norm_path(p) for p in data.get("removed", [])}
            for d in data.get("sounds", []):
                if "file" not in d:
                    continue
                self._sounds.append(Sound(
                    name=d.get("name") or Path(d["file"]).stem, file=d["file"],
                    keybind=d.get("keybind", ""), volume=float(d.get("volume", 1.0)),
                    cooldown_ms=d.get("cooldown_ms"),
                    id=d.get("id") or uuid.uuid4().hex[:8]))

    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.path, {"sounds": [s.to_json() for s in self._sounds],
                                          "removed": sorted(self.removed)})
            self.dirty = False

    def save_if_dirty(self) -> None:
        if self.dirty:
            self.save()

    # -- access
    @property
    def sounds(self) -> list[Sound]:
        with self._lock:
            return list(self._sounds)

    def get(self, sound_id: str) -> Sound | None:
        with self._lock:
            return next((s for s in self._sounds if s.id == sound_id), None)

    def add(self, sound: Sound) -> Sound:
        with self._lock:
            self._sounds.append(sound)
            self.removed.discard(norm_path(sound.file))
        self.save()
        return sound

    def add_many(self, sounds: list[Sound]) -> None:
        with self._lock:
            self._sounds.extend(sounds)
            for s in sounds:
                self.removed.discard(norm_path(s.file))
        self.save()

    def find_file(self, file: str) -> Sound | None:
        key = norm_path(file)
        with self._lock:
            return next((s for s in self._sounds if norm_path(s.file) == key), None)

    def remove(self, sound_id: str) -> bool:
        with self._lock:
            n = len(self._sounds)
            gone = [s for s in self._sounds if s.id == sound_id]
            self._sounds = [s for s in self._sounds if s.id != sound_id]
            self.removed.update(norm_path(s.file) for s in gone)
            changed = len(self._sounds) != n
        if changed:
            self.save()
        return changed

    # -- decoding
    def prepare(self, sound: Sound, force: bool = False) -> bool:
        """Make a sound ready to play (decode into RAM, or mark as streaming). Thread-safe."""
        with self._load_lock:
            if sound.state == "ready" and not force:
                return True
            sound.state, sound.error = "loading", ""
            try:
                path = str(Path(sound.file).expanduser())
                if not Path(path).is_file():
                    raise FileNotFoundError(path)
                dur = probe_duration(path)
                if dur is not None and dur > self.stream_threshold:
                    sound.streaming, sound.audio, sound.duration = True, None, dur
                else:
                    sound.streaming = False
                    sound.audio = decode_file(path, self.sr)
                    sound.duration = len(sound.audio) / self.sr
                sound.state = "ready"
                return True
            except Exception as e:  # noqa: BLE001
                sound.state, sound.error, sound.audio = "error", str(e) or repr(e), None
                return False

    def preload_async(self) -> threading.Thread:
        def run():
            for s in self.sounds:
                if s.state in ("unloaded", "error"):
                    self.prepare(s)
        t = threading.Thread(target=run, daemon=True, name="soundpad-preload")
        t.start()
        return t

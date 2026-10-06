"""Soundpad manager: library + keybinds + global listener + playback worker.

Started ONCE by main.py and independent of whichever UI tab is displayed.
The keyboard listener thread only enqueues a request (it must return fast); a worker thread
does the actual lookup / lazy decode / playback start.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .keybinds import KeybindManager, format_keybind, parse_keybind
from .loader import (Sound, SoundLibrary, StreamingSource, clean_path, is_audio_file, norm_path,
                     scan_folder)
from .player import SoundPlayer


@dataclass
class LoadResult:
    kind: str = "file"                 # file | folder
    path: str = ""
    added: int = 0
    known: int = 0                     # already in the list
    inspected: int = 0
    sounds: list = field(default_factory=list)

    def summary(self) -> str:
        if self.kind == "file":
            return "Added 1 sound" if self.added else "Sound is already in the list"
        if self.added:
            extra = f" ({self.known} already loaded)" if self.known else ""
            return f"Loaded {self.added} sound{'s' if self.added != 1 else ''} from folder{extra}"
        if self.known:
            return f"Nothing new: all {self.known} sounds are already loaded"
        return f"No audio files found ({self.inspected} files checked)"


class SoundpadManager:
    def __init__(self, config, library_path: Path | None = None):
        self.cfg = config
        sr = int(config.get("audio.sample_rate"))
        self.sr = sr
        self.library = SoundLibrary(sr, float(config.get("soundpad.stream_threshold_seconds")), library_path)
        self.player = SoundPlayer(int(config.get("soundpad.max_simultaneous")),
                                  bool(config.get("soundpad.allow_overlap")))
        self.keybinds = KeybindManager(bool(config.get("soundpad.allow_repeat")),
                                       bool(config.get("soundpad.exact_single_keys")))
        self._q: queue.Queue = queue.Queue()
        self.events: queue.SimpleQueue = queue.SimpleQueue()   # (time, sound name, via) for UI notifications
        self._worker: threading.Thread | None = None
        self._last_play: dict[str, float] = {}
        self._running = False
        self.last_error = ""

    # ------------------------------------------------------------ lifecycle
    def start(self, listener: bool = True) -> bool:
        """Start library, worker thread and (optionally) the global keyboard hook. Idempotent."""
        self.library.load()
        self.rebind_all()
        self._running = True
        threading.Thread(target=self._startup_scan, daemon=True, name="soundpad-scan").start()
        self._worker = threading.Thread(target=self._work, daemon=True, name="soundpad-worker")
        self._worker.start()
        return self.start_listener() if listener else True

    def _startup_scan(self) -> None:
        """Pick up files added to the loaded folders since last time, then pre-decode everything."""
        try:
            self.rescan_folders()
        except Exception as e:  # noqa: BLE001
            self.last_error = f"folder scan: {e}"
        if self.cfg.get("soundpad.preload"):
            self.library.preload_async()

    def start_listener(self) -> bool:
        return self.keybinds.start()

    def stop(self) -> None:
        self._running = False
        self._q.put(None)
        self.keybinds.stop()
        self.player.stop_all()

    @property
    def listener_ok(self) -> bool:
        return self.keybinds.available

    # ------------------------------------------------------------ library operations
    def rebind_all(self) -> list[str]:
        """Re-register every keybind. Returns warnings (invalid binds)."""
        self.keybinds.clear()
        warnings = []
        for s in self.library.sounds:
            if not s.keybind:
                continue
            try:
                self.keybinds.bind(s.keybind, lambda sid=s.id, kb=s.keybind: self.request_play(sid, kb), tag=s.id)
            except ValueError as e:
                warnings.append(f"{s.name}: {e}")
        stop_key = self.cfg.get("soundpad.stop_all_keybind")
        if stop_key:
            try:
                self.keybinds.bind(stop_key, self.stop_all, tag="__stop_all__")
            except ValueError as e:
                warnings.append(f"stop-all: {e}")
        return warnings

    def add_sound(self, file: str, keybind: str = "", volume: float = 1.0, name: str = "",
                  cooldown_ms: int | None = None) -> Sound:
        file = clean_path(file)
        path = Path(file)
        if not path.is_file():
            raise FileNotFoundError(f"file not found: {file}")
        if not is_audio_file(path):
            raise ValueError(f"'{path.name}' is not an audio file")
        keybind = format_keybind(parse_keybind(keybind)) if keybind.strip() else ""
        s = self.library.add(Sound(name=name or path.stem, file=str(path), keybind=keybind,
                                   volume=max(0.0, min(2.0, volume)),
                                   cooldown_ms=None if cooldown_ms is None else max(0, int(cooldown_ms))))
        self.rebind_all()
        threading.Thread(target=self.library.prepare, args=(s,), daemon=True).start()
        return s

    # ------------------------------------------------------------ loading by pasting a path
    def load_path(self, text: str) -> LoadResult:
        """The 'paste a directory' entry point. Accepts a folder (all audio inside) or a single file."""
        path = clean_path(text)
        if not path:
            raise ValueError("paste a folder path")
        p = Path(path)
        if p.is_file():
            known = self.library.find_file(str(p))
            if known is not None:
                return LoadResult("file", str(p), 0, 1, 1, [known])
            s = self.add_sound(str(p))
            return LoadResult("file", str(p), 1, 0, 1, [s])
        if not p.is_dir():
            raise FileNotFoundError(f"not found: {path}")
        recursive = bool(self.cfg.get("soundpad.scan_subfolders"))
        res = self._import_folder(p, recursive, forget_removed=True)
        folders = list(self.cfg.get("soundpad.folders") or [])
        if norm_path(p) not in {norm_path(f) for f in folders}:
            folders.append(str(p))
            self.cfg.set("soundpad.folders", folders)
        return res

    def _import_folder(self, folder: Path, recursive: bool, forget_removed: bool = False) -> LoadResult:
        files, seen = scan_folder(folder, recursive)
        res = LoadResult("folder", str(folder), inspected=seen)
        if forget_removed:                 # an explicit load brings deleted sounds back
            for f in files:
                self.library.removed.discard(norm_path(f))
        new: list[Sound] = []
        for f in files:
            key = norm_path(f)
            if self.library.find_file(str(f)) is not None:
                res.known += 1
            elif key not in self.library.removed:
                new.append(Sound(name=f.stem, file=str(f)))
        if new:
            self.library.add_many(new)
            self.rebind_all()
            if self.cfg.get("soundpad.preload"):
                self.library.preload_async()
        res.added, res.sounds = len(new), new
        return res

    def rescan_folders(self) -> int:
        """Re-read every saved folder; new files are added WITHOUT keybinds, existing bindings are kept."""
        total = 0
        recursive = bool(self.cfg.get("soundpad.scan_subfolders"))
        for f in list(self.cfg.get("soundpad.folders") or []):
            p = Path(f)
            if p.is_dir():
                total += self._import_folder(p, recursive).added
        if total:
            self.events.put((time.time(), f"{total} new sound{'s' if total != 1 else ''} found in your folders", "scan"))
        return total

    def forget_folder(self, folder: str) -> None:
        self.cfg.set("soundpad.folders", [f for f in self.cfg.get("soundpad.folders") if norm_path(f) != norm_path(folder)])

    def update_sound(self, sound_id: str, defer_save: bool = False, **fields) -> Sound:
        """defer_save=True marks the library dirty instead of writing (UI sliders; see flush())."""
        s = self.library.get(sound_id)
        if s is None:
            raise KeyError(sound_id)
        if "file" in fields:
            p = Path(clean_path(str(fields["file"])))
            if not p.is_file() or not is_audio_file(p):
                raise ValueError(f"not an audio file: {p}")
            fields["file"] = str(p)
        if "keybind" in fields:
            kb = fields["keybind"].strip()
            fields["keybind"] = format_keybind(parse_keybind(kb)) if kb else ""
        if "volume" in fields:
            fields["volume"] = max(0.0, min(2.0, float(fields["volume"])))
        if "cooldown_ms" in fields and fields["cooldown_ms"] is not None:
            fields["cooldown_ms"] = max(0, int(fields["cooldown_ms"]))
        for k, v in fields.items():
            setattr(s, k, v)
        if "file" in fields:
            s.state, s.audio, s.error = "unloaded", None, ""
            threading.Thread(target=self.library.prepare, args=(s,), daemon=True).start()
        if defer_save:
            self.library.dirty = True
        else:
            self.library.save()
        if "keybind" in fields:
            self.rebind_all()
        return s

    def flush(self) -> None:
        """Persist debounced changes (called periodically by the UI loop and on exit)."""
        self.library.save_if_dirty()

    def remove_sound(self, sound_id: str) -> None:
        self.player.stop_sound(sound_id)
        self.library.remove(sound_id)
        self.rebind_all()

    def conflicts(self, keybind: str, ignore_id: str | None = None) -> list[Sound]:
        keys = frozenset(parse_keybind(keybind))
        return [s for s in self.library.sounds
                if s.id != ignore_id and s.keybind and frozenset(parse_keybind(s.keybind)) == keys]

    # ------------------------------------------------------------ settings
    def apply_settings(self) -> list[str]:
        self.player.max_simultaneous = int(self.cfg.get("soundpad.max_simultaneous"))
        self.player.allow_overlap = bool(self.cfg.get("soundpad.allow_overlap"))
        self.keybinds.allow_repeat = bool(self.cfg.get("soundpad.allow_repeat"))
        self.keybinds.exact_single_keys = bool(self.cfg.get("soundpad.exact_single_keys"))
        return self.rebind_all()

    # ------------------------------------------------------------ playback
    def request_play(self, sound_id: str, via: str = "") -> None:
        """Called from the keyboard thread: enqueue only."""
        self._q.put((time.monotonic(), sound_id, via))

    def play_now(self, sound_id: str) -> None:
        self._q.put((None, sound_id, "UI"))   # UI play (ignores cooldown)

    def stop_all(self) -> None:
        self.player.stop_all()

    def _work(self) -> None:
        while self._running:
            item = self._q.get()
            if item is None:
                break
            t, sid, via = item
            try:
                self._play(t, sid, via)
            except Exception as e:  # noqa: BLE001
                self.last_error = repr(e)

    def _play(self, t, sound_id: str, via: str = "") -> None:
        sound = self.library.get(sound_id)
        if sound is None:
            return
        if t is not None:
            cd = sound.cooldown_ms if sound.cooldown_ms is not None else self.cfg.get("soundpad.cooldown_ms")
            cooldown = float(cd) / 1000.0
            if t - self._last_play.get(sound_id, -1e9) < cooldown:
                return
            self._last_play[sound_id] = t
        self.events.put((time.time(), sound.name, via))
        if sound.state != "ready" and not self.library.prepare(sound):
            self.last_error = f"{sound.name}: {sound.error}"
            return
        if sound.streaming:
            self.player.play(sound.id, sound.name, sound.volume,
                             stream=StreamingSource(str(Path(sound.file).expanduser()), self.sr),
                             total=int(sound.duration * self.sr))
        else:
            self.player.play(sound.id, sound.name, sound.volume, audio=sound.audio)

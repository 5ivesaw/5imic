"""The live processing engine shared by the GUI, TUI, and local CLI."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np
from .audio import AudioRouter, Capture
from .config import Settings, data_dir
from .dsp import CAPTURE_RATE, mono, rms
from .slicer import Word, cut_phrases
from .stitch import stitch
from .storage import Arena
from .transcribe import load_recognizer


class Engine:
    def __init__(self, root: Path | None = None):
        self.root = root or data_dir()
        self.settings = Settings.load(self.root)
        self.arena = Arena(self.root, self.settings.max_storage_mb,
                           self.settings.max_variants)
        self.router = AudioRouter()
        self.capture: Capture | None = None
        self.status = "Ready"
        self.last_transcript = ""
        self.last_result = ""
        self.last_latency_ms = 0.0
        self.recording = False
        self.running = False
        self.lock = threading.RLock()
        self.queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=3)
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._pending: list[np.ndarray] = []
        self._preroll = np.zeros(0, dtype=np.float32)
        self._quiet = 0
        self._active = False
        self._dropped = 0
        self._recognizer = None
        self._recognizer_name = None
        self._recognizer_lock = threading.RLock()
        self._ptt = threading.Event()
        self._ptt_thread: threading.Thread | None = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        try:
            self.router.configure(self.settings.virtual_mic, self.settings.monitor)
        except Exception as exc:
            self.status = f"Virtual mic unavailable: {exc}. Preview is still possible."
            self.router.status = f"Preview only — virtual mic unavailable: {exc}"
            try:
                self.router.monitor = __import__("soundcard").default_speaker()
            except Exception:
                pass
        self.worker = threading.Thread(target=self._recognize_loop, name="5imic-asr", daemon=True)
        self.worker.start()
        self.capture = Capture(self.settings.capture_device, self.router.is_guarded,
                               self._accept_audio, self._error)
        self.capture.enabled.clear()  # Opt-in before collecting voices.
        self.status = "Paused · press Record to begin"

    def _error(self, error: str):
        self.status = error

    def toggle(self, value: bool | None = None) -> bool:
        with self.lock:
            self.recording = not self.recording if value is None else bool(value)
            if self.capture:
                if self.recording:
                    self.capture.start()
                (self.capture.enabled.set if self.recording else self.capture.enabled.clear)()
            if not self.recording:
                self._pending = []
                self._active = False
                self._quiet = 0
            self.status = "Listening to selected output" if self.recording else "Paused"
            return self.recording

    def _accept_audio(self, chunk: np.ndarray):
        if not self.recording or self.router.is_guarded():
            self._pending = []
            self._active = False
            self._quiet = 0
            self._preroll = np.zeros(0, dtype=np.float32)
            return
        level = rms(chunk)
        voiced = level > self.settings.speech_rms
        if not self._active:
            if voiced:
                self._active = True
                self._pending = [self._preroll, chunk]
                self._quiet = 0
            else:
                self._preroll = chunk[-CAPTURE_RATE // 5:].copy()
            return
        self._pending.append(chunk)
        self._quiet = 0 if voiced else self._quiet + len(chunk)
        count = sum(len(x) for x in self._pending)
        if self._quiet >= self.settings.silence_ms * CAPTURE_RATE / 1000 or (
            count >= self.settings.max_utterance_sec * CAPTURE_RATE
        ):
            speech = np.concatenate(self._pending)
            self._pending = []
            self._active = False
            self._quiet = 0
            if len(speech) > CAPTURE_RATE // 3:
                try:
                    self.queue.put_nowait(speech)
                except queue.Full:
                    self._dropped += 1

    def _recognize_loop(self):
        while not self.stop_event.is_set():
            try:
                samples = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                started = time.monotonic()
                words: list[Word] = self._transcribe(samples)
                self.last_latency_ms = (time.monotonic() - started) * 1000
                eligible = [w for w in words if w.confidence >= self.settings.confidence]
                self.last_transcript = " ".join(w.text for w in words) or "(no speech detected)"
                # Crucial: preserve original word order/timing. Confidence-filtered
                # words must not become adjacent phantom phrases.
                segments = cut_phrases(samples, words, self.settings.confidence)
                stored = sum(self.arena.add(segment, samples) for segment in segments)
                self.status = (f"Recorded {stored} clips · {len(eligible)}/{len(words)} "
                               f"high-confidence words")
            except Exception as exc:
                self.status = f"Recognition: {exc}"
            finally:
                self.queue.task_done()

    def _transcribe(self, samples: np.ndarray) -> list[Word]:
        # Recognition models are often not re-entrant, so microphone puppet
        # mode and passive indexing share a single locked instance.
        with self._recognizer_lock:
            if self._recognizer_name != self.settings.model:
                self.status = f"Loading {self.settings.model}…"
                self._recognizer = load_recognizer(self.settings.model, self.root)
                self._recognizer_name = self.settings.model
            return self._recognizer.transcribe(samples)

    def puppet_start(self) -> bool:
        """Press-and-hold mic speech → text → borrowed clips, never raw mic pass-through."""
        if self._ptt_thread and self._ptt_thread.is_alive():
            return False
        self._ptt.set()
        self._ptt_thread = threading.Thread(target=self._puppet_run,
                                            name="5imic-puppet", daemon=True)
        self._ptt_thread.start()
        return True

    def puppet_stop(self):
        self._ptt.clear()

    def puppet(self, seconds: float = 3) -> None:
        if self.puppet_start():
            self.stop_event.wait(max(0.3, min(seconds, 10)))
            self.puppet_stop()
            if self._ptt_thread:
                self._ptt_thread.join(timeout=120)

    def _puppet_run(self):
        try:
            from .audio import _soundcard
            mic = _soundcard().default_microphone()
            if mic is None or mic.isloopback:
                raise RuntimeError("No physical microphone found for puppet mode")
            self.status = "Puppet mode · listening to your real microphone…"
            pieces = []
            try:
                recorder = mic.recorder(samplerate=CAPTURE_RATE, channels=2, blocksize=1600)
            except Exception:
                recorder = mic.recorder(samplerate=CAPTURE_RATE, channels=1, blocksize=1600)
            with recorder as stream:
                while self._ptt.is_set() and sum(len(x) for x in pieces) < 10 * CAPTURE_RATE:
                    pieces.append(mono(stream.record(numframes=1600)))
            if sum(len(x) for x in pieces) < CAPTURE_RATE // 4:
                self.status = "Puppet mode · hold longer to speak"
                return
            self.status = "Puppet mode · recognizing…"
            words = self._transcribe(np.concatenate(pieces))
            if any(w.confidence < self.settings.confidence for w in words):
                self.status = "Puppet mode · uncertain transcription; try a clearer phrase"
                return
            phrase = " ".join(w.text for w in words)
            if not phrase:
                self.status = "Puppet mode · couldn't confidently understand speech"
                return
            reply = self.say(phrase)
            self.status = (f"Puppet: {phrase} → {reply.get('spoken', reply.get('error'))}")
        except Exception as exc:
            self.status = f"Puppet mode: {exc}"
        finally:
            self._ptt.clear()

    def say(self, text: str, partial: bool = False) -> dict:
        if not text.strip():
            return {"ok": False, "error": "Type something first."}
        if len(text) > 1000:
            return {"ok": False, "error": "Limit is 1000 characters."}
        with self.lock:
            started = time.monotonic()
            result = stitch(text, self.arena.clips(), self.arena.read,
                            self.settings.mode, self.settings.effect)
            if not len(result.audio):
                return {"ok": False, "error": "No matching recorded words yet.",
                        "missing": result.missing, "coverage": 0}
            if result.coverage < self.settings.min_coverage and not partial:
                return {"ok": False, "error": "Not enough exact words recorded yet. "
                        "Use '--partial' to intentionally play only the matched words.",
                        "missing": result.missing, "coverage": result.coverage}
            search_ms = round((time.monotonic() - started) * 1000, 1)
            try:
                self.router.play(result.audio)
            except Exception as exc:
                return {"ok": False, "error": f"Audio output failed: {exc}",
                        "coverage": result.coverage, "spoken": result.spoken}
            self.last_result = result.spoken
            return {"ok": True, "spoken": result.spoken, "missing": result.missing,
                    "coverage": round(result.coverage, 3), "clip_ids": result.clip_ids,
                    "assembly_ms": search_ms, "duration_s": round(len(result.audio) / 12000, 2),
                    "route": self.router.status}

    def update(self, **values) -> dict:
        allowed = {"mode": {"natural", "low", "high", "chaos"},
                   "effect": {"clean", "crush", "glitch"},
                   "model": {"whisper-tiny.en", "whisper-base.en", "whisper-small.en", "vosk-small-en"}}
        for name, value in values.items():
            if name not in allowed or value not in allowed[name]:
                raise ValueError(f"Invalid setting: {name}={value}")
            setattr(self.settings, name, value)
        self.settings.save(self.root)
        return {"mode": self.settings.mode, "effect": self.settings.effect,
                "model": self.settings.model}

    def set_capture_device(self, device: str) -> None:
        """Switch the monitored speaker without touching virtual-mic routing."""
        with self.lock:
            was_recording = self.recording
            self.toggle(False)
            if self.capture:
                self.capture.close()
            self.settings.capture_device = device
            self.settings.save(self.root)
            self.capture = Capture(device, self.router.is_guarded, self._accept_audio, self._error)
            self.capture.enabled.clear()
            if was_recording:
                self.toggle(True)

    def stats(self) -> dict:
        return {**self.arena.stats(), "recording": self.recording, "model": self.settings.model,
                "mode": self.settings.mode, "effect": self.settings.effect,
                "route": self.router.status, "status": self.status,
                "transcript": self.last_transcript, "dropped": self._dropped,
                "asr_ms": round(self.last_latency_ms, 1)}

    def clips(self, limit: int = 40) -> list[dict]:
        records = self.arena.clips()[-max(1, min(limit, 200)):]
        return [{"id": item.id, "text": item.text, "confidence": round(item.confidence, 3),
                 "quality": round(item.quality, 3), "pitch": round(item.pitch),
                 "speaker": item.speaker, "pinned": item.pinned}
                for item in reversed(records)]

    def ingest(self, audio: np.ndarray) -> dict:
        """Explicit offline import for repeatable diagnosis, no system capture needed."""
        words = self._transcribe(audio)
        segments = cut_phrases(audio, words, self.settings.confidence)
        count = sum(self.arena.add(item, audio, speaker="import") for item in segments)
        return {"transcript": " ".join(w.text for w in words), "stored": count,
                "recognized": len(words)}

    def close(self):
        self.running = False
        self._ptt.clear()
        self.stop_event.set()
        if self.capture:
            self.capture.close()
        if self._ptt_thread:
            self._ptt_thread.join(timeout=2)
        if self.worker:
            self.worker.join(timeout=2)
        self.router.close()
        self.arena.close()


"""Cross-platform desktop loopback capture and deliberately one-way output routing."""
from __future__ import annotations

import os
import platform
import subprocess
import threading
import time
from collections.abc import Callable

import numpy as np
from .dsp import CAPTURE_RATE, STORE_RATE, mono, resample

VIRTUAL_SINK = "fiveimic_output"
VIRTUAL_SOURCE = "fiveimic_mic"


def _soundcard():
    import soundcard
    return soundcard


def list_devices() -> dict[str, list[str]]:
    sc = _soundcard()
    return {"speakers": [s.name for s in sc.all_speakers()],
            "loopbacks": [m.name for m in sc.all_microphones(include_loopback=True)
                          if m.isloopback]}


def choose_capture(sc, preference: str):
    speakers = sc.all_speakers()
    if preference == "default":
        speaker = sc.default_speaker()
    else:
        speaker = next((s for s in speakers if preference.lower() in s.name.lower()
                        or preference == str(s.id)), None)
    if speaker is None:
        raise RuntimeError("Capture speaker not found. Run '5imic devices' to list outputs.")
    if "fiveimic" in speaker.name.lower() or "cable input" in speaker.name.lower():
        raise RuntimeError("Refusing to record the virtual microphone output (feedback risk).")
    candidates = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    match = next((m for m in candidates if str(m.id) == str(speaker.id)), None)
    if not match:
        match = next((m for m in candidates if speaker.name.lower() in m.name.lower()
                      or m.name.lower() in speaker.name.lower()), None)
    if not match:
        raise RuntimeError(f"No loopback capture available for {speaker.name!r}. "
                           "On Linux, check PipeWire/PulseAudio; on Windows, enable WASAPI.")
    return speaker, match


class AudioRouter:
    def __init__(self):
        self.modules: list[str] = []
        self.playing = threading.Event()
        self.cooldown_until = 0.0
        self.status = "Not configured"
        self.virtual = None
        self.monitor = None

    def configure(self, want_virtual: bool = True, want_monitor: bool = True):
        sc = _soundcard()
        self.monitor = sc.default_speaker() if want_monitor else None
        self.virtual = None
        if want_virtual and platform.system() == "Linux":
            # Only null sink + remapped source: never route system output to input.
            names = [s.name.lower() for s in sc.all_speakers()]
            if not any(VIRTUAL_SINK in n for n in names):
                self.modules.append(self._load_module("module-null-sink",
                    f"sink_name={VIRTUAL_SINK}",
                    "sink_properties=device.description=5imic_Virtual_Output"))
            sources = subprocess.run(["pactl", "list", "short", "sources"],
                text=True, capture_output=True, check=False).stdout
            if VIRTUAL_SOURCE not in sources:
                self.modules.append(self._load_module("module-remap-source",
                    f"master={VIRTUAL_SINK}.monitor", f"source_name={VIRTUAL_SOURCE}",
                    "source_properties=device.description=5imic_Virtual_Microphone"))
            sc = _soundcard()
            self.virtual = next((s for s in sc.all_speakers()
                                if VIRTUAL_SINK in s.name.lower() or
                                VIRTUAL_SINK in str(s.id).lower()), None)
        elif want_virtual and os.name == "nt":
            self.virtual = next((s for s in sc.all_speakers()
                                if "cable input" in s.name.lower()), None)
        if self.virtual is not None and self.monitor is not None:
            if str(self.virtual.id) == str(self.monitor.id):
                self.monitor = None
        if self.virtual:
            self.status = "Virtual mic ready"
        else:
            self.status = ("Preview only — install VB-CABLE to transmit"
                           if os.name == "nt" else "Preview only — virtual mic unavailable")

    @staticmethod
    def _load_module(*parts: str) -> str:
        result = subprocess.run(["pactl", "load-module", *parts], text=True,
                                capture_output=True, timeout=8, check=True)
        module = result.stdout.strip()
        if not module.isdigit():
            raise RuntimeError(f"Unexpected pactl module ID: {module!r}")
        return module

    def is_guarded(self) -> bool:
        return self.playing.is_set() or time.monotonic() < self.cooldown_until

    def play(self, samples: np.ndarray):
        if not len(samples):
            return
        outputs = [s for s in (self.virtual, self.monitor) if s is not None]
        if not outputs:
            raise RuntimeError("No playback device available")
        if self.playing.is_set():
            raise RuntimeError("Already playing; wait for current phrase to finish")
        self.playing.set()
        failures = []
        stalled = False
        try:
            # Route separate streams in parallel. No OS-level loopback between them.
            stereo = np.repeat(samples[:, None], 2, axis=1)
            threads = []
            def stream(speaker):
                try:
                    speaker.play(stereo, samplerate=STORE_RATE)
                except Exception as exc:
                    failures.append(f"{speaker.name}: {exc}")
            for item in outputs:
                task = threading.Thread(target=stream, args=(item,), daemon=True)
                task.start()
                threads.append(task)
            for task in threads:
                task.join(timeout=max(3, len(samples) / STORE_RATE + 3))
            remaining = [task for task in threads if task.is_alive()]
            if remaining:
                stalled = True
                def release_when_done():
                    for task in remaining:
                        task.join()
                    self.cooldown_until = time.monotonic() + 0.8
                    self.playing.clear()
                threading.Thread(target=release_when_done, daemon=True).start()
                raise RuntimeError("Audio backend stalled; recording remains gated until output ends")
            if failures:
                raise RuntimeError("; ".join(failures))
        finally:
            if not stalled:
                self.cooldown_until = time.monotonic() + 0.8
                self.playing.clear()

    def close(self):
        # Unload only modules created by this process. Never touch user audio graph.
        for module in reversed(self.modules):
            subprocess.run(["pactl", "unload-module", module], capture_output=True,
                           timeout=5, check=False)
        self.modules.clear()


class Capture:
    """Recording runs in its own thread; main/UI thread never touches blocking I/O."""
    def __init__(self, device: str, guarded: Callable[[], bool],
                 on_audio: Callable[[np.ndarray], None], on_error: Callable[[str], None]):
        self.device = device
        self.guarded = guarded
        self.on_audio = on_audio
        self.on_error = on_error
        self.stop_event = threading.Event()
        self.enabled = threading.Event()
        self.enabled.set()
        self.worker: threading.Thread | None = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run, name="5imic-capture", daemon=True)
        self.worker.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                sc = _soundcard()
                _, device = choose_capture(sc, self.device)
                # Use 2 channels on WASAPI; SoundCard documents mono capture quirks.
                with device.recorder(samplerate=CAPTURE_RATE, channels=2,
                                     blocksize=3200) as recorder:
                    while not self.stop_event.is_set():
                        chunk = mono(recorder.record(numframes=3200))
                        if self.enabled.is_set() and not self.guarded():
                            self.on_audio(chunk)
                        else:
                            self.on_audio(np.zeros_like(chunk))
            except Exception as exc:
                self.on_error(f"Capture: {exc}")
                self.stop_event.wait(2.0)

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=2)


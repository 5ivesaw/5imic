"""Swappable offline speech recognition backends with word timing and confidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import numpy as np
from .dsp import CAPTURE_RATE, mono
from .slicer import Word, tokens

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_NAMES = ("whisper-tiny.en", "whisper-base.en", "whisper-small.en", "vosk-small-en")


class Recognizer(Protocol):
    def transcribe(self, audio: np.ndarray) -> list[Word]: ...


class VoskRecognizer:
    def __init__(self, model_directory: Path):
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        if not model_directory.is_dir():
            raise FileNotFoundError(f"Vosk model missing: {model_directory}. Run '5imic models install vosk-small-en'.")
        self.model = Model(str(model_directory))

    def transcribe(self, audio: np.ndarray) -> list[Word]:
        from vosk import KaldiRecognizer
        recognizer = KaldiRecognizer(self.model, CAPTURE_RATE)
        recognizer.SetWords(True)
        data = (mono(audio) * 32767).astype("<i2").tobytes()
        results = []
        for start in range(0, len(data), 8000):
            if recognizer.AcceptWaveform(data[start:start + 8000]):
                results.extend(json.loads(recognizer.Result()).get("result", []))
        results.extend(json.loads(recognizer.FinalResult()).get("result", []))
        return [Word(item["word"], float(item["start"]), float(item["end"]),
                     float(item.get("conf", 0))) for item in results if tokens(item["word"])]


class WhisperRecognizer:
    def __init__(self, name: str):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Accuracy engine missing; install '5imic[accuracy]' or use the release build.") from exc
        model = name.removeprefix("whisper-")
        self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=2,
                                  num_workers=1)

    def transcribe(self, audio: np.ndarray) -> list[Word]:
        segments, _ = self.model.transcribe(mono(audio), language="en", beam_size=3,
            word_timestamps=True, condition_on_previous_text=False, vad_filter=False)
        words = []
        for segment in segments:
            if segment.no_speech_prob > 0.75:
                continue
            for item in segment.words or []:
                parts = tokens(item.word)
                if parts:
                    words.append(Word(parts[0], float(item.start), float(item.end),
                                      float(item.probability)))
        return words


def load_recognizer(name: str, directory: Path) -> Recognizer:
    if name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {name}")
    if name == "vosk-small-en":
        return VoskRecognizer(directory / "models" / "vosk-small-en")
    return WhisperRecognizer(name)

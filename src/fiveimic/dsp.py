"""Small vectorized voice DSP functions; no heavyweight ML dependencies."""
from __future__ import annotations

import math
import numpy as np

CAPTURE_RATE = 16000
STORE_RATE = 12000


def mono(audio: np.ndarray) -> np.ndarray:
    values = np.asarray(audio, dtype=np.float32)
    if values.ndim == 2:
        values = values.mean(axis=1)
    if values.ndim != 1:
        raise ValueError("audio must be mono or frames-by-channels")
    return np.clip(values, -1.0, 1.0)


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    audio = mono(audio)
    if source_rate == target_rate or not len(audio):
        return audio.copy()
    count = max(1, round(len(audio) * target_rate / source_rate))
    positions = np.arange(count, dtype=np.float64) * (source_rate / target_rate)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def encode_ulaw(audio: np.ndarray) -> bytes:
    """ITU G.711-style 8-bit companding, with sign/magnitude reconstruction."""
    x = np.clip(mono(audio), -1.0, 1.0)
    mu = 255.0
    encoded = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    return np.clip(np.rint((encoded + 1.0) * 127.5), 0, 255).astype(np.uint8).tobytes()


def decode_ulaw(encoded: bytes) -> np.ndarray:
    q = np.frombuffer(encoded, dtype=np.uint8).astype(np.float32)
    companded = (q / 127.5) - 1.0
    return (np.sign(companded) * np.expm1(np.abs(companded) * np.log1p(255.0)) / 255.0).astype(np.float32)


def rms(audio: np.ndarray) -> float:
    if not len(audio):
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def pitch_and_brightness(audio: np.ndarray, rate: int = CAPTURE_RATE) -> tuple[float, float]:
    """Cheap, approximate metadata (not speaker identification)."""
    audio = mono(audio)
    if len(audio) < int(rate * 0.04) or rms(audio) < 0.003:
        return 0.0, 0.0
    middle = len(audio) // 2
    frame = audio[max(0, middle - int(rate * 0.025)):middle + int(rate * 0.025)]
    frame = frame - frame.mean()
    spec = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
    hz = np.fft.rfftfreq(len(frame), 1 / rate)
    brightness = float(np.dot(spec, hz) / (spec.sum() + 1e-9))
    # Compare only human voice f0 lags and gate weak/noisy periodicity.
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1:]
    minimum, maximum = max(1, rate // 420), min(len(corr) - 1, rate // 65)
    if maximum <= minimum or corr[0] <= 1e-8:
        return 0.0, brightness
    lag = int(np.argmax(corr[minimum:maximum + 1])) + minimum
    if corr[lag] / corr[0] < 0.38:
        return 0.0, brightness
    return float(rate / lag), brightness


def normalize(audio: np.ndarray, target: float = 0.095) -> np.ndarray:
    audio = mono(audio)
    level = rms(audio)
    if level < 0.0005:
        return audio
    return np.clip(audio * min(3.0, target / level), -0.90, 0.90)


def assemble(parts: list[np.ndarray], rate: int = STORE_RATE, effect: str = "clean",
             seed: int | None = None) -> np.ndarray:
    if not parts:
        return np.zeros(0, dtype=np.float32)
    joined = normalize(parts[0])
    overlap = max(1, int(rate * 0.012))
    for clip in parts[1:]:
        clip = normalize(clip)
        n = min(overlap, len(joined) // 2, len(clip) // 2)
        if n:
            phase = np.linspace(0, math.pi / 2, n, dtype=np.float32)
            seam = joined[-n:] * np.cos(phase) + clip[:n] * np.sin(phase)
            joined = np.concatenate((joined[:-n], seam, clip[n:]))
        else:
            joined = np.concatenate((joined, clip))
    if effect == "crush":
        joined = np.round(joined * 32) / 32
    elif effect == "glitch" and len(joined) > rate // 4:
        rng = np.random.default_rng(seed)
        at = int(rng.integers(rate // 8, len(joined) - rate // 10))
        fragment = joined[at:at + rate // 24]
        joined = np.concatenate((joined[:at], fragment, fragment, joined[at:]))
    elif effect != "clean":
        raise ValueError(f"Unknown effect: {effect}")
    ramp = min(len(joined) // 2, int(rate * 0.006))
    if ramp:
        joined[:ramp] *= np.linspace(0, 1, ramp, dtype=np.float32)
        joined[-ramp:] *= np.linspace(1, 0, ramp, dtype=np.float32)
    return np.clip(joined, -0.95, 0.95).astype(np.float32)


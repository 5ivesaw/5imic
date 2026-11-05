"""Acoustic-boundary-aware phrase cutting from recognizer word timestamps."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from .dsp import CAPTURE_RATE, rms


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    confidence: float


@dataclass(frozen=True)
class Slice:
    text: str
    start: int
    end: int
    confidence: float
    cleanliness: float
    locked: bool


def boundary(audio: np.ndarray, left: Word, right: Word,
             rate: int = CAPTURE_RATE) -> tuple[bool, float, int]:
    """A conservative seam score, NOT a classifier of actual coarticulation."""
    proposed = round((left.end + right.start) * rate / 2)
    proposed = max(0, min(len(audio), proposed))
    gap = right.start - left.end
    if gap >= 0.025:
        return True, 1.0, proposed
    radius = int(rate * 0.024)
    start, end = max(0, proposed - radius), min(len(audio), proposed + radius)
    if end <= start:
        return False, 0.0, proposed
    # Find a quiet 6ms seam neighborhood. Speech energy drops at many valid cuts.
    window = max(2, int(rate * 0.006))
    values = np.square(audio[start:end].astype(np.float64))
    moving = np.convolve(values, np.ones(window) / window, mode="valid")
    if not len(moving):
        return False, 0.0, proposed
    offset = int(np.argmin(moving)) + window // 2
    position = start + offset
    local = rms(audio[max(0, start - radius):min(len(audio), end + radius)])
    ratio = float(np.sqrt(moving.min()) / max(local, 1e-5))
    clean = ratio < 0.24
    return clean, float(max(0.0, 1.0 - ratio)), position


def cut_phrases(audio: np.ndarray, words: list[Word], threshold: float = 0.65,
                rate: int = CAPTURE_RATE) -> list[Slice]:
    """Emit short exact contiguous phrases without fabricated sub-word labels.

    Segments start/end only on estimated clean seams or utterance edges.
    Long unbroken speech chains may be >3 words; they stay intact rather than
    being mislabeled or artificially duplicated.
    """
    good = [w for w in words if tokens(w.text) and w.end > w.start]
    if not good:
        return []
    clean = [True]
    seam = [max(0, round((good[0].start - 0.018) * rate))]
    qualities = [1.0]
    for prev, current in zip(good, good[1:]):
        ok, score, position = boundary(audio, prev, current, rate)
        clean.append(ok)
        seam.append(position)
        qualities.append(score)
    clean.append(True)
    seam.append(min(len(audio), round((good[-1].end + 0.025) * rate)))
    qualities.append(1.0)
    clips = []
    for i in range(len(good)):
        if not clean[i]:
            continue
        # If continuous speech has no clean boundary for >5 words, retain
        # one longer honest chain rather than discarding the whole utterance.
        for j in range(i + 1, len(good) + 1):
            if j - i > 5 and j < len(good):
                continue
            if not clean[j]:
                continue
            if any(w.confidence < threshold for w in good[i:j]):
                continue
            # No word can be skipped. Avoid arbitrary max-word splitting.
            start = max(0, min(len(audio), seam[i]))
            end = max(start, min(len(audio), seam[j]))
            if end - start < rate * 0.06:
                continue
            inside = qualities[i + 1:j]
            quality = min([qualities[i], qualities[j], *inside])
            clips.append(Slice(" ".join(tokens(w.text)[0] for w in good[i:j]),
                               start, end, min(w.confidence for w in good[i:j]),
                               quality, not all(clean[i + 1:j])))
    return clips

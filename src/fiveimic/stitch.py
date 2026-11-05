"""Exact-coverage dynamic-programming phrase planner (no gibberish substitutions)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .dsp import STORE_RATE, assemble
from .slicer import tokens
from .storage import Clip


@dataclass
class Result:
    requested: str
    spoken: str
    coverage: float
    missing: list[str]
    clip_ids: list[int]
    audio: np.ndarray


def plan(text: str, clips: list[Clip], mode: str = "natural",
         speaker: str | None = None) -> tuple[list[Clip], list[str]]:
    """Cover the input with exact phrase matches, once per input position.

    DP maximizes coverage first. Missing words are skipped, NEVER replaced by
    semantically adjacent but wrong recordings; no overlapping replay possible.
    """
    words = tokens(text)
    by_first: dict[str, list[Clip]] = {}
    for clip in clips:
        ws = tokens(clip.text)
        if ws and (speaker is None or clip.speaker == speaker):
            by_first.setdefault(ws[0], []).append(clip)
    n = len(words)
    score: list[tuple[int, float]] = [(0, 0.0)] * (n + 1)
    steps: list[tuple[int, Clip | None]] = [(n, None)] * (n + 1)
    for i in range(n - 1, -1, -1):
        score[i] = score[i + 1]
        steps[i] = (i + 1, None)
        for clip in by_first.get(words[i], []):
            cw = tokens(clip.text)
            j = i + len(cw)
            if words[i:j] != cw:
                continue
            bonus = clip.confidence * 0.8 + clip.quality * 0.2
            if mode == "low":
                bonus += 0.35 if clip.pitch and clip.pitch < 145 else 0
            elif mode == "high":
                bonus += 0.35 if clip.pitch > 180 else 0
            elif mode == "chaos":
                bonus += 0.1 * ((clip.id * 17) % 7)
            elif mode != "natural":
                raise ValueError(f"Unknown voice mode: {mode}")
            candidate = (score[j][0] + len(cw), score[j][1] + bonus - 0.08)
            if candidate > score[i]:
                score[i] = candidate
                steps[i] = (j, clip)
    selected, missing = [], []
    i = 0
    while i < n:
        j, clip = steps[i]
        if clip is None:
            missing.append(words[i])
        else:
            selected.append(clip)
        i = j
    return selected, missing


def stitch(text: str, clips: list[Clip], reader: Callable[[Clip], np.ndarray],
           mode: str = "natural", effect: str = "clean",
           speaker: str | None = None) -> Result:
    selected, missing = plan(text, clips, mode, speaker)
    total = len(tokens(text))
    coverage = (total - len(missing)) / total if total else 0.0
    data = assemble([reader(item) for item in selected], STORE_RATE, effect=effect)
    return Result(text, " ".join(item.text for item in selected),
                  coverage, missing, [item.id for item in selected], data)


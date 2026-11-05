"""Crash-tolerant SQLite clip index and compact, bounded μ-law arena."""
from __future__ import annotations

import os
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from .dsp import CAPTURE_RATE, STORE_RATE, decode_ulaw, encode_ulaw, pitch_and_brightness, resample, rms
from .slicer import Slice


@dataclass(frozen=True)
class Clip:
    id: int
    text: str
    offset: int
    size: int
    confidence: float
    quality: float
    pitch: float
    brightness: float
    loudness: float
    speaker: str
    pinned: bool
    locked: bool
    created: float


class Arena:
    def __init__(self, root: Path, max_mb: int = 200, variants: int = 5):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "audio.ulaw"
        self.db = sqlite3.connect(str(self.root / "clips.db"), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY, text TEXT NOT NULL, offset INTEGER NOT NULL,
            size INTEGER NOT NULL, confidence REAL NOT NULL, quality REAL NOT NULL,
            pitch REAL NOT NULL, brightness REAL NOT NULL, loudness REAL NOT NULL,
            speaker TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
            locked INTEGER NOT NULL, created REAL NOT NULL
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS clips_text ON clips(text)")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('generation','0')")
        self.db.commit()
        self.path.touch(exist_ok=True)
        self.lock = threading.RLock()
        self.cap = max(1, max_mb) * 1024 * 1024
        self.variants = max(1, variants)
        self._recover()

    def _recover(self) -> None:
        """Finish or roll back a crash-interrupted arena compaction."""
        with self.lock, self.db:
            journal = self.root / "audio.ulaw.journal"
            backup = self.root / "audio.ulaw.backup"
            unfinished = self.root / "audio.ulaw.compact"
            if journal.exists():
                operation = json.loads(journal.read_text())
                current = int(self.db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0])
                if current == operation["old"]:
                    if backup.exists():
                        os.replace(backup, self.path)
                elif current == operation["new"]:
                    backup.unlink(missing_ok=True)
                else:
                    raise IOError("Arena compaction generation mismatch; manual recovery required")
                unfinished.unlink(missing_ok=True)
                journal.unlink()
            self.db.execute("DELETE FROM clips WHERE offset < 0 OR size < 1 OR offset+size > ?",
                            (self.path.stat().st_size,))

    @staticmethod
    def _row(row: sqlite3.Row) -> Clip:
        return Clip(int(row["id"]), row["text"], row["offset"], row["size"],
                    row["confidence"], row["quality"], row["pitch"], row["brightness"],
                    row["loudness"], row["speaker"], bool(row["pinned"]),
                    bool(row["locked"]), row["created"])

    def clips(self) -> list[Clip]:
        with self.lock:
            return [self._row(row) for row in self.db.execute("SELECT * FROM clips ORDER BY id")]

    def read(self, clip: Clip) -> np.ndarray:
        with self.lock, self.path.open("rb") as handle:
            handle.seek(clip.offset)
            data = handle.read(clip.size)
        if len(data) != clip.size:
            raise IOError("Audio arena corrupted or compacted during reading")
        return decode_ulaw(data)

    def add(self, phrase: Slice, audio: np.ndarray, speaker: str = "session") -> bool:
        segment = audio[phrase.start:phrase.end]
        stored = resample(segment, CAPTURE_RATE, STORE_RATE)
        if not len(stored) or rms(stored) < 0.003:
            return False
        content = encode_ulaw(stored)
        pitch, brightness = pitch_and_brightness(segment)
        with self.lock:
            if self.path.stat().st_size + len(content) > self.cap:
                self.compact(reserve=len(content))
                if self.path.stat().st_size + len(content) > self.cap:
                    return False  # Pinned data exhausted the cap.
            existing = self.db.execute(
                "SELECT * FROM clips WHERE text=? ORDER BY quality*confidence DESC",
                (phrase.text,)).fetchall()
            if len(existing) >= self.variants:
                # Retain the best versions, but NEVER evict a pinned user favorite.
                candidates = [r for r in existing if not r["pinned"]]
                if not candidates:
                    return False
                worst = min(candidates, key=lambda r: r["quality"] * r["confidence"])
                if phrase.cleanliness * phrase.confidence <= worst["quality"] * worst["confidence"]:
                    return False
                self.db.execute("DELETE FROM clips WHERE id=?", (worst["id"],))
            with self.path.open("ab") as handle:
                offset = handle.tell()
                handle.write(content)
                handle.flush()
            self.db.execute("""INSERT INTO clips
                (text,offset,size,confidence,quality,pitch,brightness,loudness,speaker,
                 pinned,locked,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (phrase.text, offset, len(content), phrase.confidence, phrase.cleanliness,
                 pitch, brightness, rms(stored), speaker, 0, int(phrase.locked), time.time()))
            self.db.commit()
        return True

    def compact(self, reserve: int = 0) -> None:
        """Rewrite live clips, evict oldest unpinned only, reclaim old offsets.

        Caller must hold lock or this method obtains it. Disk may temporarily
        require up to 2x arena space while atomic replacement is in progress.
        """
        with self.lock:
            rows = self.db.execute("SELECT * FROM clips ORDER BY created ASC,id ASC").fetchall()
            size = sum(row["size"] for row in rows)
            evicted = set()
            for row in rows:
                if size + reserve <= self.cap:
                    break
                if not row["pinned"]:
                    evicted.add(row["id"])
                    size -= row["size"]
            if size + reserve > self.cap:
                return
            tmp = self.root / "audio.ulaw.compact"
            offsets = {}
            with self.path.open("rb") as original, tmp.open("wb") as target:
                for row in rows:
                    if row["id"] in evicted:
                        continue
                    original.seek(row["offset"])
                    data = original.read(row["size"])
                    if len(data) != row["size"]:
                        raise IOError("Cannot compact invalid clip range")
                    offsets[row["id"]] = target.tell()
                    target.write(data)
                target.flush()
                os.fsync(target.fileno())
            old_gen = int(self.db.execute(
                "SELECT value FROM meta WHERE key='generation'").fetchone()[0])
            journal = self.root / "audio.ulaw.journal"
            backup = self.root / "audio.ulaw.backup"
            with journal.open("w") as marker:
                json.dump({"old": old_gen, "new": old_gen + 1}, marker)
                marker.flush()
                os.fsync(marker.fileno())
            os.replace(self.path, backup)
            os.replace(tmp, self.path)
            with self.db:
                for item in evicted:
                    self.db.execute("DELETE FROM clips WHERE id=?", (item,))
                self.db.executemany("UPDATE clips SET offset=? WHERE id=?",
                                    ((offset, ident) for ident, offset in offsets.items()))
                self.db.execute("UPDATE meta SET value=? WHERE key='generation'",
                                (str(old_gen + 1),))
            backup.unlink(missing_ok=True)
            journal.unlink(missing_ok=True)

    def pin(self, clip_id: int, value: bool = True) -> bool:
        with self.lock, self.db:
            result = self.db.execute("UPDATE clips SET pinned=? WHERE id=?",
                                     (int(value), clip_id))
            return result.rowcount > 0

    def clear(self, keep_pinned: bool = True) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM clips WHERE pinned=0" if keep_pinned
                            else "DELETE FROM clips")
        self.compact()

    def stats(self) -> dict:
        with self.lock:
            row = self.db.execute("""SELECT COUNT(*) total, COALESCE(SUM(pinned),0) pinned,
                COUNT(DISTINCT text) phrases FROM clips""").fetchone()
            return {"clips": row["total"], "pinned": row["pinned"],
                    "phrases": row["phrases"], "bytes": self.path.stat().st_size,
                    "cap": self.cap}

    def close(self) -> None:
        with self.lock:
            self.db.close()


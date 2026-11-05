import numpy as np
import json
import os

from fiveimic.slicer import Slice
from fiveimic.storage import Arena


def phrase(text="hello", quality=1.0):
    return Slice(text, 0, 4800, 0.98, quality, False)


def signal():
    x = np.arange(4800, dtype=np.float32)
    return 0.14 * np.sin(2 * np.pi * 200 * x / 16000).astype(np.float32)


def test_add_read_persistence_and_pin(tmp_path):
    store = Arena(tmp_path)
    assert store.add(phrase(), signal())
    clip = store.clips()[0]
    assert clip.text == "hello"
    assert abs(len(store.read(clip)) - 3600) < 2
    assert store.pin(clip.id)
    store.close()
    store = Arena(tmp_path)
    assert store.stats()["pinned"] == 1
    store.clear(keep_pinned=True)
    assert store.stats()["clips"] == 1
    store.close()


def test_dedup_compact_and_cap(tmp_path):
    store = Arena(tmp_path, max_mb=1, variants=2)
    assert store.add(phrase(quality=0.4), signal())
    assert store.add(phrase(quality=0.7), signal())
    assert not store.add(phrase(quality=0.3), signal())
    assert store.add(phrase(quality=0.9), signal())
    assert store.stats()["clips"] == 2
    before = store.stats()["bytes"]
    store.compact()
    assert store.stats()["bytes"] < before
    for clip in store.clips():
        assert len(store.read(clip)) > 0
    store.close()


def test_crash_recovery_restores_pre_compaction_arena(tmp_path):
    store = Arena(tmp_path)
    assert store.add(phrase(), signal())
    clip = store.clips()[0]
    original = store.read(clip).copy()
    store.close()
    arena = tmp_path / "audio.ulaw"
    backup = tmp_path / "audio.ulaw.backup"
    os.replace(arena, backup)
    arena.write_bytes(b"corrupted new generation")
    (tmp_path / "audio.ulaw.journal").write_text(json.dumps({"old": 0, "new": 1}))
    restored = Arena(tmp_path)
    assert np.allclose(restored.read(restored.clips()[0]), original)
    assert not backup.exists()
    assert not (tmp_path / "audio.ulaw.journal").exists()
    restored.close()


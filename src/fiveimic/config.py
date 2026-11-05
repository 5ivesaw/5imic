"""Settings and app-local paths. No configuration file required on first run."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("FIVEIMIC_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "5imic"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "5imic"


@dataclass
class Settings:
    model: str = "whisper-tiny.en"
    confidence: float = 0.65
    silence_ms: int = 450
    speech_rms: float = 0.008
    max_utterance_sec: float = 8.0
    max_storage_mb: int = 200
    max_variants: int = 5
    min_coverage: float = 0.80
    mode: str = "natural"
    effect: str = "clean"
    capture_device: str = "default"
    monitor: bool = True
    virtual_mic: bool = True
    pinned: bool = True
    overlay_x: int = 120
    overlay_y: int = 100

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        path = (root or data_dir()) / "settings.json"
        if not path.exists():
            return cls()
        values = json.loads(path.read_text(encoding="utf-8"))
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in allowed})

    def save(self, root: Path | None = None) -> None:
        directory = root or data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)


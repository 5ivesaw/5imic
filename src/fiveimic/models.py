"""On-demand local model installation, without assuming an internet connection."""
from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .transcribe import MODEL_NAMES, VOSK_URL, load_recognizer


def available(root: Path) -> dict[str, bool | str]:
    models = {name: (root / "models" / name).is_dir() for name in MODEL_NAMES}
    # Whisper downloads into a separate Hugging Face cache; don't misreport
    # its availability as False if we haven't inspected that external cache.
    for name in MODEL_NAMES:
        if name.startswith("whisper-"):
            models[name] = "managed by model cache (download on first use)"
    return models


def install(name: str, root: Path, progress=None):
    if name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {name}; choices: {', '.join(MODEL_NAMES)}")
    if name.startswith("whisper-"):
        if progress:
            progress(f"Downloading {name} through Hugging Face (first use may take a while)…")
        load_recognizer(name, root)
        if progress:
            progress(f"{name} ready")
        return
    destination = root / "models" / "vosk-small-en"
    if destination.is_dir():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="5imic-model-") as temporary:
        archive = Path(temporary) / "model.zip"
        if progress:
            progress("Downloading small English model (~40 MB)…")
        with urllib.request.urlopen(VOSK_URL, timeout=45) as response, archive.open("wb") as sink:
            copied = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > 150 * 1024 * 1024:
                    raise ValueError("Model archive unexpectedly large")
                sink.write(chunk)
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if sum(entry.file_size for entry in entries) > 450 * 1024 * 1024:
                raise ValueError("Unpacked model unexpectedly large")
            for entry in entries:
                path = Path(entry.filename)
                if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
                    raise ValueError("Unsafe model archive entry")
                if entry.is_dir():
                    continue
                target = Path(temporary) / "unpack" / Path(*path.parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
        source = Path(temporary) / "unpack"
        if not (source / "am").is_dir():
            raise ValueError("Unexpected Vosk model layout")
        os.replace(source, destination)
    if progress:
        progress("Vosk model ready")

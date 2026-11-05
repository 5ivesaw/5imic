# 5imic v0.1.0 — release candidate status

## Local verification

- Python sources compile cleanly with Python 3.12.
- 17 direct core tests pass locally, covering: audio companding and fades;
  speech boundary grouping; exact-match phrase sequencing; voice modes;
  missing-word reporting; SQLite storage, pinning and compaction; loopback
  selection and rejection of virtual output capture; local controller
  commands, interrupted compaction recovery and low-coverage playback refusal.
- The command-line router and help output start correctly from source.
- SVG branding and a multi-resolution Windows icon are included.
- Source launchers create an isolated virtual environment and run the app
  without modifying global Python packages.
- Tests and build recipes are staged for Windows and Ubuntu CI runners.

## Still requiring real-device verification

- Physical WASAPI/PipeWire loopback capture and virtual microphone enumeration.
- SoundCard output fidelity at the target sample rate on real playback hardware.
- Actual speech recognition model download, inference and word alignment.
- GUI appearance on target desktops and window managers, including Wayland.
- Windows/Linux PyInstaller executable startup and automatic release creation.
- Real sessions with game audio, poor microphones, overlapping speakers,
  headset echo, and multi-hour storage churn.

## Platform and runtime realities

- Windows needs an installed virtual audio cable driver to transmit as a mic.
- Linux needs a PipeWire/PulseAudio-compatible service plus `pactl` for an
  automatically created virtual microphone.
- First recognition model use downloads weights; speech models are not bundled.
- Passive speech detection is energy-based, not a dedicated neural VAD.
- This is an experimental, testable application; low latency and accurate
  recognition are goals, not guaranteed benchmarks.

## Publish status

The GitHub connector returned HTTP 403 with “Resource not accessible by
integration” on the first attempt to create README.md in the empty repository.
No repository files or GitHub Release were published by that attempt. This ZIP
includes the full source, tests, documentation and release workflow so it can
be pushed after GitHub content-write access is enabled.

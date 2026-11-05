"""One entry point for the GUI, live TUI, troubleshooting, and remote commands."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import wave
from pathlib import Path

import numpy as np
from . import __version__
from .config import Settings, data_dir
from .dsp import CAPTURE_RATE, resample
from .engine import Engine
from .ipc import Controller, request
from .models import available, install
from .transcribe import MODEL_NAMES


def printed(value):
    if isinstance(value, dict):
        for key, item in value.items():
            print(f"{key.replace('_', ' ').title():<16} {item}")
    else:
        print(value)


def start_owned(use_gui: bool):
    root = data_dir()
    try:
        request(root, "stats")
    except Exception:
        pass
    else:
        print("5imic is already running. Use '5imic tui' in the existing terminal, "
              "or '5imic say ...' to speak.", file=sys.stderr)
        return 1
    engine = Engine(root)
    controller = Controller(engine, root)
    controller.start()
    try:
        if use_gui:
            from .gui import App
            app = App(engine, lambda: None)
            app.run()
        else:
            engine.start()
            run_tui(engine)
    finally:
        controller.close()
        engine.close()
    return 0


def run_tui(engine: Engine):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.patch_stdout import patch_stdout

    keybindings = KeyBindings()
    @keybindings.add("f2")
    def _(event):
        engine.toggle()
        event.app.invalidate()

    def footer():
        stats = engine.stats()
        return (f" [{'REC' if stats['recording'] else 'PAUSED'}] "
                f"{stats['clips']} clips · {stats['phrases']} phrases · "
                f"{stats['bytes']/1048576:.1f} MB · {stats['mode']} / {stats['effect']} "
                f"| F2 record | :help")

    print("\n  ▥ 5IMIC / LIVE VOICE CONSOLE")
    print("  Type a sentence to play it. Recording is paused until F2 or :record.")
    print("  This app must remain open for the virtual mic to work.\n")
    session = PromptSession(bottom_toolbar=footer, refresh_interval=0.8,
                            key_bindings=keybindings)
    with patch_stdout():
        while True:
            try:
                line = session.prompt("5imic › ").strip()
            except (KeyboardInterrupt, EOFError):
                break
            if not line:
                continue
            if line in (":quit", ":exit", ":q"):
                break
            if line in (":help", "?"):
                print(":record toggle capture · :talk 3 · :stats · :clips · :model NAME · :mode MODE "
                      "· :fx EFFECT · :pin ID · :partial TEXT · :quit")
            elif line == ":record":
                print("Recording:", engine.toggle())
            elif line.startswith(":talk"):
                parts = line.split()
                duration = float(parts[1]) if len(parts) > 1 else 3.0
                engine.puppet(duration)
                print(engine.status)
            elif line == ":stats":
                printed(engine.stats())
            elif line == ":clips":
                for item in engine.clips(25):
                    print(f"#{item['id']:<5} {item['text'][:42]:<44} "
                          f"{item['confidence']:.2f} {'◆' if item['pinned'] else ' '}")
            elif line.startswith(":model "):
                print(engine.update(model=line.split(maxsplit=1)[1]))
            elif line.startswith(":mode "):
                print(engine.update(mode=line.split(maxsplit=1)[1]))
            elif line.startswith(":fx "):
                print(engine.update(effect=line.split(maxsplit=1)[1]))
            elif line.startswith(":pin "):
                print("Pinned:", engine.arena.pin(int(line.split(maxsplit=1)[1])))
            else:
                response = engine.say(line[9:] if line.startswith(":partial ") else line,
                                      partial=line.startswith(":partial "))
                printed(response)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="5imic",
        description="Live clip-built voice synthesis. No arguments opens the GUI.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui", help="Start the desktop panel and pinnable quick type bar")
    sub.add_parser("tui", help="Run capture + live stats + typing in one terminal")
    cmd = sub.add_parser("say", help="Speak through an already running app")
    cmd.add_argument("text")
    cmd.add_argument("--partial", action="store_true", help="Play known words, skip missing ones")
    sub.add_parser("stats", help="Show running engine telemetry")
    clips = sub.add_parser("clips", help="View recently indexed clip texts and IDs")
    clips.add_argument("--limit", type=int, default=25)
    pin = sub.add_parser("pin", help="Pin a clip to protect it from eviction")
    pin.add_argument("id", type=int)
    sub.add_parser("record", help="Toggle live capture")
    sub.add_parser("devices", help="List sound devices and available loopback sources")
    sub.add_parser("doctor", help="Check installation and audio routing")
    for command, choices in (("mode", ("natural", "low", "high", "chaos")),
                             ("effect", ("clean", "crush", "glitch"))):
        sub.add_parser(command).add_argument("value", choices=choices)
    models = sub.add_parser("models", help="List or install selectable offline recognizers")
    models.add_argument("action", choices=("list", "install", "set"), nargs="?", default="list")
    models.add_argument("name", choices=MODEL_NAMES, nargs="?")
    ingest = sub.add_parser("ingest", help="Import a 16-bit WAV speech sample for diagnostics")
    ingest.add_argument("wav", type=Path)
    args = parser.parse_args(argv)
    root = data_dir()
    try:
        if args.command in (None, "gui"):
            if not os.environ.get("DISPLAY") and os.name != "nt":
                print("No graphical display; opening terminal UI instead.")
                return start_owned(False)
            return start_owned(True)
        if args.command == "tui":
            return start_owned(False)
        if args.command == "devices":
            from .audio import list_devices
            printed(list_devices())
        elif args.command == "doctor":
            from .audio import choose_capture, list_devices, _soundcard
            printed({"Python": sys.version.split()[0], "data": str(root),
                     "model": Settings.load(root).model})
            printed(list_devices())
            _, device = choose_capture(_soundcard(), Settings.load(root).capture_device)
            print("Capture loopback:", device.name)
            print("Windows requires an installed virtual audio cable for app microphone output.")
        elif args.command == "models":
            if args.action == "list":
                print("Current:", Settings.load(root).model)
                printed(available(root))
            elif not args.name:
                parser.error("models install/set requires a model name")
            elif args.action == "install":
                install(args.name, root, print)
            else:
                settings = Settings.load(root)
                settings.model = args.name
                settings.save(root)
                print("Selected:", args.name)
        elif args.command == "ingest":
            with wave.open(str(args.wav), "rb") as source:
                if source.getsampwidth() != 2 or source.getnchannels() not in (1, 2):
                    raise ValueError("Import supports mono/stereo 16-bit PCM WAV")
                rate = source.getframerate()
                audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
                if source.getnchannels() == 2:
                    audio = audio.reshape(-1, 2).mean(axis=1)
                audio = resample(audio.astype(np.float32) / 32768, rate, CAPTURE_RATE)
            engine = Engine(root)
            try:
                printed(engine.ingest(audio))
            finally:
                engine.close()
        else:
            command = {"say": "say", "stats": "stats", "clips": "clips", "pin": "pin",
                       "record": "toggle",
                       "mode": "update", "effect": "update"}[args.command]
            options = ({"text": args.text, "partial": args.partial} if command == "say"
                else {"limit": args.limit} if command == "clips"
                else {"id": args.id} if command == "pin"
                else {"values": {args.command: args.value}} if command == "update" else {})
            response = request(root, command, **options)
            printed(response)
            return 0 if response.get("ok") else 1
        return 0
    except Exception as exc:
        print(f"5imic: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

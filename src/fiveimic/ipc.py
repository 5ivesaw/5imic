"""Authenticated local-only CLI bridge for an already running app."""
from __future__ import annotations

import json
import os
import secrets
import socket
import socketserver
import threading
from pathlib import Path


class Controller:
    def __init__(self, engine, root: Path):
        self.engine = engine
        self.root = root
        self.token = secrets.token_hex(24)
        controller = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    raw = self.rfile.readline(16385)
                    if len(raw) > 16384:
                        raise ValueError("Request too large")
                    request = json.loads(raw)
                    if request.get("token") != controller.token:
                        raise PermissionError("Invalid local token")
                    command = request.get("command")
                    if command == "stats":
                        response = {"ok": True, **engine.stats()}
                    elif command == "say":
                        response = engine.say(str(request.get("text", "")), bool(request.get("partial")))
                    elif command == "toggle":
                        response = {"ok": True, "recording": engine.toggle()}
                    elif command == "update":
                        response = {"ok": True, **engine.update(**request.get("values", {}))}
                    elif command == "pin":
                        response = {"ok": engine.arena.pin(int(request.get("id")))}
                    elif command == "clips":
                        response = {"ok": True, "items": engine.clips(int(request.get("limit", 40)))}
                    else:
                        response = {"ok": False, "error": "Unknown command"}
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                self.wfile.write((json.dumps(response) + "\n").encode())

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.path = root / "controller.json"

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        info = {"port": self.server.server_address[1], "token": self.token}
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump(info, file)
        os.replace(temporary, self.path)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        try:
            if json.loads(self.path.read_text())["token"] == self.token:
                self.path.unlink()
        except (FileNotFoundError, ValueError, KeyError):
            pass


def request(root: Path, command: str, **arguments) -> dict:
    path = root / "controller.json"
    if not path.exists():
        raise RuntimeError("5imic isn't running. Start it first with '5imic' or '5imic tui'.")
    info = json.loads(path.read_text())
    payload = {"token": info["token"], "command": command, **arguments}
    with socket.create_connection(("127.0.0.1", info["port"]), timeout=2) as connection:
        connection.settimeout(120)
        connection.sendall((json.dumps(payload) + "\n").encode())
        with connection.makefile("rb") as stream:
            data = stream.readline(65536)
    if not data:
        raise RuntimeError("5imic controller disconnected")
    return json.loads(data)

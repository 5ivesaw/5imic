import numpy as np

from fiveimic.engine import Engine
from fiveimic.ipc import Controller, request
from fiveimic.slicer import Slice


class DummyRouter:
    status = "Preview only"

    def __init__(self):
        self.played = []

    def play(self, audio):
        self.played.append(audio.copy())

    def close(self):
        pass


def test_say_rejects_low_coverage_and_does_not_repeat(tmp_path):
    engine = Engine(tmp_path)
    engine.router = DummyRouter()
    tone = (0.1 * np.sin(np.linspace(0, 100, 4800))).astype(np.float32)
    assert engine.arena.add(Slice("hello", 0, 4800, 0.99, 1, False), tone)
    assert engine.arena.add(Slice("human", 0, 4800, 0.99, 1, False), tone)
    denied = engine.say("hello invisible human")
    assert not denied["ok"]
    assert denied["missing"] == ["invisible"]
    partial = engine.say("hello invisible human", partial=True)
    assert partial["ok"]
    assert partial["spoken"] == "hello human"
    assert len(partial["clip_ids"]) == 2
    assert len(engine.router.played) == 1
    engine.close()


def test_local_ipc_stats_and_settings(tmp_path):
    engine = Engine(tmp_path)
    controller = Controller(engine, tmp_path)
    controller.start()
    try:
        assert request(tmp_path, "stats")["ok"]
        assert request(tmp_path, "update", values={"mode": "chaos"})["mode"] == "chaos"
        assert not request(tmp_path, "say", text="nothing")["ok"]
    finally:
        controller.close()
        engine.close()

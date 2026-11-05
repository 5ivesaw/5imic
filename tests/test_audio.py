from types import SimpleNamespace


from fiveimic.audio import choose_capture


class FakeSound:
    def __init__(self, speaker_name):
        self.speaker = SimpleNamespace(name=speaker_name, id="1")
        self.loopback = SimpleNamespace(name=speaker_name, id="1", isloopback=True)

    def all_speakers(self):
        return [self.speaker]

    def default_speaker(self):
        return self.speaker

    def all_microphones(self, include_loopback):
        return [self.loopback]


def test_matching_loopback():
    assert choose_capture(FakeSound("Headphones"), "default")[1].name == "Headphones"


def test_refuses_virtual_feedback():
    try:
        choose_capture(FakeSound("fiveimic_output"), "default")
    except RuntimeError as exc:
        assert "feedback" in str(exc)
    else:
        raise AssertionError("Should reject routing virtual output into capture")


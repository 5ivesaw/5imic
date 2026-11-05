import numpy as np

from fiveimic.stitch import plan, stitch
from fiveimic.storage import Clip


def clip(ident, name, quality=0.9, pitch=140):
    return Clip(ident, name, 0, 100, 0.97, quality, pitch, 800, 0.1,
                "session", False, False, 1)


def test_cover_exact_without_duplicate_overlapping_subphrases():
    clips = [clip(1, "a little"), clip(2, "bit about myself"), clip(3, "about myself"),
             clip(4, "a"), clip(5, "little bit")]
    selected, missing = plan("a little bit about myself", clips)
    assert missing == []
    assert " ".join(item.text for item in selected) == "a little bit about myself"
    assert len(selected) <= 3


def test_missing_words_reported_not_fabricated():
    clips = [clip(1, "hello"), clip(2, "human"), clip(3, "the real")]
    result = stitch("hello i'm a human", clips,
                    lambda _: np.full(1200, 0.2, dtype=np.float32))
    assert result.spoken == "hello human"
    assert result.missing == ["i'm", "a"]
    assert result.coverage == 0.5


def test_voice_modes_prefer_natural_pitch():
    clips = [clip(1, "hi", pitch=110), clip(2, "hi", pitch=230)]
    assert plan("hi", clips, mode="high")[0][0].id == 2
    assert plan("hi", clips, mode="low")[0][0].id == 1


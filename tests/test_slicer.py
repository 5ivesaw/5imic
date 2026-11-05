import numpy as np

from fiveimic.slicer import Word, boundary, cut_phrases, tokens


def test_punctuation_tokens():
    assert tokens("HEY, it's me! 5IMIC") == ["hey", "it's", "me", "5imic"]


def test_clean_gap_yields_exact_words_and_phrase():
    audio = np.zeros(16000, dtype=np.float32)
    audio[1000:3400] = 0.1
    audio[5000:7900] = 0.1
    words = [Word("hello", 0.06, 0.21, 0.99), Word("world", 0.31, 0.49, 0.99)]
    result = cut_phrases(audio, words)
    assert {"hello", "world", "hello world"} <= {s.text for s in result}


def test_uncertain_seam_keeps_combination_and_filters_low_confidence():
    audio = np.ones(16000, dtype=np.float32) * 0.12
    words = [Word("my", 0.1, 0.3, 0.99), Word("name", 0.3, 0.55, 0.98)]
    result = cut_phrases(audio, words)
    assert [s.text for s in result] == ["my name"]
    assert result[0].locked
    words[1] = Word("name", 0.3, 0.55, 0.1)
    assert cut_phrases(audio, words) == []


def test_gap_is_clean():
    audio = np.zeros(16000, dtype=np.float32)
    assert boundary(audio, Word("one", 0, 0.2, 1),
                    Word("two", 0.25, 0.4, 1))[0]


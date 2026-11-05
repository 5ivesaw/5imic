import numpy as np

from fiveimic.dsp import (CAPTURE_RATE, STORE_RATE, assemble, decode_ulaw,
                          encode_ulaw, resample, rms)


def test_ulaw_roundtrip_size_and_noise():
    source = (0.4 * np.sin(np.linspace(0, 30, 12000))).astype(np.float32)
    encoded = encode_ulaw(source)
    decoded = decode_ulaw(encoded)
    assert len(encoded) == len(source)
    assert len(decoded) == len(source)
    assert np.max(np.abs(source - decoded)) < 0.025


def test_resample_duration():
    source = np.ones(CAPTURE_RATE, dtype=np.float32) * 0.2
    output = resample(source, CAPTURE_RATE, STORE_RATE)
    assert len(output) == STORE_RATE
    assert abs(rms(output) - 0.2) < 0.001


def test_crossfade_no_click_and_optional_effect():
    a = np.ones(1500, dtype=np.float32) * 0.2
    b = np.ones(1800, dtype=np.float32) * -0.2
    result = assemble([a, b], effect="clean")
    assert 3000 < len(result) < 3300
    assert np.max(np.abs(np.diff(result))) < 0.1
    assert len(assemble([a, b], effect="glitch", seed=1)) > 0


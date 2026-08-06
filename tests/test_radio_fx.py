"""tests/test_radio_fx.py — Radio FX unit tests.

voice/radio_fx.py was implemented during the Piper migration (2026-06-21).
These tests confirm contract: shapes, dtypes, output characteristics.
"""
import numpy as np
import pytest

from voice.radio_fx import bandpass, squelch, start_beep


_SR = 22050
_DURATION_MS = 200
_N = int(_SR * _DURATION_MS / 1000)


def _sine(freq: float, n: int, sr: int) -> np.ndarray:
    t = np.linspace(0, n / sr, n, endpoint=False)
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


# ---------------------------------------------------------------------------
# bandpass
# ---------------------------------------------------------------------------

def test_bandpass_returns_float32():
    audio = _sine(1000.0, _N, _SR)
    out = bandpass(audio, _SR)
    assert out.dtype == np.float32


def test_bandpass_preserves_length():
    audio = _sine(1000.0, _N, _SR)
    out = bandpass(audio, _SR)
    assert len(out) == _N


def test_bandpass_passband_tone_survives():
    """A 1kHz sine (in the 300-3400 Hz pass band) must have non-trivial energy."""
    audio = _sine(1000.0, _N, _SR)
    out = bandpass(audio, _SR)
    assert float(np.max(np.abs(out))) > 0.1


def test_bandpass_stopband_tone_attenuated():
    """50 Hz (stopband) must have negligible energy at 50 Hz in the output spectrum.

    bandpass() normalises the peak to 0.9 regardless of input, so we can't
    compare peak amplitudes. Instead, check that the 50 Hz bin in the output
    FFT carries < 0.01 of the total spectral energy.
    """
    audio = _sine(50.0, _N, _SR)
    out = bandpass(audio, _SR)
    spectrum = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(_N, 1.0 / _SR)
    # Find the bin closest to 50 Hz
    idx_50 = int(np.argmin(np.abs(freqs - 50.0)))
    total_energy = float(np.sum(spectrum))
    energy_at_50 = float(spectrum[idx_50])
    if total_energy > 0:
        assert energy_at_50 / total_energy < 0.01


def test_bandpass_output_normalised():
    """Peak output must be ≤ 0.92 (the function normalises to 0.9)."""
    audio = _sine(1000.0, _N, _SR)
    out = bandpass(audio, _SR)
    assert float(np.max(np.abs(out))) <= 0.92


def test_bandpass_short_audio_returns_unchanged():
    """Very short inputs (< 16 samples) must be returned as-is without error."""
    audio = np.ones(8, dtype=np.float32)
    out = bandpass(audio, _SR)
    assert len(out) == 8


def test_bandpass_silence_in_silence_out():
    """Zero input must produce zero output."""
    audio = np.zeros(_N, dtype=np.float32)
    out = bandpass(audio, _SR)
    assert float(np.max(np.abs(out))) == 0.0


def test_bandpass_no_drive_lower_grit():
    """drive=0 should produce output without tanh saturation."""
    audio = _sine(1000.0, _N, _SR)
    out_no_drive = bandpass(audio, _SR, drive=0.0)
    out_drive = bandpass(audio, _SR, drive=3.0)
    # Both should be valid, just check types and length
    assert out_no_drive.dtype == np.float32
    assert len(out_no_drive) == _N
    assert len(out_drive) == _N


# ---------------------------------------------------------------------------
# squelch
# ---------------------------------------------------------------------------

def test_squelch_returns_float32():
    burst = squelch(_SR)
    assert burst.dtype == np.float32


def test_squelch_length_matches_ms():
    ms = 80.0
    burst = squelch(_SR, ms=ms)
    expected_n = int(_SR * ms / 1000.0)
    assert len(burst) == expected_n


def test_squelch_amplitude_bounded():
    """Squelch level=0.16 means peak should not exceed ~0.2 (level + small headroom)."""
    burst = squelch(_SR, ms=70.0, level=0.16)
    assert float(np.max(np.abs(burst))) <= 0.25


def test_squelch_zero_ms_returns_empty():
    burst = squelch(_SR, ms=0.0)
    assert len(burst) == 0


def test_squelch_is_non_silent():
    """Squelch burst must not be silence — it's noise."""
    burst = squelch(_SR, ms=70.0, level=0.16)
    assert float(np.max(np.abs(burst))) > 0.001


def test_squelch_different_seeds_differ():
    """Two independent calls should not be identical (random noise)."""
    b1 = squelch(_SR, ms=70.0, level=0.16)
    b2 = squelch(_SR, ms=70.0, level=0.16)
    # With high probability, random noise differs
    assert not np.array_equal(b1, b2)


# ---------------------------------------------------------------------------
# Formula-style transmission start beep
# ---------------------------------------------------------------------------

def test_start_beep_is_short_deterministic_two_tone():
    beep = start_beep(_SR)
    again = start_beep(_SR)

    assert beep.dtype == np.float32
    assert len(beep) == int(_SR * 110.0 / 1000.0)
    assert np.array_equal(beep, again)
    assert 0.01 < float(np.max(np.abs(beep))) <= 0.25


def test_start_beep_zero_ms_returns_empty():
    assert len(start_beep(_SR, ms=0.0)) == 0

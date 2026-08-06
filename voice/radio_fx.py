"""
voice/radio_fx.py
=================
Pit-radio / walkie-talkie audio effect for TTS output.

- Band-pass ~300-3400 Hz (telephone/radio band) via a smooth FFT mask.
- Light tanh "drive" for radio grit.
- Optional squelch noise bursts at the start / end of a transmission.
- A deterministic two-tone start beep before team-radio speech.

numpy-only — no scipy dependency. All functions operate on mono float32 [-1, 1].
"""
from __future__ import annotations

import numpy as np

_LO = 300.0   # Hz — low cutoff
_HI = 3400.0  # Hz — high cutoff


def _tone_burst(sr: int, frequency: float, ms: float,
                level: float) -> np.ndarray:
    """Windowed sine burst used by :func:`start_beep`."""
    n = int(sr * ms / 1000.0)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n, dtype=np.float32) / float(sr)
    tone = np.sin(2.0 * np.pi * frequency * t).astype(np.float32)
    # Short fades remove digital clicks while keeping the pip crisp.
    fade_n = min(max(1, int(sr * 0.004)), n // 2)
    envelope = np.ones(n, dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, fade_n, endpoint=True, dtype=np.float32)
    envelope[:fade_n] = ramp
    envelope[-fade_n:] = ramp[::-1]
    return (tone * envelope * level).astype(np.float32)


def start_beep(sr: int, ms: float = 110.0,
               level: float = 0.18) -> np.ndarray:
    """Formula-style rising two-tone cue that opens a radio transmission.

    Generated procedurally rather than loaded from a broadcast recording, so
    it stays sample-rate independent and can be mixed into both cached and
    streaming playback without becoming part of the TTS cache.
    """
    n = int(sr * ms / 1000.0)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)

    gap_n = min(int(sr * 8.0 / 1000.0), n)
    audible_n = max(0, n - gap_n)
    first_n = audible_n * 43 // 100
    second_n = audible_n - first_n

    first = _tone_burst(sr, 1350.0, first_n * 1000.0 / sr, level)
    gap = np.zeros(gap_n, dtype=np.float32)
    second = _tone_burst(sr, 1950.0, second_n * 1000.0 / sr, level)
    out = np.concatenate((first, gap, second)).astype(np.float32)
    if len(out) < n:
        out = np.pad(out, (0, n - len(out))).astype(np.float32)
    return out[:n]


def _smooth_mask(freqs: np.ndarray, lo: float, hi: float, edge: float = 120.0) -> np.ndarray:
    """Raised-cosine band mask to avoid hard brickwall ringing."""
    m = np.ones_like(freqs)
    lo_lo, lo_hi = lo - edge, lo + edge
    hi_lo, hi_hi = hi - edge, hi + edge
    m[freqs < lo_lo] = 0.0
    m[freqs > hi_hi] = 0.0
    ramp_lo = (freqs >= lo_lo) & (freqs <= lo_hi)
    m[ramp_lo] = 0.5 * (1 - np.cos(np.pi * (freqs[ramp_lo] - lo_lo) / (lo_hi - lo_lo)))
    ramp_hi = (freqs >= hi_lo) & (freqs <= hi_hi)
    m[ramp_hi] = 0.5 * (1 + np.cos(np.pi * (freqs[ramp_hi] - hi_lo) / (hi_hi - hi_lo)))
    return m


def bandpass(audio: np.ndarray, sr: int, drive: float = 1.6) -> np.ndarray:
    """Apply the radio band-pass + grit. Returns mono float32."""
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(x) < 16:
        return x
    n = len(x)
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    spectrum *= _smooth_mask(freqs, _LO, _HI)
    y = np.fft.irfft(spectrum, n).astype(np.float32)
    if drive and drive > 0:
        y = np.tanh(y * drive).astype(np.float32)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0:
        y = (y / peak) * 0.9
    return y.astype(np.float32)


def squelch(sr: int, ms: float = 70.0, level: float = 0.16) -> np.ndarray:
    """Short band-passed noise burst (radio key-up/key-down click)."""
    n = int(sr * ms / 1000.0)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    noise = np.random.uniform(-1.0, 1.0, n).astype(np.float32)
    noise = bandpass(noise, sr, drive=0.0)
    env = np.hanning(n).astype(np.float32)
    return (noise * env * level).astype(np.float32)

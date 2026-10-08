"""Reference-clip preparation (engine independent): the first stage of the profile pipeline."""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf


def read_audio(data: bytes) -> tuple[np.ndarray, int]:
    """Decode WAV (or FLAC/OGG/MP3, whatever libsndfile reads) to float32 mono."""
    try:
        samples, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as e:
        raise ValueError(f"não consegui ler o áudio ({e}); envie um .wav") from None
    if samples.size == 0:
        raise ValueError("o arquivo de áudio está vazio")
    return samples.mean(axis=1), sr


def prepare(data: bytes, target_sr: int, trim: bool = True, normalize: bool = True,
            max_seconds: float = 20.0) -> tuple[np.ndarray, list[dict]]:
    """Returns (samples at target_sr, steps) where steps describe what was done."""
    samples, sr = read_audio(data)
    steps = [{"step": "decode", "detail": f"{len(samples) / sr:.1f}s, {sr} Hz"}]
    if sr != target_sr:
        import librosa

        samples = librosa.resample(samples, orig_sr=sr, target_sr=target_sr)
        steps.append({"step": "resample", "detail": f"{sr} → {target_sr} Hz"})
    if trim:
        import librosa

        before = len(samples)
        samples, _ = librosa.effects.trim(samples, top_db=35)
        steps.append({"step": "trim", "detail": f"-{(before - len(samples)) / target_sr:.1f}s de silêncio"})
    if max_seconds and len(samples) > max_seconds * target_sr:
        samples = samples[: int(max_seconds * target_sr)]
        steps.append({"step": "cut", "detail": f"cortado em {max_seconds:g}s"})
    if normalize:
        peak = float(np.max(np.abs(samples))) or 1.0
        samples = samples * (0.89 / peak)  # -1 dBFS peak
        steps.append({"step": "normalize", "detail": "pico em -1 dBFS"})
    if len(samples) < 0.5 * target_sr:
        raise ValueError("áudio curto demais depois do corte de silêncio (mínimo 0,5s)")
    return samples.astype(np.float32), steps


def to_wav(samples: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.clip(samples, -1.0, 1.0), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()

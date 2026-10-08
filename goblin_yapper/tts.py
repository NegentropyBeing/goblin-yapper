"""TTS engines. Every engine turns (text, voice) into WAV bytes.

`voice` is the per-team dict from config ([tts.voices.<team>] merged over
[tts.voices.default]), e.g. {"ref_audio": "voices/azul.wav", "ref_text": "..."}.

Engines:
  dummy     - goblin babble tones, no dependencies (for testing the pipeline/overlay)
  sapi      - Windows built-in voices via PowerShell System.Speech (no GPU)
  omnivoice - k2-fsa OmniVoice on the GPU (pip install omnivoice + torch with CUDA)
  custom    - your own function "module:func"(text, voice) -> wav bytes | (samples, sample_rate)
"""

from __future__ import annotations

import asyncio
import importlib
import io
import logging
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

log = logging.getLogger(__name__)


def wav_duration(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / float(w.getframerate())


def samples_to_wav(samples, sample_rate: int) -> bytes:
    """float samples in [-1, 1] (list, numpy array or torch tensor) -> 16-bit mono WAV."""
    if hasattr(samples, "detach"):  # torch tensor
        samples = samples.detach().float().cpu().numpy()
    try:
        import numpy as np

        arr = np.asarray(samples, dtype=np.float32).reshape(-1)
        pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    except ImportError:
        pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Engine:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def load(self) -> None:
        """Heavy initialisation (model to GPU). Called once, in a worker thread."""

    def synthesize(self, text: str, voice: dict) -> bytes:
        raise NotImplementedError


class DummyEngine(Engine):
    name = "dummy"

    def synthesize(self, text: str, voice: dict) -> bytes:
        sr = 22050
        rng = random.Random(text)
        base = float(voice.get("pitch", 180))
        out: list[float] = []
        for _ in range(max(2, min(len(text) // 3, 60))):  # one "syllable" per ~3 chars
            f = base * rng.uniform(0.8, 1.6)
            n = int(sr * rng.uniform(0.07, 0.14))
            for i in range(n):
                env = math.sin(math.pi * i / n)
                out.append(0.3 * env * math.sin(2 * math.pi * f * i / sr) * (1 + 0.3 * math.sin(2 * math.pi * 30 * i / sr)))
            out.extend([0.0] * int(sr * 0.03))
        return samples_to_wav(out, sr)


_SAPI_PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:GY_VOICE) { $s.SelectVoice($env:GY_VOICE) }
$s.Rate = [int]$env:GY_RATE
$s.SetOutputToWaveFile($env:GY_OUT)
$s.Speak([Console]::In.ReadToEnd())
$s.Dispose()
"""


class SapiEngine(Engine):
    name = "sapi"

    def synthesize(self, text: str, voice: dict) -> bytes:
        fd, out = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            env = dict(os.environ, GY_OUT=out, GY_RATE=str(voice.get("rate", self.cfg.get("rate", 0))),
                       GY_VOICE=voice.get("sapi_voice", self.cfg.get("voice", "")))
            subprocess.run(["powershell", "-NoProfile", "-Command", _SAPI_PS], input=text.encode("utf-8"),
                           env=env, check=True, capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return Path(out).read_bytes()
        finally:
            os.unlink(out)


class OmniVoiceEngine(Engine):
    """k2-fsa OmniVoice. Voice cloning: set ref_audio (+ ref_text) per team in config.

    NOTE: written against the OmniVoice README API
    (OmniVoice.from_pretrained(...).generate(text=, ref_audio=, ref_text=)); if your
    installed version differs, adjust here or point the `custom` engine at your script.
    """

    name = "omnivoice"

    def load(self) -> None:
        import torch
        from omnivoice import OmniVoice

        dtype = getattr(torch, self.cfg.get("dtype", "float16"))
        log.info("carregando OmniVoice (%s) em %s...", self.cfg.get("model"), self.cfg.get("device"))
        self.model = OmniVoice.from_pretrained(self.cfg.get("model", "k2-fsa/OmniVoice"),
                                               device_map=self.cfg.get("device", "cuda:0"), dtype=dtype)
        self.sample_rate = int(self.cfg.get("sample_rate", 24000))

    def synthesize(self, text: str, voice: dict) -> bytes:
        kwargs = {k: voice[k] for k in ("ref_audio", "ref_text", "instruct") if voice.get(k)}
        audio = self.model.generate(text=text, **kwargs)
        if isinstance(audio, (list, tuple)):
            audio = audio[0]
        return samples_to_wav(audio, self.sample_rate)


class CustomEngine(Engine):
    """Calls your own function. Config: [tts.custom] callable = "my_tts:synthesize",
    optional load = "my_tts:load" (called once at startup), path = "scripts" (added to sys.path)."""

    name = "custom"

    def _resolve(self, spec: str):
        mod, _, fn = spec.partition(":")
        return getattr(importlib.import_module(mod), fn)

    def load(self) -> None:
        if self.cfg.get("path"):
            sys.path.insert(0, str(Path(self.cfg["path"]).resolve()))
        self.fn = self._resolve(self.cfg["callable"])
        if self.cfg.get("load"):
            self._resolve(self.cfg["load"])()

    def synthesize(self, text: str, voice: dict) -> bytes:
        result = self.fn(text, voice)
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        samples, sr = result
        return samples_to_wav(samples, int(sr))


ENGINES = {e.name: e for e in (DummyEngine, SapiEngine, OmniVoiceEngine, CustomEngine)}


class TTS:
    """Async wrapper: loads the engine once and serialises synthesis in a worker thread."""

    def __init__(self, tts_cfg: dict):
        engine_name = tts_cfg.get("engine", "dummy")
        if engine_name not in ENGINES:
            raise ValueError(f"engine TTS desconhecida: {engine_name} (opções: {', '.join(ENGINES)})")
        self.engine = ENGINES[engine_name](tts_cfg.get(engine_name, {}))
        self.voices: dict = tts_cfg.get("voices", {})
        self.error: str | None = None
        self._fallback_cfg = tts_cfg.get("sapi" if sys.platform == "win32" else "dummy", {})
        self._lock = asyncio.Lock()

    def voice_for(self, team: str | None) -> dict:
        return {**self.voices.get("default", {}), **self.voices.get(team or "", {})}

    async def load(self) -> None:
        try:
            await asyncio.to_thread(self.engine.load)
        except Exception as e:
            # e.g. omnivoice/torch missing in the packaged app: keep running with a basic voice.
            log.exception("falha ao carregar TTS %s; usando voz reserva", self.engine.name)
            self.error = f"{self.engine.name}: {e}"
            self.engine = (SapiEngine if sys.platform == "win32" else DummyEngine)(self._fallback_cfg)
        log.info("TTS pronto (engine=%s)", self.engine.name)

    async def synthesize(self, text: str, team: str | None) -> bytes:
        async with self._lock:
            return await asyncio.to_thread(self.engine.synthesize, text, self.voice_for(team))

"""TTS engines. Every engine turns (text, voice) into WAV bytes.

`voice` is the per-team dict from config ([tts.voices.<team>] merged over
[tts.voices.default]), e.g. {"ref_audio": "voices/azul.wav", "ref_text": "..."}.

Engines:
  dummy     - goblin babble tones, no dependencies (for testing the pipeline/overlay)
  sapi      - Windows built-in voices via PowerShell System.Speech (no GPU)
  server    - the TTS server (tts_server/, OmniVoice on the GPU, voice profiles)
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


class ServerEngine(Engine):
    """The TTS server (tts_server/, OmniVoice on the GPU). `voice["profile"]` picks the voice profile;
    parameters come from the server's own settings and the profile."""

    name = "server"

    def synthesize(self, text: str, voice: dict) -> bytes:
        import json
        import urllib.error
        import urllib.request

        url = self.cfg.get("url", "http://127.0.0.1:8766").rstrip("/") + "/synthesize"
        body = json.dumps({"text": text, "profile": voice.get("profile")}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode("utf-8", "replace") or f"HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"servidor TTS fora do ar ({e.reason})") from None


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


ENGINES = {e.name: e for e in (DummyEngine, SapiEngine, ServerEngine, CustomEngine)}


class TTS:
    """Async wrapper: loads the engine once and serialises synthesis in a worker thread."""

    def __init__(self, tts_cfg: dict):
        self.cfg = tts_cfg
        self.engine = self._make(tts_cfg.get("engine", "dummy"))
        self.voices: dict = tts_cfg.get("voices", {})
        # team (or "default") -> voice profile id on the TTS server; editable from the panel
        self.team_profiles: dict[str, str] = dict(tts_cfg.get("team_profiles", {}))
        self.error: str | None = None
        self._fallback_cfg = tts_cfg.get("sapi" if sys.platform == "win32" else "dummy", {})
        self._lock = asyncio.Lock()

    def _make(self, name: str) -> Engine:
        if name not in ENGINES:
            raise ValueError(f"engine TTS desconhecida: {name} (opções: {', '.join(ENGINES)})")
        return ENGINES[name](self.cfg.get(name, {}))

    async def set_engine(self, name: str) -> None:
        """Switch engines at runtime (loads the new one first, keeps the old one on failure)."""
        engine = self._make(name)
        async with self._lock:
            await asyncio.to_thread(engine.load)
            self.engine, self.error = engine, None
        log.info("TTS trocado para %s", name)

    def voice_for(self, team: str | None) -> dict:
        voice = {**self.voices.get("default", {}), **self.voices.get(team or "", {})}
        profile = self.team_profiles.get(team or "") or self.team_profiles.get("default")
        if profile:
            voice["profile"] = profile
        return voice

    async def load(self) -> None:
        try:
            await asyncio.to_thread(self.engine.load)
        except Exception as e:
            # e.g. a custom engine whose dependencies are missing: keep running with a basic voice.
            log.exception("falha ao carregar TTS %s; usando voz reserva", self.engine.name)
            self.error = f"{self.engine.name}: {e}"
            self.engine = (SapiEngine if sys.platform == "win32" else DummyEngine)(self._fallback_cfg)
        log.info("TTS pronto (engine=%s)", self.engine.name)

    async def synthesize(self, text: str, team: str | None) -> bytes:
        async with self._lock:
            return await asyncio.to_thread(self.engine.synthesize, text, self.voice_for(team))

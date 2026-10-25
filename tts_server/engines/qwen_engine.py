"""Qwen3-TTS (Alibaba Qwen) engine, Base models: voice cloning from a reference clip + its transcript.
Parameters mirror qwen-tts 0.1.1: Qwen3TTSModel.generate_voice_clone(...) and its sampling arguments.

Runs in its own environment (tts_server/.venv-qwen, made by setup-qwen.ps1): qwen-tts pins an older
transformers than OmniVoice. Qwen has no built-in transcription, so Whisper comes from transformers.
"""

from __future__ import annotations

import gc
import logging
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .base import Engine, Param

log = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
WHISPER_MODEL = "openai/whisper-large-v3-turbo"
# The languages of the Base models, until the loaded model lists its own; Portuguese first
LANGUAGES = ("portuguese", "english", "spanish", "chinese", "french", "german", "italian", "japanese", "korean", "russian")
SAMPLING_KEYS = ("do_sample", "temperature", "top_k", "top_p", "repetition_penalty", "max_new_tokens",
                 "subtalker_dosample", "subtalker_temperature", "subtalker_top_k", "subtalker_top_p")


def cache_name(model: str) -> str:
    """Cached voices hold the model's own speaker embedding, so each model size gets its own file:
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base" -> "qwen3tts-1.7b.pt"."""
    size = re.search(r"(\d+(?:\.\d+)?)b", model.lower())
    return f"qwen3tts-{size.group(1)}b.pt" if size else "qwen3tts.pt"


class QwenEngine(Engine):
    name = "qwen"
    label = "Qwen3-TTS"
    sample_rate = 24000

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.model_id = cfg.get("model") or DEFAULT_MODEL
        self.profile_cache = cache_name(self.model_id)
        size = re.search(r"(\d+(?:\.\d+)?)B", self.model_id)
        self.label = f"Qwen3-TTS {size.group(1)}B" if size else "Qwen3-TTS"
        self._asr = None

    def load(self) -> None:
        import torch
        from qwen_tts import Qwen3TTSModel

        self.torch = torch
        device, dtype = self.cfg.get("device", "cuda:0"), self.cfg.get("dtype", "bfloat16")
        if device.startswith("cuda") and not torch.cuda.is_available():
            log.warning("no CUDA GPU; using the CPU (much slower)")
            device, dtype = "cpu", "float32"
        self.device, self.dtype = device, getattr(torch, dtype)
        self.model = Qwen3TTSModel.from_pretrained(self.model_id, device_map=device, dtype=self.dtype,
                                                   attn_implementation=self.cfg.get("attn", "sdpa"))
        if self.model.model.tts_model_type != "base":
            raise ValueError(f"{self.model_id} is not a Base model: only Base models clone voices")
        self._prompts: dict[tuple[str, float], object] = {}
        listed = [str(lang).lower() for lang in self.model.model.get_supported_languages() or [] if str(lang).lower() != "auto"]
        if listed:
            self._languages = sorted(listed, key=lambda lang: (lang != "portuguese", lang))

    def info(self) -> dict:
        out = {"device": str(self.device), "model": self.model_id, "asr_loaded": self._asr is not None}
        if self.torch.cuda.is_available():
            free, total = self.torch.cuda.mem_get_info()
            # vram_used_gb is the whole card (games, browser, OBS...); vram_model_gb is this process alone
            out.update(gpu=self.torch.cuda.get_device_name(0), vram_used_gb=round((total - free) / 2**30, 2),
                       vram_total_gb=round(total / 2**30, 2),
                       vram_model_gb=round(self.torch.cuda.memory_reserved() / 2**30, 2))
        return out

    def params(self) -> list[Param]:
        langs = [{"value": "auto", "label": "detect automatically"}]
        langs += [{"value": lang, "label": lang.title()} for lang in getattr(self, "_languages", LANGUAGES)]
        return [
            Param("language", "Language", "select", "portuguese", options=langs,
                  help="Language of the spoken text."),
            Param("temperature", "Temperature", "float", 0.9, min=0.05, max=2.0, step=0.05,
                  help="Higher = more varied and expressive, lower = steadier. Too high can garble words."),
            Param("seed", "Seed", "text", "",
                  help="A whole number makes the same text come out the same way (for A/B listening). Empty = random."),
            Param("do_sample", "Sampling", "bool", True, group="advanced",
                  help="Off = always the most likely sound (greedy): steady but flat, and it may loop."),
            Param("top_k", "Top-k", "int", 50, group="advanced", min=0, max=200, step=1,
                  help="Picks only among the k most likely tokens. 0 = no limit."),
            Param("top_p", "Top-p", "float", 1.0, group="advanced", min=0.05, max=1.0, step=0.01,
                  help="Picks only among the most likely tokens that add up to this probability. 1 = no limit."),
            Param("repetition_penalty", "Repetition penalty", "float", 1.05, group="advanced", min=1.0, max=2.0, step=0.01,
                  help="Discourages repeating the same sounds; too high makes speech unnatural."),
            Param("max_new_tokens", "Max length (tokens)", "int", 2048, group="advanced", min=64, max=8192, step=64,
                  help="Cap on generated audio: 12 tokens per second, so 2048 is ~170 s. Stops runaway generations."),
            Param("subtalker_dosample", "Sub-talker: sampling", "bool", True, group="advanced",
                  help="The sub-talker fills in the fine acoustic detail of each frame."),
            Param("subtalker_temperature", "Sub-talker: temperature", "float", 0.9, group="advanced", min=0.05, max=2.0, step=0.05),
            Param("subtalker_top_k", "Sub-talker: top-k", "int", 50, group="advanced", min=0, max=200, step=1),
            Param("subtalker_top_p", "Sub-talker: top-p", "float", 1.0, group="advanced", min=0.05, max=1.0, step=0.01),
        ]

    # ---- transcription (Whisper, through transformers) ----------------

    def transcribe(self, wav: Path) -> str:
        import soundfile as sf

        if self._asr is None:
            from transformers import pipeline

            log.info("loading Whisper for transcription...")
            self._asr = pipeline("automatic-speech-recognition", model=WHISPER_MODEL, device=self.device,
                                 torch_dtype=self.dtype)
        # Samples, not the path: given a path, the pipeline decodes it with ffmpeg, which a clean
        # Windows install does not have.
        samples, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        try:
            return self._asr({"raw": samples.mean(axis=1), "sampling_rate": sr})["text"].strip()
        finally:
            self._trim()

    def release_asr(self) -> None:
        if self._asr is not None:
            self._asr = None
            gc.collect()
            self._trim()
            log.info("Whisper unloaded (VRAM freed)")

    def _trim(self) -> None:
        """Give PyTorch's cached blocks back to the GPU, so the work memory of a job isn't held for good."""
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()

    # ---- profiles ------------------------------------------------------

    def build_profile(self, wav: Path, ref_text: str, cache: Path) -> None:
        import soundfile as sf

        samples, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        try:
            # full clone (in-context): the reference audio and its transcript, not only a speaker embedding
            item = self.model.create_voice_clone_prompt(ref_audio=(samples.mean(axis=1), sr), ref_text=ref_text,
                                                        x_vector_only_mode=False)[0]
        finally:
            self._trim()
        data = {k: v.cpu() if hasattr(v, "cpu") else v for k, v in asdict(item).items()}
        self.torch.save(data, str(cache))

    def _prompt(self, cache: Path):
        from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem

        key = (str(cache), cache.stat().st_mtime)
        if key not in self._prompts:
            data = self.torch.load(str(cache), map_location=self.model.device)
            self._prompts = {k: v for k, v in self._prompts.items() if k[0] != key[0]}
            self._prompts[key] = VoiceClonePromptItem(**data)
        return self._prompts[key]

    # ---- synthesis -----------------------------------------------------

    def synthesize(self, text: str, cache: Path | None, params: dict) -> np.ndarray:
        if cache is None:
            raise ValueError("Qwen3-TTS clones a voice: pick a voice profile")
        kwargs = {k: params[k] for k in SAMPLING_KEYS if params.get(k) is not None}
        seed = str(params.get("seed") or "").strip()
        if seed.isdigit():
            self.torch.manual_seed(int(seed))  # seeds the CUDA generators too
        try:
            wavs, sr = self.model.generate_voice_clone(text=text, language=params.get("language") or "auto",
                                                       voice_clone_prompt=[self._prompt(cache)], **kwargs)
        finally:
            self._trim()
        audio = np.asarray(wavs[0], dtype=np.float32)
        if sr != self.sample_rate:
            import librosa

            audio = librosa.resample(audio, orig_sr=sr, target_sr=self.sample_rate)
        return audio

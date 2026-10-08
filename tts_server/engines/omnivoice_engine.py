"""OmniVoice (k2-fsa) engine. Parameters mirror omnivoice 0.2.1:
OmniVoice.generate(...) arguments + OmniVoiceGenerationConfig fields."""

from __future__ import annotations

import gc
import logging
from pathlib import Path

import numpy as np

from .base import Engine, Param

log = logging.getLogger(__name__)

GEN_CONFIG_KEYS = ("num_step", "guidance_scale", "t_shift", "layer_penalty_factor", "position_temperature",
                   "class_temperature", "denoise", "postprocess_output", "audio_chunk_duration",
                   "audio_chunk_threshold", "pad_duration", "fade_duration")
PINNED_LANGS = ("pt", "en", "es")


class OmniVoiceEngine(Engine):
    name = "omnivoice"
    label = "OmniVoice"
    sample_rate = 24000
    profile_cache = "omnivoice.pt"

    def load(self) -> None:
        import torch
        from omnivoice import OmniVoice

        self.torch = torch
        device, dtype = self.cfg.get("device", "cuda:0"), self.cfg.get("dtype", "float16")
        if device.startswith("cuda") and not torch.cuda.is_available():
            log.warning("sem GPU CUDA; usando a CPU (bem mais lento)")
            device, dtype = "cpu", "float32"  # float16 is GPU-only in practice
        self.model = OmniVoice.from_pretrained(self.cfg.get("model", "k2-fsa/OmniVoice"),
                                               device_map=device, dtype=getattr(torch, dtype))
        self._prompts: dict[tuple[str, float], object] = {}
        self._languages = self._language_options()

    def info(self) -> dict:
        out = {"device": str(self.model.device), "asr_loaded": getattr(self.model, "_asr_pipe", None) is not None}
        if self.torch.cuda.is_available():
            free, total = self.torch.cuda.mem_get_info()
            out.update(gpu=self.torch.cuda.get_device_name(0), vram_used_gb=round((total - free) / 2**30, 2),
                       vram_total_gb=round(total / 2**30, 2))
        return out

    def _language_options(self) -> list[dict]:
        from omnivoice.utils.lang_map import LANG_NAME_TO_ID

        by_id = {i: n for n, i in LANG_NAME_TO_ID.items()}
        rest = sorted((i for i in by_id if i not in PINNED_LANGS), key=lambda i: by_id[i])
        opts = [{"value": "auto", "label": "detectar automaticamente"}]
        opts += [{"value": i, "label": f"{by_id[i].title()} ({i})"} for i in (*PINNED_LANGS, *rest) if i in by_id]
        return opts

    def params(self) -> list[Param]:
        langs = getattr(self, "_languages", [{"value": "pt", "label": "Portuguese (pt)"}])
        return [
            Param("language", "Idioma", "select", "pt", options=langs,
                  help="Idioma do texto falado. Indicar melhora um pouco a qualidade."),
            Param("speed", "Velocidade", "float", 1.0, min=0.5, max=2.0, step=0.05,
                  help="> 1 mais rápido, < 1 mais devagar."),
            Param("num_step", "Passos de decodificação", "int", 32, min=4, max=64, step=1,
                  help="Mais passos = mais qualidade, porém mais lento. 16 é ~2x mais rápido."),
            Param("guidance_scale", "Força do guia (CFG)", "float", 2.0, min=0.0, max=5.0, step=0.1,
                  help="Quanto o modelo segue o texto e a voz de referência."),
            Param("denoise", "Remover ruído", "bool", True, help="Pede ao modelo uma saída limpa, sem o ruído da referência."),
            Param("normalize_text", "Normalizar texto", "bool", False,
                  help="Converte números, datas e moedas para a forma falada."),
            Param("instruct", "Estilo de voz (sem perfil)", "text", "",
                  help="Só quando nenhum perfil é usado. Ex: 'female, low pitch'. Treinado em inglês/chinês."),
            Param("t_shift", "t_shift", "float", 0.1, group="advanced", min=0.0, max=1.0, step=0.01,
                  help="Deslocamento do cronograma de decodificação."),
            Param("layer_penalty_factor", "Penalidade por camada", "float", 5.0, group="advanced", min=0.0, max=20.0, step=0.5),
            Param("position_temperature", "Temperatura de posição", "float", 5.0, group="advanced", min=0.0, max=20.0, step=0.5),
            Param("class_temperature", "Temperatura de classe", "float", 0.0, group="advanced", min=0.0, max=2.0, step=0.05,
                  help="0 = determinístico; maior = mais variação."),
            Param("postprocess_output", "Pós-processar saída", "bool", True, group="advanced"),
            Param("audio_chunk_duration", "Duração do trecho (s)", "float", 15.0, group="advanced", min=5.0, max=30.0, step=0.5,
                  help="Textos longos são gerados em trechos deste tamanho."),
            Param("audio_chunk_threshold", "Limite para dividir (s)", "float", 30.0, group="advanced", min=10.0, max=120.0, step=1.0,
                  help="Áudios previstos acima disto são divididos em trechos."),
            Param("pad_duration", "Silêncio nas pontas (s)", "float", 0.1, group="advanced", min=0.0, max=1.0, step=0.05),
            Param("fade_duration", "Fade (s)", "float", 0.1, group="advanced", min=0.0, max=1.0, step=0.05),
        ]

    # ---- profiles ------------------------------------------------------

    def transcribe(self, wav: Path) -> str:
        if getattr(self.model, "_asr_pipe", None) is None:
            log.info("carregando Whisper para transcrição...")
            self.model.load_asr_model()
        return self.model.transcribe(str(wav)).strip()

    def release_asr(self) -> None:
        if getattr(self.model, "_asr_pipe", None) is not None:
            self.model._asr_pipe = None
            gc.collect()
            self.torch.cuda.empty_cache()
            log.info("Whisper descarregado (VRAM liberada)")

    def build_profile(self, wav: Path, ref_text: str, cache: Path) -> None:
        # preprocess_prompt also ends the transcript with punctuation; re-trimming an already
        # trimmed clip is harmless.
        prompt = self.model.create_voice_clone_prompt(ref_audio=str(wav), ref_text=ref_text, preprocess_prompt=True)
        prompt.save(str(cache))

    def _prompt(self, cache: Path):
        from omnivoice import VoiceClonePrompt

        key = (str(cache), cache.stat().st_mtime)
        if key not in self._prompts:
            self._prompts = {k: v for k, v in self._prompts.items() if k[0] != key[0]}
            self._prompts[key] = VoiceClonePrompt.load(str(cache))
        return self._prompts[key]

    # ---- synthesis -----------------------------------------------------

    def synthesize(self, text: str, cache: Path | None, params: dict) -> np.ndarray:
        kwargs = {k: params[k] for k in GEN_CONFIG_KEYS if k in params}
        language = params.get("language")
        speed = params.get("speed")
        if cache is not None:
            kwargs["voice_clone_prompt"] = self._prompt(cache)
        elif params.get("instruct"):
            kwargs["instruct"] = params["instruct"]
        audio = self.model.generate(
            text=text,
            language=None if language in (None, "", "auto") else language,
            speed=None if speed in (None, 1.0) else speed,
            normalize_text=bool(params.get("normalize_text", False)),
            **kwargs,
        )
        return np.asarray(audio[0], dtype=np.float32)

"""OmniVoice (k2-fsa) engine. Parameters mirror omnivoice 0.2.1:
OmniVoice.generate(...) arguments + OmniVoiceGenerationConfig fields."""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .base import Engine, Param

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

GEN_CONFIG_KEYS = ("num_step", "guidance_scale", "t_shift", "layer_penalty_factor", "position_temperature",
                   "class_temperature", "denoise", "postprocess_output", "audio_chunk_duration",
                   "audio_chunk_threshold", "pad_duration", "fade_duration")
PINNED_LANGS = ("pt", "en", "es")
# omnivoice.utils.voice_design: the voice style terms, one of each kind (the Chinese dialects are left out:
# they only work in Chinese text), and omnivoice.models.omnivoice: the speech tags
STYLE_TERMS = (
    ("gender", ("male", "female")),
    ("age", ("child", "teenager", "young adult", "middle-aged", "elderly")),
    ("pitch", ("very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch")),
    ("style", ("whisper",)),
    ("accent", ("american accent", "australian accent", "british accent", "canadian accent", "chinese accent",
                "indian accent", "japanese accent", "korean accent", "portuguese accent", "russian accent")),
)
SPEECH_TAGS = ("laughter", "sigh", "confirmation-en", "question-en", "question-ah", "question-oh", "question-ei",
               "question-yi", "surprise-ah", "surprise-oh", "surprise-wa", "surprise-yo", "dissatisfaction-hnn")


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
            log.warning("no CUDA GPU; using the CPU (much slower)")
            device, dtype = "cpu", "float32"  # float16 is GPU-only in practice
        self.model = OmniVoice.from_pretrained(self.cfg.get("model", "k2-fsa/OmniVoice"),
                                               device_map=device, dtype=getattr(torch, dtype))
        self._prompts: dict[tuple[str, float], object] = {}
        self._languages = self._language_options()

    def info(self) -> dict:
        out = {"device": str(self.model.device), "asr_loaded": getattr(self.model, "_asr_pipe", None) is not None}
        if self.torch.cuda.is_available():
            free, total = self.torch.cuda.mem_get_info()
            # vram_used_gb is the whole card (games, browser, OBS...); vram_model_gb is this process alone
            out.update(gpu=self.torch.cuda.get_device_name(0), vram_used_gb=round((total - free) / 2**30, 2),
                       vram_total_gb=round(total / 2**30, 2),
                       vram_model_gb=round(self.torch.cuda.memory_reserved() / 2**30, 2))
        return out

    def _language_options(self) -> list[dict]:
        from omnivoice.utils.lang_map import LANG_NAME_TO_ID

        by_id = {i: n for n, i in LANG_NAME_TO_ID.items()}
        rest = sorted((i for i in by_id if i not in PINNED_LANGS), key=lambda i: by_id[i])
        opts = [{"value": "auto", "label": "detect automatically"}]
        opts += [{"value": i, "label": f"{by_id[i].title()} ({i})"} for i in (*PINNED_LANGS, *rest) if i in by_id]
        return opts

    def params(self) -> list[Param]:
        langs = getattr(self, "_languages", [{"value": "pt", "label": "Portuguese (pt)"}])
        return [
            Param("language", "Language", "select", "pt", options=langs,
                  help="Language of the spoken text. Setting it improves quality a little."),
            Param("speed", "Speed", "float", 1.0, min=0.5, max=2.0, step=0.05,
                  help="> 1 faster, < 1 slower."),
            Param("num_step", "Decoding steps", "int", 32, min=4, max=64, step=1,
                  help="More steps = better quality, but slower. 16 is ~2x faster."),
            Param("guidance_scale", "Guidance strength (CFG)", "float", 2.0, min=0.0, max=5.0, step=0.1,
                  help="How much the model follows the text and the reference voice."),
            Param("denoise", "Remove noise", "bool", True, help="Asks the model for clean output, without the reference's noise."),
            Param("normalize_text", "Normalize text", "bool", False,
                  help="Turns numbers, dates and currencies into their spoken form."),
            Param("instruct", "Voice style (no profile)", "text", "",
                  help="Only when no profile is used. E.g. 'female, low pitch'. Trained on English/Chinese."),
            Param("t_shift", "t_shift", "float", 0.1, group="advanced", min=0.0, max=1.0, step=0.01,
                  help="Shift of the decoding schedule."),
            Param("layer_penalty_factor", "Layer penalty", "float", 5.0, group="advanced", min=0.0, max=20.0, step=0.5),
            Param("position_temperature", "Position temperature", "float", 5.0, group="advanced", min=0.0, max=20.0, step=0.5),
            Param("class_temperature", "Class temperature", "float", 0.0, group="advanced", min=0.0, max=2.0, step=0.05,
                  help="0 = deterministic; higher = more variation."),
            Param("postprocess_output", "Post-process output", "bool", True, group="advanced"),
            Param("audio_chunk_duration", "Chunk length (s)", "float", 15.0, group="advanced", min=5.0, max=30.0, step=0.5,
                  help="Long texts are generated in chunks of this size."),
            Param("audio_chunk_threshold", "Split threshold (s)", "float", 30.0, group="advanced", min=10.0, max=120.0, step=1.0,
                  help="Audio predicted above this is split into chunks."),
            Param("pad_duration", "Edge silence (s)", "float", 0.1, group="advanced", min=0.0, max=1.0, step=0.05),
            Param("fade_duration", "Fade (s)", "float", 0.1, group="advanced", min=0.0, max=1.0, step=0.05),
        ]

    def hints(self) -> dict:
        return {"style": [{"kind": kind, "terms": list(terms)} for kind, terms in STYLE_TERMS], "style_param": "instruct",
                "tags": [f"[{tag}]" for tag in SPEECH_TAGS]}

    # ---- profiles ------------------------------------------------------

    def transcribe(self, wav: Path) -> str:
        if getattr(self.model, "_asr_pipe", None) is None:
            log.info("loading Whisper for transcription...")
            self.model.load_asr_model()
        # Samples, not the path: given a path, the Whisper pipeline decodes it with ffmpeg, which a
        # clean Windows install does not have.
        import soundfile as sf

        samples, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        try:
            return self.model.transcribe((samples.mean(axis=1), sr)).strip()
        finally:
            self._trim()

    def release_asr(self) -> None:
        if getattr(self.model, "_asr_pipe", None) is not None:
            self.model._asr_pipe = None
            gc.collect()
            self._trim()
            log.info("Whisper unloaded (VRAM freed)")

    def _trim(self) -> None:
        """Give PyTorch's cached blocks back to the GPU: the work memory of a job would otherwise stay
        reserved by this process (seen: 0.7 to 5 GB) for as long as the server runs. Costs no time."""
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()

    def build_profile(self, wav: Path, ref_text: str, cache: Path) -> None:
        # preprocess_prompt also ends the transcript with punctuation; re-trimming an already
        # trimmed clip is harmless.
        # inference_mode: omnivoice runs this one with autograd on, which keeps every activation of
        # the audio tokenizer alive (3 GB of VRAM for a 10 s clip, 6 GB for 20 s) for the same tokens.
        try:
            with self.torch.inference_mode():
                prompt = self.model.create_voice_clone_prompt(ref_audio=str(wav), ref_text=ref_text,
                                                              preprocess_prompt=True)
        finally:
            self._trim()
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
        elif params.get("instruct"):  # the voice style: with a cloned voice it has no measurable effect
            kwargs["instruct"] = params["instruct"]
        try:
            audio = self.model.generate(
                text=text,
                language=None if language in (None, "", "auto") else language,
                speed=None if speed in (None, 1.0) else speed,
                normalize_text=bool(params.get("normalize_text", False)),
                **kwargs,
            )
        finally:
            self._trim()
        import numpy as np

        return np.asarray(audio[0], dtype=np.float32)

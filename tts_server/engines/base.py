"""Engine interface for the TTS server.

To use another TTS model, add a module next to this one with an Engine subclass
and register it in engines/__init__.py. The server, profiles, pipeline and the
app's "Voz" tab only talk to this interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class Param:
    """One tunable synthesis parameter. The panel builds its form from these."""

    key: str
    label: str
    type: str  # "int" | "float" | "bool" | "select" | "text"
    default: Any
    group: str = "basic"  # "basic" | "advanced"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[dict] = field(default_factory=list)  # for "select": [{"value", "label"}]
    help: str = ""

    def to_json(self) -> dict:
        return asdict(self)

    def coerce(self, value: Any) -> Any:
        if value is None:
            return None
        if self.type == "int":
            value = int(round(float(value)))
        elif self.type == "float":
            value = float(value)
        elif self.type == "bool":
            value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "yes")
        else:
            return str(value)
        if self.min is not None:
            value = max(type(value)(self.min), value)
        if self.max is not None:
            value = min(type(value)(self.max), value)
        return value


class Engine:
    name = "base"
    label = "base"
    sample_rate = 24000
    # File name of the engine's cached voice inside a profile folder, e.g. "omnivoice.pt".
    profile_cache = "voice.bin"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def load(self) -> None:
        """Load the model (called once, in a worker thread)."""

    def info(self) -> dict:
        """Extra status shown in the panel (device, VRAM, ...)."""
        return {}

    def params(self) -> list[Param]:
        return []

    def transcribe(self, wav: Path) -> str:
        raise NotImplementedError

    def release_asr(self) -> None:
        """Free the transcription model when idle (optional)."""

    def build_profile(self, wav: Path, ref_text: str, cache: Path) -> None:
        """Turn a prepared reference clip + transcript into the engine's cached voice."""
        raise NotImplementedError

    def synthesize(self, text: str, cache: Path | None, params: dict) -> np.ndarray:
        """Return float32 mono samples at self.sample_rate. cache=None means no profile."""
        raise NotImplementedError

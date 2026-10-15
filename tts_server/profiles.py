"""Voice profiles and synthesis parameters, kept apart from the web routes and the engine.

  Params        global defaults (settings.json) and the precedence rule, over the engine's parameter list
  ProfileStore  profiles on disk: create / update / delete / list, rollback when building fails

No aiohttp, no numpy: a parameter only needs `.key`, `.default` and `.coerce(value)`, and the voice is
built by a `build(wav, ref_text, cache)` coroutine the caller supplies (the server runs it on the GPU).
Problems raise ProfileError subclasses, which carry the HTTP status the routes answer with.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable


class ProfileError(Exception):
    status = 400


class NotFound(ProfileError):
    status = 404


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:32] or "voz"


class Params:
    """Precedence: engine default < global settings < each layer given to resolve(), in order."""

    def __init__(self, engine_params: Callable[[], list], settings_path: Path):
        self.engine_params, self.settings_path = engine_params, settings_path

    def settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"params": {}}

    def save(self, params: dict) -> dict:
        settings = {"params": self.clean(params)}
        self.settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
        return settings

    def resolve(self, *layers: dict) -> dict:
        layers = (self.settings().get("params", {}), *layers)  # read the file once, not once per parameter
        out = {}
        for p in self.engine_params():
            value = p.default
            for layer in layers:
                if layer.get(p.key) is not None:
                    value = layer[p.key]
            out[p.key] = p.coerce(value)
        return out

    def clean(self, params: dict) -> dict:
        """Keep only known keys (coerced); None removes an override."""
        known = {p.key: p for p in self.engine_params()}
        return {k: known[k].coerce(v) for k, v in (params or {}).items() if k in known and v is not None}


def wav_seconds(path: Path) -> float:
    import soundfile as sf

    return sf.info(str(path)).duration


Build = Callable[[Path, str, Path], Awaitable[None]]


class ProfileStore:
    def __init__(self, root: Path, cache_name: str, params: Params, engine_name: str = "",
                 duration: Callable[[Path], float] = wav_seconds):
        self.root, self.cache_name, self.params = root, cache_name, params
        self.engine_name, self.duration = engine_name, duration
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, pid: str) -> Path:
        d = self.root / pid
        if not re.fullmatch(r"[a-z0-9-]+", pid) or not (d / "profile.json").exists():
            raise NotFound(f"profile not found: {pid}")
        return d

    def reference(self, pid: str) -> Path:
        return self.path(pid) / "reference.wav"

    def read(self, pid: str) -> dict:
        d = self.path(pid)
        meta = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        meta["ready"] = (d / self.cache_name).exists()
        return meta

    def _write(self, meta: dict) -> None:
        d = self.root / meta["id"]
        d.mkdir(exist_ok=True)
        clean = {k: v for k, v in meta.items() if k != "ready"}
        (d / "profile.json").write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")

    def list(self) -> list[dict]:
        out = [self.read(d.name) for d in sorted(self.root.iterdir()) if (d / "profile.json").exists()]
        return sorted(out, key=lambda m: m.get("created", 0))

    def for_synthesis(self, pid: str) -> tuple[Path, dict]:
        """(the profile's cached voice, its own parameters)"""
        meta = self.read(pid)
        return self.path(meta["id"]) / self.cache_name, meta.get("params", {})

    async def create(self, draft: Path, name: str, ref_text: str, params: dict, build: Build) -> dict:
        """Turn a prepared draft into a profile. The draft folder is removed on success, and the new
        profile folder on any failure."""
        name, ref_text = name.strip(), ref_text.strip()
        if not name or not ref_text:
            raise ProfileError("name and transcript are required")
        pid = f"{slugify(name)}-{secrets.token_hex(2)}"
        pdir = self.root / pid
        pdir.mkdir()
        try:
            shutil.copyfile(draft / "reference.wav", pdir / "reference.wav")
            await build(pdir / "reference.wav", ref_text, pdir / self.cache_name)
            meta = {"id": pid, "name": name, "ref_text": ref_text, "created": time.time(),
                    "duration": round(self.duration(pdir / "reference.wav"), 2),
                    "engine": self.engine_name, "params": self.params.clean(params)}
            self._write(meta)
        except BaseException:
            shutil.rmtree(pdir, ignore_errors=True)
            raise
        shutil.rmtree(draft, ignore_errors=True)
        return self.read(pid)

    async def update(self, pid: str, body: dict, build: Build) -> dict:
        """Rename, change parameters, or give a new transcript (which rebuilds the cached voice)."""
        meta = self.read(pid)
        if str(body.get("name", "")).strip():
            meta["name"] = body["name"].strip()
        if "params" in body:
            meta["params"] = self.params.clean(body["params"])
        new_text = str(body.get("ref_text", "")).strip()
        if new_text and new_text != meta["ref_text"]:
            d = self.path(pid)
            await build(d / "reference.wav", new_text, d / self.cache_name)
            meta["ref_text"] = new_text
        self._write(meta)
        return self.read(pid)

    def delete(self, pid: str) -> str:
        """Remove a profile for good; returns its name (for the log)."""
        name = self.read(pid).get("name", "?")
        shutil.rmtree(self.path(pid))
        return name

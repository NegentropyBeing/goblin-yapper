"""First-run installer for the voice runtime used by the installed app.

The MSI only ships the TTS server's code (tts_server/*.py). This module creates the heavy part
on demand, in %LOCALAPPDATA%\\GoblinYapper\\voice-runtime:

  1. download uv (pinned, checksum verified) - it fetches a standalone Python, no system Python needed
  2. uv venv with Python 3.13
  3. PyTorch 2.8 (CUDA 12.8 build, needed for RTX 50xx)
  4. OmniVoice + server dependencies (tts_server/requirements.txt)
  5. check the GPU

The model itself (~3 GB) downloads into the Hugging Face cache the first time the server starts.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections import deque
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

UV_VERSION = "0.12.18"
UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
UV_SHA256 = "cae6a3bc25239f83dffb467a4b180508d9da23986c04639ebfa44e43e6a84bff"
TORCH = ["torch==2.8.0+cu128", "torchaudio==2.8.0+cu128"]
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
RUNTIME_VERSION = "1"  # bump when the runtime's packages change, to force a reinstall

SERVER_FILES = ("server.py", "audio.py", "requirements.txt", "engines/__init__.py", "engines/base.py",
                "engines/omnivoice_engine.py")


def bundled_server_dir() -> Path:
    """tts_server/ shipped with the app (PyInstaller data) or next to the source."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "tts_server"  # noqa: SLF001
    return Path(__file__).resolve().parent.parent / "tts_server"


def runtime_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "GoblinYapper" / "voice-runtime"


class VoiceInstaller:
    STEPS = ("uv", "python", "torch", "omnivoice", "gpu")
    LABELS = {"uv": "baixando o instalador (uv)", "python": "preparando o Python",
              "torch": "instalando PyTorch com CUDA (~3 GB)", "omnivoice": "instalando OmniVoice",
              "gpu": "verificando a GPU"}

    def __init__(self, root: Path | None = None):
        self.root = root or runtime_dir()
        self.venv = self.root / ".venv"
        self.python = self.venv / "Scripts" / "python.exe"
        self.server_dir = self.root / "server"
        self.marker = self.root / "installed.txt"
        self.state = "idle"  # idle | running | done | error
        self.step: str | None = None
        self.error: str | None = None
        self.gpu: str | None = None
        self.started: float | None = None
        self.log: deque[str] = deque(maxlen=200)
        self.task: asyncio.Task | None = None

    @property
    def installed(self) -> bool:
        try:
            return self.python.exists() and self.marker.read_text().strip() == RUNTIME_VERSION
        except OSError:
            return False

    def sync_server_code(self) -> Path:
        """Copy the app's TTS server code into the runtime (keeps it in step with app updates)."""
        src = bundled_server_dir()
        for rel in SERVER_FILES:
            dst = self.server_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / rel, dst)
        return self.server_dir / "server.py"

    def status(self) -> dict:
        return {"state": self.state, "step": self.step, "label": self.LABELS.get(self.step or ""),
                "steps": [{"id": s, "label": self.LABELS[s]} for s in self.STEPS],
                "error": self.error, "gpu": self.gpu, "dir": str(self.root),
                "elapsed": round(time.time() - self.started) if self.started else None,
                "log": list(self.log)[-12:]}

    def start(self, on_done=None) -> None:
        if self.state == "running":
            return
        self.state, self.error, self.gpu, self.started = "running", None, None, time.time()
        self.log.clear()
        self.task = asyncio.get_running_loop().create_task(self._run(on_done))

    async def _run(self, on_done) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            uv = await self._get_uv()
            env = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(self.root / "python"), "UV_NO_CACHE": "1"}
            self.step = "python"
            await self._exec([uv, "venv", "--python", "3.13", "--allow-existing", str(self.venv)], env)
            self.step = "torch"
            await self._exec([uv, "pip", "install", "--python", str(self.python), *TORCH, "--index-url", TORCH_INDEX], env)
            self.step = "omnivoice"
            self.sync_server_code()
            await self._exec([uv, "pip", "install", "--python", str(self.python), "-r",
                              str(self.server_dir / "requirements.txt")], env)
            self.step = "gpu"
            out = await self._exec([str(self.python), "-c",
                                    "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"], env)
            self.gpu = out.strip().splitlines()[-1] if out.strip() else "?"
            self.marker.write_text(RUNTIME_VERSION)
            self.state, self.step = "done", None
            log.info("servidor de voz instalado em %s (%s)", self.root, self.gpu)
            if on_done:
                await on_done()
        except Exception as e:
            log.exception("falha ao instalar o servidor de voz")
            self.state, self.error = "error", str(e) or type(e).__name__

    async def _get_uv(self) -> str:
        self.step = "uv"
        uv = self.root / "uv" / "uv.exe"
        if uv.exists():
            return str(uv)
        self.log.append(f"baixando {UV_URL}")
        async with aiohttp.ClientSession() as s, s.get(UV_URL, timeout=aiohttp.ClientTimeout(total=300)) as r:
            r.raise_for_status()
            data = await r.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != UV_SHA256:
            raise RuntimeError(f"checksum do uv não confere ({digest}); download corrompido ou adulterado")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next(n for n in z.namelist() if n.endswith("uv.exe"))
            uv.parent.mkdir(parents=True, exist_ok=True)
            uv.write_bytes(z.read(member))
        self.log.append(f"uv {UV_VERSION} ok (sha256 verificado)")
        return str(uv)

    async def _exec(self, cmd: list[str], env: dict) -> str:
        self.log.append("> " + " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd)))
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = []
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                out.append(line)
                self.log.append(line)
        if await proc.wait() != 0:
            raise RuntimeError(f"{self.LABELS[self.step]} falhou: {out[-1] if out else 'sem saída'}")
        return "\n".join(out)

"""Starts and supervises the TTS server (tts_server/server.py) in its own Python environment.

If something already answers at the configured URL (e.g. you started the TTS server by
hand), it is used as is and not managed.

Which Python environment runs it, in order:
  1. [tts.server] python (+ script) from the config
  2. running from source with tts_server/.venv present (made by tts_server/setup.ps1)
  3. the voice runtime the app installs on first use (tts_install.py, %LOCALAPPDATA%)
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .tts_install import VoiceInstaller

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TTSService:
    def __init__(self, cfg: dict, data_dir: Path):
        self.url = cfg.get("url", "http://127.0.0.1:8766").rstrip("/")
        self.autostart = cfg.get("autostart", True)
        self.engine = cfg.get("engine", "omnivoice")
        self.installer = VoiceInstaller()
        dev_python = PROJECT_ROOT / "tts_server" / ".venv" / "Scripts" / "python.exe"
        self.uses_runtime = False
        if cfg.get("python"):
            self.python = Path(cfg["python"])
            self.script = Path(cfg.get("script") or PROJECT_ROOT / "tts_server" / "server.py")
        elif not getattr(sys, "frozen", False) and dev_python.exists() and not cfg.get("use_runtime"):
            self.python, self.script = dev_python, PROJECT_ROOT / "tts_server" / "server.py"
        else:
            self.uses_runtime = True
            self.python, self.script = self.installer.python, self.installer.server_dir / "server.py"
        self.data_dir = data_dir / "tts"
        self.proc: asyncio.subprocess.Process | None = None
        self.mode = "stopped"  # stopped | managed | external | not_installed | exited
        self.session: aiohttp.ClientSession | None = None

    @property
    def installed(self) -> bool:
        if self.uses_runtime:
            return self.installer.installed
        return self.python.exists() and self.script.exists()

    async def _alive(self) -> bool:
        try:
            async with self.session.get(f"{self.url}/status", timeout=aiohttp.ClientTimeout(total=1)) as r:
                return r.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def start(self) -> None:
        self.session = self.session or aiohttp.ClientSession()
        if await self._alive():
            self.mode = "external"
            log.info("servidor TTS já rodando em %s; usando ele", self.url)
            return
        if not self.installed:
            self.mode = "not_installed"
            log.warning("servidor de voz não instalado; instale pela aba Voz (ou rode tts_server\\setup.ps1)")
            return
        if self.uses_runtime:
            self.installer.sync_server_code()  # the runtime gets this app version's server code
        port = str(urlparse(self.url).port or 8766)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.proc = await asyncio.create_subprocess_exec(
            str(self.python), str(self.script), "--data-dir", str(self.data_dir), "--port", port,
            "--engine", self.engine, "--parent-pid", str(os.getpid()),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.mode = "managed"
        log.info("servidor TTS iniciado (pid %s), log em %s", self.proc.pid, self.data_dir / "tts-server.log")
        asyncio.get_running_loop().create_task(self._watch(self.proc))

    async def _watch(self, proc) -> None:
        code = await proc.wait()
        if proc is self.proc:
            self.mode = "exited"
            log.warning("servidor TTS encerrou (código %s); veja %s", code, self.data_dir / "tts-server.log")

    async def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        self.mode = "stopped"

    async def restart(self) -> None:
        if self.mode == "external":
            raise RuntimeError("o servidor TTS foi iniciado fora do app; reinicie-o por lá")
        await self.stop()
        await self.start()

    async def close(self) -> None:
        await self.stop()
        if self.session:
            await self.session.close()

    def install(self) -> None:
        """Install the voice runtime in the background, then start the server."""
        if not self.uses_runtime:
            raise RuntimeError("este servidor de voz é configurado manualmente (tts_server/setup.ps1)")
        self.installer.start(on_done=self.start)

    async def status(self) -> dict:
        out = {"mode": self.mode, "url": self.url, "log": str(self.data_dir / "tts-server.log"),
               "can_install": self.uses_runtime, "install": self.installer.status()}
        if self.mode in ("managed", "external") and self.session:
            try:
                async with self.session.get(f"{self.url}/status", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    out["server"] = await r.json()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                out["server"] = {"state": "starting" if self.mode == "managed" else "unreachable"}
        return out

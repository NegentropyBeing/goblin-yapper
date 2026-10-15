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

from .i18n import MessageError
from .tts import DEFAULT_SERVER_URL
from .tts_install import VoiceInstaller

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ServiceError(MessageError, RuntimeError):
    """The operator asked for something the voice server can't do right now."""


class TTSService:
    def __init__(self, cfg: dict, data_dir: Path):
        self.url = cfg.get("url", DEFAULT_SERVER_URL).rstrip("/")
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
        self.stderr_path = self.data_dir / "tts-server.stderr"
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
        if self.proc and self.proc.returncode is None:
            return  # already on
        if await self._alive():
            self.mode = "external"
            log.info("TTS server already running at %s; using it", self.url)
            return
        if not self.installed:
            self.mode = "not_installed"
            log.warning("voice server not installed; install it from the Voice tab (or run tts_server\\setup.ps1)")
            return
        if self.uses_runtime:
            self.installer.sync_server_code()  # the runtime gets this app version's server code
        port = str(urlparse(self.url).port or 8766)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # stderr goes to a file: a crash before the server sets up its own log (a bad import) shows up only there
        with open(self.stderr_path, "wb") as err:
            self.proc = await asyncio.create_subprocess_exec(
                str(self.python), str(self.script), "--data-dir", str(self.data_dir), "--port", port,
                "--engine", self.engine, "--parent-pid", str(os.getpid()),
                stdout=subprocess.DEVNULL, stderr=err,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.mode = "managed"
        log.info("TTS server started (pid %s), log at %s", self.proc.pid, self.data_dir / "tts-server.log")
        asyncio.get_running_loop().create_task(self._watch(self.proc))

    async def _watch(self, proc) -> None:
        code = await proc.wait()
        if proc is self.proc:
            self.mode = "exited"
            log.warning("TTS server exited (code %s); see %s", code, self.data_dir / "tts-server.log")
            self._copy_crash_to_log()

    def _copy_crash_to_log(self) -> None:
        """Put what the dead server wrote to stderr into tts-server.log, where the panel tells the user to look."""
        try:
            tail = self.stderr_path.read_text(encoding="utf-8", errors="replace").strip()[-4000:]
            if tail:
                with open(self.data_dir / "tts-server.log", "a", encoding="utf-8") as f:
                    f.write(f"\n--- the server exited; error output ---\n{tail}\n")
        except OSError:
            pass

    async def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        self.mode = "stopped"

    async def restart(self) -> None:
        if self.mode == "external":
            raise ServiceError("tts.external_restart")
        await self.stop()
        await self.start()

    async def turn_off(self) -> None:
        """Unload the model: ending the server process is what gives all its VRAM back."""
        if self.mode == "external":
            raise ServiceError("tts.external_stop")
        await self.stop()
        log.info("TTS server turned off from the panel")

    async def close(self) -> None:
        await self.stop()
        if self.session:
            await self.session.close()

    def install(self) -> None:
        """Install the voice runtime in the background, then start the server."""
        if not self.uses_runtime:
            raise ServiceError("tts.manual_setup")
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

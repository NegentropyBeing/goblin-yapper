"""python -m goblin_yapper [--data-dir DIR] [--channel name] [--port N] [--no-chat] [--no-console]

The data dir holds config.toml (created from the default on first run), settings.json
(changes made in the panel), assets/ (goblin images), voices/, scripts/ and the log.
Relative paths in config.toml resolve against it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
import tomllib
from pathlib import Path

from aiohttp import web

from .app import App
from .teams import SorterError
from .server import make_web_app
from .tts import TTS

log = logging.getLogger("goblin_yapper")

DEFAULT_CONFIG = Path(__file__).resolve().parent / "default_config.toml"


async def console_loop(app: App) -> None:
    print(App.HELP + "\n  quit                      sai\n")
    while True:
        try:
            line = await asyncio.to_thread(input, "> ")
        except EOFError:
            # No interactive stdin: keep running headless.
            return
        if line.strip().lower() in ("quit", "exit"):
            raise SystemExit
        if out := await app.command(line):
            print(out)


async def watch_parent(pid: int) -> None:
    """Exit when the desktop app that spawned us goes away (even if it crashed)."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        alive = lambda: handle and kernel32.WaitForSingleObject(handle, 0) != 0  # noqa: E731
    else:
        def alive():
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
    while alive():
        await asyncio.sleep(2)
    log.info("app principal encerrou; saindo")
    os._exit(0)


async def main(args: argparse.Namespace, data_dir: Path) -> None:
    config_path = data_dir / "config.toml"
    if not config_path.exists():
        shutil.copyfile(DEFAULT_CONFIG, config_path)
        log.info("config criado em %s", config_path)
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))

    tts = TTS(cfg.get("tts", {}))
    app = App(cfg, tts, settings_path=data_dir / "settings.json")
    await tts.load()

    srv = app.cfg.get("server", {})
    host, port = args.host or srv.get("host", "127.0.0.1"), args.port or int(srv.get("port", 8765))
    runner = web.AppRunner(make_web_app(app, data_dir / "assets"), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("painel: http://%s:%s/panel  |  overlay: http://%s:%s/overlay", host, port, host, port)

    worker = asyncio.create_task(app.speech_worker())
    if args.parent_pid:
        watchdog = asyncio.create_task(watch_parent(args.parent_pid))  # noqa: F841 (kept alive by the loop)
    if not args.no_chat:
        try:
            app.start_chat(args.channel or app.cfg.get("twitch", {}).get("channel", ""))
        except SorterError as e:  # invalid channel in config/settings
            log.warning("%s", e)
    if not app.channel:
        log.warning("sem canal da Twitch configurado (use o painel ou: channel <canal>)")
    try:
        if not args.no_console:
            await console_loop(app)
        await worker
    finally:
        worker.cancel()
        if app.chat_task:
            app.chat_task.cancel()
        await runner.cleanup()


def setup_logging(data_dir: Path, verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(data_dir / "goblin-yapper.log", encoding="utf-8")]
    if sys.stderr is not None:  # None in a windowed (no console) build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname).1s %(name)s: %(message)s", datefmt="%H:%M:%S")


def cli() -> None:
    p = argparse.ArgumentParser(prog="goblin_yapper")
    p.add_argument("--data-dir", default=".", help="pasta de dados (config, assets, vozes, log)")
    p.add_argument("--channel", help="canal da Twitch (sobrepõe o config)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--no-chat", action="store_true", help="não conectar ao chat (testes)")
    p.add_argument("--no-console", action="store_true", help="sem console interativo (modo app)")
    p.add_argument("--parent-pid", type=int, help="encerra quando este processo terminar (usado pelo app)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(data_dir)
    setup_logging(data_dir, args.verbose)
    try:
        asyncio.run(main(args, data_dir))
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:
        log.exception("erro fatal")
        raise


if __name__ == "__main__":
    sys.exit(cli())

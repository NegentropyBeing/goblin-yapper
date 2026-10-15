"""Goblin Yapper TTS server: loads a TTS model on the GPU once and serves it over HTTP.

Runs in its own Python environment (PyTorch + the TTS engine), started by the app.

  python tts_server/server.py --data-dir DIR [--port 8766] [--engine omnivoice] [--parent-pid N]

  GET    /status                          state: loading | ready | error, plus GPU/VRAM info
  GET    /schema                          engine name + parameter definitions (the panel builds its form from it)
  GET    /settings   PUT /settings        global parameter defaults {"params": {...}}
  GET    /profiles                        voice profiles
  POST   /pipeline/prepare                raw audio body -> cleaned reference draft (?trim=1&normalize=1&max_seconds=20)
  GET    /pipeline/<draft>/reference.wav
  POST   /pipeline/<draft>/transcribe     -> {"text": ...}  (Whisper; unloaded again when idle)
  POST   /asr/release                     unload Whisper now, freeing its VRAM
  POST   /profiles                        {"draft_id", "name", "ref_text", "params"?} -> builds the cached voice
  PATCH  /profiles/<id>                   {"name"?, "ref_text"? (rebuilds), "params"?}
  DELETE /profiles/<id>
  GET    /profiles/<id>/reference.wav
  POST   /synthesize                      {"text", "profile"?, "params"?, "global_params"?} -> audio/wav

Parameter precedence: engine default < global settings < request global_params < profile params < request params.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio  # noqa: E402
from engines import get_engine  # noqa: E402
from profiles import ProfileError, ProfileStore, Params  # noqa: E402

log = logging.getLogger("tts_server")
ASR_IDLE_SECONDS = 300


class TTSServer:
    def __init__(self, data_dir: Path, engine_name: str, engine_cfg: dict):
        self.data_dir = data_dir
        self.profiles_dir = data_dir / "profiles"
        self.drafts_dir = data_dir / "drafts"
        shutil.rmtree(self.drafts_dir, ignore_errors=True)  # drafts don't survive restarts
        self.drafts_dir.mkdir(parents=True)
        self.engine = get_engine(engine_name)(engine_cfg)
        self.params = Params(self.engine.params, data_dir / "settings.json")
        self.profiles = ProfileStore(self.profiles_dir, self.engine.profile_cache, self.params, self.engine.name)
        self.state, self.error = "loading", None
        self.busy = None  # what the GPU is doing right now
        self.lock = asyncio.Lock()
        self._asr_timer: asyncio.TimerHandle | None = None

    # ---- lifecycle -----------------------------------------------------

    def load_in_background(self) -> None:
        def run():
            t = time.time()
            try:
                self.engine.load()
                self.state = "ready"
                log.info("%s ready in %.1fs", self.engine.label, time.time() - t)
            except Exception as e:
                log.exception("failed to load the model")
                self.state, self.error = "error", f"{type(e).__name__}: {e}"

        threading.Thread(target=run, daemon=True).start()

    def require_ready(self) -> None:
        if self.state != "ready":
            raise web.HTTPServiceUnavailable(text="modelo carregando" if self.state == "loading" else f"erro: {self.error}")

    async def gpu(self, what: str, fn, *args):
        """Serialize GPU work and run it off the event loop."""
        self.require_ready()
        async with self.lock:
            self.busy = what
            try:
                return await asyncio.to_thread(fn, *args)
            finally:
                self.busy = None

    def schedule_asr_release(self) -> None:
        if self._asr_timer:
            self._asr_timer.cancel()
        loop = asyncio.get_running_loop()
        self._asr_timer = loop.call_later(ASR_IDLE_SECONDS, lambda: loop.create_task(self.gpu("liberando Whisper", self.engine.release_asr)))

    async def release_asr_now(self) -> None:
        if self._asr_timer:
            self._asr_timer.cancel()
            self._asr_timer = None
        await self.gpu("liberando Whisper", self.engine.release_asr)


def make_app(srv: TTSServer) -> web.Application:
    routes = web.RouteTableDef()

    def draft_dir(draft: str) -> Path:
        d = srv.drafts_dir / draft
        if not re.fullmatch(r"[a-f0-9]{12}", draft) or not d.exists():
            raise web.HTTPNotFound(text="draft not found (did the server restart?)")
        return d

    @routes.get("/status")
    async def status(_):
        info = srv.engine.info() if srv.state == "ready" else {}
        # profiles_dir: the server reports its own folder, so the panel shows the truth even when
        # it is attached to a server started elsewhere (with another data dir)
        return web.json_response({"state": srv.state, "error": srv.error, "busy": srv.busy,
                                  "engine": srv.engine.name, "label": srv.engine.label,
                                  "profiles_dir": str(srv.profiles_dir), **info})

    @routes.get("/schema")
    async def schema(_):
        return web.json_response({"engine": srv.engine.name, "label": srv.engine.label,
                                  "sample_rate": srv.engine.sample_rate,
                                  "params": [p.to_json() for p in srv.engine.params()]})

    @routes.get("/settings")
    async def get_settings(_):
        return web.json_response(srv.params.settings())

    @routes.put("/settings")
    async def put_settings(request):
        body = await request.json()
        return web.json_response(srv.params.save(body.get("params", {})))

    # -- pipeline: prepare -> transcribe -> create

    @routes.post("/pipeline/prepare")
    async def prepare(request):
        data = await request.read()
        q = request.query
        try:
            samples, steps = await asyncio.to_thread(
                audio.prepare, data, srv.engine.sample_rate, q.get("trim", "1") == "1",
                q.get("normalize", "1") == "1", float(q.get("max_seconds", 20)))
        except ValueError as e:
            raise web.HTTPBadRequest(text=str(e))
        draft = secrets.token_hex(6)
        d = srv.drafts_dir / draft
        d.mkdir()
        (d / "original").write_bytes(data)
        (d / "reference.wav").write_bytes(audio.to_wav(samples, srv.engine.sample_rate))
        return web.json_response({"draft_id": draft, "duration": round(len(samples) / srv.engine.sample_rate, 2),
                                  "steps": steps, "url": f"/pipeline/{draft}/reference.wav"})

    @routes.get("/pipeline/{draft}/reference.wav")
    async def draft_audio(request):
        return web.FileResponse(draft_dir(request.match_info["draft"]) / "reference.wav")

    @routes.post("/pipeline/{draft}/transcribe")
    async def transcribe(request):
        d = draft_dir(request.match_info["draft"])
        t = time.time()
        text = await srv.gpu("transcribing", srv.engine.transcribe, d / "reference.wav")
        srv.schedule_asr_release()
        return web.json_response({"text": text, "seconds": round(time.time() - t, 2)})

    @routes.post("/profiles")
    async def create_profile(request):
        body = await request.json()
        d = draft_dir(str(body.get("draft_id", "")))

        async def build(wav, ref_text, cache):
            await srv.gpu("creating profile", srv.engine.build_profile, wav, ref_text, cache)

        try:
            meta = await srv.profiles.create(d, str(body.get("name", "")), str(body.get("ref_text", "")),
                                             body.get("params", {}), build)
        except (web.HTTPException, ProfileError):
            raise
        except Exception as e:
            log.exception("failed to create the profile")
            raise web.HTTPInternalServerError(text=f"failed to create the profile: {e}")
        log.info("profile created: %s (%s)", meta["name"], meta["id"])
        if srv._asr_timer:  # the draft is done with Whisper: don't hold its VRAM for the idle timeout
            await srv.release_asr_now()
        return web.json_response(meta)

    @routes.post("/asr/release")
    async def release_asr(_):
        await srv.release_asr_now()
        return web.json_response({"ok": True})

    @routes.get("/profiles")
    async def profiles(_):
        return web.json_response(srv.profiles.list())

    @routes.get("/profiles/{id}/reference.wav")
    async def profile_audio(request):
        return web.FileResponse(srv.profiles.reference(request.match_info["id"]))

    @routes.patch("/profiles/{id}")
    async def update_profile(request):
        async def build(wav, ref_text, cache):
            await srv.gpu("recreating profile", srv.engine.build_profile, wav, ref_text, cache)

        return web.json_response(await srv.profiles.update(request.match_info["id"], await request.json(), build))

    @routes.delete("/profiles/{id}")
    async def delete_profile(request):
        pid = request.match_info["id"]
        name = srv.profiles.delete(pid)
        log.info("profile deleted: %s (%s)", name, pid)  # deletions are permanent, so leave a trace
        return web.json_response({"ok": True})

    @routes.post("/synthesize")
    async def synthesize(request):
        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            raise web.HTTPBadRequest(text="texto vazio")
        cache, profile_params = None, {}
        if body.get("profile"):
            cache, profile_params = srv.profiles.for_synthesis(str(body["profile"]))
        # "global_params" previews unsaved global settings: they sit below the profile's own params.
        params = srv.params.resolve(body.get("global_params") or {}, profile_params, body.get("params") or {})
        t = time.time()
        samples = await srv.gpu("generating speech", srv.engine.synthesize, text, cache, params)
        gen = time.time() - t
        dur = len(samples) / srv.engine.sample_rate
        log.info("speech: %.2fs of audio in %.2fs (%s)", dur, gen, body.get("profile") or "no profile")
        return web.Response(body=audio.to_wav(samples, srv.engine.sample_rate), content_type="audio/wav",
                            headers={"X-Gen-Seconds": f"{gen:.2f}", "X-Audio-Seconds": f"{dur:.2f}"})

    @web.middleware
    async def errors(request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except ProfileError as e:
            return web.Response(status=e.status, text=str(e))
        except Exception as e:
            log.exception("error in %s", request.path)
            raise web.HTTPInternalServerError(text=f"{type(e).__name__}: {e}")

    app = web.Application(middlewares=[errors], client_max_size=50 * 1024 * 1024)
    app.add_routes(routes)
    return app


async def watch_parent(pid: int) -> None:
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
    log.info("parent process exited; quitting")
    os._exit(0)


async def main(args) -> None:
    data_dir = Path(args.data_dir).resolve()
    srv = TTSServer(data_dir, args.engine, {"model": args.model, "device": args.device, "dtype": args.dtype})
    runner = web.AppRunner(make_app(srv), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    log.info("TTS server at http://127.0.0.1:%s (engine=%s)", args.port, args.engine)
    srv.load_in_background()
    if args.parent_pid:
        asyncio.create_task(watch_parent(args.parent_pid))
    await asyncio.Event().wait()


def cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", required=True)
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--engine", default="omnivoice")
    p.add_argument("--model", default="k2-fsa/OmniVoice")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--dtype", default="float16")
    p.add_argument("--parent-pid", type=int)
    args = p.parse_args()
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
                        datefmt="%H:%M:%S",
                        handlers=[logging.FileHandler(data_dir / "tts-server.log", encoding="utf-8"),
                                  *([logging.StreamHandler()] if sys.stderr else [])])
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()

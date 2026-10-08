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
import json
import logging
import os
import re
import secrets
import shutil
import sys
import threading
import time
import unicodedata
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio  # noqa: E402
from engines import get_engine  # noqa: E402

log = logging.getLogger("tts_server")
ASR_IDLE_SECONDS = 300


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:32] or "voz"


class TTSServer:
    def __init__(self, data_dir: Path, engine_name: str, engine_cfg: dict):
        self.data_dir = data_dir
        self.profiles_dir = data_dir / "profiles"
        self.drafts_dir = data_dir / "drafts"
        self.settings_path = data_dir / "settings.json"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.drafts_dir, ignore_errors=True)  # drafts don't survive restarts
        self.drafts_dir.mkdir(parents=True)
        self.engine = get_engine(engine_name)(engine_cfg)
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
                log.info("%s pronto em %.1fs", self.engine.label, time.time() - t)
            except Exception as e:
                log.exception("falha ao carregar o modelo")
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

    # ---- settings / params ---------------------------------------------

    def settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"params": {}}

    def resolve_params(self, *layers: dict) -> dict:
        out = {}
        for p in self.engine.params():
            value = p.default
            for layer in (self.settings().get("params", {}), *layers):
                if layer.get(p.key) is not None:
                    value = layer[p.key]
            out[p.key] = p.coerce(value)
        return out

    def clean_params(self, params: dict) -> dict:
        """Keep only known keys (coerced); None removes an override."""
        known = {p.key: p for p in self.engine.params()}
        return {k: known[k].coerce(v) for k, v in (params or {}).items() if k in known and v is not None}

    # ---- profiles ------------------------------------------------------

    def profile_dir(self, pid: str) -> Path:
        d = self.profiles_dir / pid
        if not re.fullmatch(r"[a-z0-9-]+", pid) or not (d / "profile.json").exists():
            raise web.HTTPNotFound(text=f"perfil não encontrado: {pid}")
        return d

    def read_profile(self, pid: str) -> dict:
        d = self.profile_dir(pid)
        meta = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        meta["ready"] = (d / self.engine.profile_cache).exists()
        return meta

    def write_profile(self, meta: dict) -> None:
        d = self.profiles_dir / meta["id"]
        d.mkdir(exist_ok=True)
        clean = {k: v for k, v in meta.items() if k != "ready"}
        (d / "profile.json").write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_profiles(self) -> list[dict]:
        out = []
        for d in sorted(self.profiles_dir.iterdir()):
            if (d / "profile.json").exists():
                out.append(self.read_profile(d.name))
        return sorted(out, key=lambda m: m.get("created", 0))

    def schedule_asr_release(self) -> None:
        if self._asr_timer:
            self._asr_timer.cancel()
        loop = asyncio.get_running_loop()
        self._asr_timer = loop.call_later(ASR_IDLE_SECONDS, lambda: loop.create_task(self.gpu("liberando Whisper", self.engine.release_asr)))


def make_app(srv: TTSServer) -> web.Application:
    routes = web.RouteTableDef()

    def draft_dir(draft: str) -> Path:
        d = srv.drafts_dir / draft
        if not re.fullmatch(r"[a-f0-9]{12}", draft) or not d.exists():
            raise web.HTTPNotFound(text="rascunho não encontrado (o servidor reiniciou?)")
        return d

    @routes.get("/status")
    async def status(_):
        info = srv.engine.info() if srv.state == "ready" else {}
        return web.json_response({"state": srv.state, "error": srv.error, "busy": srv.busy,
                                  "engine": srv.engine.name, "label": srv.engine.label, **info})

    @routes.get("/schema")
    async def schema(_):
        return web.json_response({"engine": srv.engine.name, "label": srv.engine.label,
                                  "sample_rate": srv.engine.sample_rate,
                                  "params": [p.to_json() for p in srv.engine.params()]})

    @routes.get("/settings")
    async def get_settings(_):
        return web.json_response(srv.settings())

    @routes.put("/settings")
    async def put_settings(request):
        body = await request.json()
        settings = {"params": srv.clean_params(body.get("params", {}))}
        srv.settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
        return web.json_response(settings)

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
        text = await srv.gpu("transcrevendo", srv.engine.transcribe, d / "reference.wav")
        srv.schedule_asr_release()
        return web.json_response({"text": text, "seconds": round(time.time() - t, 2)})

    @routes.post("/profiles")
    async def create_profile(request):
        body = await request.json()
        d = draft_dir(str(body.get("draft_id", "")))
        name = str(body.get("name", "")).strip()
        ref_text = str(body.get("ref_text", "")).strip()
        if not name or not ref_text:
            raise web.HTTPBadRequest(text="nome e transcrição são obrigatórios")
        pid = f"{slugify(name)}-{secrets.token_hex(2)}"
        pdir = srv.profiles_dir / pid
        pdir.mkdir()
        shutil.copyfile(d / "reference.wav", pdir / "reference.wav")
        try:
            await srv.gpu("criando perfil", srv.engine.build_profile, pdir / "reference.wav", ref_text,
                          pdir / srv.engine.profile_cache)
        except Exception as e:
            shutil.rmtree(pdir, ignore_errors=True)
            if isinstance(e, web.HTTPException):
                raise
            log.exception("falha ao criar perfil")
            raise web.HTTPInternalServerError(text=f"falha ao criar perfil: {e}")
        import soundfile as sf

        meta = {"id": pid, "name": name, "ref_text": ref_text, "created": time.time(),
                "duration": round(sf.info(str(pdir / "reference.wav")).duration, 2),
                "engine": srv.engine.name, "params": srv.clean_params(body.get("params", {}))}
        srv.write_profile(meta)
        shutil.rmtree(d, ignore_errors=True)
        log.info("perfil criado: %s (%s)", name, pid)
        return web.json_response(srv.read_profile(pid))

    @routes.get("/profiles")
    async def profiles(_):
        return web.json_response(srv.list_profiles())

    @routes.get("/profiles/{id}/reference.wav")
    async def profile_audio(request):
        return web.FileResponse(srv.profile_dir(request.match_info["id"]) / "reference.wav")

    @routes.patch("/profiles/{id}")
    async def update_profile(request):
        pid = request.match_info["id"]
        meta = srv.read_profile(pid)
        body = await request.json()
        if str(body.get("name", "")).strip():
            meta["name"] = body["name"].strip()
        if "params" in body:
            meta["params"] = srv.clean_params(body["params"])
        new_text = str(body.get("ref_text", "")).strip()
        if new_text and new_text != meta["ref_text"]:
            d = srv.profile_dir(pid)
            await srv.gpu("recriando perfil", srv.engine.build_profile, d / "reference.wav", new_text,
                          d / srv.engine.profile_cache)
            meta["ref_text"] = new_text
        srv.write_profile(meta)
        return web.json_response(srv.read_profile(pid))

    @routes.delete("/profiles/{id}")
    async def delete_profile(request):
        shutil.rmtree(srv.profile_dir(request.match_info["id"]))
        return web.json_response({"ok": True})

    @routes.post("/synthesize")
    async def synthesize(request):
        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            raise web.HTTPBadRequest(text="texto vazio")
        cache, profile_params = None, {}
        if body.get("profile"):
            meta = srv.read_profile(str(body["profile"]))
            cache = srv.profile_dir(meta["id"]) / srv.engine.profile_cache
            profile_params = meta.get("params", {})
        # "global_params" previews unsaved global settings: they sit below the profile's own params.
        params = srv.resolve_params(body.get("global_params") or {}, profile_params, body.get("params") or {})
        t = time.time()
        samples = await srv.gpu("gerando fala", srv.engine.synthesize, text, cache, params)
        gen = time.time() - t
        dur = len(samples) / srv.engine.sample_rate
        log.info("fala: %.2fs de áudio em %.2fs (%s)", dur, gen, body.get("profile") or "sem perfil")
        return web.Response(body=audio.to_wav(samples, srv.engine.sample_rate), content_type="audio/wav",
                            headers={"X-Gen-Seconds": f"{gen:.2f}", "X-Audio-Seconds": f"{dur:.2f}"})

    @web.middleware
    async def errors(request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as e:
            log.exception("erro em %s", request.path)
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
    log.info("processo pai encerrou; saindo")
    os._exit(0)


async def main(args) -> None:
    data_dir = Path(args.data_dir).resolve()
    srv = TTSServer(data_dir, args.engine, {"model": args.model, "device": args.device, "dtype": args.dtype})
    runner = web.AppRunner(make_app(srv), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    log.info("servidor TTS em http://127.0.0.1:%s (engine=%s)", args.port, args.engine)
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

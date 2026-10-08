"""HTTP + WebSocket server: OBS overlay, operator panel, audio files and the control API.

  GET    /overlay              OBS browser source (?team=azul to pin one goblin, ?audio=0 to mute)
  GET    /panel                operator panel (also loaded by the desktop app)
  GET    /audio/<id>.wav       synthesized speech
  GET    /api/state            current state (JSON)
  POST   /api/command          {"command": "sort"} -> {"output": "...", "state": {...}}
  GET    /api/assets           goblin images per team
  PUT    /api/assets/<file>    upload goblin.png / goblin.gif / <team>.png / <team>.gif (raw body)
  DELETE /api/assets/<file>
  WS     /ws                   pushes state/speak/idle/stop/assets; accepts {"type": "ended", "id": n}
  GET    /api/tts-service      TTS server process status (+ the server's own /status)
  POST   /api/tts-service/restart
  POST   /api/tts-service/install  first-run install of the voice runtime (installed app)
  *      /api/tts/<path>       forwarded to the TTS server (profiles, pipeline, schema, settings, synthesize)
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiohttp
from aiohttp import WSMsgType, web

from .app import App
from .teams import TEAM_NAMES

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
ASSET_FILES = {f"{stem}.{ext}" for stem in ("goblin", *TEAM_NAMES) for ext in ("png", "gif")}
MAX_ASSET_BYTES = 20 * 1024 * 1024


def find_assets(assets_dir: Path) -> dict:
    """Per team: {'idle': url|None, 'talk': url|None}. Looks for <team>.png/.gif, then goblin.png/.gif.
    URLs carry the file mtime so overlays pick up replaced images."""
    out = {}
    for team in (*TEAM_NAMES, "default"):
        entry = {}
        for state, ext in (("idle", "png"), ("talk", "gif")):
            entry[state] = None
            for stem in (team, "goblin"):
                f = assets_dir / f"{stem}.{ext}"
                if f.exists():
                    entry[state] = f"/assets/{f.name}?v={int(f.stat().st_mtime)}"
                    break
        out[team] = entry
    return out


def make_web_app(app: App, assets_dir: Path) -> web.Application:
    assets_dir.mkdir(parents=True, exist_ok=True)

    async def root(_):
        raise web.HTTPFound("/panel")

    def page(name):
        async def handler(_):
            return web.FileResponse(WEB_DIR / name, headers={"Cache-Control": "no-cache"})
        return handler

    async def audio(request):
        wav = app.audio.get(int(request.match_info["id"]))
        if wav is None:
            raise web.HTTPNotFound()
        return web.Response(body=wav, content_type="audio/wav")

    async def state(_):
        return web.json_response(app.state())

    async def assets(_):
        return web.json_response({"files": sorted(p.name for p in assets_dir.iterdir() if p.name in ASSET_FILES),
                                  "teams": find_assets(assets_dir)})

    def asset_path(request) -> Path:
        name = request.match_info["name"].lower()
        if name not in ASSET_FILES:
            raise web.HTTPBadRequest(text=f"nome inválido; use um de: {', '.join(sorted(ASSET_FILES))}")
        return assets_dir / name

    async def upload_asset(request):
        path = asset_path(request)
        data = await request.read()
        if not data or len(data) > MAX_ASSET_BYTES:
            raise web.HTTPBadRequest(text="arquivo vazio ou maior que 20MB")
        if not (data.startswith(b"\x89PNG") if path.suffix == ".png" else data[:4] == b"GIF8"):
            raise web.HTTPBadRequest(text=f"o arquivo não é um {path.suffix[1:].upper()} válido")
        path.write_bytes(data)
        await app.broadcast({"type": "assets"})
        return web.json_response({"ok": True})

    async def delete_asset(request):
        asset_path(request).unlink(missing_ok=True)
        await app.broadcast({"type": "assets"})
        return web.json_response({"ok": True})

    async def command(request):
        try:
            body = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="JSON inválido; esperado {\"command\": \"...\"}")
        output = await app.command(str(body.get("command", "")))
        return web.json_response({"output": output, "state": app.state()})

    async def ws_handler(request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        app.clients.add(ws)
        await ws.send_str(json.dumps(app.state()))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if data.get("type") == "ended":
                    app.on_audio_ended(int(data["id"]))
        finally:
            app.clients.discard(ws)
        return ws

    async def tts_service_status(_):
        if app.tts_service is None:
            return web.json_response({"mode": "disabled"})
        return web.json_response(await app.tts_service.status())

    async def tts_service_restart(_):
        try:
            await app.tts_service.restart()
        except RuntimeError as e:
            raise web.HTTPConflict(text=str(e))
        return web.json_response(await app.tts_service.status())

    async def tts_service_install(_):
        try:
            app.tts_service.install()
        except RuntimeError as e:
            raise web.HTTPConflict(text=str(e))
        return web.json_response(await app.tts_service.status())

    async def tts_proxy(request):
        svc = app.tts_service
        if svc is None or svc.session is None:
            raise web.HTTPServiceUnavailable(text="servidor TTS desativado")
        url = f"{svc.url}/{request.match_info['tail']}"
        headers = {k: v for k, v in request.headers.items() if k.lower() == "content-type"}
        try:
            async with svc.session.request(request.method, url, params=request.query, data=await request.read(),
                                           headers=headers, timeout=aiohttp.ClientTimeout(total=300)) as r:
                body = await r.read()
                out = {k: v for k, v in r.headers.items() if k.lower() == "content-type" or k.lower().startswith("x-")}
                return web.Response(body=body, status=r.status, headers=out)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise web.HTTPServiceUnavailable(text=f"servidor TTS fora do ar ({type(e).__name__})")

    wa = web.Application(client_max_size=60 * 1024 * 1024)
    wa.add_routes([
        web.get("/", root),
        web.get("/overlay", page("overlay.html")),
        web.get("/panel", page("panel.html")),
        web.get(r"/audio/{id:\d+}.wav", audio),
        web.get("/api/state", state),
        web.get("/api/assets", assets),
        web.put("/api/assets/{name}", upload_asset),
        web.delete("/api/assets/{name}", delete_asset),
        web.post("/api/command", command),
        web.get("/ws", ws_handler),
        web.get("/api/tts-service", tts_service_status),
        web.post("/api/tts-service/restart", tts_service_restart),
        web.post("/api/tts-service/install", tts_service_install),
        web.route("*", "/api/tts/{tail:.*}", tts_proxy),
        web.static("/assets", assets_dir),
        web.static("/web", WEB_DIR),
    ])
    return wa

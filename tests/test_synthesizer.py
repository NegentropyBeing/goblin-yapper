import asyncio
import sys

import pytest
from aiohttp import web

from goblin_yapper.app import App
from goblin_yapper.server import make_web_app
from goblin_yapper.tts import DummyEngine, Synthesizer

WAV = DummyEngine({}).synthesize("oi", {})


async def _stub_server(fail=None):
    """A TTS server stand-in on a free port. `fail`: HTTP status to answer /synthesize with."""
    calls = []

    async def status(_):
        return web.json_response({"state": "ready"})

    async def synth(request):
        calls.append(await request.json())
        if fail:
            return web.Response(status=fail, text="boom")
        return web.Response(body=WAV, content_type="audio/wav")

    wa = web.Application()
    wa.add_routes([web.get("/status", status), web.post("/synthesize", synth)])
    runner = web.AppRunner(wa, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}", calls


def _server_cfg(url, **extra):
    return {"engine": "server", "server": {"url": url, "autostart": True, **extra}}


def test_configure_applies_the_finished_config():
    synth = Synthesizer({"engine": "dummy"})
    synth.configure({"engine": "sapi", "voices": {"azul": {"rate": 3}}, "team_profiles": {"azul": "p1"},
                     "sapi": {"voice": "Maria"}})
    assert synth.engine.name == "sapi"
    assert synth.voice_for("azul") == {"rate": 3, "profile": "p1"}
    assert synth._fallback_cfg == ({"voice": "Maria"} if sys.platform == "win32" else {})


def test_app_settings_override_voices_and_engine(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"tts": {"engine": "sapi", "voices": {"azul": {"rate": 5}}}}', encoding="utf-8")
    app = App({"tts": {"engine": "dummy", "voices": {"azul": {"rate": 1}}}}, Synthesizer({"engine": "dummy"}),
              settings_path=settings)
    assert app.tts.engine.name == "sapi"
    assert app.tts.voice_for("azul")["rate"] == 5


def test_team_profile_changes_the_voice_key():
    synth = Synthesizer({"engine": "dummy"})
    before = synth.voice_key("azul")
    synth.set_team_profile("azul", "goblin-1")
    assert synth.voice_key("azul") != before
    assert synth.voice_key("verde") == before.replace('"azul"', '"verde"')
    synth.set_team_profile("azul", None)
    assert synth.voice_key("azul") == before


def test_server_engine_synthesizes_over_http():
    async def run():
        runner, url, calls = await _stub_server()
        try:
            synth = Synthesizer(_server_cfg(url))
            synth.set_team_profile("azul", "goblin-1")
            assert await synth.synthesize("olá", "azul") == WAV
            assert calls == [{"text": "olá", "profile": "goblin-1"}]
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_server_engine_reports_http_errors_and_a_server_that_is_down():
    async def run():
        runner, url, _ = await _stub_server(fail=500)
        try:
            with pytest.raises(RuntimeError, match="boom"):
                await Synthesizer(_server_cfg(url)).synthesize("oi", None)
        finally:
            await runner.cleanup()
        with pytest.raises(RuntimeError, match="is down"):
            await Synthesizer(_server_cfg(url)).synthesize("oi", None)  # nothing listens there anymore

    asyncio.run(run())


def test_start_uses_a_server_that_is_already_running_and_close_releases_it(tmp_path):
    async def run():
        runner, url, _ = await _stub_server()
        synth = Synthesizer(_server_cfg(url), tmp_path)
        try:
            await synth.start()
            assert synth.service.mode == "external"
            assert (await synth.service.status())["server"] == {"state": "ready"}
        finally:
            await synth.close()
            await runner.cleanup()

    asyncio.run(run())


async def _call(app, assets_dir, method, path):
    """One request against the panel's web app, on a free port."""
    import aiohttp

    runner = web.AppRunner(make_web_app(app, assets_dir), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as s, s.request(method, f"http://127.0.0.1:{port}{path}") as r:
            return r.status, await r.text()
    finally:
        await runner.cleanup()


def test_service_routes_without_a_service_say_so(tmp_path):
    async def run():
        app = App({}, Synthesizer({"engine": "dummy"}))
        assert (await _call(app, tmp_path, "GET", "/api/tts-service"))[1] == '{"mode": "disabled"}'
        assert (await _call(app, tmp_path, "POST", "/api/tts-service/start"))[0] == 503

    asyncio.run(run())


def test_restarting_an_external_server_is_a_conflict(tmp_path):
    async def run():
        runner, url, _ = await _stub_server()
        synth = Synthesizer(_server_cfg(url), tmp_path)
        try:
            await synth.service.start()
            status, _ = await _call(App({}, synth), tmp_path / "assets", "POST", "/api/tts-service/restart")
            assert status == 409
        finally:
            await synth.close()
            await runner.cleanup()

    asyncio.run(run())

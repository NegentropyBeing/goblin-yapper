"""What the HTTP API tells the panel: messages travel as a key plus values, never as text in one language."""

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from goblin_yapper.app import App
from goblin_yapper.server import make_web_app
from goblin_yapper.tts import TTS


def _with_client(tmp_path, check):
    async def run():
        app = App({"teams": {"count": 2}}, TTS({"engine": "dummy"}))
        async with TestClient(TestServer(make_web_app(app, tmp_path))) as client:
            await check(client)

    asyncio.run(run())


def test_a_command_reply_carries_its_key_values_and_an_english_text(tmp_path):
    async def check(client):
        ok = await (await client.post("/api/command", json={"command": "open"})).json()
        assert (ok["ok"], ok["key"], ok["output"]) == (True, "msg.queue_open", "queue open")
        assert ok["state"]["queue_open"] is True
        bad = await (await client.post("/api/command", json={"command": "bogus"})).json()
        assert (bad["ok"], bad["key"], bad["params"]) == (False, "err.unknown_command", {"command": "bogus"})
        assert bad["output"] == "error: unknown command: bogus (type help)"

    _with_client(tmp_path, check)


def test_http_errors_are_a_key_and_values_too(tmp_path):
    async def check(client):
        r = await client.put("/api/assets/nope.png", data=b"x")
        body = await r.json()
        assert r.status == 400 and body["key"] == "http.bad_asset_name" and "goblin.png" in body["params"]["allowed"]
        r = await client.put("/api/assets/goblin.png", data=b"not a png")
        assert (await r.json())["key"] == "http.asset_not_image"
        r = await client.post("/api/command", data=b"{")
        assert r.status == 400 and (await r.json())["key"] == "http.bad_json"

    _with_client(tmp_path, check)

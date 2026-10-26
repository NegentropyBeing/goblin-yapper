"""What the HTTP API tells the panel: messages travel as a key plus values, never as text in one language."""

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from goblin_yapper.app import App
from goblin_yapper.server import make_web_app, retime_gif
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


def _gif(delays: list[int], local_colors: bool = False) -> bytes:
    """A tiny gif (1x1, global colors) with one frame per delay, in centiseconds."""
    out = b"GIF89a" + b"\x01\x00\x01\x00\x80\x00\x00" + b"\x00\x00\x00\xff\xff\xff"
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"  # loop forever
    for d in delays:
        out += b"\x21\xf9\x04\x00" + d.to_bytes(2, "little") + b"\x00\x00"
        out += b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00" + (b"\x80" + b"\x00" * 6 if local_colors else b"\x00")
        out += b"\x02\x02\x44\x01\x00"
    return out + b"\x3b"


def test_retiming_a_gif_rescales_every_frame_delay():
    def delays(data):
        return [int.from_bytes(data[i + 4:i + 6], "little") for i in range(len(data)) if data[i:i + 3] == b"\x21\xf9\x04"]

    src = _gif([10, 20, 0, 3], local_colors=True)
    assert delays(retime_gif(src, 2)) == [5, 10, 5, 2]  # an unset delay plays as 10; never under 2
    assert delays(retime_gif(src, 0.5)) == [20, 40, 20, 6]
    assert retime_gif(src, 1) == src
    assert len(retime_gif(src, 2)) == len(src)


def test_the_gif_is_served_at_the_asked_speed(tmp_path):
    (tmp_path / "goblin.gif").write_bytes(_gif([10]))

    async def check(client):
        r = await client.get("/assets/goblin.gif?speed=200")
        assert r.status == 200 and r.content_type == "image/gif"
        assert (await r.read()) == _gif([5])
        assert (await (await client.get("/assets/goblin.gif")).read()) == _gif([10])
        assert (await client.get("/assets/azul.gif")).status == 404

    _with_client(tmp_path, check)

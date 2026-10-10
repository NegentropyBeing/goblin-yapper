import asyncio
import json
import random

import pytest

from goblin_yapper.app import App, strip_emotes
from goblin_yapper.teams import QUEUE, SorterError, TeamSorter
from goblin_yapper.tts import TTS, wav_duration
from goblin_yapper.twitch import ChatMessage, parse_line
from goblin_yapper.voice import VoiceController


def sorter(n=4, people=0, open_=True):
    s = TeamSorter(n, rng=random.Random(1))
    s.queue_open = open_
    for i in range(people):
        s.join(f"user{i}")
    return s


def sizes(s):
    return sorted(len(m) for m in s.teams.values())


def test_join_closed_and_duplicates():
    s = sorter(open_=False)
    assert s.join("A") == "closed"
    s.queue_open = True
    assert s.join("A", "A_Display") == "queued"
    assert s.join("a") == "already"
    assert s.snapshot()["queue"] == [{"id": "a", "name": "A_Display"}]


def test_sort_is_balanced():
    s = sorter(4, 10)
    assert s.sort() == 10
    assert sizes(s) == [2, 2, 3, 3]
    assert s.queue == []


def test_late_joiner_goes_to_smallest_team():
    s = sorter(3, 5)
    s.sort()
    smallest = [t for t, m in s.teams.items() if len(m) == 1]
    assert s.join("late") in smallest
    assert sizes(s) == [2, 2, 2]


def test_late_joiner_queued_when_auto_assign_off():
    s = sorter(2, 2)
    s.auto_assign_late = False
    s.sort()
    assert s.join("late") == "queued"


def test_move_reset_resort_clear():
    s = sorter(2, 4)
    s.sort()
    with pytest.raises(SorterError):
        s.move("user0", "roxo")  # only azul/verde exist
    s.move("user0", QUEUE)
    assert s.where("user0") == QUEUE
    s.move("user0", "azul")
    assert s.team_of("user0") == "azul"
    s.return_all_to_queue()
    assert len(s.queue) == 4 and not s.sorted
    s.resort()
    assert sizes(s) == [2, 2]
    s.clear()
    assert s.queue == [] and sizes(s) == [0, 0]


def test_reduce_team_count_redistributes():
    s = sorter(4, 8)
    s.sort()
    s.set_team_count(2)
    assert list(s.teams) == ["azul", "verde"]
    assert sizes(s) == [4, 4]


def test_voice_same_team_and_other_person():
    s = sorter(2, 6)
    s.sort()
    v = VoiceController(s, random.Random(2))
    first = v.pick_random("azul")
    team = v.active_team
    assert team == "azul"
    for _ in range(10):
        prev = v.active
        nxt = v.pick_random()  # same team, different person
        assert v.active_team == team and nxt != prev
    v.stop()
    v.pick_random()  # remembers last team after stop
    assert v.active_team == team
    assert v.give("someone_else") == "someone_else"
    assert v.active_team is None


def test_voice_empty_team_errors():
    s = sorter(2, 0)
    with pytest.raises(SorterError):
        VoiceController(s).pick_random("azul")


def test_parse_privmsg():
    line = "@display-name=Fulano;emotes= :fulano!fulano@fulano.tmi.twitch.tv PRIVMSG #canal :olá mundo :)"
    tags, prefix, cmd, params = parse_line(line)
    assert cmd == "PRIVMSG" and params == ["#canal", "olá mundo :)"]
    assert tags["display-name"] == "Fulano" and prefix.startswith("fulano!")


def test_strip_emotes():
    assert strip_emotes("Kappa oi Kappa", "25:0-4,9-13").strip() == "oi"


def test_dummy_tts_produces_wav():
    wav = asyncio.run(TTS({"engine": "dummy"}).synthesize("olá goblin", "azul"))
    assert wav[:4] == b"RIFF" and wav_duration(wav) > 0.1


def test_app_flow():
    async def run():
        app = App({"teams": {"count": 2}}, TTS({"engine": "dummy"}))
        assert "fila aberta" in await app.command("open")
        for name in ("ana", "bia", "caio", "duda"):
            await app.on_chat(ChatMessage(name, name.title(), "!joinsort", {}))
        assert len(app.sorter.queue) == 4
        await app.command("sort")
        assert sizes(app.sorter) == [2, 2]
        out = await app.command("voice azul")
        speaker = app.voice.active
        assert "voz para" in out and app.voice.active_team == "azul"
        await app.on_chat(ChatMessage(speaker, speaker, "oi chat https://x.com", {}))
        await app.on_chat(ChatMessage(speaker, speaker, "!comando", {}))
        other = next(u for u in ("ana", "bia", "caio", "duda") if u != speaker)
        await app.on_chat(ChatMessage(other, other, "não sou eu", {}))
        assert app.speech_q.qsize() == 1
        utt = app.speech_q.get_nowait()
        assert utt.text == "oi chat" and utt.team == "azul"
        await app.command(f"remove {speaker}")
        assert app.voice.active is None
        assert (await app.command("bogus")).startswith("erro")

    asyncio.run(run())


def test_tint_config_and_command():
    async def run():
        app = App({"teams": {"tint_strength": 0.3, "tint": {"azul": {"color": "#000001"}, "verde": "#000002"}}},
                  TTS({"engine": "dummy"}))
        assert app.tints["azul"] == {"color": "#000001", "strength": 0.3}
        assert app.tints["verde"]["color"] == "#000002"
        assert "força 0.70" in await app.command("tint roxo #112233 0.7")
        assert app.state()["tints"]["roxo"] == {"color": "#112233", "strength": 0.7}
        await app.command("tint roxo off")
        assert app.tints["roxo"]["strength"] == 0
        assert (await app.command("tint roxo vermelho")).startswith("erro")
        assert (await app.command("tint laranja #112233")).startswith("erro")

    asyncio.run(run())


def test_channel_normalization():
    from goblin_yapper.app import normalize_channel

    for raw in ("negentropybeing", "#NegentropyBeing", "@negentropybeing", "https://www.twitch.tv/negentropybeing",
                "twitch.tv/negentropybeing/", "https://m.twitch.tv/negentropybeing?ref=x"):
        assert normalize_channel(raw) == "negentropybeing", raw

    async def run():
        app = App({}, TTS({"engine": "dummy"}))
        assert (await app.command("channel https://www.twitch.tv/negentropybeing")) == "chat: #negentropybeing"
        assert app.settings["twitch"]["channel"] == "negentropybeing"
        assert (await app.command("channel não-é-canal!")).startswith("erro")
        assert app.channel == "negentropybeing"  # unchanged after a bad name
        await app.command("channel off")

    asyncio.run(run())


def test_join_while_closed_sends_notice():
    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send_str(self, data):
            self.sent.append(json.loads(data))

    async def run():
        app = App({}, TTS({"engine": "dummy"}))
        ws = FakeWS()
        app.clients.add(ws)
        await app.on_chat(ChatMessage("ana", "Ana", "!joinsort", {}))
        assert app.sorter.queue == []
        assert ws.sent == [{"type": "notice", "text": "Ana tentou entrar, mas a fila está fechada"}]
        await app.command("open")
        await app.on_chat(ChatMessage("ana", "Ana", "!JoinSorting", {}))
        assert app.sorter.queue == ["ana"]

    asyncio.run(run())


def test_long_messages_are_not_cut():
    async def run():
        app = App({}, TTS({"engine": "dummy"}))
        long_text = "goblin " * 100
        assert await app.say("ana", long_text)
        assert app.speech_q.get_nowait().text == long_text.strip()

    asyncio.run(run())


def test_teamvoice_and_engine_commands(tmp_path):
    async def run():
        settings = tmp_path / "settings.json"
        app = App({}, TTS({"engine": "dummy"}), settings_path=settings)
        assert (await app.command("teamvoice azul goblin-azul-1")) == "voz de azul: goblin-azul-1"
        await app.command("teamvoice default narrador-2")
        assert app.tts.voice_for("azul")["profile"] == "goblin-azul-1"
        assert app.tts.voice_for("verde")["profile"] == "narrador-2"  # falls back to default
        await app.command("teamvoice azul none")
        assert "azul" not in app.tts.team_profiles
        assert json.loads(settings.read_text(encoding="utf-8"))["tts"]["team_profiles"] == {"default": "narrador-2"}
        assert (await app.command("teamvoice laranja x")).startswith("erro")

        assert (await app.command("engine sapi")) == "TTS: sapi"
        assert app.tts.engine.name == "sapi"
        assert (await app.command("engine nope")).startswith("erro")
        assert app.tts.engine.name == "sapi"  # unchanged after a bad name

        # saved team voices come back on restart
        again = App({}, TTS({"engine": "dummy"}), settings_path=settings)
        assert again.tts.team_profiles == {"default": "narrador-2"}

    asyncio.run(run())


def _two_team_app(multi):
    app = App({"teams": {"count": 2}, "voice": {"multi": multi}}, TTS({"engine": "dummy"}))
    app.sorter.queue_open = True
    for u in ("a1", "a2", "v1", "v2"):
        app.sorter.join(u)
    app.sorter.queue.clear()
    app.sorter.teams = {"azul": ["a1", "a2"], "verde": ["v1", "v2"]}
    app.sorter.sorted = True
    return app


def test_single_mode_one_speaker_total():
    async def run():
        app = _two_team_app(multi=False)
        await app.command("voice azul")
        await app.command("voice verde")
        assert [t for _, t in app.voice.speakers()] == ["verde"]

    asyncio.run(run())


def test_multi_mode_one_speaker_per_team():
    async def run():
        app = _two_team_app(multi=True)
        await app.command("voice azul")
        await app.command("voice verde")
        speakers = dict((t, u) for u, t in app.voice.speakers())
        assert set(speakers) == {"azul", "verde"}
        assert [s["team"] for s in app.state()["speakers"]] == ["azul", "verde"]

        # both speakers are read; a non-speaker isn't
        await app.on_chat(ChatMessage(speakers["azul"], "A", "oi do azul", {}))
        await app.on_chat(ChatMessage(speakers["verde"], "V", "oi do verde", {}))
        other = next(u for u in ("a1", "a2") if u != speakers["azul"])
        await app.on_chat(ChatMessage(other, "X", "não falo", {}))
        assert app.speech_q.qsize() == 2

        # next on azul replaces only azul's speaker
        await app.command("next azul")
        assert app.voice.speaker_of("azul") == other
        assert app.voice.speaker_of("verde") == speakers["verde"]
        # the old azul speaker's queued line was dropped, verde's kept
        assert [u.user for u in app.speech_q._queue] == [speakers["verde"]]

        # stop one team, then everyone
        assert (await app.command("stop verde")).startswith("voz retirada de")
        assert [t for _, t in app.voice.speakers()] == ["azul"]
        await app.command("stop")
        assert app.voice.speakers() == [] and app.speech_q.qsize() == 0

    asyncio.run(run())


def test_multivoice_toggle_and_per_speaker_queue_limit(tmp_path):
    async def run():
        settings = tmp_path / "settings.json"
        app = App({"teams": {"count": 2}, "tts": {"max_queue": 2}}, TTS({"engine": "dummy"}), settings_path=settings)
        app.sorter.teams = {"azul": ["a1"], "verde": ["v1"]}
        await app.command("multivoice on")
        await app.command("give a1")
        await app.command("give v1")
        for i in range(4):
            await app.on_chat(ChatMessage("a1", "A", f"azul {i}", {}))
        await app.on_chat(ChatMessage("v1", "V", "verde ainda fala", {}))
        # a1 is capped at 2 queued lines, v1 still gets in
        assert [u.user for u in app.speech_q._queue] == ["a1", "a1", "v1"]
        assert json.loads(settings.read_text(encoding="utf-8"))["voice"]["multi"] is True

        await app.command("multivoice off")  # keeps only the most recent speaker
        assert app.voice.users == ["v1"]
        assert [u.user for u in app.speech_q._queue] == ["v1"]
        assert (await app.command("multivoice talvez")).startswith("erro")

    asyncio.run(run())


class Sock:
    """Stands in for a websocket: records what the server sent it."""

    def __init__(self):
        self.sent = []

    async def send_str(self, data):
        self.sent.append(json.loads(data))


def _app_with_overlays(**overlays):
    """overlays: name -> (pinned team | None, audio on?). Also connects a panel (no hello)."""
    app = App({"teams": {"count": 2}}, TTS({"engine": "dummy"}))
    socks = {"panel": Sock()}
    app.clients.add(socks["panel"])
    for name, (team, audio) in overlays.items():
        socks[name] = Sock()
        app.clients.add(socks[name])
        app.overlays[socks[name]] = {"team": team, "audio": audio}
    return app, socks


def test_pick_player_routing():
    app, s = _app_with_overlays(main=(None, True), azul=("azul", True), verde_muted=("verde", False))
    assert app.pick_player("azul") is s["azul"]        # the team's own source
    assert app.pick_player("verde") is s["main"]       # its source is muted -> main
    assert app.pick_player("roxo") is s["main"]        # no source of its own -> main
    assert app.pick_player(None) is s["main"]          # chatter without a team -> main
    app.clients.discard(s["main"])                     # main closed
    assert app.pick_player("azul") is s["azul"]
    assert app.pick_player("verde") is None and app.pick_player(None) is None
    assert app.state()["overlays"] == [{"team": "azul", "audio": True}, {"team": "verde", "audio": False}]


def _run_one_line(app, team):
    """Queue one test line, let the worker send it, acknowledge it, return when idle."""
    async def run():
        worker = asyncio.create_task(app.speech_worker())
        await app.say("teste", "oi", team=team)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if app.speaking:
                app.on_audio_ended(app.speaking.id)
                break
        await asyncio.sleep(0.05)
        worker.cancel()

    asyncio.run(run())


def test_only_the_team_overlay_is_told_to_play():
    app, s = _app_with_overlays(main=(None, True), azul=("azul", True), verde=("verde", True))
    _run_one_line(app, "azul")
    plays = {name: [m["play"] for m in sock.sent if m["type"] == "speak"] for name, sock in s.items()}
    assert plays == {"panel": [False], "main": [False], "azul": [True], "verde": [False]}
    # everyone still hears about the line (to animate) and its end
    assert all(any(m["type"] == "idle" for m in sock.sent) for sock in s.values())
    assert not any(m["type"] == "notice" for m in s["panel"].sent)


def test_no_audio_overlay_gives_a_notice():
    app, s = _app_with_overlays(azul=("azul", True))
    _run_one_line(app, "verde")  # verde has no source and there is no main one
    assert [m["play"] for m in s["azul"].sent if m["type"] == "speak"] == [False]
    assert any(m["type"] == "notice" and "verde" in m["text"] for m in s["panel"].sent)


def test_panel_is_the_last_resort_player():
    app, s = _app_with_overlays(azul=("azul", True))
    app.overlays[s["panel"]] = {"role": "panel", "team": None, "audio": True}
    assert app.pick_player("azul") is s["azul"]    # an overlay always wins
    assert app.pick_player("verde") is s["panel"]  # no overlay for verde, no main -> the panel plays it
    assert app.state()["overlays"] == [{"team": "azul", "audio": True}]  # panels aren't listed as OBS sources
    _run_one_line(app, "verde")
    assert [m["play"] for m in s["panel"].sent if m["type"] == "speak"] == [True]
    assert not any(m["type"] == "notice" for m in s["panel"].sent)


def test_testvoice_uses_the_team_phrase_and_profile():
    async def run():
        app = App({"teams": {"count": 2}, "tts": {"test_phrase": "Oi, time {team}!"}}, TTS({"engine": "dummy"}))
        await app.command("teamvoice verde goblin-verde-1")
        assert (await app.command("testvoice verde")) == "testando a voz do time verde"
        utt = app.speech_q.get_nowait()
        assert (utt.text, utt.team, utt.chat) == ("Oi, time verde!", "verde", False)
        assert app.tts.voice_for(utt.team)["profile"] == "goblin-verde-1"
        assert (await app.command("testvoice roxo")).startswith("erro")  # only 2 teams active
        assert (await app.command("testvoice")).startswith("erro")

    asyncio.run(run())

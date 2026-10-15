import asyncio
import json
import random

import pytest

from goblin_yapper.app import CHORUS_TEXT, CHORUS_TRIGGER, App, strip_emotes
from goblin_yapper.i18n import Message
from goblin_yapper.teams import QUEUE, SorterError, TeamSorter
from goblin_yapper.tts import TTS, wav_duration
from goblin_yapper.twitch import ChatMessage, parse_line
from goblin_yapper.voice import VoiceController

from .fakes import Sock, StuckEngine


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
        assert (await app.command("open")).key == "msg.queue_open"
        for name in ("ana", "bia", "caio", "duda"):
            await app.on_chat(ChatMessage(name, name.title(), "!joinsort", {}))
        assert len(app.sorter.queue) == 4
        await app.command("sort")
        assert sizes(app.sorter) == [2, 2]
        out = await app.command("voice azul")
        speaker = app.voice.active
        assert out.key == "msg.voice_to" and app.voice.active_team == "azul"
        await app.on_chat(ChatMessage(speaker, speaker, "oi chat https://x.com", {}))
        await app.on_chat(ChatMessage(speaker, speaker, "!comando", {}))
        other = next(u for u in ("ana", "bia", "caio", "duda") if u != speaker)
        await app.on_chat(ChatMessage(other, other, "não sou eu", {}))
        assert app.speech.queue.qsize() == 1
        utt = app.speech.queue.get_nowait()
        assert utt.text == "oi chat" and utt.team == "azul"
        await app.command(f"remove {speaker}")
        assert app.voice.active is None
        assert not (await app.command("bogus")).ok

    asyncio.run(run())


def test_tint_config_and_command():
    async def run():
        app = App({"teams": {"tint_strength": 0.3, "tint": {"azul": {"color": "#000001"}, "verde": "#000002"}}},
                  TTS({"engine": "dummy"}))
        assert app.tints["azul"] == {"color": "#000001", "strength": 0.3}
        assert app.tints["verde"]["color"] == "#000002"
        tinted = await app.command("tint roxo #112233 0.7")
        assert (tinted.key, tinted.params["strength"]) == ("msg.tint", "0.70")
        assert app.state()["tints"]["roxo"] == {"color": "#112233", "strength": 0.7}
        await app.command("tint roxo off")
        assert app.tints["roxo"]["strength"] == 0
        assert not (await app.command("tint roxo vermelho")).ok
        assert not (await app.command("tint laranja #112233")).ok

    asyncio.run(run())


def test_channel_normalization():
    from goblin_yapper.app import normalize_channel

    for raw in ("negentropybeing", "#NegentropyBeing", "@negentropybeing", "https://www.twitch.tv/negentropybeing",
                "twitch.tv/negentropybeing/", "https://m.twitch.tv/negentropybeing?ref=x"):
        assert normalize_channel(raw) == "negentropybeing", raw

    async def run():
        app = App({}, TTS({"engine": "dummy"}))
        chat = await app.command("channel https://www.twitch.tv/negentropybeing")
        assert (chat.key, chat.params) == ("msg.chat_on", {"channel": "negentropybeing"})
        assert app.config.settings["twitch"]["channel"] == "negentropybeing"
        assert not (await app.command("channel não-é-canal!")).ok
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
        assert ws.sent == [{"type": "notice", "key": "notice.queue_closed", "params": {"user": "Ana"},
                            "text": "Ana tried to join, but the queue is closed"}]
        await app.command("open")
        await app.on_chat(ChatMessage("ana", "Ana", "!JoinSorting", {}))
        assert app.sorter.queue == ["ana"]

    asyncio.run(run())


def test_long_messages_are_not_cut():
    async def run():
        app = App({}, TTS({"engine": "dummy"}))
        long_text = "goblin " * 100
        assert await app.say("ana", long_text)
        assert app.speech.queue.get_nowait().text == long_text.strip()

    asyncio.run(run())


def test_teamvoice_and_engine_commands(tmp_path):
    async def run():
        settings = tmp_path / "settings.json"
        app = App({}, TTS({"engine": "dummy"}), settings_path=settings)
        voice = await app.command("teamvoice azul goblin-azul-1")
        assert (voice.key, voice.params) == ("msg.team_voice", {"team": "azul", "profile": "goblin-azul-1"})
        await app.command("teamvoice default narrador-2")
        assert app.tts.voice_for("azul")["profile"] == "goblin-azul-1"
        assert app.tts.voice_for("verde")["profile"] == "narrador-2"  # falls back to default
        await app.command("teamvoice azul none")
        assert "azul" not in app.tts.team_profiles
        assert json.loads(settings.read_text(encoding="utf-8"))["tts"]["team_profiles"] == {"default": "narrador-2"}
        assert not (await app.command("teamvoice laranja x")).ok

        engine = await app.command("engine sapi")
        assert (engine.key, engine.params) == ("msg.engine", {"engine": "sapi"})
        assert app.tts.engine.name == "sapi"
        assert not (await app.command("engine nope")).ok
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
        assert app.speech.queue.qsize() == 2

        # next on azul replaces only azul's speaker
        await app.command("next azul")
        assert app.voice.speaker_of("azul") == other
        assert app.voice.speaker_of("verde") == speakers["verde"]
        # the old azul speaker's queued line was dropped, verde's kept
        assert [u.user for u in app.speech.queue._queue] == [speakers["verde"]]

        # stop one team, then everyone
        assert (await app.command("stop verde")).key == "msg.voice_removed"
        assert [t for _, t in app.voice.speakers()] == ["azul"]
        await app.command("stop")
        assert app.voice.speakers() == [] and app.speech.queue.qsize() == 0

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
        assert [u.user for u in app.speech.queue._queue] == ["a1", "a1", "v1"]
        assert json.loads(settings.read_text(encoding="utf-8"))["voice"]["multi"] is True

        await app.command("multivoice off")  # keeps only the most recent speaker
        assert app.voice.users == ["v1"]
        assert [u.user for u in app.speech.queue._queue] == ["v1"]
        assert not (await app.command("multivoice talvez")).ok

    asyncio.run(run())


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
        worker = asyncio.create_task(app.speech.run())
        await app.say("teste", "oi", team=team)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if app.speech.speaking:
                app.on_audio_ended(app.speech.speaking.id)
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
    assert any(m["type"] == "notice" and (m["key"], m["params"]) == ("notice.no_overlay_team", {"team": "verde"})
               for m in s["panel"].sent)


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
        assert (await app.command("testvoice verde")).key == "msg.testvoice"
        utt = app.speech.queue.get_nowait()
        assert (utt.text, utt.team, utt.chat) == ("Oi, time verde!", "verde", False)
        assert app.tts.voice_for(utt.team)["profile"] == "goblin-verde-1"
        assert not (await app.command("testvoice roxo")).ok  # only 2 teams active
        assert not (await app.command("testvoice")).ok

    asyncio.run(run())


def _game(cfg=None, people=("ana", "bia", "caio", "duda")):
    """App with a fake clock (app.clock[0], in seconds), a connected chat and an open queue."""
    app = App({"teams": {"count": 2}, **(cfg or {})}, TTS({"engine": "dummy"}))
    app.clock = [0.0]
    app.now = lambda: app.clock[0]
    app.chat_status = "connected"
    app.sorter.queue_open = True
    return app, people


def test_inactive_chatters_are_removed_after_the_limit(tmp_path):
    async def run():
        app, people = _game()
        app.config.settings_path = tmp_path / "settings.json"
        for name in people:
            await app.on_chat(ChatMessage(name, name.title(), "!joinsort", {}))
        await app.tick()
        app.clock[0] = 9 * 60
        await app.on_chat(ChatMessage("ana", "Ana", "ainda estou aqui", {}))
        app.clock[0] = 11 * 60
        await app.tick()
        assert len(app.sorter.queue) == 4  # off by default
        assert (await app.command("autoremove on 10")).params == {"minutes": "10"}
        assert app.state()["auto_remove"] == {"on": True, "minutes": 10.0}
        saved = json.loads(app.config.settings_path.read_text(encoding="utf-8"))["teams"]
        assert saved == {"inactive_remove": True, "inactive_minutes": 10.0}
        app.chat_status = "reconnecting"
        await app.tick()
        assert len(app.sorter.queue) == 4  # the chat is down: nobody can be heard, nobody is removed
        app.chat_status = "connected"
        await app.tick()
        assert app.sorter.queue == ["ana"]  # only the one who wrote in the last 10 minutes stays
        assert not (await app.command("autoremove on zero")).ok
        assert not (await app.command("autoremove")).ok
        assert (await app.command("autoremove off")).key == "msg.autoremove_off"
        app.clock[0] = 60 * 60
        await app.tick()
        assert app.sorter.queue == ["ana"]

    asyncio.run(run())


def test_reconnecting_restarts_the_inactivity_clocks():
    async def run():
        app, _ = _game({"teams": {"count": 2, "inactive_remove": True, "inactive_minutes": 5}})
        await app.command("add ana")
        await app.tick()
        app.clock[0] = 20 * 60
        app.last_seen.clear()  # what _set_chat_status("connected") does
        await app.tick()
        assert app.sorter.queue == ["ana"]
        app.clock[0] = 26 * 60
        await app.tick()
        assert app.sorter.queue == []

    asyncio.run(run())


def test_voice_rotates_inside_the_team_after_the_limit():
    async def run():
        app, people = _game()
        for name in people:
            await app.command(f"add {name}")
        await app.command("sort")
        await app.command("voice azul")
        first = app.voice.active
        await app.tick()
        app.clock[0] = 6 * 60
        await app.tick()
        assert app.voice.active == first  # off by default
        assert (await app.command("autorotate on 5")).params == {"minutes": "5"}
        app.speech.speaking = type("U", (), {"user": first, "id": 1, "team": "azul"})()  # their line is playing: wait
        await app.tick()
        assert app.voice.active == first
        app.speech.speaking = None
        await app.tick()
        second = app.voice.active
        assert second != first and app.voice.active_team == "azul"
        app.clock[0] = 10 * 60
        await app.tick()
        assert app.voice.active == second  # the new speaker's own 5 minutes started at the hand-over
        app.clock[0] = 11 * 60 + 1
        await app.tick()
        assert app.voice.active == first

    asyncio.run(run())


def test_rotation_in_multi_mode_and_idle_speaker_is_replaced():
    async def run():
        app, people = _game({"voice": {"multi": True, "rotate": True, "rotate_minutes": 5},
                             "teams": {"count": 2, "inactive_remove": True, "inactive_minutes": 3}})
        for name in people:
            await app.command(f"add {name}")
        await app.command("sort")
        await app.command("voice azul")
        await app.command("voice verde")
        azul, verde = app.voice.speaker_of("azul"), app.voice.speaker_of("verde")
        await app.tick()
        app.clock[0] = 4 * 60
        for name in people:
            if name != azul:  # everyone but azul's speaker keeps chatting
                await app.on_chat(ChatMessage(name, name, "oi", {}))
        await app.tick()
        # azul's speaker went silent: out of the game, and the voice went to their teammate
        assert app.sorter.where(azul) is None
        assert app.voice.speaker_of("azul") not in (None, azul)
        assert app.voice.speaker_of("verde") == verde
        app.clock[0] = 5 * 60 + 1
        for name in people:
            await app.on_chat(ChatMessage(name, name, "oi", {}))
        await app.tick()
        assert app.voice.speaker_of("verde") != verde  # verde's 5 minutes are over
        assert len(app.voice.users) == 2

    asyncio.run(run())


async def _until(cond, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


@pytest.mark.parametrize("reentrant", [True, False])
def test_skip_drops_the_line_stuck_in_generation_and_the_queue_goes_on(reentrant):
    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send_str(self, data):
            self.sent.append(json.loads(data))

    async def run():
        app = App({}, TTS({"engine": "dummy"}))
        engine = app.tts.engine = StuckEngine(reentrant)
        ws = FakeWS()
        app.clients.add(ws)
        worker = asyncio.create_task(app.speech.run())
        assert not (await app.command("skip")).ok  # nothing in progress
        await app.say("ana", "travada")
        await app.say("bia", "segunda")
        await _until(lambda: app.speech.generating is not None and engine.calls)
        assert app.state()["generating"] == {"user": "ana", "team": None}
        assert (await app.command("skip")).key == "msg.skipped_generating"
        spoken = lambda: [m["text"] for m in ws.sent if m["type"] == "speak"]  # noqa: E731
        if reentrant:
            await _until(lambda: spoken() == ["segunda"])  # went on although the first call is still hanging
            assert not engine.release.is_set()
        else:
            await asyncio.sleep(0.2)
            assert spoken() == [] and engine.calls == ["travada"]  # this engine can't take a second call yet
            engine.release.set()
            await _until(lambda: spoken() == ["segunda"])
        # skipping a line that is playing ends it and tells the players to stop
        speak = next(m for m in ws.sent if m["type"] == "speak")
        assert (await app.command("skip")).key == "msg.skipped"
        await _until(lambda: app.speech.speaking is None)
        assert {"type": "stop", "id": speak["id"]} in ws.sent
        engine.release.set()
        worker.cancel()

    asyncio.run(run())


def test_stop_also_frees_a_generation_in_progress():
    async def run():
        app = App({}, TTS({"engine": "dummy"}))
        engine = app.tts.engine = StuckEngine(True)
        worker = asyncio.create_task(app.speech.run())
        await app.say("ana", "travada")
        await _until(lambda: app.speech.generating is not None and engine.calls)
        await app.command("stop")
        await _until(lambda: app.speech.generating is None)
        engine.release.set()
        worker.cancel()

    asyncio.run(run())


def test_hideidle_toggle_is_saved_and_sent_to_overlays(tmp_path):
    async def run():
        settings = tmp_path / "settings.json"
        app = App({"teams": {"count": 2}}, TTS({"engine": "dummy"}), settings_path=settings)
        assert app.state()["hide_idle"] is False  # off by default
        assert not not (await app.command("hideidle on")).ok
        assert app.state()["hide_idle"] is True
        assert json.loads(settings.read_text(encoding="utf-8"))["overlay"] == {"hide_idle": True}
        # kept on the next start
        assert App({}, TTS({"engine": "dummy"}), settings_path=settings).state()["hide_idle"] is True
        await app.command("hideidle off")
        assert app.state()["hide_idle"] is False
        assert not (await app.command("hideidle")).ok

    asyncio.run(run())


def test_chorus_every_team_voice_says_the_phrase_together():
    async def run():
        app, s = _app_with_overlays(main=(None, True), azul=("azul", True))
        calls = []
        synth = app.tts.engine.synthesize
        app.tts.engine.synthesize = lambda text, voice: calls.append(voice.get("profile")) or synth(text, voice)
        worker = asyncio.create_task(app.speech.run())
        speaks = lambda name: [m for m in s[name].sent if m["type"] == "speak"]

        # someone else sending the glyph (even with the voice) doesn't start it
        await app.on_chat(ChatMessage("outro", "Outro", CHORUS_TRIGGER, {}))
        assert app.speech.queue.empty()

        # the one chatter does, without being in the game
        await app.on_chat(ChatMessage("NegentropyBeing", "NegentropyBeing", CHORUS_TRIGGER, {}))
        await _until(lambda: len(app.speech.playing) == 2)
        await asyncio.sleep(0.02)
        assert len(calls) == 2  # one clip per team, even with the same voice settings
        lines = speaks("panel")
        assert [m["team"] for m in lines] == ["azul", "verde"] and len({m["id"] for m in lines}) == 2
        assert all(m["text"] == CHORUS_TEXT and m["id"] in app.speech.audio for m in lines)
        # each team's clip goes to its own source, or to the main one
        assert [m["play"] for m in speaks("azul")] == [True, False]
        assert [m["play"] for m in speaks("main")] == [False, True]
        # the line is over only when every player has finished
        app.on_audio_ended(lines[0]["id"])
        await asyncio.sleep(0.03)
        assert app.speech.speaking is not None
        app.on_audio_ended(lines[1]["id"])
        await _until(lambda: app.speech.speaking is None)
        await asyncio.sleep(0.02)
        assert [m["id"] for m in s["panel"].sent if m["type"] == "idle"] == [m["id"] for m in lines]
        assert not app.speech.audio

        # again: the clips are reused, and skip cuts all of them
        await app.on_chat(ChatMessage("negentropybeing", "NegentropyBeing", CHORUS_TRIGGER, {}))
        await _until(lambda: len(app.speech.playing) == 2)
        assert len(calls) == 2  # one clip per team, even with the same voice settings
        ids = [u.id for u in app.speech.playing]
        assert not not (await app.command("skip")).ok
        await _until(lambda: app.speech.speaking is None)
        assert [m["id"] for m in s["panel"].sent if m["type"] == "stop"] == ids
        worker.cancel()

    asyncio.run(run())


def test_voice_reports_who_lost_it_from_every_mutating_call():
    v = VoiceController(sorter(2, 6), random.Random(1))
    v.sorter.sort()
    first = v.pick_random("any")
    assert v.take_lost() == set()
    second = v.give("alguem")  # single mode: giving the voice takes it from the first speaker
    assert v.take_lost() == {first}
    assert v.take_lost() == set()  # cleared once taken
    v.prune(lambda u: u != second)
    assert v.take_lost() == {second}
    v.give("x")
    v.stop()
    assert v.take_lost() == {"x"}


def test_voice_picking_the_same_speaker_again_is_not_a_loss_and_multi_off_reports_the_dropped():
    s = sorter(2, 2)  # one chatter per team: the pick can only land on the same person
    s.sort()
    v = VoiceController(s, random.Random(1), multi=True)
    a, b = v.pick_random("azul"), v.pick_random("verde")
    v.take_lost()
    assert v.pick_random("azul") == a and v.take_lost() == set()
    v.set_multi(False)
    assert v.users == [a] and v.take_lost() == {b}
    v.give(b)
    assert v.take_lost() == {a}


def test_interface_language_is_validated_stored_and_survives_a_restart(tmp_path):
    async def run():
        path = tmp_path / "settings.json"
        app = App({}, TTS({"engine": "dummy"}), path)
        assert app.state()["language"] is None  # no choice yet: the panel follows the system
        await app.command("language pt-BR")
        assert app.state()["language"] == "pt-BR"
        await app.command("language klingon")
        assert app.state()["language"] == "pt-BR"  # a language we have no catalog for is refused
        assert json.loads(path.read_text(encoding="utf-8"))["ui"]["language"] == "pt-BR"
        await app.command("language en")
        assert App({}, TTS({"engine": "dummy"}), path).state()["language"] == "en"

    asyncio.run(run())


def test_commands_answer_with_a_key_and_values_never_with_text():
    async def run():
        app = App({"teams": {"count": 2}}, TTS({"engine": "dummy"}))
        for line, key, params in [
            ("tint laranja #112233", "err.unknown_team", {"team": "laranja"}),
            ("teams x", "err.usage", {"usage": "teams <1-4>"}),
            ("bogus", "err.unknown_command", {"command": "bogus"}),
            ("remove ninguem", "err.not_in_game", {"user": "ninguem"}),
            ("language klingon", "err.usage", {"usage": "language <en|pt-BR>"}),
        ]:
            reply = await app.command(line)
            assert (reply.key, reply.params, reply.ok) == (key, params, False), line

    asyncio.run(run())


def test_a_reply_renders_in_english_for_the_console_and_the_api():
    assert str(Message("msg.queue_open")) == "queue open"
    assert str(Message("err.unknown_team", {"team": "laranja"}, ok=False)) == "error: unknown team: laranja"
    assert str(Message("msg.tint", {"team": "azul", "color": "#fff", "strength": "0.70"})) == "azul tint: #fff strength 0.70"
    assert str(Message("no.such.key")) == "no.such.key"

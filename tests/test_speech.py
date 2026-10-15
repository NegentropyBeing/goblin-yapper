import asyncio

from goblin_yapper.speech import SpeechSession

from .fakes import FakeRoster, FakeStage, FakeSynth


def _session(**kw):
    stage, roster, synth = FakeStage(**kw), FakeRoster(), FakeSynth()
    return SpeechSession(synth, stage, roster, {"max_queue": 2}), stage, roster, synth


async def _until(cond, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timeout")


def test_a_line_is_generated_announced_played_and_cleaned_up():
    async def run():
        s, stage, _, synth = _session()
        worker = asyncio.create_task(s.run())
        assert await s.say("Ana", "olá https://x.com mundo", "ana")
        await _until(lambda: s.speaking is not None)
        speak = next(m for m in stage.sent if m["type"] == "speak")
        assert speak["text"] == "olá  mundo" and speak["team"] == "azul" and speak["play"] is True
        assert s.speaking.id in s.audio
        s.on_audio_ended(s.speaking.id)
        await _until(lambda: s.speaking is None)
        assert not s.audio and stage.sent[-1] == {"type": "idle", "id": speak["id"]}
        worker.cancel()

    asyncio.run(run())


def test_the_queue_limit_is_per_speaker():
    async def run():
        s, *_ = _session()
        assert await s.say("Ana", "um", "ana") and await s.say("Ana", "dois", "ana")
        assert not await s.say("Ana", "três", "ana")
        assert await s.say("Bia", "outro", "bia")

    asyncio.run(run())


def test_a_line_without_a_player_still_animates_for_the_clip_length_and_says_so():
    async def run():
        s, stage, *_ = _session(with_player=False)
        worker = asyncio.create_task(s.run())
        await s.say("Ana", "oi", "ana")
        await _until(lambda: any(m["type"] == "notice" for m in stage.sent))
        await _until(lambda: s.speaking is None and any(m["type"] == "idle" for m in stage.sent))
        worker.cancel()

    asyncio.run(run())


def test_a_failing_tts_reports_and_the_next_line_goes_on():
    async def run():
        s, stage, _, synth = _session()
        worker = asyncio.create_task(s.run())
        synth.fail = "sem GPU"
        await s.say("Ana", "primeira", "ana")
        await _until(lambda: any(m.get("key") == "notice.tts_failed" and m["params"] == {"error": "sem GPU"} for m in stage.sent))
        synth.fail = None
        await s.say("Ana", "segunda", "ana")
        await _until(lambda: s.speaking is not None)
        assert s.speaking.text == "segunda"
        worker.cancel()

    asyncio.run(run())


def test_a_chorus_waits_for_every_player_to_report_the_end():
    async def run():
        s, stage, *_ = _session()
        worker = asyncio.create_task(s.run())
        await s.say("Ana", "juntos", "ana", chorus=True)
        await _until(lambda: len(s.playing) == 2)
        first, second = [u.id for u in s.playing]
        s.on_audio_ended(first)
        await asyncio.sleep(0.05)
        assert s.speaking is not None  # one team still playing
        s.on_audio_ended(second)
        await _until(lambda: s.speaking is None)
        worker.cancel()

    asyncio.run(run())


def test_a_session_survives_a_broadcast_that_fails_mid_playback():
    async def run():
        s, stage, *_ = _session()
        worker = asyncio.create_task(s.run())
        stage.fail_on = "idle"
        await s.say("Ana", "quebra", "ana")
        await _until(lambda: s.speaking is not None)
        s.on_audio_ended(s.speaking.id)
        await asyncio.sleep(0.1)
        stage.fail_on = None
        await s.say("Ana", "depois", "ana")
        await _until(lambda: s.speaking is not None and s.speaking.text == "depois", timeout=2)
        worker.cancel()

    asyncio.run(run())

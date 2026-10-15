"""Stand-ins shared by the tests."""

import json


class Sock:
    """Stands in for a websocket: records what the server sent it."""

    def __init__(self):
        self.sent = []

    async def send_str(self, data):
        self.sent.append(json.loads(data))


class StuckEngine:
    """First call hangs until released; later calls answer at once."""
    name = "stuck"

    def __init__(self, reentrant):
        import threading

        self.reentrant = reentrant
        self.release = threading.Event()
        self.calls = []

    def synthesize(self, text, voice):
        from goblin_yapper.tts import DummyEngine

        self.calls.append(text)
        if len(self.calls) == 1:
            self.release.wait(10)
        return DummyEngine({}).synthesize(text, voice)


class FakeStage:
    """The overlays side of the speech session: records what was sent, plays on one fake client."""

    def __init__(self, with_player=True):
        self.ws = Sock()
        self.clients = {self.ws}
        self.with_player = with_player
        self.sent = []
        self.fail_on = None  # message type whose broadcast should raise

    def state(self):
        return {"type": "state"}

    async def broadcast(self, msg):
        if msg.get("type") == self.fail_on:
            raise RuntimeError("broadcast failed")
        self.sent.append(msg)

    async def send(self, ws, msg):
        self.sent.append(msg)

    def pick_player(self, team):
        return self.ws if self.with_player else None


class FakeRoster:
    def __init__(self, speakers=("ana",), teams=("azul", "verde")):
        self.speakers, self._teams = set(speakers), list(teams)

    def is_speaker(self, user):
        return user in self.speakers

    def team_of(self, login):
        return self._teams[0] if login in self.speakers else None

    def teams(self):
        return self._teams


class FakeSynth:
    """Answers every line with a short clip; `fail` makes it raise."""

    def __init__(self):
        from goblin_yapper.tts import DummyEngine

        self.wav = DummyEngine({}).synthesize("oi", {})
        self.fail = None
        self.calls = []

    def voice_key(self, team):
        return f"voice:{team}"

    async def synthesize(self, text, team):
        self.calls.append((text, team))
        if self.fail:
            raise RuntimeError(self.fail)
        return self.wav

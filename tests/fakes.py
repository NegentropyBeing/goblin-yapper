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

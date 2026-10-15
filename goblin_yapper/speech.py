"""The speech session: the queue of lines to say and the pipeline that voices them one at a time.

Interface: say / skip / interrupt / on_audio_ended, run() (the worker), and the read-only state
`generating`, `speaking`, `playing`, `audio` (the clips the web app serves at /audio/<id>.wav).

It talks to the rest of the app through two ports:
  stage   - the overlays/panel: `clients`, `state()`, `broadcast(msg)`, `send(ws, msg)`, `pick_player(team)`
  roster  - who may speak: `is_speaker(user)`, `team_of(login)`, `teams()`
and to the TTS through a synthesizer: `synthesize(text, team)`, `voice_key(team)`.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from collections import Counter
from dataclasses import dataclass, replace

from .i18n import Message, notice
from .teams import SorterError
from .tts import wav_duration

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)


@dataclass
class Utterance:
    id: int
    user: str
    display: str
    team: str | None
    text: str
    gen: int
    chat: bool = False  # from a speaker's chat message (dropped if they lose the voice)
    chorus: bool = False  # said by every team's voice at the same time


class SpeechSession:
    def __init__(self, synth, stage, roster, tts_cfg: dict):
        self.synth, self.stage, self.roster, self.tts_cfg = synth, stage, roster, tts_cfg
        self.audio: dict[int, bytes] = {}  # utterance id -> wav, served at /audio/<id>.wav
        self.queue: asyncio.Queue[Utterance] = asyncio.Queue()
        self.ended = asyncio.Event()
        self.gen = 0                       # bumped on stop/speaker change to discard stale speech
        self.ids = itertools.count(1)
        self.speaking: Utterance | None = None
        # the lines playing right now: just `speaking`, or one per team (all at once) for a chorus
        self.playing: list[Utterance] = []
        self._awaiting: set[int] = set()   # playing lines whose player hasn't reported the end yet
        self._chorus_wavs: dict[str, bytes] = {}  # engine + voice -> the chorus phrase, generated once
        self.generating: Utterance | None = None  # line the TTS is working on right now
        self._synth: asyncio.Future | None = None
        self._skipped = False
        self.pending: Counter[str] = Counter()  # queued utterances per user

    async def say(self, display: str, text: str, login: str | None = None, team: str | None = None,
                  chat: bool = False, chorus: bool = False) -> bool:
        text = URL_RE.sub("", text).strip()
        if not text or (self.tts_cfg.get("skip_commands", True) and text.startswith("!")):
            return False
        user = (login or display).lower()
        # the limit is per speaker, so one chatty speaker can't crowd out the other teams
        if self.pending[user] >= int(self.tts_cfg.get("max_queue", 5)):
            log.info("speech queue of %s is full, ignoring: %s", display, text)
            return False
        team = team or (self.roster.team_of(login) if login else None)
        self.pending[user] += 1
        self.queue.put_nowait(Utterance(next(self.ids), user, display, team, text, self.gen, chat, chorus))
        return True

    def _stale(self, utt: Utterance) -> bool:
        return utt.gen != self.gen or (utt.chat and not self.roster.is_speaker(utt.user))

    async def run(self) -> None:
        while True:
            utt = await self.queue.get()
            self.pending[utt.user] -= 1
            if self._stale(utt):
                continue
            try:
                await self._voice(utt)
            except Exception:
                log.exception("error while speaking: %s", utt.text)  # one bad line must not stop the worker

    async def _voice(self, utt: Utterance) -> None:
        parts = await self._render(utt)
        if not parts or self._stale(utt):
            return
        if not self.stage.clients:
            log.warning("no overlay connected; line dropped: %s", utt.text)
            return
        self.playing = [part for part, _ in parts]
        self.speaking = lead = self.playing[0]
        self.ended.clear()
        try:
            # Everyone gets each line (to animate); exactly one overlay is told to play its audio.
            players = {part.id: self.stage.pick_player(part.team) for part in self.playing}
            self._awaiting = {i for i, ws in players.items() if ws is not None}
            has_player = bool(self._awaiting)
            for part, wav in parts:
                self.audio[part.id] = wav
                log.info("[%s/%s] %s", part.display, part.team or "-", part.text)
            for part in self.playing:
                msg = {"type": "speak", "id": part.id, "url": f"/audio/{part.id}.wav",
                       "team": part.team, "user": part.display, "text": part.text}
                for ws in list(self.stage.clients):
                    await self.stage.send(ws, {**msg, "play": ws is players[part.id]})
            if not has_player:
                await self.stage.broadcast(notice("notice.no_overlay_team", team=lead.team) if lead.team
                                           else notice("notice.no_overlay_no_team"))
            try:
                # without a player nobody will report the end: just animate for the clip's length
                await asyncio.wait_for(self.ended.wait(),
                                       timeout=max(wav_duration(wav) for _, wav in parts) + (3 if has_player else 0))
            except asyncio.TimeoutError:
                log.debug("overlay did not confirm the end of audio %s", lead.id)
        finally:
            # also when a broadcast fails or the worker is cancelled: never leave the line "speaking"
            self.speaking, self.playing = None, []
            self._awaiting.clear()
            for part, _ in parts:
                self.audio.pop(part.id, None)
        for part, _ in parts:
            await self.stage.broadcast({"type": "idle", "id": part.id})

    async def _render(self, utt: Utterance) -> list[tuple[Utterance, bytes]]:
        """The line's audio as (line, wav) pairs: itself, or one copy per team for a chorus (generated
        one after the other and held, to start together). Empty if it failed or was skipped."""
        if not utt.chorus:
            wav = await self._generate(utt)
            return [] if wav is None else [(utt, wav)]
        parts = []
        for team in list(self.roster.teams()):
            part = replace(utt, id=next(self.ids), team=team)
            # per team: without a profile the TTS server makes up a voice on each generation
            key = self.synth.voice_key(team)
            wav = self._chorus_wavs.get(key)
            if wav is None:
                wav = await self._generate(part)
                if wav is None:
                    if self._skipped:
                        return []
                    continue  # this team's voice failed: the others still speak
                self._chorus_wavs[key] = wav
            parts.append((part, wav))
        return parts

    async def _generate(self, utt: Utterance) -> bytes | None:
        """The line's audio, or None if the TTS failed or the line was skipped meanwhile."""
        self.generating, self._skipped = utt, False
        self._synth = asyncio.ensure_future(self.synth.synthesize(utt.text, utt.team))
        await self.stage.broadcast(self.stage.state())
        try:
            return await self._synth
        except asyncio.CancelledError:
            if not self._skipped:
                raise  # the worker itself is being cancelled
            log.info("line skipped while being generated: %s", utt.text)
        except Exception as e:
            log.warning("TTS failed: %s", e)
            await self.stage.broadcast(notice("notice.tts_failed", error=str(e)))
        finally:
            self.generating = self._synth = None
            await self.stage.broadcast(self.stage.state())
        return None

    def _cancel_generation(self) -> None:
        if self._synth:
            self._skipped = True
            self._synth.cancel()

    async def skip(self) -> Message:
        """Drop the one line in progress (stuck in the TTS, or playing) and go on with the queue."""
        if self.generating:
            utt = self.generating
            self._cancel_generation()
            return Message("msg.skipped_generating", {"user": utt.display})
        if self.speaking:
            utt = self.speaking
            await self._stop_playing()
            return Message("msg.skipped", {"user": utt.display})
        raise SorterError("err.no_line")

    async def _stop_playing(self) -> None:
        for utt in self.playing:
            await self.stage.broadcast({"type": "stop", "id": utt.id})
        self.ended.set()

    def on_audio_ended(self, utt_id: int) -> None:
        if any(utt.id == utt_id for utt in self.playing):
            self._awaiting.discard(utt_id)
            if not self._awaiting:
                self.ended.set()

    async def interrupt(self, users: set[str] | None = None) -> None:
        """Drop queued speech and cut the current audio: everyone's (users=None) or only these users'."""
        if users is None:
            self.gen += 1
        kept = []
        while not self.queue.empty():
            utt = self.queue.get_nowait()
            if users is None or utt.user in users:
                self.pending[utt.user] -= 1
            else:
                kept.append(utt)
        for utt in kept:
            self.queue.put_nowait(utt)
        if self.generating and (users is None or self.generating.user in users):
            self._cancel_generation()  # don't leave the pipeline waiting for a line nobody will hear
        if self.speaking and (users is None or self.speaking.user in users):
            await self._stop_playing()

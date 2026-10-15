"""Glue: chat -> sorter/voice -> TTS -> overlay. Operator commands live here so the
console, the HTTP API and the future frontend all share the same actions."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import LANGUAGES, Message, notice, notice_many, render
from .teams import QUEUE, SorterError, TeamSorter
from .config import Config
from .speech import SpeechSession
from .tts import TTS
from .twitch import ChatMessage, read_chat
from .voice import ANY, VoiceController

log = logging.getLogger(__name__)

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
CHANNEL_RE = re.compile(r"^[a-z0-9_]{1,25}$")
LEGACY_TEST_PHRASE = "Fala chat! Aqui é o goblin do time {team}."  # what default_config.toml used to set
# this chatter sending this glyph makes every team's goblin say the phrase together
CHORUS_USER, CHORUS_TRIGGER = "negentropybeing", "𓁈"
CHORUS_TEXT = "Eu sou uma Metralhadora em estado de Graça"


def normalize_channel(raw: str) -> str:
    """Accepts 'name', '#name', '@name' or a pasted link like https://www.twitch.tv/name."""
    c = raw.strip().lower()
    c = re.sub(r"^(https?://)?([a-z]+\.)?twitch\.tv/", "", c)
    return c.split("/")[0].split("?")[0].lstrip("#@")

DEFAULT_TINTS = {"azul": "#3b82f6", "verde": "#22c55e", "roxo": "#a855f7", "amarelo": "#facc15"}


def load_tints(tcfg: dict) -> dict[str, dict]:
    """[teams.tint.<team>] color/strength; a plain "#hex" string is also accepted.
    `tint_strength` is the default strength for teams that don't set one."""
    default_strength = float(tcfg.get("tint_strength", 0.55))
    tints = {}
    for team, color in DEFAULT_TINTS.items():
        entry = tcfg.get("tint", {}).get(team, {})
        if isinstance(entry, str):
            entry = {"color": entry}
        tints[team] = {"color": entry.get("color", color), "strength": float(entry.get("strength", default_strength))}
    return tints


def strip_emotes(text: str, emotes_tag: str) -> str:
    """Remove Twitch emotes using the `emotes` IRC tag ('id:0-4,6-10/id2:12-15')."""
    if not emotes_tag:
        return text
    spans = []
    for part in emotes_tag.split("/"):
        _, _, ranges = part.partition(":")
        for r in ranges.split(","):
            a, _, b = r.partition("-")
            if a.isdigit() and b.isdigit():
                spans.append((int(a), int(b)))
    for a, b in sorted(spans, reverse=True):
        text = text[:a] + text[b + 1:]
    return text


class _Roster:
    """Who may speak, as the speech session sees it."""

    def __init__(self, sorter: TeamSorter, voice: VoiceController):
        self.sorter, self.voice = sorter, voice

    def is_speaker(self, user: str) -> bool:
        return self.voice.is_speaker(user)

    def team_of(self, login: str) -> str | None:
        return self.sorter.team_of(login)

    def teams(self):
        return self.sorter.teams


@dataclass
class App:
    cfg: dict
    tts: TTS
    # settings.json: what the operator changed in the panel (channel, team count, tints),
    # layered over config.toml so the hand-written config and its comments stay untouched.
    settings_path: Path | None = None
    sorter: TeamSorter = field(init=False)
    voice: VoiceController = field(init=False)

    def __post_init__(self):
        self.config = self.cfg if isinstance(self.cfg, Config) else Config(self.cfg, self.settings_path)
        self.cfg = self.config.data
        tcfg = self.cfg.get("teams", {})
        self.sorter = TeamSorter(tcfg.get("count", 2), tcfg.get("auto_assign_late", True))
        self.sorter.queue_open = tcfg.get("queue_open_on_start", False)
        vcfg = self.cfg.get("voice", {})
        self.voice = VoiceController(self.sorter, multi=bool(vcfg.get("multi", False)))
        # the two timers of tick(): chatters silent for too long leave; the voice moves on by itself
        self.inactive = {"on": bool(tcfg.get("inactive_remove", False)), "minutes": float(tcfg.get("inactive_minutes", 10))}
        self.rotate = {"on": bool(vcfg.get("rotate", False)), "minutes": float(vcfg.get("rotate_minutes", 5))}
        self.now = time.monotonic
        self.last_seen: dict[str, float] = {}    # chatter in the game -> time of their last chat message
        self.voice_since: dict[str, float] = {}  # speaker -> when they got the voice
        self.tts.configure(self.cfg.get("tts", {}))  # settings.json may override engine, voices, profiles
        self.tints = load_tints(tcfg)
        # team (pinned) OBS sources hide their goblin while the team has nobody with the voice
        self.hide_idle = bool(self.cfg.get("overlay", {}).get("hide_idle", False))
        # the language the operator reads the panel in; None until they choose (the panel then follows the system)
        language = self.cfg.get("ui", {}).get("language")
        self.language = language if language in LANGUAGES else None
        tw = self.cfg.get("twitch", {})
        self.join_cmds = {c.lower() for c in tw.get("join_commands", ["!joinsort", "!joinsorting"])}
        self.leave_cmds = {c.lower() for c in tw.get("leave_commands", ["!leavesort"])}
        self.tts_cfg = self.cfg.get("tts", {})
        self.clients: set = set()          # overlay/frontend websockets
        # websocket -> {"role": "overlay" | "panel", "team": pinned team | None, "audio": bool}
        self.overlays: dict = {}
        self.speech = SpeechSession(self.tts, self, _Roster(self.sorter, self.voice), self.tts_cfg)
        self.channel: str = ""
        self.chat_status = "off"  # off | connecting | connected | reconnecting
        self.chat_task: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()

    def persist(self, patch: dict) -> None:
        self.config.update(patch)

    def _bg(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    # ---- twitch chat ---------------------------------------------------

    def start_chat(self, channel: str) -> None:
        channel = normalize_channel(channel)
        if channel and not CHANNEL_RE.match(channel):
            raise SorterError("err.invalid_channel", channel=channel)
        if self.chat_task:
            self.chat_task.cancel()
            self.chat_task = None
        self.channel = channel
        self.chat_status = "connecting" if self.channel else "off"
        if self.channel:
            self.chat_task = asyncio.get_running_loop().create_task(self._chat_loop(self.channel))

    def _set_chat_status(self, status: str) -> None:
        self.chat_status = status
        if status == "connected":
            self.last_seen.clear()  # nobody could be heard while the chat was down: restart the inactivity clocks
        self._bg(self.broadcast(self.state()))

    async def _chat_loop(self, channel: str) -> None:
        async for msg in read_chat(channel, on_status=self._set_chat_status):
            try:
                await self.on_chat(msg)
            except Exception:
                log.exception("error handling a message from %s", msg.login)

    # ---- state / broadcast ---------------------------------------------

    def state(self) -> dict:
        return {
            "type": "state",
            **self.sorter.snapshot(),
            # "voice" = most recent speaker; "speakers" = everyone with the voice (one per team in multi mode)
            "voice": {"id": self.voice.active,
                      "user": self.sorter.name(self.voice.active) if self.voice.active else None,
                      "team": self.voice.active_team},
            "speakers": [{"id": u, "user": self.sorter.name(u), "team": t} for u, t in self.voice.speakers()],
            "multi_voice": self.voice.multi,
            "auto_remove": self.inactive,
            "auto_rotate": self.rotate,
            "generating": {"user": self.speech.generating.display, "team": self.speech.generating.team}
                          if self.speech.generating else None,
            # OBS sources currently connected (panels, which only play as a last resort, aren't listed)
            "overlays": [{"team": info["team"], "audio": info["audio"]} for ws, info in self.overlays.items()
                         if ws in self.clients and info.get("role", "overlay") == "overlay"],
            "speaking": self.speech.speaking.team if self.speech.speaking else None,
            "tints": self.tints,
            "hide_idle": self.hide_idle,
            "language": self.language,
            "chat": {"channel": self.channel, "status": self.chat_status},
            "tts_engine": self.tts.engine.name,
            "tts_error": self.tts.error,
            "team_profiles": self.tts.team_profiles,
            "data_dir": str(self.config.data_dir) if self.config.data_dir else None,
        }

    async def send(self, ws, msg: dict) -> None:
        try:
            await ws.send_str(json.dumps(msg))
        except Exception:
            self.clients.discard(ws)
            self.overlays.pop(ws, None)

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self.clients):
            await self.send(ws, msg)

    def pick_player(self, team: str | None):
        """The one client that plays a line's audio: the team's own (pinned) overlay if it has
        audio on, else the main (unpinned) overlay, else an open panel (so voices can be tested
        without OBS), else nobody."""
        audible = [(ws, info) for ws, info in self.overlays.items() if info["audio"] and ws in self.clients]
        overlays = [(ws, info) for ws, info in audible if info.get("role", "overlay") == "overlay"]
        for wanted in ([team] if team else []) + [None]:
            for ws, info in overlays:
                if info["team"] == wanted:
                    return ws
        return next((ws for ws, info in audible if info.get("role") == "panel"), None)

    # ---- chat ----------------------------------------------------------

    async def on_chat(self, msg: ChatMessage) -> None:
        first = msg.text.strip().split(" ", 1)[0].lower()
        self.last_seen[msg.login.lower()] = self.now()  # any message counts as activity (tick() drops outsiders)
        if first == CHORUS_TRIGGER and msg.login.lower() == CHORUS_USER:
            await self.say(msg.display, CHORUS_TEXT, msg.login, chorus=True)
        elif first in self.join_cmds:
            result = self.sorter.join(msg.login, msg.display)
            if result == "closed":
                log.info("%s tried to join, but the queue is closed", msg.display)
                await self.broadcast(notice("notice.queue_closed", user=msg.display))
            elif result == "already":
                log.info("%s is already in the queue/a team", msg.display)
            else:
                log.info("%s joined -> %s", msg.display, result)
                await self.broadcast(self.state())
        elif first in self.leave_cmds:
            if self.sorter.leave(msg.login):
                log.info("%s left", msg.display)
                await self.broadcast(self.state())
        elif self.voice.is_speaker(msg.login):
            await self.say(msg.display, strip_emotes(msg.text, msg.tags.get("emotes", "")), msg.login, chat=True)

    async def say(self, display: str, text: str, login: str | None = None, team: str | None = None,
                  chat: bool = False, chorus: bool = False) -> bool:
        return await self.speech.say(display, text, login, team, chat, chorus)

    async def skip(self) -> Message:
        return await self.speech.skip()

    def on_audio_ended(self, utt_id: int) -> None:
        self.speech.on_audio_ended(utt_id)

    async def interrupt(self, users: set[str] | None = None) -> None:
        await self.speech.interrupt(users)

    # ---- timers --------------------------------------------------------

    async def timers(self) -> None:
        while True:
            await asyncio.sleep(1)
            try:
                await self.tick()
            except Exception:
                log.exception("error in the timers")

    async def tick(self) -> None:
        """Inactive chatters leave the queue/teams; a speaker's time with the voice runs out."""
        now, s, v = self.now(), self.sorter, self.voice
        members = [*s.queue, *(u for m in s.teams.values() for u in m)]
        # people added by hand (or from before a reconnect) count from the moment they are first seen here
        self.last_seen = {u: self.last_seen.get(u, now) for u in members}
        self.voice_since = {u: self.voice_since.get(u, now) for u in v.users}
        notices: list[Message] = []
        # only while the chat is connected: otherwise nobody can be heard and everyone would be thrown out
        if self.inactive["on"] and self.chat_status == "connected":
            idle = [u for u in members if now - self.last_seen[u] >= self.inactive["minutes"] * 60]
            for u in idle:
                team, had_voice = s.team_of(u), v.is_speaker(u)
                s.leave(u)
                v.prune(lambda x, u=u: x != u)
                # with rotation on, the team doesn't go silent because its speaker was the idle one
                if had_voice and self.rotate["on"] and team and s.teams[team]:
                    v.pick_random(team)
            if idle:
                notices.append(Message("notice.inactive_removed", {"users": ", ".join(map(s.name, idle))}))
        if self.rotate["on"]:
            for u in list(v.users):
                team = s.team_of(u)
                if u not in v.users or team is None or now - self.voice_since.get(u, now) < self.rotate["minutes"] * 60:
                    continue
                if any(utt and utt.user == u for utt in (self.speech.speaking, self.speech.generating)):
                    continue  # let their current line finish; try again on the next tick
                new = v.pick_random(team)  # same person again if the team has nobody else
                self.voice_since[new] = now
                if new != u:
                    notices.append(Message("notice.voice_moved", {"team": team, "user": s.name(new)}))
        if lost := v.take_lost():
            await self.interrupt(lost)
        if notices:
            log.info("; ".join(map(str, notices)))
            await self.broadcast(self.state())
            await self.broadcast(notice_many(notices))

    # ---- operator commands ---------------------------------------------

    HELP = """commands:
  open | close              open/close the queue (!joinsort)
  teams <1-4>               set the number of teams
  sort                      sort the queue into teams
  resort                    put everyone back in the queue and sort again
  reset                     put everyone in the teams back in the queue
  clear                     clear the queue and the teams
  add <user>                add someone by hand
  move <user> <team|fila>   move someone to another team
  remove <user>             take someone out
  voice [team|any]          give the voice to a random person (no argument = same team)
  next [team]               another person from the same team
  give <user>               give the voice to a specific person
  stop [team|user]          take the voice away (no argument = from everyone) and stop the audio
  skip                      skip the line in progress (being generated or playing)
  multivoice <on|off>       one speaker per team at the same time
  autoremove <on|off> [min] remove from the queue/teams whoever stays [min] minutes without chatting
  autorotate <on|off> [min] pass the voice to another person on the team every [min] minutes
  hideidle <on|off>         hide the goblin of a team with nobody holding the voice
  channel <channel|off>     connect to another channel's chat
  tint <team> <#color|off> [strength 0-1]   change a team goblin's tint
  teamvoice <team|default> <profile|none>   a team's voice profile (Voice tab)
  engine <server|sapi|dummy>                TTS engine
  language <en|pt-BR>       the language of the panel
  test <team> <text>        test the TTS/goblin of a team
  testvoice <team>          the team's goblin says a fixed phrase with the team's voice
  state                     show the state"""

    async def command(self, line: str, language: str | None = None) -> Message:
        """Run one operator command. The answer is a Message (a key plus values) the panel puts in its language.

        `language` is the one the panel is showing; it picks what the goblins *say* in a test (the stored
        choice, or English, when the caller doesn't say)."""
        lang = language if language in LANGUAGES else (self.language or "en")
        parts = line.strip().split()
        if not parts:
            return Message("msg.text", {"text": ""})
        cmd, args = parts[0].lower(), parts[1:]
        s, v = self.sorter, self.voice
        try:
            if cmd in ("help", "?"):
                return Message("msg.text", {"text": self.HELP})
            if cmd == "state":
                return Message("msg.text", {"text": self.describe()})
            if cmd == "test":
                if len(args) < 2:
                    raise SorterError("err.usage", usage="test <team> <text>")
                team = None if args[0] in (QUEUE, "-", "none") else args[0].lower()
                ok = await self.say(render("test.label", None, lang), " ".join(args[1:]), team=team)
                return Message("msg.test_sent" if ok else "msg.test_ignored")
            if cmd == "testvoice":
                # fixed phrase through the whole pipeline: TTS engine -> the team's voice profile -> its overlay
                team = args[0].lower() if args else ""
                if team not in s.teams:
                    raise SorterError("err.usage", usage=f"testvoice <team> ({', '.join(s.teams)})")
                name = render(f"team.{team}", None, lang)
                phrase = self.tts_cfg.get("test_phrase")  # set in config.toml: said as written
                if phrase == LEGACY_TEST_PHRASE:
                    phrase = None  # the old default, copied into every config.toml: not a choice, follow the language
                phrase = phrase.replace("{team}", team) if phrase else render("testvoice.phrase", {"team": name}, lang)
                ok = await self.say(f"{render('test.label', None, lang)} {name}", phrase, team=team)
                return Message("msg.testvoice", {"team": team}) if ok else Message("msg.testvoice_full")
            if cmd == "skip":
                return await self.skip()
            if cmd == "engine":
                if not args:
                    raise SorterError("err.usage", usage="engine <server|sapi|dummy|custom>")
                try:
                    await self.tts.set_engine(args[0].lower())
                except Exception as e:
                    raise SorterError("err.engine_switch", engine=args[0], error=str(e))
                self.persist({"tts": {"engine": self.tts.engine.name}})
                await self.broadcast(self.state())
                return Message("msg.engine", {"engine": self.tts.engine.name})
            out = self._mutate(cmd, args, s, v)
            # A speaker removed from the game loses the voice too.
            if cmd == "remove":
                v.prune(lambda u: u != args[0].lower())
            elif cmd == "clear":
                v.prune(lambda u: s.where(u) is not None)
            if cmd == "stop" and not args:
                await self.interrupt()  # everything, including test lines
            elif lost := v.take_lost():
                await self.interrupt(lost)  # only the speakers who lost the voice
            await self.broadcast(self.state())
            return out
        except SorterError as e:
            return e.message

    def _mutate(self, cmd: str, args: list[str], s: TeamSorter, v: VoiceController) -> Message:
        def need(n: int, usage: str):
            if len(args) < n:
                raise SorterError("err.usage", usage=usage)

        if cmd == "open":
            s.queue_open = True
            return Message("msg.queue_open")
        if cmd == "close":
            s.queue_open = False
            return Message("msg.queue_closed")
        if cmd == "teams":
            need(1, "teams <1-4>")
            if not args[0].isdigit():
                raise SorterError("err.usage", usage="teams <1-4>")
            s.set_team_count(int(args[0]))
            self.persist({"teams": {"count": int(args[0])}})
            return Message("msg.teams", {"teams": ", ".join(s.teams)})
        if cmd == "sort":
            return Message("msg.sorted", {"count": s.sort()})
        if cmd == "resort":
            return Message("msg.resorted", {"count": s.resort()})
        if cmd == "reset":
            s.return_all_to_queue()
            return Message("msg.all_back")
        if cmd == "clear":
            s.clear()
            return Message("msg.cleared")
        if cmd == "add":
            need(1, "add <user>")
            where = s.add(args[0])
            if where == "queued":
                return Message("msg.added_queued", {"user": args[0]})
            if where == "already":
                return Message("msg.added_already", {"user": args[0]})
            return Message("msg.added_team", {"user": args[0], "team": where})
        if cmd == "move":
            need(2, "move <user> <team|fila>")
            s.move(args[0], args[1])
            return Message("msg.moved", {"user": args[0], "to": args[1]})
        if cmd == "remove":
            need(1, "remove <user>")
            s.remove(args[0])
            return Message("msg.removed", {"user": args[0]})
        if cmd == "tint":
            need(2, "tint <team> <#rrggbb|off> [strength 0-1]")
            team = args[0].lower()
            if team not in self.tints:
                raise SorterError("err.unknown_team", team=team)
            tint = self.tints[team]
            if args[1].lower() == "off":
                tint["strength"] = 0.0
            else:
                if not HEX_RE.match(args[1]):
                    raise SorterError("err.bad_color")
                tint["color"] = args[1].lower()
            if len(args) > 2:
                try:
                    tint["strength"] = max(0.0, min(1.0, float(args[2])))
                except ValueError:
                    raise SorterError("err.bad_strength")
            self.persist({"teams": {"tint": {team: dict(tint)}}})
            return Message("msg.tint", {"team": team, "color": tint["color"], "strength": f"{tint['strength']:.2f}"})
        if cmd == "teamvoice":
            need(2, "teamvoice <team|default> <profile|none>")
            team = args[0].lower()
            if team != "default" and team not in self.tints:
                raise SorterError("err.unknown_team", team=team)
            self.tts.set_team_profile(team, None if args[1].lower() == "none" else args[1])
            self.config.replace(("tts", "team_profiles"), dict(self.tts.team_profiles))  # replace: removals persist
            profile = self.tts.team_profiles.get(team)
            return Message("msg.team_voice", {"team": team, "profile": profile or "default"})
        if cmd == "channel":
            need(1, "channel <channel|off>")
            channel = "" if args[0].lower() == "off" else args[0]
            self.start_chat(channel)
            self.persist({"twitch": {"channel": self.channel}})
            return Message("msg.chat_on", {"channel": self.channel}) if self.channel else Message("msg.chat_off")
        if cmd in ("voice", "next", "give"):
            if cmd == "give":
                need(1, "give <user>")
                user = v.give(args[0])
            else:
                user = v.pick_random(args[0] if args else None)
            return Message("msg.voice_to", {"user": s.name(user), "team": s.team_of(user) or "-"})
        if cmd == "stop":
            removed = v.stop(args[0] if args else None)
            return Message("msg.voice_removed", {"users": ", ".join(map(s.name, removed))}) if removed \
                else Message("msg.nobody_had_voice")
        if cmd == "multivoice":
            if not args or args[0].lower() not in ("on", "off"):
                raise SorterError("err.usage", usage="multivoice <on|off>")
            on = args[0].lower() == "on"
            v.set_multi(on)
            self.persist({"voice": {"multi": on}})
            return Message("msg.multivoice_on" if on else "msg.multivoice_off")
        if cmd == "language":
            if not args or args[0] not in LANGUAGES:
                raise SorterError("err.usage", usage=f"language <{'|'.join(LANGUAGES)}>")
            self.language = args[0]
            self.persist({"ui": {"language": self.language}})
            return Message("msg.language", {"language": self.language})
        if cmd == "hideidle":
            if not args or args[0].lower() not in ("on", "off"):
                raise SorterError("err.usage", usage="hideidle <on|off>")
            self.hide_idle = args[0].lower() == "on"
            self.persist({"overlay": {"hide_idle": self.hide_idle}})
            return Message("msg.hideidle_on" if self.hide_idle else "msg.hideidle_off")
        if cmd in ("autoremove", "autorotate"):
            opt, section, key = ((self.inactive, "teams", "inactive") if cmd == "autoremove"
                                 else (self.rotate, "voice", "rotate"))
            if not args or args[0].lower() not in ("on", "off"):
                raise SorterError("err.usage", usage=f"{cmd} <on|off> [minutes]")
            if len(args) > 1:
                try:
                    minutes = float(args[1].replace(",", "."))
                except ValueError:
                    minutes = 0.0
                if not (math.isfinite(minutes) and 0 < minutes <= 1440):
                    raise SorterError("err.bad_minutes")
                opt["minutes"] = minutes
            opt["on"] = args[0].lower() == "on"
            on_key = "inactive_remove" if cmd == "autoremove" else "rotate"
            self.persist({section: {on_key: opt["on"], f"{key}_minutes": opt["minutes"]}})
            if opt["on"]:
                return Message(f"msg.{cmd}_on", {"minutes": f"{opt['minutes']:g}"})
            return Message(f"msg.{cmd}_off")
        raise SorterError("err.unknown_command", command=cmd)

    def describe(self) -> str:
        """The state as plain English text, for the console."""
        s, v = self.sorter, self.voice
        lines = [f"queue ({'open' if s.queue_open else 'closed'}): {', '.join(map(s.name, s.queue)) or '-'}"]
        for team, members in s.teams.items():
            lines.append(f"  {team:8} ({len(members)}): {', '.join(map(s.name, members)) or '-'}")
        speakers = ", ".join(f"{s.name(u)} ({t or 'no team'})" for u, t in v.speakers())
        lines.append(f"voice{' (several teams)' if v.multi else ''}: {speakers or '-'}")
        return "\n".join(lines)


__all__ = ["App", "ANY", "strip_emotes"]

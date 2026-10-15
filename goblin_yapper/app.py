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

from .teams import QUEUE, SorterError, TeamSorter
from .config import Config
from .speech import SpeechSession
from .tts import TTS
from .twitch import ChatMessage, read_chat
from .voice import ANY, VoiceController

log = logging.getLogger(__name__)

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
CHANNEL_RE = re.compile(r"^[a-z0-9_]{1,25}$")
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
        tw = self.cfg.get("twitch", {})
        self.join_cmds = {c.lower() for c in tw.get("join_commands", ["!joinsort", "!joinsorting"])}
        self.leave_cmds = {c.lower() for c in tw.get("leave_commands", ["!leavesort"])}
        self.tts_cfg = self.cfg.get("tts", {})
        self.clients: set = set()          # overlay/frontend websockets
        # websocket -> {"role": "overlay" | "panel", "team": pinned team | None, "audio": bool}
        self.overlays: dict = {}
        self.speech = SpeechSession(self.tts, self, _Roster(self.sorter, self.voice), self.tts_cfg)
        self.channel: str = ""
        self.chat_status = "desligado"
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
            raise SorterError(f"canal inválido: {channel} (use só o nome, ex: meucanal)")
        if self.chat_task:
            self.chat_task.cancel()
            self.chat_task = None
        self.channel = channel
        self.chat_status = "conectando" if self.channel else "desligado"
        if self.channel:
            self.chat_task = asyncio.get_running_loop().create_task(self._chat_loop(self.channel))

    def _set_chat_status(self, status: str) -> None:
        self.chat_status = status
        if status == "conectado":
            self.last_seen.clear()  # nobody could be heard while the chat was down: restart the inactivity clocks
        self._bg(self.broadcast(self.state()))

    async def _chat_loop(self, channel: str) -> None:
        async for msg in read_chat(channel, on_status=self._set_chat_status):
            try:
                await self.on_chat(msg)
            except Exception:
                log.exception("erro processando mensagem de %s", msg.login)

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
                log.info("%s tentou entrar, mas a fila está fechada", msg.display)
                await self.broadcast({"type": "notice", "text": f"{msg.display} tentou entrar, mas a fila está fechada"})
            elif result == "already":
                log.info("%s já está na fila/time", msg.display)
            else:
                log.info("%s entrou -> %s", msg.display, result)
                await self.broadcast(self.state())
        elif first in self.leave_cmds:
            if self.sorter.leave(msg.login):
                log.info("%s saiu", msg.display)
                await self.broadcast(self.state())
        elif self.voice.is_speaker(msg.login):
            await self.say(msg.display, strip_emotes(msg.text, msg.tags.get("emotes", "")), msg.login, chat=True)

    async def say(self, display: str, text: str, login: str | None = None, team: str | None = None,
                  chat: bool = False, chorus: bool = False) -> bool:
        return await self.speech.say(display, text, login, team, chat, chorus)

    async def skip(self) -> str:
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
                log.exception("erro nos temporizadores")

    async def tick(self) -> None:
        """Inactive chatters leave the queue/teams; a speaker's time with the voice runs out."""
        now, s, v = self.now(), self.sorter, self.voice
        members = [*s.queue, *(u for m in s.teams.values() for u in m)]
        # people added by hand (or from before a reconnect) count from the moment they are first seen here
        self.last_seen = {u: self.last_seen.get(u, now) for u in members}
        self.voice_since = {u: self.voice_since.get(u, now) for u in v.users}
        notices = []
        # only while the chat is connected: otherwise nobody can be heard and everyone would be thrown out
        if self.inactive["on"] and self.chat_status == "conectado":
            idle = [u for u in members if now - self.last_seen[u] >= self.inactive["minutes"] * 60]
            for u in idle:
                team, had_voice = s.team_of(u), v.is_speaker(u)
                s.leave(u)
                v.prune(lambda x, u=u: x != u)
                # with rotation on, the team doesn't go silent because its speaker was the idle one
                if had_voice and self.rotate["on"] and team and s.teams[team]:
                    v.pick_random(team)
            if idle:
                notices.append(f"removido(s) por inatividade: {', '.join(map(s.name, idle))}")
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
                    notices.append(f"voz do time {team} passou para {s.name(new)}")
        if lost := v.take_lost():
            await self.interrupt(lost)
        if notices:
            log.info("; ".join(notices))
            await self.broadcast(self.state())
            await self.broadcast({"type": "notice", "text": "; ".join(notices), "ok": True})

    # ---- operator commands ---------------------------------------------

    HELP = """comandos:
  open | close              abre/fecha a fila (!joinsort)
  teams <1-4>               define número de times
  sort                      sorteia a fila nos times
  resort                    devolve todos à fila e sorteia de novo
  reset                     devolve todos os times à fila
  clear                     limpa fila e times
  add <user>                adiciona alguém manualmente
  move <user> <time|fila>   troca alguém de time
  remove <user>             tira alguém
  voice [time|any]          dá voz a alguém aleatório (sem arg = mesmo time)
  next [time]               outra pessoa do mesmo time
  give <user>               dá voz a alguém específico
  stop [time|user]          tira a voz (sem arg = de todos) e para o áudio
  skip                      pula a fala em andamento (sendo gerada ou tocando)
  multivoice <on|off>       um falante por time ao mesmo tempo
  autoremove <on|off> [min] tira da fila/times quem ficar [min] minutos sem falar no chat
  autorotate <on|off> [min] passa a voz para outra pessoa do time a cada [min] minutos
  hideidle <on|off>         esconde o goblin do time que está sem ninguém com a voz
  channel <canal|off>       conecta ao chat de outro canal
  tint <time> <#cor|off> [força 0-1]   muda a tinta do goblin do time
  teamvoice <time|default> <perfil|none>   perfil de voz do time (aba Voz)
  engine <server|sapi|dummy>                motor de TTS
  test <time> <texto>       testa o TTS/goblin de um time
  testvoice <time>          o goblin do time diz uma frase fixa com a voz do time
  state                     mostra o estado"""

    async def command(self, line: str) -> str:
        parts = line.strip().split()
        if not parts:
            return ""
        cmd, args = parts[0].lower(), parts[1:]
        s, v = self.sorter, self.voice
        try:
            if cmd in ("help", "?"):
                return self.HELP
            if cmd == "state":
                return self.describe()
            if cmd == "test":
                if len(args) < 2:
                    raise SorterError("uso: test <time> <texto>")
                team = None if args[0] in (QUEUE, "-", "none") else args[0].lower()
                ok = await self.say("teste", " ".join(args[1:]), team=team)
                return "enviado ao TTS" if ok else "ignorado"
            if cmd == "testvoice":
                # fixed phrase through the whole pipeline: TTS engine -> the team's voice profile -> its overlay
                team = args[0].lower() if args else ""
                if team not in s.teams:
                    raise SorterError(f"uso: testvoice <time> ({', '.join(s.teams)})")
                phrase = self.tts_cfg.get("test_phrase", "Fala chat! Aqui é o goblin do time {team}.").replace("{team}", team)
                ok = await self.say(f"teste {team}", phrase, team=team)
                return f"testando a voz do time {team}" if ok else "fila de testes cheia, aguarde"
            if cmd == "skip":
                return await self.skip()
            if cmd == "engine":
                if not args:
                    raise SorterError("uso: engine <server|sapi|dummy|custom>")
                try:
                    await self.tts.set_engine(args[0].lower())
                except Exception as e:
                    raise SorterError(f"não consegui trocar para {args[0]}: {e}")
                self.persist({"tts": {"engine": self.tts.engine.name}})
                await self.broadcast(self.state())
                return f"TTS: {self.tts.engine.name}"
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
            return f"erro: {e}"

    def _mutate(self, cmd: str, args: list[str], s: TeamSorter, v: VoiceController) -> str:
        def need(n: int, usage: str):
            if len(args) < n:
                raise SorterError(f"uso: {usage}")

        if cmd == "open":
            s.queue_open = True
            return "fila aberta"
        if cmd == "close":
            s.queue_open = False
            return "fila fechada"
        if cmd == "teams":
            need(1, "teams <1-4>")
            if not args[0].isdigit():
                raise SorterError("uso: teams <1-4>")
            s.set_team_count(int(args[0]))
            self.persist({"teams": {"count": int(args[0])}})
            return f"times: {', '.join(s.teams)}"
        if cmd == "sort":
            return f"{s.sort()} sorteado(s)\n{self.describe()}"
        if cmd == "resort":
            return f"{s.resort()} re-sorteado(s)\n{self.describe()}"
        if cmd == "reset":
            s.return_all_to_queue()
            return "todos de volta à fila"
        if cmd == "clear":
            s.clear()
            return "tudo limpo"
        if cmd == "add":
            need(1, "add <user>")
            return f"{args[0]}: {s.add(args[0])}"
        if cmd == "move":
            need(2, "move <user> <time|fila>")
            s.move(args[0], args[1])
            return f"{args[0]} -> {args[1]}"
        if cmd == "remove":
            need(1, "remove <user>")
            s.remove(args[0])
            return f"{args[0]} removido"
        if cmd == "tint":
            need(2, "tint <time> <#rrggbb|off> [força 0-1]")
            team = args[0].lower()
            if team not in self.tints:
                raise SorterError(f"time desconhecido: {team}")
            tint = self.tints[team]
            if args[1].lower() == "off":
                tint["strength"] = 0.0
            else:
                if not HEX_RE.match(args[1]):
                    raise SorterError("cor deve ser #rrggbb")
                tint["color"] = args[1].lower()
            if len(args) > 2:
                try:
                    tint["strength"] = max(0.0, min(1.0, float(args[2])))
                except ValueError:
                    raise SorterError("força deve ser um número entre 0 e 1")
            self.persist({"teams": {"tint": {team: dict(tint)}}})
            return f"tinta {team}: {tint['color']} força {tint['strength']:.2f}"
        if cmd == "teamvoice":
            need(2, "teamvoice <time|default> <perfil|none>")
            team = args[0].lower()
            if team != "default" and team not in self.tints:
                raise SorterError(f"time desconhecido: {team}")
            self.tts.set_team_profile(team, None if args[1].lower() == "none" else args[1])
            self.config.replace(("tts", "team_profiles"), dict(self.tts.team_profiles))  # replace: removals persist
            return f"voz de {team}: {self.tts.team_profiles.get(team, 'padrão')}"
        if cmd == "channel":
            need(1, "channel <canal|off>")
            channel = "" if args[0].lower() == "off" else args[0]
            self.start_chat(channel)
            self.persist({"twitch": {"channel": self.channel}})
            return f"chat: #{self.channel}" if self.channel else "chat desligado"
        if cmd in ("voice", "next"):
            user = v.pick_random(args[0] if args else None)
            return f"voz para {s.name(user)} ({s.team_of(user) or 'sem time'})"
        if cmd == "give":
            need(1, "give <user>")
            user = v.give(args[0])
            return f"voz para {s.name(user)} ({s.team_of(user) or 'sem time'})"
        if cmd == "stop":
            removed = v.stop(args[0] if args else None)
            return f"voz retirada de {', '.join(map(s.name, removed))}" if removed else "ninguém tinha a voz"
        if cmd == "multivoice":
            if not args or args[0].lower() not in ("on", "off"):
                raise SorterError("uso: multivoice <on|off>")
            on = args[0].lower() == "on"
            v.set_multi(on)
            self.persist({"voice": {"multi": on}})
            return "vários times podem falar ao mesmo tempo" if on else "só uma pessoa com a voz por vez"
        if cmd == "hideidle":
            if not args or args[0].lower() not in ("on", "off"):
                raise SorterError("uso: hideidle <on|off>")
            self.hide_idle = args[0].lower() == "on"
            self.persist({"overlay": {"hide_idle": self.hide_idle}})
            return ("goblins dos times somem enquanto o time está sem voz" if self.hide_idle
                    else "goblins dos times sempre visíveis")
        if cmd in ("autoremove", "autorotate"):
            opt, section, key = ((self.inactive, "teams", "inactive") if cmd == "autoremove"
                                 else (self.rotate, "voice", "rotate"))
            if not args or args[0].lower() not in ("on", "off"):
                raise SorterError(f"uso: {cmd} <on|off> [minutos]")
            if len(args) > 1:
                try:
                    minutes = float(args[1].replace(",", "."))
                except ValueError:
                    minutes = 0.0
                if not (math.isfinite(minutes) and 0 < minutes <= 1440):
                    raise SorterError("minutos deve ser um número entre 0 e 1440")
                opt["minutes"] = minutes
            opt["on"] = args[0].lower() == "on"
            on_key = "inactive_remove" if cmd == "autoremove" else "rotate"
            self.persist({section: {on_key: opt["on"], f"{key}_minutes": opt["minutes"]}})
            if cmd == "autoremove":
                return (f"inativos saem após {opt['minutes']:g} min sem falar no chat" if opt["on"]
                        else "remoção de inativos desligada")
            return f"a voz troca de pessoa a cada {opt['minutes']:g} min" if opt["on"] else "rotação da voz desligada"
        raise SorterError(f"comando desconhecido: {cmd} (digite help)")

    def describe(self) -> str:
        s, v = self.sorter, self.voice
        lines = [f"fila ({'aberta' if s.queue_open else 'fechada'}): {', '.join(map(s.name, s.queue)) or '-'}"]
        for team, members in s.teams.items():
            lines.append(f"  {team:8} ({len(members)}): {', '.join(map(s.name, members)) or '-'}")
        speakers = ", ".join(f"{s.name(u)} ({t or 'sem time'})" for u, t in v.speakers())
        lines.append(f"voz{' (vários times)' if v.multi else ''}: {speakers or '-'}")
        return "\n".join(lines)


__all__ = ["App", "ANY", "strip_emotes"]

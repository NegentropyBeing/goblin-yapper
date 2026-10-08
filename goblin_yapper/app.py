"""Glue: chat -> sorter/voice -> TTS -> overlay. Operator commands live here so the
console, the HTTP API and the future frontend all share the same actions."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .teams import QUEUE, SorterError, TeamSorter
from .tts import TTS, wav_duration
from .twitch import ChatMessage, read_chat
from .voice import ANY, VoiceController

log = logging.getLogger(__name__)

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
CHANNEL_RE = re.compile(r"^[a-z0-9_]{1,25}$")


def normalize_channel(raw: str) -> str:
    """Accepts 'name', '#name', '@name' or a pasted link like https://www.twitch.tv/name."""
    c = raw.strip().lower()
    c = re.sub(r"^(https?://)?([a-z]+\.)?twitch\.tv/", "", c)
    return c.split("/")[0].split("?")[0].lstrip("#@")

DEFAULT_TINTS = {"azul": "#3b82f6", "verde": "#22c55e", "roxo": "#a855f7", "amarelo": "#facc15"}


def deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


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


@dataclass
class Utterance:
    id: int
    user: str
    display: str
    team: str | None
    text: str
    gen: int


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
        self.settings: dict = {}
        if self.settings_path and self.settings_path.exists():
            try:
                self.settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except ValueError:
                log.warning("settings.json inválido, ignorando")
        self.cfg = deep_merge(json.loads(json.dumps(self.cfg)), self.settings)
        tcfg = self.cfg.get("teams", {})
        self.sorter = TeamSorter(tcfg.get("count", 2), tcfg.get("auto_assign_late", True))
        self.sorter.queue_open = tcfg.get("queue_open_on_start", False)
        self.voice = VoiceController(self.sorter)
        self.tints = load_tints(tcfg)
        tw = self.cfg.get("twitch", {})
        self.join_cmds = {c.lower() for c in tw.get("join_commands", ["!joinsort", "!joinsorting"])}
        self.leave_cmds = {c.lower() for c in tw.get("leave_commands", ["!leavesort"])}
        self.tts_cfg = self.cfg.get("tts", {})
        self.clients: set = set()          # overlay/frontend websockets
        self.audio: dict[int, bytes] = {}  # utterance id -> wav, served at /audio/<id>.wav
        self.speech_q: asyncio.Queue[Utterance] = asyncio.Queue()
        self.ended = asyncio.Event()
        self.gen = 0                       # bumped on stop/speaker change to discard stale speech
        self.ids = itertools.count(1)
        self.speaking: Utterance | None = None
        self.channel: str = ""
        self.chat_status = "desligado"
        self.chat_task: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()

    def persist(self, patch: dict) -> None:
        deep_merge(self.settings, patch)
        if self.settings_path:
            self.settings_path.write_text(json.dumps(self.settings, indent=2, ensure_ascii=False), encoding="utf-8")

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
            "voice": {"id": self.voice.active,
                      "user": self.sorter.name(self.voice.active) if self.voice.active else None,
                      "team": self.voice.active_team},
            "speaking": self.speaking.team if self.speaking else None,
            "tints": self.tints,
            "chat": {"channel": self.channel, "status": self.chat_status},
            "tts_engine": self.tts.engine.name,
            "tts_error": self.tts.error,
            "data_dir": str(self.settings_path.parent) if self.settings_path else None,
        }

    async def broadcast(self, msg: dict) -> None:
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:
                self.clients.discard(ws)

    # ---- chat ----------------------------------------------------------

    async def on_chat(self, msg: ChatMessage) -> None:
        first = msg.text.strip().split(" ", 1)[0].lower()
        if first in self.join_cmds:
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
        elif self.voice.active and msg.login.lower() == self.voice.active:
            await self.say(msg.display, strip_emotes(msg.text, msg.tags.get("emotes", "")), msg.login)

    async def say(self, display: str, text: str, login: str | None = None, team: str | None = None) -> bool:
        text = URL_RE.sub("", text).strip()
        if not text or (self.tts_cfg.get("skip_commands", True) and text.startswith("!")):
            return False
        if self.speech_q.qsize() >= int(self.tts_cfg.get("max_queue", 5)):
            log.info("fila de fala cheia, ignorando: %s", text)
            return False
        team = team or (self.sorter.team_of(login) if login else None)
        self.speech_q.put_nowait(Utterance(next(self.ids), login or display, display, team, text, self.gen))
        return True

    # ---- speech pipeline -----------------------------------------------

    async def speech_worker(self) -> None:
        while True:
            utt = await self.speech_q.get()
            if utt.gen != self.gen:
                continue
            try:
                wav = await self.tts.synthesize(utt.text, utt.team)
            except Exception:
                log.exception("falha no TTS")
                continue
            if utt.gen != self.gen:
                continue
            if not self.clients:
                log.warning("nenhum overlay conectado; fala descartada: %s", utt.text)
                continue
            self.audio[utt.id] = wav
            self.speaking = utt
            self.ended.clear()
            log.info("[%s/%s] %s", utt.display, utt.team or "-", utt.text)
            await self.broadcast({"type": "speak", "id": utt.id, "url": f"/audio/{utt.id}.wav",
                                  "team": utt.team, "user": utt.display, "text": utt.text})
            try:
                await asyncio.wait_for(self.ended.wait(), timeout=wav_duration(wav) + 3)
            except asyncio.TimeoutError:
                log.debug("overlay não confirmou fim do áudio %s", utt.id)
            self.speaking = None
            self.audio.pop(utt.id, None)
            await self.broadcast({"type": "idle", "id": utt.id})

    def on_audio_ended(self, utt_id: int) -> None:
        if self.speaking and self.speaking.id == utt_id:
            self.ended.set()

    async def interrupt(self) -> None:
        """Drop queued speech and cut the current audio."""
        self.gen += 1
        while not self.speech_q.empty():
            self.speech_q.get_nowait()
        if self.speaking:
            await self.broadcast({"type": "stop", "id": self.speaking.id})
            self.ended.set()

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
  next                      outra pessoa do mesmo time
  give <user>               dá voz a alguém específico
  stop                      tira a voz / para o áudio
  channel <canal|off>       conecta ao chat de outro canal
  tint <time> <#cor|off> [força 0-1]   muda a tinta do goblin do time
  test <time> <texto>       testa o TTS/goblin de um time
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
            out = self._mutate(cmd, args, s, v)
            # Speaker removed from the game loses the voice too.
            if cmd in ("remove", "clear") and v.active and s.where(v.active) is None:
                v.stop()
                cmd = "stop"
            if cmd in ("voice", "next", "give", "stop"):
                await self.interrupt()
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
        if cmd == "channel":
            need(1, "channel <canal|off>")
            channel = "" if args[0].lower() == "off" else args[0]
            self.start_chat(channel)
            self.persist({"twitch": {"channel": self.channel}})
            return f"chat: #{self.channel}" if self.channel else "chat desligado"
        if cmd in ("voice", "next"):
            team = args[0] if cmd == "voice" and args else None
            user = v.pick_random(team)
            return f"voz para {s.name(user)} ({v.active_team or 'sem time'})"
        if cmd == "give":
            need(1, "give <user>")
            user = v.give(args[0])
            return f"voz para {s.name(user)} ({v.active_team or 'sem time'})"
        if cmd == "stop":
            prev = v.stop()
            return f"voz retirada de {s.name(prev)}" if prev else "ninguém tinha a voz"
        raise SorterError(f"comando desconhecido: {cmd} (digite help)")

    def describe(self) -> str:
        s, v = self.sorter, self.voice
        lines = [f"fila ({'aberta' if s.queue_open else 'fechada'}): {', '.join(map(s.name, s.queue)) or '-'}"]
        for team, members in s.teams.items():
            lines.append(f"  {team:8} ({len(members)}): {', '.join(map(s.name, members)) or '-'}")
        lines.append(f"voz: {s.name(v.active) + ' (' + (v.active_team or 'sem time') + ')' if v.active else '-'}")
        return "\n".join(lines)


__all__ = ["App", "ANY", "strip_emotes"]

"""Glue: chat -> sorter/voice -> TTS -> overlay. Operator commands live here so the
console, the HTTP API and the future frontend all share the same actions."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
from collections import Counter
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
    chat: bool = False  # from a speaker's chat message (dropped if they lose the voice)


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
        self.voice = VoiceController(self.sorter, multi=bool(self.cfg.get("voice", {}).get("multi", False)))
        self.tts.team_profiles.update(self.cfg.get("tts", {}).get("team_profiles", {}))
        self.tints = load_tints(tcfg)
        tw = self.cfg.get("twitch", {})
        self.join_cmds = {c.lower() for c in tw.get("join_commands", ["!joinsort", "!joinsorting"])}
        self.leave_cmds = {c.lower() for c in tw.get("leave_commands", ["!leavesort"])}
        self.tts_cfg = self.cfg.get("tts", {})
        self.clients: set = set()          # overlay/frontend websockets
        # websocket -> {"role": "overlay" | "panel", "team": pinned team | None, "audio": bool}
        self.overlays: dict = {}
        self.audio: dict[int, bytes] = {}  # utterance id -> wav, served at /audio/<id>.wav
        self.speech_q: asyncio.Queue[Utterance] = asyncio.Queue()
        self.ended = asyncio.Event()
        self.gen = 0                       # bumped on stop/speaker change to discard stale speech
        self.ids = itertools.count(1)
        self.speaking: Utterance | None = None
        self.pending: Counter[str] = Counter()  # queued utterances per user
        self.tts_service = None  # TTSService, set by __main__
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
            # "voice" = most recent speaker; "speakers" = everyone with the voice (one per team in multi mode)
            "voice": {"id": self.voice.active,
                      "user": self.sorter.name(self.voice.active) if self.voice.active else None,
                      "team": self.voice.active_team},
            "speakers": [{"id": u, "user": self.sorter.name(u), "team": t} for u, t in self.voice.speakers()],
            "multi_voice": self.voice.multi,
            # OBS sources currently connected (panels, which only play as a last resort, aren't listed)
            "overlays": [{"team": info["team"], "audio": info["audio"]} for ws, info in self.overlays.items()
                         if ws in self.clients and info.get("role", "overlay") == "overlay"],
            "speaking": self.speaking.team if self.speaking else None,
            "tints": self.tints,
            "chat": {"channel": self.channel, "status": self.chat_status},
            "tts_engine": self.tts.engine.name,
            "tts_error": self.tts.error,
            "team_profiles": self.tts.team_profiles,
            "data_dir": str(self.settings_path.parent) if self.settings_path else None,
        }

    async def _send(self, ws, msg: dict) -> None:
        try:
            await ws.send_str(json.dumps(msg))
        except Exception:
            self.clients.discard(ws)
            self.overlays.pop(ws, None)

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self.clients):
            await self._send(ws, msg)

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
        elif self.voice.is_speaker(msg.login):
            await self.say(msg.display, strip_emotes(msg.text, msg.tags.get("emotes", "")), msg.login, chat=True)

    async def say(self, display: str, text: str, login: str | None = None, team: str | None = None,
                  chat: bool = False) -> bool:
        text = URL_RE.sub("", text).strip()
        if not text or (self.tts_cfg.get("skip_commands", True) and text.startswith("!")):
            return False
        user = (login or display).lower()
        # the limit is per speaker, so one chatty speaker can't crowd out the other teams
        if self.pending[user] >= int(self.tts_cfg.get("max_queue", 5)):
            log.info("fila de fala de %s cheia, ignorando: %s", display, text)
            return False
        team = team or (self.sorter.team_of(login) if login else None)
        self.pending[user] += 1
        self.speech_q.put_nowait(Utterance(next(self.ids), user, display, team, text, self.gen, chat))
        return True

    def _stale(self, utt: Utterance) -> bool:
        return utt.gen != self.gen or (utt.chat and not self.voice.is_speaker(utt.user))

    # ---- speech pipeline -----------------------------------------------

    async def speech_worker(self) -> None:
        while True:
            utt = await self.speech_q.get()
            self.pending[utt.user] -= 1
            if self._stale(utt):
                continue
            try:
                wav = await self.tts.synthesize(utt.text, utt.team)
            except Exception as e:
                log.warning("falha no TTS: %s", e)
                await self.broadcast({"type": "notice", "text": f"TTS falhou: {e}"})
                continue
            if self._stale(utt):
                continue
            if not self.clients:
                log.warning("nenhum overlay conectado; fala descartada: %s", utt.text)
                continue
            self.audio[utt.id] = wav
            self.speaking = utt
            self.ended.clear()
            log.info("[%s/%s] %s", utt.display, utt.team or "-", utt.text)
            # Everyone gets the line (to animate); exactly one overlay is told to play its audio.
            player = self.pick_player(utt.team)
            msg = {"type": "speak", "id": utt.id, "url": f"/audio/{utt.id}.wav",
                   "team": utt.team, "user": utt.display, "text": utt.text}
            for ws in list(self.clients):
                await self._send(ws, {**msg, "play": ws is player})
            if player is None:
                await self.broadcast({"type": "notice", "text":
                                      f"nenhum overlay com áudio para {'o time ' + utt.team if utt.team else 'quem está sem time'}"})
            try:
                # without a player nobody will report the end: just animate for the clip's length
                await asyncio.wait_for(self.ended.wait(), timeout=wav_duration(wav) + (3 if player else 0))
            except asyncio.TimeoutError:
                log.debug("overlay não confirmou fim do áudio %s", utt.id)
            self.speaking = None
            self.audio.pop(utt.id, None)
            await self.broadcast({"type": "idle", "id": utt.id})

    def on_audio_ended(self, utt_id: int) -> None:
        if self.speaking and self.speaking.id == utt_id:
            self.ended.set()

    async def interrupt(self, users: set[str] | None = None) -> None:
        """Drop queued speech and cut the current audio: everyone's (users=None) or only these users'."""
        if users is None:
            self.gen += 1
        kept = []
        while not self.speech_q.empty():
            utt = self.speech_q.get_nowait()
            if users is None or utt.user in users:
                self.pending[utt.user] -= 1
            else:
                kept.append(utt)
        for utt in kept:
            self.speech_q.put_nowait(utt)
        if self.speaking and (users is None or self.speaking.user in users):
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
  next [time]               outra pessoa do mesmo time
  give <user>               dá voz a alguém específico
  stop [time|user]          tira a voz (sem arg = de todos) e para o áudio
  multivoice <on|off>       um falante por time ao mesmo tempo
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
            before = set(v.users)
            out = self._mutate(cmd, args, s, v)
            # A speaker removed from the game loses the voice too.
            if cmd == "remove":
                v.prune(lambda u: u != args[0].lower())
            elif cmd == "clear":
                v.prune(lambda u: s.where(u) is not None)
            if cmd == "stop" and not args:
                await self.interrupt()  # everything, including test lines
            elif lost := before - set(v.users):
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
            if args[1].lower() == "none":
                self.tts.team_profiles.pop(team, None)
            else:
                self.tts.team_profiles[team] = args[1]
            # replace (not merge) so removals are saved too
            self.settings.setdefault("tts", {})["team_profiles"] = dict(self.tts.team_profiles)
            self.persist({})
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

"""Anonymous (read-only) Twitch chat reader over IRC. No OAuth needed."""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
from dataclasses import dataclass
from typing import AsyncIterator, Callable

log = logging.getLogger(__name__)

HOST, PORT = "irc.chat.twitch.tv", 6697


@dataclass
class ChatMessage:
    login: str
    display: str
    text: str
    tags: dict[str, str]


def parse_line(line: str) -> tuple[dict[str, str], str, str, list[str]]:
    """Returns (tags, prefix, command, params). The trailing param is the last element."""
    tags: dict[str, str] = {}
    if line.startswith("@"):
        raw, line = line[1:].split(" ", 1)
        for item in raw.split(";"):
            k, _, v = item.partition("=")
            tags[k] = v
    prefix = ""
    if line.startswith(":"):
        prefix, line = line[1:].split(" ", 1)
    if " :" in line:
        line, trailing = line.split(" :", 1)
        params = line.split() + [trailing]
    else:
        params = line.split()
    command = params.pop(0) if params else ""
    return tags, prefix, command, params


async def read_chat(channel: str, on_status: Callable[[str], None] = lambda s: None) -> AsyncIterator[ChatMessage]:
    """Yields chat messages forever, reconnecting with backoff.
    on_status gets 'conectado' once the channel is joined and 'reconectando' on drops."""
    channel = channel.lower().lstrip("#")
    backoff = 1
    while True:
        writer = None
        try:
            reader, writer = await asyncio.open_connection(HOST, PORT, ssl=ssl.create_default_context())
            nick = f"justinfan{random.randint(10000, 99999)}"
            writer.write(
                f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\nPASS SCHMOOPIIE\r\nNICK {nick}\r\nJOIN #{channel}\r\n".encode()
            )
            await writer.drain()
            log.info("conectado ao chat de #%s como %s", channel, nick)
            backoff = 1
            while True:
                raw = await asyncio.wait_for(reader.readline(), timeout=360)
                if not raw:
                    raise ConnectionError("conexão fechada")
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if not line:
                    continue
                tags, prefix, command, params = parse_line(line)
                if command == "PING":
                    writer.write(f"PONG :{params[-1] if params else 'tmi.twitch.tv'}\r\n".encode())
                    await writer.drain()
                elif command == "ROOMSTATE":
                    on_status("conectado")
                elif command == "RECONNECT":
                    raise ConnectionError("servidor pediu reconexão")
                elif command == "PRIVMSG" and len(params) >= 2:
                    login = prefix.split("!", 1)[0]
                    text = params[-1]
                    if text.startswith("\x01ACTION ") and text.endswith("\x01"):  # /me
                        text = text[8:-1]
                    yield ChatMessage(login, tags.get("display-name") or login, text, tags)
        except (OSError, ConnectionError, asyncio.TimeoutError) as e:
            log.warning("chat desconectado (%s); reconectando em %ss", e, backoff)
            on_status("reconectando")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        finally:
            if writer:
                writer.close()

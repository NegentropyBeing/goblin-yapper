"""Text the operator reads, kept apart from the code that decides what to say.

The server never sends a sentence: it sends a Message, a key plus values ({"key": "err.unknown_team",
"params": {"team": "x"}}). The panel looks the key up in the catalog of the language the operator chose
(web/i18n/<language>.json); English is the reference. `str(message)` renders it in English, for the console,
the logs and the "output" field of the HTTP API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

LANGUAGES = ("en", "pt-BR")
CATALOGS = Path(__file__).resolve().parent / "web" / "i18n"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=None)
def catalog(language: str = "en") -> dict:
    return json.loads((CATALOGS / f"{language}.json").read_text(encoding="utf-8"))


def render(key: str, params: dict | None = None, language: str = "en") -> str:
    """The key's text in `language` (English when that language lacks it, the key itself when nobody has it)."""
    text = catalog(language).get(key) or catalog("en").get(key, key)
    values = params or {}
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


@dataclass(frozen=True)
class Message:
    key: str
    params: dict = field(default_factory=dict)
    ok: bool = True

    def __str__(self) -> str:
        text = render(self.key, self.params)
        return text if self.ok else render("err.prefix", {"error": text})

    def payload(self) -> dict:
        """What goes over the wire, to the panel and to API clients."""
        return {"ok": self.ok, "key": self.key, "params": self.params, "output": str(self)}


class MessageError(Exception):
    """An error the operator is told about: raised with a key and values, shown in their language."""

    def __init__(self, key: str, **params):
        self.message = Message(key, params, ok=False)
        super().__init__(render(key, params))


def notice(key: str, *, ok: bool = False, **params) -> dict:
    """A notice for the panel's toast. Red unless `ok`."""
    out = {"type": "notice", "key": key, "params": params, "text": render(key, params)}
    if ok:
        out["ok"] = True
    return out


def notice_many(items: list[Message]) -> dict:
    """Several good-news notices shown together, one toast: the panel joins them with '; '."""
    return {"type": "notice", "ok": True, "items": [{"key": m.key, "params": m.params} for m in items],
            "text": "; ".join(str(m) for m in items)}

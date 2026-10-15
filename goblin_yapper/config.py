"""Layered settings: config.toml (hand-written, comments untouched) under settings.json (what the
operator changed in the panel).

Interface: Config(base, settings_path) reads and merges both; `data` is the merged dict, `section(name)`
one part of it; `update(patch)` merges a change in and saves it; `replace(path, value)` swaps a whole
value (so removals persist too); `data_dir` is where settings.json lives.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    def __init__(self, base: dict | None = None, settings_path: Path | None = None):
        self.settings_path = settings_path
        self.settings: dict = {}
        if settings_path and settings_path.exists():
            try:
                self.settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except ValueError:
                log.warning("settings.json inválido, ignorando")
        self.data = deep_merge(json.loads(json.dumps(base or {})), self.settings)

    @property
    def data_dir(self) -> Path | None:
        return self.settings_path.parent if self.settings_path else None

    def section(self, name: str) -> dict:
        return self.data.get(name, {})

    def update(self, patch: dict) -> None:
        deep_merge(self.settings, patch)
        deep_merge(self.data, json.loads(json.dumps(patch)))
        self._save()

    def replace(self, path: tuple[str, ...], value) -> None:
        """Set `value` at `path`, replacing what was there (update() would only merge into it)."""
        for tree in (self.settings, self.data):
            node = tree
            for key in path[:-1]:
                node = node.setdefault(key, {})
            node[path[-1]] = json.loads(json.dumps(value))
        self._save()

    def _save(self) -> None:
        if self.settings_path:
            self.settings_path.write_text(json.dumps(self.settings, indent=2, ensure_ascii=False), encoding="utf-8")

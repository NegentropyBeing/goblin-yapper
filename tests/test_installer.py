"""The Windows installer is one .msi per interface language (the panel itself speaks both)."""

import json
from pathlib import Path

CONF = Path(__file__).resolve().parent.parent / "app" / "src-tauri" / "tauri.conf.json"


def test_the_installer_is_built_in_english_and_portuguese():
    bundle = json.loads(CONF.read_text(encoding="utf-8"))["bundle"]
    assert "msi" in bundle["targets"]
    assert bundle["windows"]["wix"]["language"] == ["en-US", "pt-BR"]

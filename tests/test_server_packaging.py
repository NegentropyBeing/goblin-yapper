"""The TTS server's code is copied into the voice runtime and bundled into the installer from explicit lists;
a module missing from either crashes the server on import (it happened with profiles.py in v0.6.0)."""

from pathlib import Path

from goblin_yapper.tts_install import SERVER_FILES

ROOT = Path(__file__).resolve().parent.parent
TTS = ROOT / "tts_server"
SOURCES = sorted(p.relative_to(TTS).as_posix() for p in TTS.rglob("*.py") if ".venv" not in p.parts
                 and "__pycache__" not in p.parts)


def test_runtime_copies_every_server_module():
    assert set(SERVER_FILES) - {"requirements.txt"} == set(SOURCES)


def test_installer_bundles_every_server_module():
    build = (ROOT / "build.ps1").read_text(encoding="utf-8")
    for rel in SOURCES:
        bundled = f"$tts\{rel}" if "/" not in rel else "$tts\engines\*.py"
        assert bundled in build, f"{rel} is not bundled by build.ps1"

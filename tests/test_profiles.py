import asyncio
import json
import wave

import pytest

from tts_server.profiles import NotFound, Params, ProfileError, ProfileStore, slugify


class P:
    """A synthesis parameter, as the engine declares them."""

    def __init__(self, key, default, lo=None, hi=None):
        self.key, self.default, self.lo, self.hi = key, default, lo, hi

    def coerce(self, v):
        v = float(v)
        return max(self.lo, v) if self.lo is not None and v < self.lo else min(self.hi, v) if self.hi is not None and v > self.hi else v


def _params(tmp_path):
    return Params(lambda: [P("speed", 1.0, 0.5, 2.0), P("temp", 0.7)], tmp_path / "settings.json")


def _draft(tmp_path, name="d1"):
    d = tmp_path / name
    d.mkdir()
    with wave.open(str(d / "reference.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(b"\0\0" * 8000)
    return d


def _store(tmp_path):
    return ProfileStore(tmp_path / "profiles", "voice.bin", _params(tmp_path), "fake", duration=lambda p: 1.0)


async def _build(wav, text, cache):
    cache.write_text(text)


def test_params_precedence_engine_default_global_then_each_layer():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as t:
        params = _params(Path(t))
        assert params.resolve() == {"speed": 1.0, "temp": 0.7}
        params.save({"speed": 1.5, "bogus": 3})
        assert params.settings() == {"params": {"speed": 1.5}}  # unknown keys dropped
        assert params.resolve() == {"speed": 1.5, "temp": 0.7}
        assert params.resolve({"speed": 1.8}, {"temp": 0.2}, {"speed": 9}) == {"speed": 2.0, "temp": 0.2}  # last wins, clamped
        assert params.resolve({"speed": None}) == {"speed": 1.5, "temp": 0.7}  # None doesn't override


def test_params_read_the_settings_file_once_per_resolve(tmp_path, monkeypatch):
    params = _params(tmp_path)
    reads = []
    monkeypatch.setattr(params, "settings", lambda: reads.append(1) or {"params": {}})
    params.resolve()
    assert len(reads) == 1


def test_slugify():
    assert slugify("Narrador Épico!") == "narrador-epico"
    assert slugify("???") == "voz"


def test_create_builds_the_voice_lists_it_and_removes_the_draft(tmp_path):
    async def run():
        store = _store(tmp_path)
        draft = _draft(tmp_path)
        meta = await store.create(draft, "  Goblin Azul ", " olá ", {"speed": 9, "x": 1}, _build)
        assert meta["id"].startswith("goblin-azul-") and meta["name"] == "Goblin Azul"
        assert meta["ref_text"] == "olá" and meta["ready"] is True and meta["params"] == {"speed": 2.0}
        assert not draft.exists()
        assert [m["id"] for m in store.list()] == [meta["id"]]
        cache, own = store.for_synthesis(meta["id"])
        assert cache.read_text() == "olá" and own == {"speed": 2.0}

    asyncio.run(run())


def test_a_failed_build_leaves_no_profile_and_keeps_the_draft(tmp_path):
    async def run():
        store = _store(tmp_path)
        draft = _draft(tmp_path)

        async def boom(*_):
            raise RuntimeError("sem GPU")

        with pytest.raises(RuntimeError):
            await store.create(draft, "Voz", "texto", {}, boom)
        assert store.list() == [] and list((tmp_path / "profiles").iterdir()) == [] and draft.exists()

    asyncio.run(run())


def test_create_needs_a_name_and_a_transcript(tmp_path):
    async def run():
        with pytest.raises(ProfileError, match="obrigatórios"):
            await _store(tmp_path).create(_draft(tmp_path), "  ", "texto", {}, _build)

    asyncio.run(run())


def test_update_renames_sets_params_and_rebuilds_only_for_a_new_transcript(tmp_path):
    async def run():
        store = _store(tmp_path)
        meta = await store.create(_draft(tmp_path), "Voz", "um", {}, _build)
        built = []

        async def build(wav, text, cache):
            built.append(text)
            await _build(wav, text, cache)

        out = await store.update(meta["id"], {"name": " Nova ", "params": {"temp": 0.1}, "ref_text": "um"}, build)
        assert out["name"] == "Nova" and out["params"] == {"temp": 0.1} and built == []
        out = await store.update(meta["id"], {"ref_text": "dois"}, build)
        assert out["ref_text"] == "dois" and built == ["dois"]
        assert json.loads((tmp_path / "profiles" / meta["id"] / "profile.json").read_text())["ref_text"] == "dois"

    asyncio.run(run())


def test_delete_returns_the_name_and_unknown_or_unsafe_ids_are_not_found(tmp_path):
    async def run():
        store = _store(tmp_path)
        meta = await store.create(_draft(tmp_path), "Voz", "um", {}, _build)
        assert store.delete(meta["id"]) == "Voz"
        for pid in (meta["id"], "../etc", "NOPE"):
            with pytest.raises(NotFound):
                store.read(pid)
        assert NotFound.status == 404

    asyncio.run(run())

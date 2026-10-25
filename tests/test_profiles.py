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
    return Params(lambda: [P("speed", 1.0, 0.5, 2.0), P("temp", 0.7)], tmp_path / "settings.json", "fake")


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
        with pytest.raises(ProfileError, match="are required"):
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


# ---- shared by every engine: parameters per engine, each engine's own cached voice


def _profile_dir(tmp_path, pid="velho-0001", params=None, engine="omnivoice", caches=("omnivoice.pt",)):
    """A profile folder as an earlier version left it."""
    d = tmp_path / "profiles" / pid
    d.mkdir(parents=True)
    meta = {"id": pid, "name": "Velho", "ref_text": "olá", "created": 1.0, "duration": 1.0,
            "engine": engine, "params": params if params is not None else {"speed": 1.2}}
    (d / "profile.json").write_text(json.dumps(meta))
    (d / "reference.wav").write_bytes(b"RIFF")
    for c in caches:
        (d / c).write_text("old")
    return d


def test_settings_from_before_are_omnivoices_and_each_engine_keeps_its_own(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"params": {"speed": 1.5}}))
    omni = Params(lambda: [P("speed", 1.0)], tmp_path / "settings.json", "omnivoice")
    qwen = Params(lambda: [P("temp", 0.9)], tmp_path / "settings.json", "qwen")
    assert omni.settings() == {"params": {"speed": 1.5}}
    assert qwen.settings() == {"params": {}} and qwen.resolve() == {"temp": 0.9}
    assert qwen.save({"temp": 0.5, "speed": 2}) == {"params": {"temp": 0.5}}
    assert json.loads((tmp_path / "settings.json").read_text()) == {"params": {"omnivoice": {"speed": 1.5}, "qwen": {"temp": 0.5}}}
    assert omni.resolve() == {"speed": 1.5}


def test_a_broken_settings_file_reads_as_empty(tmp_path):
    (tmp_path / "settings.json").write_text("[1, 2]")
    assert _params(tmp_path).settings() == {"params": {}}


def test_profile_params_from_before_belong_to_the_engine_that_made_the_profile(tmp_path):
    async def run():
        _profile_dir(tmp_path)
        params = Params(lambda: [P("temp", 0.9)], tmp_path / "settings.json", "qwen")
        qwen = ProfileStore(tmp_path / "profiles", "qwen3tts.pt", params, "qwen")
        omni = ProfileStore(tmp_path / "profiles", "omnivoice.pt", _params(tmp_path), "omnivoice")
        assert omni.read("velho-0001")["params"] == {"speed": 1.2}
        meta = qwen.read("velho-0001")
        assert meta["params"] == {} and meta["ready"] is False
        await qwen.update("velho-0001", {"params": {"temp": 0.3}}, _build)
        on_disk = json.loads((tmp_path / "profiles" / "velho-0001" / "profile.json").read_text())
        assert on_disk["params"] == {"omnivoice": {"speed": 1.2}, "qwen": {"temp": 0.3}}
        assert omni.read("velho-0001")["params"] == {"speed": 1.2} and qwen.read("velho-0001")["params"] == {"temp": 0.3}

    asyncio.run(run())


def test_another_engine_sees_the_profile_and_builds_its_missing_voice(tmp_path):
    async def run():
        d = _profile_dir(tmp_path)
        qwen = ProfileStore(tmp_path / "profiles", "qwen3tts.pt", _params(tmp_path), "qwen")
        assert qwen.missing() == ["velho-0001"]
        await qwen.build_missing("velho-0001", _build)
        assert (d / "qwen3tts.pt").read_text() == "olá" and (d / "omnivoice.pt").read_text() == "old"
        assert qwen.missing() == [] and qwen.read("velho-0001")["ready"] is True

        async def never(*_):
            raise AssertionError("already built")

        await qwen.build_missing("velho-0001", never)

    asyncio.run(run())


def test_a_new_transcript_drops_the_other_engines_stale_voices(tmp_path):
    async def run():
        d = _profile_dir(tmp_path, caches=("omnivoice.pt", "qwen3tts-0.6b.pt", "qwen3tts-1.7b.pt"))
        qwen = ProfileStore(tmp_path / "profiles", "qwen3tts-1.7b.pt", _params(tmp_path), "qwen")
        await qwen.update("velho-0001", {"ref_text": "novo"}, _build)
        assert sorted(f.name for f in d.iterdir()) == ["profile.json", "qwen3tts-1.7b.pt", "reference.wav"]
        assert (d / "qwen3tts-1.7b.pt").read_text() == "novo"

    asyncio.run(run())


def test_a_failed_rebuild_keeps_every_voice(tmp_path):
    async def run():
        d = _profile_dir(tmp_path, caches=("omnivoice.pt", "qwen3tts.pt"))
        qwen = ProfileStore(tmp_path / "profiles", "qwen3tts.pt", _params(tmp_path), "qwen")

        async def boom(*_):
            raise RuntimeError("sem GPU")

        with pytest.raises(RuntimeError):
            await qwen.update("velho-0001", {"ref_text": "novo"}, boom)
        assert (d / "omnivoice.pt").exists() and qwen.read("velho-0001")["ref_text"] == "olá"

    asyncio.run(run())

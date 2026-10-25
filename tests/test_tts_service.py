"""Which voice model the app's TTS server runs, and in which Python environment: each engine has its own
(qwen-tts and OmniVoice need different transformers), and switching model restarts the server."""

import asyncio

import pytest

from goblin_yapper import tts_service
from goblin_yapper.i18n import MessageError
from goblin_yapper.tts_install import VoiceInstaller
from goblin_yapper.tts_service import TTSService


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A source checkout with no environments yet; make(env) creates tts_server/<env>."""
    root = tmp_path / "project"
    (root / "tts_server").mkdir(parents=True)
    (root / "tts_server" / "server.py").write_text("")
    monkeypatch.setattr(tts_service, "PROJECT_ROOT", root)
    monkeypatch.setattr(tts_service, "VoiceInstaller", lambda: VoiceInstaller(tmp_path / "runtime"))

    def make(env):
        python = root / "tts_server" / env / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_text("")
        return python

    return make


def _service(tmp_path, **cfg):
    return TTSService(cfg, tmp_path)


def test_each_engine_runs_in_its_own_environment(tmp_path, project):
    omni, qwen = project(".venv"), project(".venv-qwen")
    assert _service(tmp_path).python == omni
    svc = _service(tmp_path, engine="qwen")
    assert svc.python == qwen and not svc.uses_runtime and svc.installed


def test_qwen_is_never_the_installed_runtime(tmp_path, project):
    svc = _service(tmp_path, engine="qwen")
    assert not svc.uses_runtime and not svc.installed  # no .venv-qwen: not installed, not "install it for me"
    assert _service(tmp_path).uses_runtime  # OmniVoice without tts_server/.venv falls back to the runtime


def test_a_python_set_by_hand_is_used_for_every_engine(tmp_path, project):
    svc = _service(tmp_path, engine="qwen", python="C:/mine/python.exe")
    assert str(svc.python).replace("\\", "/") == "C:/mine/python.exe"


def test_the_models_on_offer_say_which_are_installed_and_how_to_install_the_rest(tmp_path, project):
    project(".venv")
    models = {m["id"]: m for m in _service(tmp_path).models()}
    assert list(models) == ["omnivoice", "qwen-1.7b", "qwen-0.6b"]
    assert models["omnivoice"]["installed"] and "setup" not in models["omnivoice"]
    assert not models["qwen-0.6b"]["installed"] and models["qwen-0.6b"]["setup"] == "tts_server\\setup-qwen.ps1"


def test_the_choice_follows_the_engine_and_model_in_the_config(tmp_path, project):
    assert _service(tmp_path).choice == "omnivoice"
    assert _service(tmp_path, engine="qwen").choice == "qwen-1.7b"  # no model: the engine's default
    assert _service(tmp_path, engine="qwen", model="Qwen/Qwen3-TTS-12Hz-0.6B-Base").choice == "qwen-0.6b"
    assert _service(tmp_path, engine="qwen", model="D:/my-finetune").choice is None


def test_the_server_gets_the_model_and_the_load_options_set_by_hand(tmp_path, project):
    assert _service(tmp_path)._model_args() == []
    svc = _service(tmp_path, engine="qwen", model="Qwen/Qwen3-TTS-12Hz-0.6B-Base", dtype="float16", attn="eager")
    assert svc._model_args() == ["--model", "Qwen/Qwen3-TTS-12Hz-0.6B-Base", "--dtype", "float16", "--attn", "eager"]


def _recording(svc):
    calls = []

    async def stop():
        calls.append("stop")

    async def start():
        calls.append(("start", svc.engine, svc.model, svc.python.parent.parent.name))

    svc.stop, svc.start = stop, start
    return calls


def test_switching_model_restarts_the_server_in_the_new_environment(tmp_path, project):
    project(".venv"), project(".venv-qwen")
    svc = _service(tmp_path)
    calls = _recording(svc)
    asyncio.run(svc.set_model("qwen-0.6b"))
    assert calls == ["stop", ("start", "qwen", "Qwen/Qwen3-TTS-12Hz-0.6B-Base", ".venv-qwen")]
    assert svc.choice == "qwen-0.6b"
    asyncio.run(svc.set_model("omnivoice"))
    assert calls[-1] == ("start", "omnivoice", None, ".venv") and svc.choice == "omnivoice"


def test_a_model_that_is_not_installed_or_unknown_leaves_the_server_alone(tmp_path, project):
    project(".venv")
    svc = _service(tmp_path)
    calls = _recording(svc)
    with pytest.raises(MessageError) as e:
        asyncio.run(svc.set_model("qwen-1.7b"))
    assert e.value.message.key == "tts.model_not_installed" and e.value.message.params["script"] == "tts_server\\setup-qwen.ps1"
    with pytest.raises(MessageError) as e:
        asyncio.run(svc.set_model("nope"))
    assert e.value.message.key == "tts.unknown_model"
    assert calls == [] and svc.choice == "omnivoice"


def test_a_server_started_outside_the_app_is_not_switched(tmp_path, project):
    project(".venv-qwen")
    svc = _service(tmp_path)
    svc.mode = "external"
    with pytest.raises(MessageError) as e:
        asyncio.run(svc.set_model("qwen-1.7b"))
    assert e.value.message.key == "tts.external_restart"

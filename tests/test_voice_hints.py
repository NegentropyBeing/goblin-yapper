"""The voice style terms and speech tags the panel offers in its hint menus.

The voice server itself (server.py, audio.py) needs numpy and soundfile, which only its own environment has;
these tests talk to the engine, which /schema passes the hints on from."""

import json
from pathlib import Path

from tts_server.engines.omnivoice_engine import OmniVoiceEngine

I18N = Path(__file__).resolve().parent.parent / "goblin_yapper" / "web" / "i18n"


def test_omnivoice_lists_the_voice_style_terms_one_kind_at_a_time():
    style = OmniVoiceEngine({}).hints()["style"]
    assert [kind["kind"] for kind in style] == ["gender", "age", "pitch", "style", "accent"]
    terms = {kind["kind"]: kind["terms"] for kind in style}
    assert terms["gender"] == ["male", "female"]
    assert terms["age"] == ["child", "teenager", "young adult", "middle-aged", "elderly"]
    assert terms["pitch"] == ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"]
    assert terms["style"] == ["whisper"]
    assert "british accent" in terms["accent"] and len(terms["accent"]) == 10
    # the Chinese dialects only work in Chinese text: left out of the menu
    assert not any("话" in t for kind in style for t in kind["terms"])


def test_omnivoice_names_the_parameter_its_voice_style_goes_in():
    engine = OmniVoiceEngine({})
    assert engine.hints()["style_param"] == "instruct"
    assert "instruct" in {p.key for p in engine.params()}


def test_omnivoice_lists_the_speech_tags():
    tags = OmniVoiceEngine({}).hints()["tags"]
    assert tags[:2] == ["[laughter]", "[sigh]"]
    assert "[surprise-ah]" in tags and "[dissatisfaction-hnn]" in tags
    assert len(tags) == 13


def test_every_term_tag_and_kind_has_a_name_in_both_languages():
    # the panel names them from the catalog: style_kind.<kind>, style.<term> (spaces as _), tag.<tag without []>
    hints = OmniVoiceEngine({}).hints()
    keys = {f"style_kind.{kind['kind']}" for kind in hints["style"]}
    keys |= {f"style.{term.replace(' ', '_')}" for kind in hints["style"] for term in kind["terms"]}
    keys |= {f"tag.{tag.strip('[]')}" for tag in hints["tags"]}
    for lang in ("en", "pt-BR"):
        catalog = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
        assert sorted(keys - set(catalog)) == [], f"{lang}.json lacks names for these hints"

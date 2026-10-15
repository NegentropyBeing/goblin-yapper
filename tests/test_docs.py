"""Each bilingual document is a pair: English is the default file, Portuguese carries the .pt-BR suffix, and
each one links to the other at the top. English docs name the interface by its English labels."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAIRS = [("README", ROOT), ("DEVELOPMENT", ROOT / "docs"), ("TESTE", ROOT / "docs")]
LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")


def doc(name: str, folder: Path, lang: str) -> Path:
    return folder / (f"{name}.md" if lang == "en" else f"{name}.pt-BR.md")


def test_every_document_exists_in_both_languages_and_links_to_its_twin():
    for name, folder in PAIRS:
        en, pt = doc(name, folder, "en"), doc(name, folder, "pt-BR")
        assert en.exists() and pt.exists(), f"{name} needs both {en.name} and {pt.name}"
        assert pt.name in "\n".join(en.read_text(encoding="utf-8").splitlines()[:12]), f"{en.name} must link to {pt.name} at the top"
        assert en.name in "\n".join(pt.read_text(encoding="utf-8").splitlines()[:12]), f"{pt.name} must link to {en.name} at the top"


def test_portuguese_documents_link_to_portuguese_documents():
    for name, folder in PAIRS:
        pt = doc(name, folder, "pt-BR")
        for target in LINK.findall(pt.read_text(encoding="utf-8")):
            twin = (pt.parent / target).resolve()
            if twin == doc(name, folder, "en").resolve():
                continue  # the link to its English twin, at the top
            if twin.name.endswith(".pt-BR.md") or twin.name in ("CHANGELOG.md", "SPEC.md") or not twin.exists():
                continue
            assert not twin.with_name(twin.stem + ".pt-BR.md").exists(), f"{pt.name} links to {target}, which has a pt-BR twin"


def test_english_documents_name_the_interface_in_english():
    catalog = {lang: json.loads((ROOT / "goblin_yapper" / "web" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
               for lang in ("en", "pt-BR")}
    labels = {catalog["pt-BR"][k].lstrip("⏭⏹🎤🔊 ") for k in catalog["en"]  # the icon in front of a label is not part of its name
              if k.split(".")[0] in ("btn", "queue") and catalog["pt-BR"][k] != catalog["en"][k]}
    labels = {label for label in labels if len(label) > 4}
    assert labels, "no button labels to check"
    for name, folder in PAIRS:
        text = doc(name, folder, "en").read_text(encoding="utf-8") if doc(name, folder, "en").exists() else ""
        leaked = sorted(label for label in labels if label in text)
        assert leaked == [], f"{name}.md names the interface in Portuguese: {leaked}"

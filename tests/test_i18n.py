"""The panel and the overlay read their text from one catalog per language. English is the reference:
every key is born there, and pt-BR must carry exactly the same keys."""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "goblin_yapper" / "web"
I18N = WEB / "i18n"
PAGES = ("panel.html", "overlay.html")
# Keys used in markup (data-i18n="key", data-i18n-title="key", ...) and in scripts (t("key"), t('key')).
MARKUP_KEY = re.compile(r'data-i18n(?:-[a-z]+)?="([^"]+)"')
SCRIPT_KEY = re.compile(r"""\bt\(\s*["']([A-Za-z0-9_.]+)["']""")


def catalog(lang: str) -> dict:
    return json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))


def used_keys() -> dict[str, set[str]]:
    used = {}
    for name in PAGES:
        text = (WEB / name).read_text(encoding="utf-8")
        used[name] = set(MARKUP_KEY.findall(text)) | set(SCRIPT_KEY.findall(text))
    return used


def test_both_catalogs_carry_the_same_keys():
    en, pt = catalog("en"), catalog("pt-BR")
    assert set(pt) - set(en) == set(), "keys in pt-BR with no English source"
    assert set(en) - set(pt) == set(), "keys not translated to pt-BR yet"


def test_no_catalog_entry_is_empty():
    for lang in ("en", "pt-BR"):
        empty = [k for k, v in catalog(lang).items() if not str(v).strip()]
        assert empty == [], f"{lang} has empty text for {empty}"


def test_every_key_the_pages_use_exists_in_english():
    en = catalog("en")
    for name, keys in used_keys().items():
        assert sorted(keys - set(en)) == [], f"{name} uses keys missing from en.json"


def test_every_key_the_server_sends_exists_in_both_languages():
    # message keys are literals in the Python sources: "msg.queue_open", "err.usage", "notice.queue_closed", ...
    sent = set()
    for source in (WEB.parent).glob("*.py"):
        sent |= set(re.findall(r'"((?:msg|err|notice|http|tts)\.[a-z_]+)"', source.read_text(encoding="utf-8")))
    assert sent, "found no message keys in the server sources"
    for lang in ("en", "pt-BR"):
        assert sorted(sent - set(catalog(lang))) == [], f"{lang}.json lacks keys the server sends"


def test_the_panel_uses_the_catalog_at_all():
    assert used_keys()["panel.html"], "panel.html has no data-i18n or t(...) keys"

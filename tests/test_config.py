import json

from goblin_yapper.config import Config, deep_merge


def test_deep_merge_merges_dicts_and_replaces_everything_else():
    base = {"a": {"x": 1, "y": 2}, "list": [1], "keep": 1}
    assert deep_merge(base, {"a": {"y": 3}, "list": [2], "new": {"z": 1}}) == \
        {"a": {"x": 1, "y": 3}, "list": [2], "keep": 1, "new": {"z": 1}}


def test_settings_json_layers_over_the_base_and_the_base_is_not_mutated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"tts": {"engine": "sapi"}}', encoding="utf-8")
    base = {"tts": {"engine": "dummy", "max_queue": 5}}
    cfg = Config(base, path)
    assert cfg.section("tts") == {"engine": "sapi", "max_queue": 5}
    assert base["tts"]["engine"] == "dummy"
    assert cfg.section("missing") == {}


def test_update_merges_saves_and_shows_up_in_the_merged_data(tmp_path):
    path = tmp_path / "settings.json"
    cfg = Config({"teams": {"count": 4, "tint": {"azul": {"color": "#fff"}}}}, path)
    cfg.update({"teams": {"count": 2}})
    cfg.update({"teams": {"tint": {"azul": {"strength": 0.5}}}})
    assert cfg.section("teams")["count"] == 2
    assert cfg.section("teams")["tint"]["azul"] == {"color": "#fff", "strength": 0.5}
    assert json.loads(path.read_text(encoding="utf-8")) == {"teams": {"count": 2, "tint": {"azul": {"strength": 0.5}}}}
    assert Config({}, path).data == json.loads(path.read_text(encoding="utf-8"))  # survives a restart


def test_replace_makes_removals_persist(tmp_path):
    path = tmp_path / "settings.json"
    cfg = Config({}, path)
    cfg.replace(("tts", "team_profiles"), {"azul": "a", "verde": "v"})
    cfg.replace(("tts", "team_profiles"), {"verde": "v"})  # update() would have kept azul
    assert cfg.section("tts")["team_profiles"] == {"verde": "v"}
    assert Config({}, path).section("tts")["team_profiles"] == {"verde": "v"}


def test_invalid_settings_json_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{oops", encoding="utf-8")
    assert Config({"a": 1}, path).data == {"a": 1}


def test_without_a_path_nothing_is_written_and_there_is_no_data_dir():
    cfg = Config({"a": 1})
    cfg.update({"a": 2})
    assert cfg.data == {"a": 2} and cfg.data_dir is None

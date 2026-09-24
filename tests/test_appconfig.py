"""Thứ tự ưu tiên cấu hình: init > env > .env > config/*.yaml; env rỗng rơi về YAML."""

from pathlib import Path

import pytest
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from appconfig import CONFIG_DIR, YamlSettings


def _settings_class(yaml_file: Path, section: str | None = None) -> type[YamlSettings]:
    class Probe(YamlSettings):
        model_config = SettingsConfigDict(
            yaml_file=yaml_file, yaml_config_section=section, populate_by_name=True
        )

        probe_model: str
        probe_timeout_s: float = Field(validation_alias="PROBE_TIMEOUT_ALIAS")
        probe_key: str = ""

    return Probe


@pytest.fixture
def probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> type[YamlSettings]:
    for name in ("PROBE_MODEL", "PROBE_TIMEOUT_ALIAS", "PROBE_KEY"):
        monkeypatch.delenv(name, raising=False)
    yaml_file = tmp_path / "probe.yaml"
    yaml_file.write_text("probe_model: from-yaml\nprobe_timeout_s: 3.0\n", encoding="utf-8")
    return _settings_class(yaml_file)


def test_yaml_is_the_default(probe) -> None:
    settings = probe(_env_file=None)
    assert (settings.probe_model, settings.probe_timeout_s, settings.probe_key) == (
        "from-yaml",
        3.0,
        "",
    )


def test_dotenv_overrides_yaml_and_env_overrides_dotenv(probe, tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PROBE_MODEL=from-dotenv\nPROBE_TIMEOUT_ALIAS=5\n", encoding="utf-8")
    assert probe(_env_file=env_file).probe_model == "from-dotenv"
    assert probe(_env_file=env_file).probe_timeout_s == 5.0

    monkeypatch.setenv("PROBE_MODEL", "from-env")
    assert probe(_env_file=env_file).probe_model == "from-env"
    assert probe(_env_file=env_file, probe_model="from-init").probe_model == "from-init"


def test_blank_env_means_yaml_even_when_dotenv_sets_it(probe, tmp_path, monkeypatch) -> None:
    """`KEY=` ở env vẫn thắng .env (test dùng cách này để chặn giá trị thật trong .env của dev)."""
    env_file = tmp_path / ".env"
    env_file.write_text("PROBE_MODEL=from-dotenv\nPROBE_KEY=real-secret\n", encoding="utf-8")
    monkeypatch.setenv("PROBE_MODEL", "  ")
    monkeypatch.setenv("PROBE_KEY", "")
    settings = probe(_env_file=env_file)
    assert settings.probe_model == "from-yaml"
    assert settings.probe_key == ""


def test_section_selects_a_sub_mapping(tmp_path: Path) -> None:
    yaml_file = tmp_path / "probe.yaml"
    yaml_file.write_text(
        "a:\n  probe_model: model-a\n  probe_timeout_s: 1\n"
        "b:\n  probe_model: model-b\n  probe_timeout_s: 2\n",
        encoding="utf-8",
    )
    assert _settings_class(yaml_file, "b")(_env_file=None).probe_model == "model-b"


def test_missing_yaml_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="missing.yaml"):
        _settings_class(tmp_path / "missing.yaml")(_env_file=None)


def test_repo_config_dir_has_one_file_per_module() -> None:
    assert {path.name for path in CONFIG_DIR.glob("*.yaml")} == {
        "asr.yaml",
        "engine.yaml",
        "http.yaml",
        "livekit.yaml",
        "llm.yaml",
        "session.yaml",
        "speech.yaml",
        "tts.yaml",
    }

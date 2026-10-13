"""Protect paid builds against duplicate synthesis, stale audio and false approval."""

import csv
import json
from dataclasses import replace

import pytest
from scripts import tts_build_static as build

from inference.tts.base import TTSResult
from inference.tts.config import VbeeTTSConfig


@pytest.fixture
def config():
    return VbeeTTSConfig(api_token="test-only-token", app_id="test-only-app")


@pytest.fixture
def source():
    assets, catalog = build.load_shortlist("2026-10-08")
    return assets[:2], catalog


class FakeVbee:
    def __init__(self, config, *, failure=None):
        self.config = config
        self.calls = []
        self.failure = failure
        self.closed = False

    def synthesize(self, text):
        self.calls.append(text)
        if self.failure:
            raise self.failure
        return TTSResult(pcm=b"\x01\x00" * 800, sample_rate=8000, voice=self.config.voice_code)

    def close(self):
        self.closed = True


def test_dry_run_does_not_construct_provider_or_write_files(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        build.VbeeTTS, "__init__", lambda *args, **kwargs: pytest.fail("Paid provider called")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "tts_build_static.py",
            "--date",
            "2026-10-08",
            "--dry-run",
            "--out",
            str(tmp_path / "dry"),
        ],
    )
    assert build.main() == 0
    report = json.loads(capsys.readouterr().out)
    # 74 câu catalog 08-10 + 12 câu bước hỏi số điện thoại (13-10)
    assert report["total"] == 86 and report["selected_characters"] == 5794
    assert not (tmp_path / "dry").exists()


def test_resume_uses_verified_audio_without_provider_calls(config, source, tmp_path):
    assets, catalog = source
    provider = FakeVbee(config)
    first = build.run_build(
        assets, catalog, config, tmp_path, synthesize=True, provider_factory=lambda c: provider
    )
    assert provider.calls == [a["utterance"] for a in assets]
    assert provider.closed and first["summary"]["generated"] == 2
    assert not first["release_ready"]
    assert all(e["listening_status"] == "NOT_REVIEWED" for e in first["assets"])
    second = build.run_build(
        assets,
        catalog,
        config,
        tmp_path,
        synthesize=True,
        provider_factory=lambda c: pytest.fail("Unchanged audio must not be charged again"),
    )
    assert second["summary"]["generated"] == 2
    assert len(second["attempts"]) == 2


def test_changed_audio_bytes_trigger_rebuild_even_when_wav_format_is_valid(
    config, source, tmp_path
):
    assets, catalog = source
    first = build.run_build(
        assets, catalog, config, tmp_path, synthesize=True, provider_factory=FakeVbee
    )
    entry = first["assets"][0]
    raw = bytearray((tmp_path / entry["file"]).read_bytes())
    raw[-2] = 2
    (tmp_path / entry["file"]).write_bytes(raw)
    provider = FakeVbee(config)
    second = build.run_build(
        assets, catalog, config, tmp_path, synthesize=True, provider_factory=lambda c: provider
    )
    assert provider.calls == [assets[0]["utterance"]]
    assert second["summary"]["generated"] == 2


def test_rename_legacy_files_preserves_audio_review_and_paid_resume(config, source, tmp_path):
    assets, catalog = source
    first = build.run_build(
        assets, catalog, config, tmp_path, synthesize=True, provider_factory=FakeVbee
    )
    for entry in first["assets"]:
        legacy = f"{entry['cache_key']}.wav"
        (tmp_path / entry["file"]).rename(tmp_path / legacy)
        entry["file"] = legacy
    (tmp_path / "build_manifest.json").write_text(json.dumps(first), encoding="utf-8")
    sheet = tmp_path / "listening_sheet.csv"
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0].update(listening_status="REVISE", reviewer="Hưng", notes="Kiểm ngắt nghỉ")
    with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    renamed = build.run_build(
        assets,
        catalog,
        config,
        tmp_path,
        rename_files=True,
        provider_factory=lambda c: pytest.fail("Renaming must not call Vbee"),
    )
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    for before, after in zip(first["assets"], renamed["assets"], strict=True):
        assert after["cache_key"] == before["cache_key"]
        assert build.digest((tmp_path / after["file"]).read_bytes()) == before["audio_sha256"]
        assert not (tmp_path / before["file"]).exists()
        assert f'src="{after["file"]}"' in page
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
        assert row["listening_status"] == "REVISE" and row["reviewer"] == "Hưng"
        assert row["file"] == renamed["assets"][0]["file"]
    resumed = build.run_build(
        assets,
        catalog,
        config,
        tmp_path,
        synthesize=True,
        provider_factory=lambda c: pytest.fail("Renamed audio must not be charged again"),
    )
    assert resumed["summary"]["generated"] == len(assets)
    assert len(resumed["attempts"]) == len(first["attempts"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("voice", "other-voice"),
        ("speed", 0.9),
        ("bitrate", 64),
        ("sample_rate", 16000),
        ("schema_version", 2),
    ],
)
def test_audio_configuration_change_does_not_reuse_previous_asset(
    config, source, tmp_path, field, value
):
    assets, catalog = source
    build.run_build(assets, catalog, config, tmp_path, synthesize=True, provider_factory=FakeVbee)
    changed = {**build.audio_config(config), field: value}
    assert all(e["build_status"] == "MISSING" for e in build.plan_build(assets, changed, tmp_path))


def test_exact_text_punctuation_is_part_of_audio_identity(config):
    safe = build.audio_config(config)
    assert build.cache_key("Dạ, em chờ anh chị ạ.", safe) != build.cache_key(
        "Dạ em chờ anh chị ạ.", safe
    )


def test_budget_is_checked_before_constructing_paid_provider(config, source, tmp_path):
    assets, catalog = source
    with pytest.raises(ValueError, match="ngân sách"):
        build.run_build(
            assets,
            catalog,
            config,
            tmp_path,
            synthesize=True,
            max_characters=1,
            provider_factory=lambda c: pytest.fail("Budget exceeded"),
        )
    assert not (tmp_path / "build_manifest.json").exists()
    assert not (tmp_path / ".build.lock").exists()


def test_first_failure_stops_remaining_requests_and_does_not_expose_exception_text(
    config, source, tmp_path
):
    assets, catalog = source
    provider = FakeVbee(config, failure=RuntimeError("secret-token-and-sensitive-response"))
    manifest = build.run_build(
        assets, catalog, config, tmp_path, synthesize=True, provider_factory=lambda c: provider
    )
    assert provider.calls == [assets[0]["utterance"]]
    assert provider.closed and manifest["assets"][0]["build_status"] == "ERROR"
    assert manifest["assets"][1]["build_status"] == "MISSING"
    assert len(manifest["attempts"]) == 1
    assert manifest["attempts"][0]["billed_characters"] is None
    assert "secret-token" not in (tmp_path / "build_manifest.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "change",
    [
        {"sample_rate": 16000},
        {"voice": "wrong-voice"},
        {"fallback_used": True},
        {"provider_actual": "elevenlabs"},
        {"pcm": b"\x00"},
        {"pcm": b"\x00\x00" * 800},
    ],
)
def test_provider_output_with_wrong_source_or_invalid_audio_is_rejected(config, change):
    result = TTSResult(pcm=b"\x01\x00" * 800, sample_rate=8000, voice=config.voice_code)
    with pytest.raises(ValueError):
        build.make_wav(replace(result, **change), build.audio_config(config))


def test_review_is_preserved_on_resume_but_never_published_as_release(config, source, tmp_path):
    assets, catalog = source
    build.run_build(assets, catalog, config, tmp_path, synthesize=True, provider_factory=FakeVbee)
    sheet = tmp_path / "listening_sheet.csv"
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0].update(
        listening_status="PASS",
        reviewer="Hưng",
        fidelity_1_0="1",
        naturalness_1_5="4",
        audio_cut_1_0="0",
    )
    with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    resumed = build.run_build(assets, catalog, config, tmp_path)
    assert not resumed["release_ready"]
    assert not (tmp_path / "manifest.json").exists()
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        assert next(csv.DictReader(handle))["reviewer"] == "Hưng"
    (tmp_path / resumed["assets"][0]["file"]).unlink()
    build.run_build(assets, catalog, config, tmp_path)
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        review = next(csv.DictReader(handle))
        assert review["listening_status"] == "NOT_REVIEWED" and review["reviewer"] == ""


def test_active_lock_prevents_parallel_paid_build(config, source, tmp_path):
    assets, catalog = source
    (tmp_path / ".build.lock").write_text("123", encoding="ascii")
    with pytest.raises(ValueError, match="lock"):
        build.run_build(
            assets,
            catalog,
            config,
            tmp_path,
            synthesize=True,
            provider_factory=lambda c: pytest.fail("Another build owns the lock"),
        )
    assert (tmp_path / ".build.lock").read_text(encoding="ascii") == "123"


def test_stale_catalog_fails_before_any_audio_is_built(monkeypatch, tmp_path):
    _, catalog = build.load_shortlist("2026-10-08")
    catalog["template_sha256"] = "outdated"
    (tmp_path / "tts-utterance-catalog-2026-10-08.json").write_text(
        json.dumps(catalog), encoding="utf-8"
    )
    monkeypatch.setattr(build, "DATA", tmp_path)
    with pytest.raises(ValueError, match="Catalog cũ"):
        build.load_shortlist("2026-10-08")


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example/v1/tts",
        "https://token@api.vbee.vn/v1/tts",
        "https://api.vbee.vn/v1/tts?token=secret",
    ],
)
def test_build_configuration_cannot_leak_credentials_to_alternate_endpoint(config, endpoint):
    with pytest.raises(ValueError):
        build.audio_config(config.model_copy(update={"endpoint": endpoint}))

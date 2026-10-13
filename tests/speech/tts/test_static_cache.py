"""Static hits must avoid paid TTS; invalid/unapproved inputs must never hit."""

import json
import logging
from fnmatch import fnmatch
from pathlib import PurePosixPath

import pytest
from scripts import tts_build_static as build
from scripts.tts_release_static import release_candidate
from tests.speech.tts.static_support import (
    RELEASE,
    CountingProvider,
    cached_synthesizer,
    release_manifest,
)

from inference.tts import TTSGateway
from inference.tts.config import VbeeTTSConfig
from speech import bundle
from speech.audio.codec import encode_wav
from speech.settings import SpeechSettings
from speech.tts.static_cache import StaticAudioCache, StaticCacheSettings, create_static_cache
from speech.types import AudioSegment


@pytest.fixture
def small_release(tmp_path):
    assets, catalog = build.load_shortlist("2026-10-08")
    assets = assets[:2]
    config = VbeeTTSConfig(api_token="offline-only", app_id="offline-only", _env_file=None)
    identity = build.audio_config(config)
    candidate, output = tmp_path / "candidate", tmp_path / "release-v1"
    build.run_build(
        assets,
        catalog,
        config,
        candidate,
        synthesize=True,
        provider_factory=lambda c: CountingProvider(identity),
    )
    manifest = release_candidate(
        candidate,
        output,
        assets,
        catalog,
        identity,
        reviewer="Hưng",
        approval_note="Đã nghe tất cả và đạt",
    )
    return output, manifest, assets, catalog, identity, candidate


async def test_shipped_catalog_covers_all_74_current_utterances_in_sync_and_stream():
    assets, _ = build.load_shortlist("2026-10-08")
    tts, provider, fallback = cached_synthesizer()
    assert len(tts._static_cache) == len(assets) == 74
    for asset in assets:
        audio = tts.synthesize(asset["utterance"])
        chunks = [c async for c in tts.synthesize_stream(asset["utterance"])]
        assert audio.cache_hit and audio.billed_characters == 0
        assert b"".join(chunks) == audio.pcm
        assert all(len(c) <= 320 and len(c) % 2 == 0 for c in chunks)
        assert tts.last_stream_result.cache_key == audio.cache_key
        assert tts.last_stream_result.billed_characters == 0
    assert not provider.calls and not fallback.calls


def test_shipped_release_matches_configured_vbee_audio():
    # Đổi giọng/tốc độ trong config/tts.yaml mà không thu lại thì runtime bỏ cả release (chỉ có log
    # TTS_STATIC_MANIFEST_MISMATCH), mọi câu tĩnh lại tốn Vbee — như speed 1.15 ngày 12/10.
    config = VbeeTTSConfig(api_token="offline-only", app_id="offline-only", _env_file=None)
    assert release_manifest()["audio_config"] == build.audio_config(config)


async def test_dynamic_and_changed_exact_text_use_provider_and_do_not_enter_static_store():
    tts, provider, _ = cached_synthesizer()
    static = release_manifest()["assets"][0]["utterance"]
    for text in ("Lịch khám của anh là ngày 15 tháng 10, lúc 10 giờ.", static + " ", static[:-1]):
        assert not tts.synthesize(text).cache_hit
        assert [c async for c in tts.synthesize_stream(text)]
        assert not tts.last_stream_result.cache_hit
        assert tts._static_cache.lookup(text) is None
    assert provider.calls == [
        t.strip()
        for t in ("Lịch khám của anh là ngày 15 tháng 10, lúc 10 giờ.", static + " ", static[:-1])
        for _ in range(2)
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("voice", "other-voice"),
        ("model", "other-model"),
        ("speed", 0.9),
        ("bitrate", 64),
        ("sample_rate", 16000),
        ("encoding", "OTHER"),
        ("channels", 2),
        ("endpoint", "https://other.example/tts"),
        ("api_mode", "async"),
        ("schema_version", 2),
    ],
)
def test_configuration_change_misses_entire_previous_release(field, value):
    identity = {**release_manifest()["audio_config"], field: value}
    store = StaticAudioCache(RELEASE, identity)
    assert len(store) == 0


@pytest.mark.parametrize(
    "defect", ["missing", "checksum", "rate", "truncated", "path", "unapproved", "text"]
)
def test_invalid_asset_falls_back_to_exact_requested_text(small_release, defect, caplog):
    folder, manifest, *_ = small_release
    entry = manifest["assets"][0]
    text = entry["utterance"]
    path = folder / entry["file"]
    if defect == "missing":
        path.unlink()
    elif defect == "checksum":
        path.write_bytes(path.read_bytes()[:-2] + b"\x02\x00")
    elif defect in ("rate", "truncated"):
        raw = (
            encode_wav(AudioSegment(pcm=b"\x01\x00" * 800, sample_rate=16000))
            if defect == "rate"
            else path.read_bytes()[:-2]
        )
        path.write_bytes(raw)
        entry["audio_sha256"] = build.digest(raw)
    elif defect == "path":
        entry["file"] = "../outside.wav"
    elif defect == "unapproved":
        entry["listening_status"] = "NOT_REVIEWED"
    elif defect == "text":
        entry["utterance"] += " sửa"
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="speech.tts.static_cache"):
        store = StaticAudioCache(folder, manifest["audio_config"])
    assert "TTS_STATIC_ASSETS_SKIPPED: 1/2" in caplog.text
    assert store.lookup(text) is None
    assert store.lookup(manifest["assets"][1]["utterance"]) is not None
    provider = CountingProvider(manifest["audio_config"])
    tts = bundle.SpeechSynthesizer(TTSGateway(provider, provider_name="vbee"), store)
    assert not tts.synthesize(text).cache_hit
    assert provider.calls == [text]


@pytest.mark.parametrize(
    "change",
    [{"release_ready": False}, {"status": "CANDIDATE_PENDING_LISTENING"}, {"schema_version": 2}],
)
def test_unreleased_manifest_never_supplies_audio(small_release, change):
    folder, manifest, *_ = small_release
    manifest.update(change)
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert not len(StaticAudioCache(folder, manifest["audio_config"]))


def test_explicit_owner_approval_packages_only_audio_and_manifest_and_never_overwrites(
    small_release,
):
    folder, manifest, assets, catalog, identity, candidate = small_release
    assert len(list(folder.iterdir())) == len(assets) + 1
    assert not list(folder.glob("*.csv")) and not list(folder.glob("*.html"))
    assert manifest["approval"]["method"] == "owner_confirmation"
    assert all(e["listening_status"] == "PASS" for e in manifest["assets"])
    with pytest.raises(ValueError, match="tồn tại"):
        release_candidate(
            candidate, folder, assets, catalog, identity, reviewer="Hưng", approval_note="Đạt"
        )


async def test_cache_cancel_stops_chunks_and_old_cleanup_does_not_cancel_new_stream():
    tts, provider, fallback = cached_synthesizer()
    text = release_manifest()["assets"][0]["utterance"]
    old = tts.synthesize_stream(text)
    assert await anext(old)
    await tts.cancel()
    assert [c async for c in old] == []
    new = tts.synthesize_stream(text)
    assert await anext(new)
    await old.aclose()
    assert await anext(new)
    await tts.cancel()
    assert [c async for c in new] == []
    assert not provider.calls and not fallback.calls
    assert provider.cancel_calls == fallback.cancel_calls == 0


@pytest.mark.parametrize("problem", ["missing", "mismatch"])
def test_unusable_release_is_reported_as_an_error(tmp_path, caplog, problem):
    identity = release_manifest()["audio_config"]
    if problem == "mismatch":
        (tmp_path / "manifest.json").write_bytes((RELEASE / "manifest.json").read_bytes())
        identity = {**identity, "voice": "other-voice"}
    with caplog.at_level(logging.ERROR, logger="speech.tts.static_cache"):
        assert not len(StaticAudioCache(tmp_path, identity))
    expected = "UNAVAILABLE" if problem == "missing" else "MISMATCH"
    assert f"TTS_STATIC_MANIFEST_{expected}" in caplog.text


def test_docker_image_ships_the_configured_release():
    """Thiếu audio trong image không lỗi ở request nào, chỉ âm thầm gọi Vbee: chặn ngay ở CI."""
    root = RELEASE.parents[3]
    directory = PurePosixPath(StaticCacheSettings(_env_file=None).directory)
    assert not directory.is_absolute() and (root / directory / "manifest.json").is_file()
    copies = [
        line.split()[1:]
        for line in (root / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("COPY ") and "--from" not in line
    ]
    # WORKDIR /app và CALLBOT_CONFIG_DIR=/app/config: thư mục tương đối tính từ /app
    assert any(
        len(args) == 2
        and directory.is_relative_to(args[0])
        and PurePosixPath(args[1]) == PurePosixPath(args[0])
        for args in copies
    ), "Dockerfile phải COPY thư mục release TTS tĩnh vào /app"
    ignored = [
        line.strip().rstrip("/")
        for line in (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(("#", "!"))
    ]
    parents = [str(directory), *(str(p) for p in directory.parents if str(p) != ".")]
    assert not [p for p in ignored for path in parents if fnmatch(path, p)]


def test_disabled_and_other_provider_keep_original_gateway_path():
    provider = CountingProvider()
    gateway = TTSGateway(provider, provider_name="vbee")
    assert create_static_cache(gateway, StaticCacheSettings(enabled=False)) is None
    assert create_static_cache(TTSGateway(provider, provider_name="elevenlabs")) is None
    text = release_manifest()["assets"][0]["utterance"]
    assert not bundle.SpeechSynthesizer(gateway).synthesize(text).cache_hit
    assert provider.calls == [text]


def test_both_bundle_factories_share_verified_store(monkeypatch, tmp_path):
    from tests.transports.http.fakes import FakeASR

    monkeypatch.setattr(
        bundle,
        "create_tts_gateway",
        lambda *a, **k: TTSGateway(CountingProvider(), provider_name="vbee"),
    )
    monkeypatch.setattr(bundle, "create_asr_gateway", lambda *a, **k: None)
    monkeypatch.setattr(bundle, "SpeechRecognizer", lambda g: FakeASR())
    settings = SpeechSettings(
        vad_provider="energy", turn_validator_enabled=False, audio_dir=str(tmp_path)
    )
    http = bundle.build_speech_bundle(settings)
    livekit = bundle.build_streaming_bundle(
        settings,
        sample_rate=8000,
        frame_ms=20,
        input_queue_ms=1000,
        asr_queue_ms=1000,
        barge_in_preroll_ms=200,
        asr=FakeASR(),
    )
    assert http.tts._static_cache is livekit.tts._static_cache
    assert len(http.tts._static_cache) == 74

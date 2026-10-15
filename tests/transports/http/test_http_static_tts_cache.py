"""Real HTTP/Core and audio store with packaged static TTS and offline dynamic TTS."""

import io
import wave
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from tests.speech.tts.static_support import RELEASE, cached_synthesizer, release_manifest
from tests.tracing.test_speech_tracing import MemorySink, _tracer
from tests.transports.http.fakes import FakeASR
from tests.transports.http.test_calls import _call_mode_factory, _start, _turn

from callbot.engine import EngineSettings
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI
from speech.audio.storage import AudioArtifactStore
from speech.bundle import SpeechBundle


def test_unchanged_audio_stays_cached_and_renamed_greetings_use_provider(
    tmp_path, redis_store_factory, redis_server
):
    tts, provider, fallback = cached_synthesizer()
    asr = FakeASR()
    sink = MemorySink()
    speech = SpeechBundle(
        asr, tts, AudioArtifactStore(str(tmp_path / "audio"), "http://testserver")
    )
    app = create_app(
        clinic_factory=FakeClinicAPI,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: speech,
        call_mode_factory=_call_mode_factory(redis_server),
        tracer_factory=lambda: _tracer(sink),
    )
    static_urls = []
    opening_urls = []
    with TestClient(app) as client:
        for completed_calls, call_id in enumerate(("static-cache-call-a", "static-cache-call-b")):
            opening = _start(client, call_id, mode="audio")
            assert opening.status_code == 200
            opening_body = opening.json()
            assert "bệnh viện" in opening_body["utterance"]
            assert "vinmec" not in opening_body["utterance"].lower()
            assert tts._static_cache.lookup(opening_body["utterance"]) is None
            assert provider.calls[-1] == opening_body["utterance"]
            assert urlsplit(opening_body["audio_url"]).path == f"/audio/{call_id}/0.wav"
            assert client.get(opening_body["audio_url"]).status_code == 200
            opening_urls.append(opening_body["audio_url"])
            asr.transcript = "Nguyễn Văn A"
            turn = _turn(client, call_id, 1, None, audio_url="https://offline.test/input.wav")
            assert turn.status_code == 200
            body = turn.json()
            expected = tts._static_cache.lookup(body["utterance"])
            assert expected is not None
            path = urlsplit(body["audio_url"]).path
            # Trúng cache: trỏ audio đã duyệt, không chép WAV theo call/turn
            assert path == f"/audio-static/{expected.cache_key}.wav"
            static_urls.append(body["audio_url"])
            audio = client.get(path)
            assert audio.status_code == 200
            assert audio.headers["content-type"] == "audio/wav"
            assert "immutable" in audio.headers["cache-control"]
            with wave.open(io.BytesIO(audio.content), "rb") as clip:
                assert (clip.getframerate(), clip.getnchannels(), clip.getsampwidth()) == (
                    8000,
                    1,
                    2,
                )
                assert clip.readframes(clip.getnframes()) == expected.pcm
            assert len(provider.calls) == completed_calls * 2 + 1 and not fallback.calls
            asr.transcript = "14/03/1978"
            dynamic = _turn(client, call_id, 2, None, audio_url="https://offline.test/dob.wav")
            assert dynamic.status_code == 200
            assert tts._static_cache.lookup(dynamic.json()["utterance"]) is None
            assert provider.calls[-1] == dynamic.json()["utterance"]
            # Câu động vẫn ghi WAV theo lượt; lượt tĩnh không để lại file nào
            assert urlsplit(dynamic.json()["audio_url"]).path == f"/audio/{call_id}/2.wav"
            assert client.get(f"/audio/{call_id}/2.wav").status_code == 200
            saved = sorted(p.name for p in (tmp_path / "audio" / call_id).iterdir())
            assert saved == ["0.sha256", "0.wav", "2.sha256", "2.wav"]
        assert len(provider.calls) == 4 and not fallback.calls
        text = _start(client, "static-cache-text-only", mode="text")
        assert text.status_code == 200 and text.json()["audio_url"] is None
        assert len(provider.calls) == 4
        # Câu hỏi ngày sinh dùng chung audio tĩnh; retry lời chào dùng WAV đúng nguyên văn đã lưu.
        assert static_urls[0] == static_urls[1]
        assert (
            _start(client, "static-cache-call-a", mode="audio").json()["audio_url"]
            == opening_urls[0]
        )
        assert len(provider.calls) == 4
        for path in (
            f"/audio-static/{'0' * 64}.wav",
            "/audio-static/manifest.json",
            "/audio-static/ABC.wav",
            f"/audio-static/{RELEASE.name}/manifest.json",
        ):
            assert client.get(path).status_code == 404
    spans = [s for s in sink.spans if s.component == "TTS"]
    hits = [s for s in spans if s.attributes.get("cache_hit") is True]
    assert len(hits) == 2  # Câu hỏi ngày sinh ở hai cuộc gọi.
    for span in hits:
        assert span.attributes["cost_usd"] == 0
        assert span.attributes["billed_characters"] == 0
        assert span.attributes["catalog_version"] == release_manifest()["catalog_version"]
        assert len(span.attributes["cache_key"]) == 64
    misses = [s for s in spans if s.attributes.get("cache_hit") is False]
    assert len(misses) == 4  # Hai lời chào mới và hai câu đọc lại lịch.
    assert all("billed_characters" not in s.attributes for s in misses)
    assert speech.audio_store.purge_older_than(-1) == 2
    assert len(list(RELEASE.glob("*.wav"))) == 82

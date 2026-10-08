"""Real HTTP/Core and audio store with packaged static TTS and offline dynamic TTS."""

import io
import wave
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from tests.speech.tts.static_support import RELEASE, cached_synthesizer
from tests.tracing.test_speech_tracing import MemorySink, _tracer
from tests.transports.http.fakes import FakeASR
from tests.transports.http.test_calls import _call_mode_factory, _start, _turn

from callbot.engine import EngineSettings
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI
from speech.audio.storage import AudioArtifactStore
from speech.bundle import SpeechBundle


def test_static_audio_is_ready_across_calls_and_turns_with_zero_provider_cost(
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
    with TestClient(app) as client:
        for completed_calls, call_id in enumerate(("static-cache-call-a", "static-cache-call-b")):
            opening = _start(client, call_id, mode="audio")
            assert opening.status_code == 200
            asr.transcript = "Nguyễn Văn A"
            turn = _turn(client, call_id, 1, None, audio_url="https://offline.test/input.wav")
            assert turn.status_code == 200
            for response in (opening, turn):
                body = response.json()
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
            assert len(provider.calls) == completed_calls and not fallback.calls
            asr.transcript = "14/03/1978"
            dynamic = _turn(client, call_id, 2, None, audio_url="https://offline.test/dob.wav")
            assert dynamic.status_code == 200
            assert tts._static_cache.lookup(dynamic.json()["utterance"]) is None
            assert provider.calls[-1] == dynamic.json()["utterance"]
            # Câu động vẫn ghi WAV theo lượt; lượt tĩnh không để lại file nào
            assert urlsplit(dynamic.json()["audio_url"]).path == f"/audio/{call_id}/2.wav"
            assert client.get(f"/audio/{call_id}/2.wav").status_code == 200
            saved = sorted(p.name for p in (tmp_path / "audio" / call_id).iterdir())
            assert saved == ["2.sha256", "2.wav"]
        assert len(provider.calls) == 2 and not fallback.calls
        text = _start(client, "static-cache-text-only", mode="text")
        assert text.status_code == 200 and text.json()["audio_url"] is None
        assert len(provider.calls) == 2
        # Cùng câu chào ở hai cuộc gọi: cùng một URL, retry cùng lượt cũng nhận đúng URL đó
        assert static_urls[0] == static_urls[2] and static_urls[1] == static_urls[3]
        assert (
            _start(client, "static-cache-call-a", mode="audio").json()["audio_url"]
            == (static_urls[0])
        )
        for path in (
            f"/audio-static/{'0' * 64}.wav",
            "/audio-static/manifest.json",
            "/audio-static/ABC.wav",
            f"/audio-static/{RELEASE.name}/manifest.json",
        ):
            assert client.get(path).status_code == 404
    spans = [s for s in sink.spans if s.component == "TTS"]
    hits = [s for s in spans if s.attributes.get("cache_hit") is True]
    assert len(hits) == 5  # 2 cuộc x (chào + lượt 1) + retry lời chào: tra lại RAM, cost 0
    for span in hits:
        assert span.attributes["cost_usd"] == 0
        assert span.attributes["billed_characters"] == 0
        assert span.attributes["catalog_version"] == "2026-10-08-v1"
        assert len(span.attributes["cache_key"]) == 64
    misses = [s for s in spans if s.attributes.get("cache_hit") is False]
    assert len(misses) == 2
    assert all("billed_characters" not in s.attributes for s in misses)
    assert speech.audio_store.purge_older_than(-1) == 2
    assert len(list(RELEASE.glob("*.wav"))) == 73

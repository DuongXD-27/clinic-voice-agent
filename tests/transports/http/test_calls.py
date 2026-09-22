import json
from typing import Any, Optional
from urllib.parse import unquote
from uuid import uuid4

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient
from tests.engine.fake_clinic import FakeClinicAPI, clinic_error
from tests.engine.test_cancel_dialogue import BrokenSemantic, FakeSemantic
from tests.transports.http.fakes import FakeASR, FakeTTS, make_speech_bundle

from callbot.engine import (
    CallBusy,
    CallConflict,
    CallEnded,
    EngineSettings,
    ReconciliationRequired,
    RedisSessionStore,
    SessionNotFound,
    SessionStoreUnavailable,
    TurnConflict,
    TurnOutOfOrder,
)
from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.templates import AI_DISCLOSURE, greeting
from callbot.engine.extraction.semantic import ReplyKind, SemanticOutcome
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.calls import _extraction_debug, get_orchestrator
from callbot.transports.http.main import create_app
from speech.audio import encode_wav
from speech.types import AudioSegment


def _call_mode_factory(redis_server):
    """Cùng fakeredis instance với redis_store_factory — không tự tạo Redis client thật."""
    return lambda: CallModeStore(
        fakeredis.FakeRedis(server=redis_server, decode_responses=True),
        key_prefix=f"test:{uuid4().hex}",
    )


def _start(
    client: TestClient,
    call_id: str,
    direction: str = "outbound",
    appointment_id: Optional[str] = "apt_00417",
    caller_number: Optional[str] = None,
    mode: str = "text",
    max_turns: int = 20,
):
    return client.post(
        "/v1/calls",
        json={
            "call_id": call_id,
            "direction": direction,
            "appointment_id": appointment_id,
            "caller_number": caller_number,
            "locale": "vi-VN",
            "mode": mode,
            "max_turns": max_turns,
        },
    )


def _turn(
    client: TestClient,
    call_id: str,
    turn: int,
    text: Optional[str],
    silence_ms: int = 0,
    audio_url: Optional[str] = None,
):
    return client.post(
        f"/v1/calls/{call_id}/turn",
        json={"turn": turn, "audio_url": audio_url, "text": text, "silence_ms": silence_ms},
    )


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_demo_page_is_served(client: TestClient) -> None:
    response = client.get("/demo/")
    assert response.status_code == 200
    assert "Vinmec Callbot Console" in response.text
    assert "/v1/calls" in response.text
    assert "Extraction:" in response.text


def test_extraction_debug_does_not_credit_ner_for_a_semantic_reading() -> None:
    debug = _extraction_debug(
        {
            "question_id": "CANCEL_RECONFIRM",
            "transcript": "ngày đó tôi phải có mặt ở cơ quan",
            "full_name": {"value": None, "provenance": None, "span": None},
            "cancel_reason": {
                "value": "PATIENT_UNAVAILABLE",
                "provenance": "FALLBACK",
                "span": "phải có mặt ở cơ quan",
            },
        }
    ).model_dump()

    assert debug == {
        "question_id": "CANCEL_RECONFIRM",
        "source": "LLM",
        "provenance": "FALLBACK",
    }


def test_extraction_debug_reports_ner_without_pii() -> None:
    debug = _extraction_debug(
        {
            "question_id": "ASK_NAME",
            "transcript": "à ừ thì là Nguyễn Văn A nhé em",
            "full_name": {
                "value": "nguyễn văn a",
                "provenance": "FALLBACK",
                "span": "nguyễn văn a",
            },
        }
    ).model_dump()

    assert debug == {
        "question_id": "ASK_NAME",
        "source": "NER",
        "provenance": "FALLBACK",
    }
    assert "nguyễn văn a" not in str(debug).lower()


def test_demo_audio_upload_returns_public_narrowband_wav(client: TestClient) -> None:
    source = AudioSegment(pcm=b"\x00\x00" * 1600, sample_rate=16000)
    response = client.put(
        "/demo-api/audio/c_browser/1.wav",
        content=encode_wav(source),
        headers={"Content-Type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["audio_url"] == "http://testserver/audio/demo-input/c_browser/1.wav"
    assert body["sample_rate"] == 8000
    assert body["duration_ms"] == 100
    assert body["content_type"] == "audio/wav"
    saved = client.get("/audio/demo-input/c_browser/1.wav")
    assert saved.status_code == 200
    assert saved.content.startswith(b"RIFF")


@pytest.mark.parametrize(
    ("path", "content", "status", "code"),
    [
        ("/demo-api/audio/bad.id/1.wav", b"RIFF", 422, "INVALID_CALL_ID"),
        ("/demo-api/audio/c_empty/1.wav", b"", 400, "EMPTY_AUDIO"),
        ("/demo-api/audio/c_bad/1.wav", b"not a wav", 422, "INVALID_WAV"),
    ],
)
def test_demo_audio_upload_rejects_invalid_input(
    client: TestClient, path: str, content: bytes, status: int, code: str
) -> None:
    response = client.put(path, content=content)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_start_call_returns_engine_opening(client: TestClient) -> None:
    response = _start(client, "c_test_1")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "call_id": "c_test_1",
        "utterance": greeting("outbound"),
        "audio_url": None,
        "state": "AWAITING_IDENTITY",
        "turn": 0,
    }
    # [R-26] endpoint dùng đúng câu chào công bố AI của engine, không hard-code lại
    assert AI_DISCLOSURE in body["utterance"]


def test_name_turn_asks_dob_instead_of_transferring(client: TestClient) -> None:
    _start(client, "c_test_2")
    response = _turn(client, "c_test_2", 1, "Nguyễn Văn A.")
    assert response.status_code == 200
    assert response.json() == {
        "utterance": t.ASK_DOB,
        "audio_url": None,
        "state": "AWAITING_IDENTITY",
        "ended": False,
        "outcome": None,
    }


def test_demo_header_exposes_rule_source_without_pii(client: TestClient) -> None:
    _start(client, "c_demo_debug")
    response = client.post(
        "/v1/calls/c_demo_debug/turn",
        headers={"X-Demo-Debug": "1"},
        json={"turn": 1, "audio_url": None, "text": "Nguyễn Văn A.", "silence_ms": 0},
    )

    assert response.status_code == 200
    assert response.json() == {
        "utterance": t.ASK_DOB,
        "audio_url": None,
        "state": "AWAITING_IDENTITY",
        "ended": False,
        "outcome": None,
    }
    debug = {
        "question_id": response.headers["X-Demo-Extraction-Question-Id"],
        "source": response.headers["X-Demo-Extraction-Source"],
        "provenance": response.headers["X-Demo-Extraction-Provenance"],
    }
    assert debug == {
        "question_id": "ASK_NAME",
        "source": "RULE",
        "provenance": "NORMALIZED",
    }
    assert "nguyễn văn a" not in str(debug).lower()


def test_dob_turn_continues_same_session(client: TestClient, clinic: FakeClinicAPI) -> None:
    _start(client, "c_test_3")
    _turn(client, "c_test_3", 1, "Nguyễn Văn A.")
    response = _turn(client, "c_test_3", 2, "Ngày 14 tháng 3 năm 1978.")
    assert response.status_code == 200
    body = response.json()
    # Tên ở lượt 1 còn trong session nên xác minh thành công và chuyển sang hỏi nhu cầu
    assert body["state"] == "AWAITING_INTENT"
    assert body["ended"] is False
    assert body["outcome"] is None
    assert "14 tháng 10" in body["utterance"]
    assert clinic.writes == []


def test_calls_do_not_share_state(client: TestClient) -> None:
    _start(client, "c_iso_a")
    _start(client, "c_iso_b")
    _turn(client, "c_iso_a", 1, "Nguyễn Văn A.")

    # c_iso_b chưa có tên: giữ ngày sinh (T-02) nhưng vẫn phải hỏi tên — không dùng tên của c_iso_a
    response = _turn(client, "c_iso_b", 1, "Ngày 14 tháng 3 năm 1978.")
    assert response.json()["utterance"] == t.ASK_NAME_AFTER_DOB
    assert response.json()["state"] == "AWAITING_IDENTITY"
    assert _turn(client, "c_iso_a", 2, "Ngày 14 tháng 3 năm 1978.").json()["state"] == (
        "AWAITING_INTENT"
    )


def test_unknown_call_returns_404(client: TestClient) -> None:
    response = _turn(client, "c_missing", 1, "xin chào")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CALL_NOT_FOUND"


def test_silence_and_empty_transcript_map_differently(client: TestClient) -> None:
    _start(client, "c_silence")
    silence = _turn(client, "c_silence", 1, None, silence_ms=1500)
    assert silence.status_code == 200
    # T-08: nhắc im lặng rồi hỏi lại câu đang chờ (câu chào hỏi tên)
    assert silence.json()["utterance"] == f"{t.SILENCE} {t.GREETING_OUTBOUND}"

    _start(client, "c_empty")
    empty = _turn(client, "c_empty", 1, "", silence_ms=0)
    assert empty.status_code == 200
    assert empty.json()["utterance"] == t.ASK_NAME_AGAIN


def test_text_call_rejects_audio_url(client: TestClient) -> None:
    _start(client, "c_text_audio")
    response = _turn(client, "c_text_audio", 1, None, audio_url="https://harness/clip.wav")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AUDIO_URL_NOT_ALLOWED"


# --- mode=audio: ZipFormer self-host nối vào đường HTTP chấm điểm (§4.1.2) ----------------


def test_start_call_audio_mode_returns_audio_url(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    tts = FakeTTS(respond=True)
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path, tts=tts),
        call_mode_factory=_call_mode_factory(redis_server),
    )
    with TestClient(app) as audio_client:
        response = _start(audio_client, "c_audio_1", mode="audio")
        assert response.status_code == 200
        body = response.json()
        assert body["audio_url"] == "http://test/audio/c_audio_1/0.wav"
        assert tts.spoken == [body["utterance"]]


def test_tts_failure_still_replies_without_audio(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    """TTS lỗi (vd. key không có quyền model TTS) không chặn cuộc gọi audio — vẫn test được STT."""
    asr = FakeASR(transcript="Nguyễn Văn A")
    tts = FakeTTS(error=RuntimeError("403 model_not_found"))
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path, asr=asr, tts=tts),
        call_mode_factory=_call_mode_factory(redis_server),
    )
    with TestClient(app) as audio_client:
        start = _start(audio_client, "c_audio_tts_down", mode="audio")
        assert start.status_code == 200
        assert start.json()["audio_url"] is None and start.json()["utterance"]
        turn = _turn(
            audio_client, "c_audio_tts_down", 1, None, audio_url="https://harness/clips/1.wav"
        )
        assert turn.status_code == 200
        assert turn.json()["utterance"] == t.ASK_DOB and turn.json()["audio_url"] is None


def test_turn_with_audio_url_transcribes_and_replies_with_audio(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    asr = FakeASR(transcript="Nguyễn Văn A")
    tts = FakeTTS(respond=True)
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path, asr=asr, tts=tts),
        call_mode_factory=_call_mode_factory(redis_server),
    )
    with TestClient(app) as audio_client:
        _start(audio_client, "c_audio_2", mode="audio")
        response = _turn(
            audio_client, "c_audio_2", 1, None, audio_url="https://harness/clips/c_audio_2/1.wav"
        )
        assert response.status_code == 200
        body = response.json()
        # Transcript "Nguyễn Văn A" đi đúng đường IE như mode=text — engine không đổi
        assert body["utterance"] == t.ASK_DOB
        assert body["audio_url"] == "http://test/audio/c_audio_2/1.wav"
        # asr.received[0] là warm-up lúc lifespan startup (segment câm) — không đếm ở đây
        assert asr.received[-1].sample_rate == 8000


def test_silence_turn_in_audio_mode_still_replies_with_audio(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    tts = FakeTTS(respond=True)
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path, tts=tts),
        call_mode_factory=_call_mode_factory(redis_server),
    )
    with TestClient(app) as audio_client:
        _start(audio_client, "c_audio_3", mode="audio")
        # Không audio_url, chỉ silence_ms — vẫn phải nói lại bằng audio (§1.1.7)
        response = _turn(audio_client, "c_audio_3", 1, None, silence_ms=2000)
        assert response.status_code == 200
        assert response.json()["utterance"].startswith(t.SILENCE)
        assert response.json()["audio_url"] is not None


def test_turn_with_text_in_audio_mode_rejected(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path),
        call_mode_factory=_call_mode_factory(redis_server),
    )
    with TestClient(app) as audio_client:
        _start(audio_client, "c_audio_4", mode="audio")
        response = _turn(audio_client, "c_audio_4", 1, "Nguyễn Văn A")
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "TEXT_NOT_ALLOWED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"direction": "outbound", "appointment_id": None},
        {"direction": "inbound", "appointment_id": None, "caller_number": None},
        {"direction": "inbound", "appointment_id": "apt_00417", "caller_number": "0912345600"},
        {"max_turns": 0},
    ],
)
def test_start_call_rejects_invalid_input(client: TestClient, overrides: dict[str, Any]) -> None:
    assert _start(client, "c_invalid", **overrides).status_code == 422


@pytest.mark.parametrize(
    ("turn", "text", "silence_ms"),
    [(0, "xin chào", 0), (1, None, 0), (1, "xin chào", -1)],
)
def test_turn_rejects_invalid_input(
    client: TestClient, turn: int, text: Optional[str], silence_ms: int
) -> None:
    _start(client, "c_invalid_turn")
    assert _turn(client, "c_invalid_turn", turn, text, silence_ms=silence_ms).status_code == 422


def test_orchestrator_created_once_and_clinic_closed_on_shutdown(
    redis_store_factory, redis_server, tmp_path
) -> None:
    created: list[FakeClinicAPI] = []
    closed: list[FakeClinicAPI] = []

    class ClosableClinic(FakeClinicAPI):
        def close(self) -> None:
            closed.append(self)

    def factory() -> FakeClinicAPI:
        clinic = ClosableClinic()
        created.append(clinic)
        return clinic

    app = create_app(
        clinic_factory=factory,
        engine_settings=EngineSettings(),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path),
        call_mode_factory=_call_mode_factory(redis_server),
    )
    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        _start(client, "c_lifecycle")
        _turn(client, "c_lifecycle", 1, "Nguyễn Văn A.")
        assert app.state.orchestrator is orchestrator
        assert len(created) == 1
        assert closed == []
    assert closed == created


class _RaisingOrchestrator:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def start_call(self, call):
        raise self._exc

    def handle_turn(self, call_id, caller):
        raise self._exc

    def handle_turn_with_details(self, call_id, caller):
        raise self._exc


_REQUEST = httpx.Request("GET", "https://clinic-mock.example/v1/appointments/apt_00417")


@pytest.mark.parametrize(
    ("exc", "status_code", "code"),
    [
        (SessionNotFound("c_x"), 404, "CALL_NOT_FOUND"),
        (httpx.ConnectError("refused", request=_REQUEST), 502, "UPSTREAM_ERROR"),
        (
            httpx.HTTPStatusError(
                "boom", request=_REQUEST, response=httpx.Response(500, request=_REQUEST)
            ),
            502,
            "UPSTREAM_ERROR",
        ),
        (httpx.ReadTimeout("slow", request=_REQUEST), 504, "UPSTREAM_TIMEOUT"),
        (RuntimeError("sk_secret_key leaked"), 500, "INTERNAL_ERROR"),
        (CallConflict("c_x"), 409, "CALL_CONFLICT"),
        (TurnConflict("c_x"), 409, "TURN_CONFLICT"),
        (TurnOutOfOrder("c_x", 3, 2), 409, "TURN_OUT_OF_ORDER"),
        (CallEnded("c_x"), 409, "CALL_ENDED"),
        (CallBusy("c_x"), 409, "CALL_BUSY"),
        (ReconciliationRequired("c_x", 2, "sk_secret"), 409, "CALL_RECONCILIATION_REQUIRED"),
        (SessionStoreUnavailable("private store details"), 503, "SESSION_STORE_UNAVAILABLE"),
    ],
)
def test_engine_errors_map_to_http_status(
    client: TestClient, exc: Exception, status_code: int, code: str
) -> None:
    client.app.dependency_overrides[get_orchestrator] = lambda: _RaisingOrchestrator(exc)
    for response in (_start(client, "c_err"), _turn(client, "c_err", 1, "xin chào")):
        assert response.status_code == status_code
        assert response.json()["detail"]["code"] == code
        assert "sk_secret" not in response.text
        assert "Traceback" not in response.text


# --- F-03: thứ tự lượt và replay qua HTTP ------------------------------------------------


def test_turn_order_errors_over_http(client: TestClient) -> None:
    _start(client, "c_http_order")
    first = _turn(client, "c_http_order", 1, "Nguyễn Văn A.")

    skipped = _turn(client, "c_http_order", 3, "14/03/1978")
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["code"] == "TURN_OUT_OF_ORDER"
    assert skipped.json()["detail"]["expected_turn"] == 2

    conflict = _turn(client, "c_http_order", 1, "Trần Văn B")
    assert (conflict.status_code, conflict.json()["detail"]["code"]) == (409, "TURN_CONFLICT")

    replay = _turn(client, "c_http_order", 1, "Nguyễn Văn A.")
    assert replay.status_code == 200 and replay.json() == first.json()


def test_start_call_is_idempotent_over_http(client: TestClient) -> None:
    first = _start(client, "c_http_open")
    _turn(client, "c_http_open", 1, "Nguyễn Văn A.")
    again = _start(client, "c_http_open")
    assert again.status_code == 200 and again.json() == first.json()
    # Context không bị reset: lượt 2 vẫn là ngày sinh
    assert _turn(client, "c_http_open", 2, "14/03/1978").json()["state"] == "AWAITING_INTENT"

    other = _start(client, "c_http_open", max_turns=5)
    assert (other.status_code, other.json()["detail"]["code"]) == (409, "CALL_CONFLICT")


def test_new_turn_after_end_returns_call_ended(client: TestClient) -> None:
    _start(client, "c_http_end")
    last = _turn(client, "c_http_end", 1, "cho tôi gặp nhân viên")
    assert last.json()["ended"] is True
    after = _turn(client, "c_http_end", 2, "alo")
    assert (after.status_code, after.json()["detail"]["code"]) == (409, "CALL_ENDED")
    replay = _turn(client, "c_http_end", 1, "cho tôi gặp nhân viên")
    assert (replay.status_code, replay.json()["detail"]["code"]) == (409, "CALL_ENDED")


def test_ready_reports_session_store(
    client: TestClient, redis_store_factory, redis_server, tmp_path
) -> None:
    assert client.get("/ready").json() == {"status": "ready"}

    class Down(RedisSessionStore):
        def check_ready(self) -> None:
            raise SessionStoreUnavailable("redis down")

    app = create_app(
        clinic_factory=FakeClinicAPI,
        engine_settings=EngineSettings(),
        session_store_factory=lambda: Down(redis_store_factory()._client),
        speech_factory=lambda: make_speech_bundle(tmp_path),
        call_mode_factory=_call_mode_factory(redis_server),
    )
    with TestClient(app) as down:
        response = down.get("/ready")
        assert response.status_code == 503
        assert response.json()["code"] == "SESSION_STORE_UNAVAILABLE"
        assert down.get("/health").status_code == 200  # liveness không phụ thuộc Redis


# --- F-04: Information Extraction mới trên đường HTTP -------------------------------------


def _conversation(client: TestClient, call_id: str, lines: list[Optional[str]], **start):
    assert _start(client, call_id, **start).status_code == 200
    bodies = []
    for turn, line in enumerate(lines, start=1):
        response = (
            _turn(client, call_id, turn, None, silence_ms=2000)
            if line is None
            else _turn(client, call_id, turn, line)
        )
        assert response.status_code == 200, response.text
        bodies.append(response.json())
    return bodies


@pytest.mark.parametrize(
    ("call_id", "start", "lines", "outcome", "write"),
    [
        (
            "c_ie_confirm",
            {},
            ["Nguyễn Văn A", "14/03/1978", "Có, tôi đến được."],
            "CONFIRMED",
            ("apt_00417", "CONFIRMED", {}),
        ),
        (
            "c_ie_cancel",
            {},
            ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch", "Vâng", "Hủy đi"],
            "CANCELLED",
            ("apt_00417", "CANCELLED", {"cancel_reason": "UNSPECIFIED"}),
        ),
        (
            "c_ie_resched",
            {},
            ["Nguyễn Văn A", "14/03/1978", "Cho tôi đổi lịch", "10 giờ sáng", "Được"],
            "RESCHEDULED",
            ("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_aa01"}),
        ),
        (
            "c_ie_book",
            {"direction": "inbound", "appointment_id": None, "caller_number": "0912345600"},
            ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch khám", "khung 1", "Đồng ý"],
            "BOOKED",
            ("apt_new_1", "BOOKED", {"slot_id": "slot_aa01"}),
        ),
        (
            "c_ie_voicemail",
            {},
            ["Quý khách vui lòng để lại lời nhắn sau tiếng bíp"],
            "UNREACHABLE",
            ("apt_00417", "UNREACHABLE", {"unreachable_reason": "VOICEMAIL"}),
        ),
    ],
)
def test_information_extraction_over_http(
    client: TestClient,
    clinic: FakeClinicAPI,
    call_id: str,
    start: dict[str, Any],
    lines: list[str],
    outcome: str,
    write: tuple,
) -> None:
    bodies = _conversation(client, call_id, lines, **start)
    assert bodies[-1]["ended"] is True and bodies[-1]["outcome"] == outcome
    assert clinic.writes == [write]

    store = client.app.state.session_store
    last = store.get_turn(call_id, len(lines))
    assert last.status == "COMPLETED" and last.extraction is None
    assert last.input == {} and last.result == {}
    assert store.get_session(call_id).context == {}
    [command] = store.list_commands(call_id)
    assert command.status == "SUCCEEDED"


def test_http_app_restart_keeps_active_session_in_redis(
    redis_store_factory, redis_server, tmp_path
) -> None:
    clinic = FakeClinicAPI()

    def new_app():
        return create_app(
            clinic_factory=lambda: clinic,
            engine_settings=EngineSettings(),
            session_store_factory=redis_store_factory,
            speech_factory=lambda: make_speech_bundle(tmp_path),
            call_mode_factory=_call_mode_factory(redis_server),
        )

    with TestClient(new_app()) as first:
        _start(first, "c_restart_http")
        _turn(first, "c_restart_http", 1, "Nguyễn Văn A.")
        asked = _turn(first, "c_restart_http", 1, "Nguyễn Văn A.").json()

    with TestClient(new_app()) as second:
        assert _turn(second, "c_restart_http", 1, "Nguyễn Văn A.").json() == asked
        assert _turn(second, "c_restart_http", 2, "14/03/1978").status_code == 200


def test_confirm_over_http_reports_confirmed_only_after_write(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    """T-04: lượt đọc lại chưa ghi gì; CONFIRMED chỉ xuất hiện ở lượt Clinic đã ghi."""
    _start(client, "c_http_confirm")
    _turn(client, "c_http_confirm", 1, "Nguyễn Văn A.")
    readback = _turn(client, "c_http_confirm", 2, "Ngày 14 tháng 3 năm 1978.").json()
    assert "tại Vinmec Times City" in readback["utterance"] and readback["outcome"] is None
    assert clinic.writes == []

    body = _turn(client, "c_http_confirm", 3, "Vâng").json()
    assert (body["ended"], body["outcome"], body["state"]) == (True, "CONFIRMED", "ENDED")
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]


def _at_confirm_readback(client: TestClient, call_id: str) -> None:
    _start(client, call_id)
    _turn(client, call_id, 1, "Nguyễn Văn A.")
    _turn(client, call_id, 2, "Ngày 14 tháng 3 năm 1978.")


def test_rejected_confirm_over_http_is_transferred(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_confirm_readback(client, "c_http_rejected")
    clinic.fail_next("confirm_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    body = _turn(client, "c_http_rejected", 3, "Vâng").json()
    assert (body["outcome"], body["ended"]) == ("TRANSFERRED", True)
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]


def test_unknown_confirm_outcome_over_http_needs_reconciliation(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_confirm_readback(client, "c_http_unknown")
    clinic.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)
    response = _turn(client, "c_http_unknown", 3, "Vâng")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CALL_RECONCILIATION_REQUIRED"


# --- T-05: hội thoại Cancel qua HTTP ------------------------------------------------------------


def _at_cancel_reconfirm(client: TestClient, call_id: str, request: str = "Tôi muốn hủy lịch"):
    """Đã xác minh và đã nêu yêu cầu hủy ở lượt 3; lượt kế tiếp là 4."""
    _start(client, call_id)
    _turn(client, call_id, 1, "Nguyễn Văn A.")
    _turn(client, call_id, 2, "Ngày 14 tháng 3 năm 1978.")
    body = _turn(client, call_id, 3, request).json()
    assert (body["state"], body["ended"]) == ("AWAITING_CONFIRMATION", False)
    return body


def test_cancel_over_http_reports_cancelled_only_after_the_second_turn(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_cancel_reconfirm(client, "c_http_cancel", "Tôi muốn hủy lịch vì hôm đó tôi bận")
    assert clinic.writes == []

    body = _turn(client, "c_http_cancel", 4, "Hủy giúp tôi").json()
    assert (body["ended"], body["outcome"], body["state"]) == (True, "CANCELLED", "ENDED")
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "PATIENT_UNAVAILABLE"})]


def test_unclear_then_clear_cancel_over_http_writes_once_with_the_reason(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_cancel_reconfirm(client, "c_http_cancel_unclear")
    assert _turn(client, "c_http_cancel_unclear", 4, "Vâng").json()["ended"] is False
    # Lượt chỉ nêu lý do: ghi nhận lý do, hỏi lại câu xác nhận, vẫn chưa ghi
    body = _turn(client, "c_http_cancel_unclear", 5, "Hôm đó tôi đi công tác").json()
    assert body["ended"] is False and clinic.writes == []

    body = _turn(client, "c_http_cancel_unclear", 6, "Hủy giúp tôi").json()
    assert (body["ended"], body["outcome"]) == (True, "CANCELLED")
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "PATIENT_UNAVAILABLE"})]


def test_changing_mind_to_reschedule_over_http_does_not_cancel(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_cancel_reconfirm(client, "c_http_cancel_mind", "Tôi muốn hủy lịch vì bận")
    body = _turn(client, "c_http_cancel_mind", 4, "Không hủy nữa, tôi muốn đổi lịch").json()
    assert (body["state"], body["ended"]) == ("OFFERING_SLOTS", False)
    assert clinic.writes == []


def test_rejected_cancel_over_http_is_transferred(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_cancel_reconfirm(client, "c_http_cancel_rejected")
    clinic.fail_next("cancel_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    body = _turn(client, "c_http_cancel_rejected", 4, "Hủy giúp tôi").json()
    assert (body["outcome"], body["ended"]) == ("TRANSFERRED", True)
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]


def test_unknown_cancel_outcome_over_http_needs_reconciliation(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_cancel_reconfirm(client, "c_http_cancel_unknown")
    clinic.fail_next("cancel_appointment", outcome_unknown=True, apply_first=True)
    response = _turn(client, "c_http_cancel_unknown", 4, "Hủy giúp tôi")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CALL_RECONCILIATION_REQUIRED"


def test_cancel_with_a_wrong_status_over_http_needs_reconciliation(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    """2xx nhưng bản ghi không ở CANCELLED: chặn đối soát, không ghi thêm lệnh nào."""
    _at_cancel_reconfirm(client, "c_http_cancel_status")
    clinic.cancel_appointment = lambda *args, **kwargs: {
        **clinic.appointments["apt_00417"],
        "status": "SCHEDULED",
    }
    response = _turn(client, "c_http_cancel_status", 4, "Hủy giúp tôi")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CALL_RECONCILIATION_REQUIRED"
    assert clinic.writes == []


def test_resent_cancel_turn_over_http_does_not_write_twice(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_cancel_reconfirm(client, "c_http_cancel_replay")
    assert _turn(client, "c_http_cancel_replay", 4, "Hủy giúp tôi").json()["outcome"] == "CANCELLED"
    replay = _turn(client, "c_http_cancel_replay", 4, "Hủy giúp tôi")
    assert (replay.status_code, replay.json()["detail"]["code"]) == (409, "CALL_ENDED")
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "UNSPECIFIED"})]


# --- T-05 §8: tầng ngữ nghĩa qua HTTP ------------------------------------------------------


def _use_semantic(client: TestClient, semantic) -> None:
    """Gắn `SemanticExtractor` giả vào Orchestrator của app — không có request mạng nào."""
    client.app.state.orchestrator._extractor._semantic = semantic


def test_semantic_reason_over_http_needs_a_second_turn_before_cancelling(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    """Model đọc ra lý do từ câu không có từ khóa nào; vẫn phải xác nhận ở lượt riêng."""
    line = "Ngày đó tôi phải có mặt ở cơ quan"
    _use_semantic(
        client,
        FakeSemantic(
            {
                line.lower(): SemanticOutcome(
                    ReplyKind.INFORM_REASON,
                    cancel_reason="PATIENT_UNAVAILABLE",
                    reason_span="phải có mặt ở cơ quan",
                )
            }
        ),
    )
    _at_cancel_reconfirm(client, "c_http_sem_reason")

    body = _turn(client, "c_http_sem_reason", 4, line).json()
    assert body["ended"] is False and clinic.writes == []

    body = _turn(client, "c_http_sem_reason", 5, "Hủy giúp tôi").json()
    assert (body["ended"], body["outcome"]) == (True, "CANCELLED")
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "PATIENT_UNAVAILABLE"})]


def test_semantic_cannot_cancel_without_a_real_confirmation_over_http(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    """Model khẳng định CONFIRM_ACTION cho một câu mâu thuẫn: HTTP vẫn không trả CANCELLED."""
    line = "Không, hủy đi"
    _use_semantic(
        client,
        FakeSemantic(
            {line.lower(): SemanticOutcome(ReplyKind.CONFIRM_ACTION, reply_span="hủy đi")}
        ),
    )
    _at_cancel_reconfirm(client, "c_http_sem_promote")

    body = _turn(client, "c_http_sem_promote", 4, line).json()
    assert (body["ended"], body["outcome"]) == (False, None)
    assert clinic.writes == []


def test_a_broken_semantic_layer_does_not_break_the_http_turn(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    """Lỗi provider không được thành lỗi Clinic hay 5xx; lượt đi nhánh hỏi lại."""
    _use_semantic(client, BrokenSemantic())
    _at_cancel_reconfirm(client, "c_http_sem_broken")

    response = _turn(client, "c_http_sem_broken", 4, "Tôi không đủ tiền")
    assert response.status_code == 200
    assert response.json()["ended"] is False and clinic.writes == []

    body = _turn(client, "c_http_sem_broken", 5, "Hủy giúp tôi").json()
    assert (body["ended"], body["outcome"]) == (True, "CANCELLED")
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "COST"})]


def test_the_http_response_shape_is_unchanged_by_the_semantic_layer(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    """T-05 §8.4: không thêm khóa vào response chuẩn chỉ để debug semantic."""
    _use_semantic(client, FakeSemantic({}))
    _at_cancel_reconfirm(client, "c_http_sem_shape")
    plain = _turn(client, "c_http_sem_shape", 4, "Ừ thì cũng tùy em thôi").json()

    _use_semantic(client, None)
    _at_cancel_reconfirm(client, "c_http_sem_shape2")
    without = _turn(client, "c_http_sem_shape2", 4, "Ừ thì cũng tùy em thôi").json()
    assert set(plain) == set(without)


# --- T-08: silence và tín hiệu đường dây qua HTTP ----------------------------------------------

_APPOINTMENT_FACTS = ("14 tháng 10", "9 giờ", "Nội tổng quát", "Times City")


def test_outbound_three_silences_over_http_mark_unreachable(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    bodies = _conversation(client, "c_http_silent", [None, None, None])
    assert [body["ended"] for body in bodies] == [False, False, True]
    # Listing 2 không có trường lý do: lý do nằm ở writelog Mock (và trace)
    assert bodies[-1]["outcome"] == "UNREACHABLE"
    assert clinic.writes == [("apt_00417", "UNREACHABLE", {"unreachable_reason": "SILENCE"})]


def test_inbound_three_silences_over_http_transfer_without_write(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    bodies = _conversation(
        client,
        "c_http_in_silent",
        [None, None, None],
        direction="inbound",
        appointment_id=None,
        caller_number="0912345600",
    )
    assert (bodies[-1]["outcome"], bodies[-1]["ended"]) == ("TRANSFERRED", True)
    assert clinic.writes == []


def test_voicemail_over_http_marks_unreachable_without_disclosing(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    bodies = _conversation(
        client,
        "c_http_vm",
        ["Nguyễn Văn A", "Xin chào, bạn đã gọi đến số của Lan. Hiện không thể nghe máy"],
    )
    assert (bodies[-1]["outcome"], bodies[-1]["ended"]) == ("UNREACHABLE", True)
    assert clinic.writes == [("apt_00417", "UNREACHABLE", {"unreachable_reason": "VOICEMAIL"})]
    spoken = " ".join(body["utterance"] for body in bodies)
    assert not any(fact in spoken for fact in _APPOINTMENT_FACTS)


def test_unknown_unreachable_outcome_over_http_needs_reconciliation(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    clinic.fail_next("mark_unreachable", outcome_unknown=True, apply_first=True)
    _conversation(client, "c_http_vm_unknown", [None, None])
    response = _turn(client, "c_http_vm_unknown", 3, None, silence_ms=2000)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CALL_RECONCILIATION_REQUIRED"


# --- Lỗi kết thúc cuộc gọi qua HTTP ---------------------------------------------------------------

DEBUG = {"X-Demo-Debug": "1"}


def _debug_turn(client: TestClient, call_id: str, turn: int, text: Optional[str], **kwargs):
    return client.post(
        f"/v1/calls/{call_id}/turn",
        json={"turn": turn, "audio_url": None, "text": text, "silence_ms": 0, **kwargs},
        headers=DEBUG,
    )


def _extraction_fields(header: str) -> dict[str, Any]:
    return json.loads(unquote(header))


def _demo_headers(response) -> dict[str, str]:
    return {k: v for k, v in response.headers.items() if k.lower().startswith("x-demo-")}


@pytest.mark.parametrize("status", ["CANCELLED", "TRANSFERRED", "UNREACHABLE", "RESCHEDULED"])
def test_start_on_a_non_actionable_appointment_is_409_before_any_session_or_audio(
    client: TestClient, clinic: FakeClinicAPI, status: str
) -> None:
    clinic.appointments["apt_00417"]["status"] = status
    response = _start(client, "c_http_open_blocked", mode="audio")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "APPOINTMENT_NOT_ACTIONABLE"
    assert status not in detail["message"]  # message cố định, không lộ trạng thái lịch
    assert client.app.state.session_store.get_session("c_http_open_blocked") is None
    assert client.app.state.speech.tts.spoken == []


def test_start_on_an_invalid_appointment_read_is_502(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    del clinic.appointments["apt_00417"]["starts_at"]
    response = _start(client, "c_http_open_invalid")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "CLINIC_INVALID_RESPONSE"


def test_invalid_state_transition_over_http_is_409_with_extraction_headers(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_confirm_readback(client, "c_http_not_actionable")
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    response = _debug_turn(client, "c_http_not_actionable", 3, "Vâng")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "APPOINTMENT_NOT_ACTIONABLE"
    headers = _demo_headers(response)
    fields = _extraction_fields(headers.pop("x-demo-extraction-fields"))
    assert headers == {
        "x-demo-extraction-source": "RULE",
        "x-demo-extraction-provenance": "EXACT",
        "x-demo-extraction-question-id": "CONFIRM_READBACK",
        "x-demo-error-type": "APPOINTMENT_NOT_ACTIONABLE",
        "x-demo-error-code": "INVALID_STATE_TRANSITION",
    }
    # Chỉ header extraction-fields mang nội dung câu; các header nhãn vẫn không có
    assert "Vâng" not in " ".join(headers.values())
    assert fields["transcript"] == "Vâng"
    assert fields["fields"] == [
        {"field": "agreement", "value": "AGREE", "span": "vâng", "provenance": "EXACT"}
    ]
    assert clinic.writes == []


def test_a_failed_call_returns_the_saved_error_to_every_later_request(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_confirm_readback(client, "c_http_failed_replay")
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    first = _debug_turn(client, "c_http_failed_replay", 3, "Vâng")
    calls_before = len(clinic.calls)

    for response in (
        _debug_turn(client, "c_http_failed_replay", 3, "Vâng"),
        _debug_turn(client, "c_http_failed_replay", 4, "Tôi muốn hủy lịch"),
        _start(client, "c_http_failed_replay"),
    ):
        assert response.status_code == first.status_code == 409
        assert response.json() == first.json()
    assert _demo_headers(first)["x-demo-error-type"] == "APPOINTMENT_NOT_ACTIONABLE"
    assert len(clinic.calls) == calls_before


def test_rejected_transfer_over_http_is_502_and_never_transferred(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _start(client, "c_http_transfer_rejected")
    clinic.fail_next("transfer_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    response = _debug_turn(client, "c_http_transfer_rejected", 1, "cho tôi gặp nhân viên")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "CLINIC_TERMINATION_FAILED"
    headers = _demo_headers(response)
    assert headers["x-demo-transfer-reason"] == "PATIENT_REQUEST"
    assert headers["x-demo-error-type"] == "CLINIC_TERMINATION_FAILED"
    assert headers["x-demo-error-code"] == "IDEMPOTENCY_CONFLICT"
    assert clinic.writes == []


def test_successful_transfer_over_http_exposes_the_requested_reason(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _start(client, "c_http_transfer_ok")
    response = _debug_turn(client, "c_http_transfer_ok", 1, "cho tôi gặp nhân viên")
    assert response.status_code == 200 and response.json()["outcome"] == "TRANSFERRED"
    assert response.headers["X-Demo-Transfer-Reason"] == "PATIENT_REQUEST"
    assert "X-Demo-Error-Type" not in response.headers
    assert set(response.json()) == {"utterance", "audio_url", "state", "ended", "outcome"}


def test_rejected_unreachable_over_http_is_502_not_transferred(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _start(client, "c_http_unreachable_rejected")
    clinic.fail_next("mark_unreachable", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    for turn in (1, 2):
        assert (
            _turn(client, "c_http_unreachable_rejected", turn, None, silence_ms=2000).json()[
                "ended"
            ]
            is False
        )
    response = _turn(client, "c_http_unreachable_rejected", 3, None, silence_ms=2000)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "CLINIC_TERMINATION_FAILED"
    assert clinic.writes == []


def test_debug_headers_are_absent_without_the_debug_request_header(
    client: TestClient, clinic: FakeClinicAPI
) -> None:
    _at_confirm_readback(client, "c_http_no_debug")
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    response = _turn(client, "c_http_no_debug", 3, "Vâng")
    assert response.status_code == 409 and _demo_headers(response) == {}


def test_demo_header_lists_the_words_each_field_was_read_from(client: TestClient) -> None:
    _start(client, "c_http_fields")
    _debug_turn(client, "c_http_fields", 1, "Nguyễn Văn A")
    response = _debug_turn(client, "c_http_fields", 2, "Ngày 14 tháng 3 năm 1978")
    fields = _extraction_fields(response.headers["X-Demo-Extraction-Fields"])
    assert fields["transcript"] == "Ngày 14 tháng 3 năm 1978"
    dob = next(f for f in fields["fields"] if f["field"] == "dob")
    assert dob["value"] == "1978-03-14" and dob["span"] and dob["provenance"] != "NONE"
    # Chỉ trường trích được; trường không có tín hiệu bị bỏ
    assert all(f["provenance"] != "NONE" for f in fields["fields"])


def test_extraction_fields_are_not_sent_without_the_debug_header(client: TestClient) -> None:
    _start(client, "c_http_fields_off")
    response = _turn(client, "c_http_fields_off", 1, "Nguyễn Văn A")
    assert "X-Demo-Extraction-Fields" not in response.headers

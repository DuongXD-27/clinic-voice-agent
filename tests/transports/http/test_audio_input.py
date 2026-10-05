"""Audio input failures and silence must not alter the shared Core contract."""

import httpx
import pytest
from tests.transports.http.test_calls import _start, _turn

from callbot.engine.session import CallContext
from speech.types import Transcript


def _context(client, call_id):
    store = client.app.state.orchestrator.sessions.store
    return CallContext.from_dict(store.get_session(call_id).context)


@pytest.mark.parametrize("direction", ["inbound", "outbound"])
def test_explicit_silence_skips_broken_audio_and_asr(client, clinic, monkeypatch, direction):
    call_id = "c_silence_audio"
    speech = client.app.state.speech

    def forbidden(*args):
        pytest.fail("silence_ms must bypass loading and ASR")

    monkeypatch.setattr(speech, "audio_loader", forbidden)
    monkeypatch.setattr(speech.asr, "transcribe", forbidden)
    assert (
        _start(
            client,
            call_id,
            mode="audio",
            direction=direction,
            appointment_id="apt_00417" if direction == "outbound" else None,
            caller_number="0912345600" if direction == "inbound" else None,
        ).status_code
        == 200
    )
    for turn in (1, 2, 3):
        response = _turn(client, call_id, turn, None, silence_ms=2000, audio_url="https://broken")
        assert response.status_code == 200
        if turn < 3:
            ctx = _context(client, call_id)
            assert ctx.silent_turns == turn and ctx.failed_understandings == 0
    assert response.json()["outcome"] == (
        "UNREACHABLE" if direction == "outbound" else "TRANSFERRED"
    )
    assert len(clinic.writes) == (1 if direction == "outbound" else 0)


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_asr_is_not_silence_even_when_asr_labels_it_silent(client, clinic, monkeypatch, text):
    _start(client, "c_empty_asr", mode="audio")
    monkeypatch.setattr(
        client.app.state.speech.asr,
        "transcribe",
        lambda segment: Transcript(text=text, confidence=0.01, is_silence=True),
    )
    response = _turn(client, "c_empty_asr", 1, None, audio_url="https://clip")
    assert response.status_code == 200 and not response.json()["ended"]
    ctx = _context(client, "c_empty_asr")
    assert ctx.silent_turns == 0 and ctx.failed_understandings == 1
    assert clinic.writes == []


@pytest.mark.parametrize("stage", ["audio_loader", "asr"])
@pytest.mark.parametrize(
    "error", [ValueError("private transcript"), httpx.ReadTimeout("private URL")]
)
def test_stt_failure_does_not_consume_turn_and_can_retry(client, clinic, monkeypatch, stage, error):
    _start(client, "c_failed_asr", mode="audio")
    speech = client.app.state.speech
    target, attribute = (
        (speech, "audio_loader") if stage == "audio_loader" else (speech.asr, "transcribe")
    )
    original = getattr(target, attribute)

    def fail(*args):
        raise error

    monkeypatch.setattr(target, attribute, fail)
    spoken_before = list(speech.tts.spoken)
    response = _turn(client, "c_failed_asr", 1, None, audio_url="https://clip")
    assert response.status_code == 503 and response.json()["detail"]["code"] == "UPSTREAM"
    assert "private" not in response.text
    ctx = _context(client, "c_failed_asr")
    assert ctx.turn == 0 and ctx.silent_turns == ctx.failed_understandings == 0
    assert clinic.writes == [] and speech.tts.spoken == spoken_before
    monkeypatch.setattr(target, attribute, original)
    speech.asr.transcript = "Nguyễn Văn A"
    retry = _turn(client, "c_failed_asr", 1, None, audio_url="https://clip")
    assert retry.status_code == 200
    assert _context(client, "c_failed_asr").question.question_id.value == "ASK_DOB"


@pytest.mark.parametrize("mode", ["text", "audio"])
def test_identical_transcript_uses_same_identity_readback_and_confirm_flow(client, clinic, mode):
    call_id = "c_input_parity"
    _start(client, call_id, mode=mode)
    speech = client.app.state.speech
    for turn, text in enumerate(["Nguyễn Văn A", "14/03/1978", "vâng"], start=1):
        speech.asr.transcript = text
        speech.asr.confidence = 1.0  # Certain extraction; low confidence is tested separately.
        response = _turn(
            client,
            call_id,
            turn,
            text if mode == "text" else None,
            audio_url=f"https://clip/{turn}" if mode == "audio" else None,
        )
        assert response.status_code == 200
        if turn == 1:
            ctx = _context(client, call_id)
            assert ctx.question.question_id.value == "ASK_DOB" and not ctx.identity_verified
            assert clinic.writes == []
        elif turn == 2:
            ctx = _context(client, call_id)
            assert ctx.identity_verified and ctx.question.question_id.value == "CONFIRM_READBACK"
            assert clinic.writes == []
    assert response.json()["state"] == "ENDED" and response.json()["outcome"] == "CONFIRMED"
    assert len(clinic.writes) == 1 and clinic.writes[0][1] == "CONFIRMED"


def test_low_asr_confidence_reasks_open_identity_without_disclosure(client, clinic):
    _start(client, "c_low_confidence", mode="audio")
    speech = client.app.state.speech
    speech.asr.transcript = "Nguyễn Văn A"
    speech.asr.confidence = 0.01
    response = _turn(client, "c_low_confidence", 1, None, audio_url="https://clip/1")
    assert response.status_code == 200
    ctx = _context(client, "c_low_confidence")
    assert ctx.question.question_id.value == "ASK_NAME" and not ctx.identity_verified
    assert ctx.claimed_name is None and ctx.failed_understandings == 1
    assert "Nguyễn" not in response.json()["utterance"] and clinic.writes == []

"""Retry đầu vào audio dùng transcript đã lưu, không gọi ASR khi replay/invalid turn."""

import pytest
from tests.transports.http.test_calls import _start, _turn

from callbot.engine.types import CallerInput


def _audio(client, call_id, turn, text):
    client.app.state.speech.asr.transcript = text
    return _turn(client, call_id, turn, None, audio_url=f"https://clip/{turn}")


def test_replay_uses_committed_transcript_without_asr(client, clinic):
    _start(client, "c_cached", mode="audio")
    first = _audio(client, "c_cached", 1, "Nguyễn Văn A")
    speech = client.app.state.speech
    seen_asr = len(speech.asr.received)
    calls = list(clinic.calls)
    speech.asr.transcript = "Nguyễn Văn B"
    retry = _audio(client, "c_cached", 1, "Nguyễn Văn B")
    assert retry.json() == first.json() and retry.status_code == 200
    assert len(speech.asr.received) == seen_asr
    assert clinic.calls == calls
    changed = _turn(client, "c_cached", 1, None, audio_url="https://different")
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "TURN_CONFLICT"
    assert len(speech.asr.received) == seen_asr


def test_invalid_order_and_ended_call_do_not_invoke_asr(client, clinic):
    _start(client, "c_order_audio", mode="audio")
    speech = client.app.state.speech
    before = len(speech.asr.received)
    assert _audio(client, "c_order_audio", 3, "alo").status_code == 409
    assert len(speech.asr.received) == before
    assert _audio(client, "c_order_audio", 1, "cho tôi gặp nhân viên").json()["ended"]
    before = len(speech.asr.received)
    assert _audio(client, "c_order_audio", 1, "cho tôi gặp nhân viên").status_code == 409
    assert len(speech.asr.received) == before


def test_interrupted_processing_reuses_transcript_from_reserved_turn(client, clinic, monkeypatch):
    _start(client, "c_resolved", mode="audio")
    speech = client.app.state.speech
    speech.asr.transcript = "Nguyễn Văn A"
    bot = client.app.state.orchestrator

    class Crash(BaseException):
        pass

    def interrupted(*args):
        raise Crash()

    with monkeypatch.context() as patch:
        patch.setattr(bot, "_process", interrupted)
        with pytest.raises(Crash):
            bot.handle_turn_with_details(
                "c_resolved",
                CallerInput(1, audio_url="https://clip/1"),
                resolve_input=lambda: CallerInput(
                    1, text="Nguyễn Văn A", audio_url="https://clip/1"
                ),
            )
    before = len(speech.asr.received)
    retry = _audio(client, "c_resolved", 1, "Nguyễn Văn B")
    assert retry.status_code == 200 and "ngày" in retry.json()["utterance"]
    assert len(speech.asr.received) == before and clinic.writes == []

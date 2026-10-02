"""Retry audio qua Core thật: không chạy lại ASR hoặc lệnh Clinic đã commit."""

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from tests.transports.http.test_calls import _start, _turn

from callbot.transports.http.call_mode import OUTPUT_RETRY_TTL_S, CallModeStore


def _audio(client, call_id, turn, text):
    client.app.state.speech.asr.transcript = text
    return _turn(client, call_id, turn, None, audio_url=f"https://clip/{turn}")


def test_replay_uses_committed_transcript_and_audio_without_asr_or_tts(client, clinic):
    _start(client, "c_cached", mode="audio")
    first = _audio(client, "c_cached", 1, "Nguyễn Văn A")
    speech = client.app.state.speech
    seen_asr, seen_tts = len(speech.asr.received), len(speech.tts.spoken)
    calls = list(clinic.calls)
    speech.asr.transcript = "Nguyễn Văn B"
    retry = _audio(client, "c_cached", 1, "Nguyễn Văn B")
    assert retry.json() == first.json() and retry.status_code == 200
    assert len(speech.asr.received) == seen_asr and len(speech.tts.spoken) == seen_tts
    assert clinic.calls == calls
    changed = _turn(client, "c_cached", 1, None, audio_url="https://different")
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "TURN_CONFLICT"
    assert len(speech.asr.received) == seen_asr


@pytest.mark.parametrize("failure", ["provider", "none", "empty", "storage"])
@pytest.mark.parametrize("terminal", [False, True])
def test_output_failure_recovers_without_repeating_core(
    client, clinic, monkeypatch, failure, terminal
):
    call_id = "c_output_retry"
    _start(client, call_id, mode="audio")
    if terminal:
        assert _audio(client, call_id, 1, "Nguyễn Văn A").status_code == 200
        assert _audio(client, call_id, 2, "14/03/1978").status_code == 200
    turn = 3 if terminal else 1
    text = "vâng" if terminal else "Nguyễn Văn A"
    speech = client.app.state.speech
    mode = client.app.state.call_mode
    with monkeypatch.context() as patch:
        if failure == "provider":
            speech.tts.error = RuntimeError("private provider response")
        elif failure == "none":
            speech.tts.respond = False
        elif failure == "empty":
            from speech.types import AudioSegment

            patch.setattr(speech.tts, "synthesize", lambda text: AudioSegment(pcm=b""))
        else:

            def broken(*args):
                raise OSError("private storage path")

            patch.setattr(speech.audio_store, "save", broken)
        response = _audio(client, call_id, turn, text)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUDIO_OUTPUT_UNAVAILABLE"
    assert "private" not in response.text
    store = client.app.state.session_store
    before = store.get_session(call_id)
    assert before.last_completed_turn == turn
    calls, writes = list(clinic.calls), list(clinic.writes)
    seen_asr = len(speech.asr.received)
    pending = mode.pending_output(call_id, turn)
    if terminal:
        assert before.context == {} and before.purged_reason == "ENDED"
        assert pending["action"]["outcome"] == "CONFIRMED"
        assert "transcript" not in pending and "extraction" not in pending
        assert 0 < mode._client.ttl(mode._output_key(call_id, turn)) <= OUTPUT_RETRY_TTL_S
        changed = _turn(client, call_id, turn, None, audio_url="https://changed")
        assert changed.status_code == 409
    else:
        assert pending is None
    speech.tts.error = None
    speech.tts.respond = True
    retry = _audio(client, call_id, turn, "ASR lần sau trả nội dung khác")
    assert retry.status_code == 200
    assert retry.json()["ended"] == terminal and retry.json()["audio_url"]
    assert client.get(retry.json()["audio_url"]).status_code == 200
    assert len(speech.asr.received) == seen_asr
    assert clinic.calls == calls and clinic.writes == writes
    assert store.get_session(call_id) == before
    assert mode.pending_output(call_id, turn) is None
    if terminal:
        assert _audio(client, call_id, turn, text).status_code == 409


def test_opening_output_retry_keeps_mode_and_does_not_reset_call(client, clinic):
    speech = client.app.state.speech
    speech.tts.error = TimeoutError("private")
    assert _start(client, "c_open_retry", mode="audio").status_code == 503
    before = client.app.state.session_store.get_session("c_open_retry")
    calls = list(clinic.calls)
    assert _start(client, "c_open_retry", mode="text").status_code == 409
    speech.tts.error = None
    response = _start(client, "c_open_retry", mode="audio")
    assert response.status_code == 200 and response.json()["audio_url"]
    assert client.app.state.session_store.get_session("c_open_retry") == before
    assert clinic.calls == calls


def test_transport_lock_serializes_duplicate_audio_requests(client, monkeypatch):
    _start(client, "c_race_audio", mode="audio")
    speech = client.app.state.speech
    speech.asr.transcript = "Nguyễn Văn A"
    entered, release = threading.Event(), threading.Event()
    original = speech.asr.transcribe
    before = len(speech.asr.received)

    def held(segment):
        entered.set()
        assert release.wait(2)
        return original(segment)

    monkeypatch.setattr(speech.asr, "transcribe", held)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_turn, client, "c_race_audio", 1, None, 0, "https://clip/1")
        try:
            assert entered.wait(2)
            second = executor.submit(_turn, client, "c_race_audio", 1, None, 0, "https://clip/1")
        finally:
            release.set()
        responses = [first.result(timeout=3), second.result(timeout=3)]
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json() == responses[1].json()
    assert len(speech.asr.received) == before + 1


def test_pending_output_ttl_is_not_extended_by_retry(client):
    mode = client.app.state.call_mode
    mode.save_pending_output("c_ttl", 1, "digest", {"utterance": "cũ"})
    key = mode._output_key("c_ttl", 1)
    mode._client.expire(key, 10)
    mode.save_pending_output("c_ttl", 1, "digest", {"utterance": "mới"})
    assert mode._client.ttl(key) <= 10
    assert mode.pending_output("c_ttl", 1)["action"]["utterance"] == "cũ"


def test_expired_terminal_receipt_does_not_reopen_core(client, clinic):
    _start(client, "c_expired_output", mode="audio")
    speech = client.app.state.speech
    speech.tts.error = TimeoutError("private")
    assert _audio(client, "c_expired_output", 1, "cho tôi gặp nhân viên").status_code == 503
    mode = client.app.state.call_mode
    mode._client.delete(mode._output_key("c_expired_output", 1))
    before = list(clinic.calls)
    seen_asr = len(speech.asr.received)
    speech.tts.error = None
    assert _audio(client, "c_expired_output", 1, "cho tôi gặp nhân viên").status_code == 409
    assert clinic.calls == before and len(speech.asr.received) == seen_asr


def test_terminal_receipt_storage_failure_cannot_repeat_clinic_write(client, clinic, monkeypatch):
    from callbot.engine import SessionStoreUnavailable

    _start(client, "c_missing_receipt", mode="audio")
    assert _audio(client, "c_missing_receipt", 1, "Nguyễn Văn A").status_code == 200
    assert _audio(client, "c_missing_receipt", 2, "14/03/1978").status_code == 200

    def unavailable(*args):
        raise SessionStoreUnavailable("private")

    with monkeypatch.context() as patch:
        patch.setattr(client.app.state.call_mode, "save_pending_output", unavailable)
        response = _audio(client, "c_missing_receipt", 3, "vâng")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SESSION_STORE_UNAVAILABLE"
    calls = list(clinic.calls)
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
    assert _audio(client, "c_missing_receipt", 3, "vâng").status_code == 409
    assert clinic.calls == calls


def test_terminal_output_can_recover_on_another_transport_instance(client, monkeypatch):
    _start(client, "c_worker_retry", mode="audio")
    original = client.app.state.call_mode
    speech = client.app.state.speech
    speech.tts.error = TimeoutError("private")
    assert _audio(client, "c_worker_retry", 1, "cho tôi gặp nhân viên").status_code == 503
    other = CallModeStore(original._client, key_prefix=original._prefix)
    monkeypatch.setattr(client.app.state, "call_mode", other)
    speech.tts.error = None
    response = _audio(client, "c_worker_retry", 1, "ASR không được gọi lần nữa")
    assert response.status_code == 200 and response.json()["outcome"] == "TRANSFERRED"
    assert original.pending_output("c_worker_retry", 1) is None


def test_mode_and_pending_output_work_across_transport_instances(client):
    original = client.app.state.call_mode
    other = CallModeStore(original._client, key_prefix=original._prefix)
    original.set_audio("c_shared")
    original.save_pending_output("c_shared", 2, "digest", {"utterance": "đã duyệt"})
    assert other.is_audio("c_shared")
    assert other.pending_output("c_shared", 2) == original.pending_output("c_shared", 2)


def test_turn_checks_mode_after_start_has_released_transport_lock(client, clinic, monkeypatch):
    call_id = "c_mode_race"
    assert _start(client, call_id, mode="audio").status_code == 200
    mode = client.app.state.call_mode
    # Tái hiện khoảng start đã mở Core nhưng chưa ghi mode, không dùng sleep để tạo race.
    mode._client.delete(mode._key(call_id))
    original_lock = mode.request_lock

    @contextmanager
    def start_finishes_before_turn(call_id):
        with original_lock(call_id):
            mode.set_audio(call_id)
            yield

    monkeypatch.setattr(mode, "request_lock", start_finishes_before_turn)
    before = client.app.state.session_store.get_session(call_id)
    response = _turn(client, call_id, 1, "Nguyễn Văn A")
    assert response.status_code == 422 and response.json()["detail"]["code"] == "TEXT_NOT_ALLOWED"
    assert client.app.state.session_store.get_session(call_id) == before
    assert clinic.writes == []

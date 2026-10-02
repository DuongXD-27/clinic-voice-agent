"""Kiểm chứng tích hợp ASR self-host bằng clip 8 kHz có sẵn; không gọi Luna/TTS thật.

Chạy riêng: CALLBOT_REAL_ASR=1 python -X utf8 -m pytest tests/transports/http/test_audio_real_asr.py -q
"""

import os
from pathlib import Path
from time import perf_counter

import pytest
import yaml
from tests.transports.http.test_calls import _start, _turn

from inference.asr import create_asr_gateway
from speech.asr.recognizer import SpeechRecognizer
from speech.audio.codec import decode_wav

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    os.environ.get("CALLBOT_REAL_ASR") != "1", reason="Kiểm chứng ASR self-host chạy opt-in"
)


@pytest.fixture(scope="module")
def real_asr():
    # Chọn tường minh model local, không đọc asr_provider từ .env của máy.
    return SpeechRecognizer(create_asr_gateway("zipformer"))


@pytest.mark.parametrize(
    "scenario,clips,outcome",
    [
        ("identity", ["STT_ID_02", "STT_DOB_01"], None),
        ("confirm", ["STT_ID_02", "STT_DOB_01", "STT_CF_01"], "CONFIRMED"),
        ("voicemail", ["STT_SIG_04"], "UNREACHABLE"),
    ],
)
def test_real_asr_clips_drive_shared_core(
    client, clinic, monkeypatch, real_asr, scenario, clips, outcome
):
    speech = client.app.state.speech
    monkeypatch.setattr(speech, "asr", real_asr)
    golden = yaml.safe_load((ROOT / "eval/stt-bench/golden-cases.yaml").read_text(encoding="utf-8"))
    paths = {row["id"]: ROOT / "eval/stt-bench" / row["audio"] for row in golden["cases"]}
    loaded = []

    def load(clip):
        loaded.append(clip)
        return decode_wav(paths[clip].read_bytes())

    monkeypatch.setattr(speech, "audio_loader", load)
    call_id = f"c_real_{scenario}"
    assert _start(client, call_id, mode="audio").status_code == 200
    for turn, clip in enumerate(clips, 1):
        started = perf_counter()
        response = _turn(client, call_id, turn, None, audio_url=clip)
        assert response.status_code == 200, response.text
        assert client.get(response.json()["audio_url"]).status_code == 200
        elapsed = perf_counter() - started
        assert elapsed < 8.0
        if not response.json()["ended"]:
            record = client.app.state.session_store.get_turn(call_id, turn)
            print(f"{scenario} lượt {turn}: {record.input['text']!r}; {elapsed:.3f}s")
    assert loaded == clips
    assert response.json()["outcome"] == outcome
    assert len(clinic.writes) == (0 if outcome is None else 1)
    assert speech.tts.spoken[-1] == response.json()["utterance"]

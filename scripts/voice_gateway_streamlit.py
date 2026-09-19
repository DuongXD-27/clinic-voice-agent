"""Streamlit UI cơ bản để quan sát phản ứng thật của hệ thống (Phase 5, tuỳ chọn,
temp/plan_mvp_zipformer.md) — bọc lại đúng logic đã verify trong voice_gateway.py,
không viết lại STT/Core/TTS.

Mic chạy nền liên tục qua một thread Python (không dùng streamlit-webrtc/browser
mic) — VAD tự cắt câu, mỗi câu tự động gửi qua Core rồi phát trả lời qua loa,
đồng thời hiện transcript + audio player trên trang. Chỉ outbound.

Chạy:
    streamlit run scripts/voice_gateway_streamlit.py
"""

import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx  # noqa: E402
import streamlit as st  # noqa: E402

from voice_gateway import (  # noqa: E402
    CoreClient,
    _frame_generator,
    capture_one_segment,
    drain_stale_audio,
    play_audio,
    start_mic,
)

from callbot.speech.asr.zipformer import ZipFormerASR, default_paths  # noqa: E402
from callbot.speech.audio.codec import encode_wav  # noqa: E402
from callbot.speech.settings import SpeechSettings  # noqa: E402
from callbot.speech.tts import create_tts  # noqa: E402
from callbot.speech.vad import EnergyFrameClassifier, StreamingVAD  # noqa: E402

st.set_page_config(page_title="Voice Gateway — quan sát trực tiếp", page_icon="🎙️")

# Kịch bản cho apt_00417 (canonical fixture — temp/HANDOFF.md §5.1, §6.2). Từ khóa
# lấy đúng từ code engine (src/callbot/engine/dialogue/extraction/*.py), không đoán.
IDENTITY_STEPS = [
    'Bot hỏi họ tên → nói: "Nguyễn Văn A"',
    'Bot hỏi ngày sinh → nói: "mười bốn tháng ba năm một chín bảy tám"',
]
SCENARIOS = {
    "confirm": {
        "label": "✅ Xác nhận tham dự (Confirm)",
        "steps": IDENTITY_STEPS + [
            'Bot đọc lại lịch hẹn, hỏi xác nhận → nói bất kỳ từ đồng ý: "vâng" / "đúng" / "có" / "đồng ý"',
        ],
        "note": None,
    },
    "cancel": {
        "label": "❌ Hủy lịch (Cancel — xác nhận 2 lần)",
        "steps": IDENTITY_STEPS + [
            'Nói: "tôi muốn hủy lịch" (hoặc "không đến được", "không đi nữa"...)',
            'Bot hỏi xác nhận lại → PHẢI lặp lại đúng từ "hủy". Chỉ nói "vâng"/"đúng"/"không sao" KHÔNG đủ — engine coi là chưa rõ ràng và hỏi lại.',
        ],
        "note": "Contract §SF-05: hủy lịch bắt buộc xác nhận rõ ràng 2 lần, không chấp nhận trả lời mơ hồ.",
    },
    "transfer": {
        "label": "📞 Chuyển tiếp nhân viên (Transfer)",
        "steps": IDENTITY_STEPS + [
            'Nói một trong: "cho tôi gặp nhân viên", hoặc câu hỏi ngoài phạm vi như "bảo hiểm của tôi thế nào", "viện phí bao nhiêu", hoặc "tôi là vợ anh ấy" (không phải chính bệnh nhân trả lời)',
        ],
        "note": "Cũng tự chuyển tiếp nếu bot không hiểu 2 lượt liên tiếp (nói câu vô nghĩa 2 lần để thử).",
    },
    "reschedule": {
        "label": "🔁 Đổi lịch (Reschedule)",
        "steps": IDENTITY_STEPS + [
            'Nói: "tôi muốn đổi lịch" (hoặc "dời lịch", "đổi giờ", "hẹn lại")',
            'Bot đọc tối đa 3 khung giờ → chọn: "khung một" / "khung hai" / "cái đầu tiên" / "cái cuối", hoặc mô tả ngày giờ',
            'Bot đọc lại khung đã chọn, hỏi xác nhận → nói: "chốt" / "đặt đi" / "vâng"',
        ],
        "note": "Khung giờ hiển thị lấy đúng từ GET /v1/slots — chỉ có slot_91d2 (14/10 15:00) đang trống thật.",
    },
    "unreachable": {
        "label": "🔇 Không liên lạc được (Unreachable)",
        "steps": ["Không nói gì cả — im lặng liên tục trong nhiều lượt."],
        "note": (
            "⚠️ CHƯA test được bằng giọng nói ở UI này: vòng lặp hiện tại chỉ gửi lượt lên "
            "Core khi VAD phát hiện có tiếng nói, chưa có cơ chế gửi 'lượt im lặng' "
            "(silence_ms) khi bạn không nói gì. Cần sửa thêm nếu muốn test nhánh này."
        ),
    },
}


@st.cache_resource
def _load_asr() -> ZipFormerASR:
    return ZipFormerASR(**default_paths())


@st.cache_resource
def _load_tts():
    return create_tts(SpeechSettings(tts_provider="openai"))


def _worker(
    q: "queue.Queue",
    stop_event: threading.Event,
    mic_proc,
    core: CoreClient,
    asr: ZipFormerASR,
    vad: StreamingVAD,
    tts,
    output_device: str,
) -> None:
    """Chạy trong thread nền — không được gọi bất kỳ hàm st.* nào ở đây."""
    frames = _frame_generator(mic_proc.stdout)
    try:
        while not stop_event.is_set():
            drain_stale_audio(mic_proc.stdout)
            segment = capture_one_segment(vad, frames)
            if segment is None:
                q.put({"type": "stopped"})
                return

            transcript = asr.transcribe(segment)
            if transcript.is_silence:
                continue
            q.put({"type": "caller", "text": transcript.text})

            try:
                result = core.send_turn(transcript.text)
            except Exception as exc:
                q.put({"type": "error", "text": f"Lỗi gọi Core: {exc}"})
                return

            audio_bytes: Optional[bytes] = None
            if tts is not None and result["utterance"].strip():
                tts_segment = tts.synthesize(result["utterance"])
                if tts_segment is not None:
                    play_audio(tts_segment, output_device)
                    audio_bytes = encode_wav(tts_segment)
            q.put({"type": "bot", "text": result["utterance"], "audio": audio_bytes})

            if result["ended"]:
                q.put({"type": "ended", "outcome": result["outcome"]})
                return
    except Exception as exc:  # phòng lỗi bất ngờ trong thread nền không làm crash UI
        q.put({"type": "error", "text": f"Lỗi luồng nền: {exc}"})


def _drain_queue() -> None:
    q = st.session_state.event_queue
    while True:
        try:
            event = q.get_nowait()
        except queue.Empty:
            break
        if event["type"] in ("caller", "bot"):
            st.session_state.messages.append(event)
        elif event["type"] == "ended":
            st.session_state.messages.append(
                {"type": "system", "text": f"Cuộc gọi kết thúc: {event['outcome']}"}
            )
            st.session_state.running = False
        elif event["type"] in ("stopped", "error"):
            st.session_state.messages.append(
                {"type": "system", "text": event.get("text", "Mic đã dừng.")}
            )
            st.session_state.running = False


def _stop() -> None:
    if st.session_state.get("mic_proc") is not None:
        st.session_state.mic_proc.terminate()
    if st.session_state.get("stop_event") is not None:
        st.session_state.stop_event.set()
    if st.session_state.get("worker") is not None:
        st.session_state.worker.join(timeout=3)
    if st.session_state.get("core") is not None:
        st.session_state.core.close()
    st.session_state.running = False


st.session_state.setdefault("running", False)
st.session_state.setdefault("messages", [])
st.session_state.setdefault("event_queue", queue.Queue())

with st.sidebar:
    st.title("🎙️ Voice Gateway")
    st.caption("Mic thật → VAD → ZipFormer 68M → Core Agent (HTTP) → OpenAI TTS → loa")

    scenario_key = st.selectbox(
        "Kịch bản đang test",
        list(SCENARIOS),
        format_func=lambda k: SCENARIOS[k]["label"],
        disabled=st.session_state.running,
    )
    st.session_state.scenario_key = scenario_key

    appointment_id = st.text_input("Appointment ID (outbound)", value="apt_00417", disabled=st.session_state.running)
    base_url = st.text_input("Core base URL", value="http://localhost:8002", disabled=st.session_state.running)
    input_device = st.text_input("Mic device (ALSA)", value="default", disabled=st.session_state.running)
    output_device = st.text_input("Loa device (ALSA)", value="default", disabled=st.session_state.running)
    vad_threshold = st.slider("Ngưỡng RMS VAD", 100.0, 3000.0, 500.0, step=50.0, disabled=st.session_state.running)
    vad_silence_ms = st.slider("Im lặng để chốt câu (ms)", 200, 1500, 600, step=50, disabled=st.session_state.running)
    max_turns = st.number_input("Số lượt tối đa", min_value=1, value=20, disabled=st.session_state.running)

    st.divider()
    st.caption("apt_00417 chỉ đi được MỘT nhánh mỗi lần — reset trước khi đổi kịch bản khác.")
    clinic_mock_url = st.text_input("Clinic-mock URL (từ host)", value="http://localhost:8000", disabled=st.session_state.running)
    clinic_mock_key = st.text_input("Clinic-mock API key", value="sk_dev_demo", type="password", disabled=st.session_state.running)
    if st.button("🔄 Reset dữ liệu clinic-mock", use_container_width=True, disabled=st.session_state.running):
        try:
            headers = {"Authorization": f"Bearer {clinic_mock_key}"}
            httpx.post(f"{clinic_mock_url}/_harness/reset", headers=headers, timeout=10).raise_for_status()
            httpx.post(f"{clinic_mock_url}/_harness/seed", headers=headers, timeout=10).raise_for_status()
        except Exception as exc:
            st.error(f"Reset lỗi: {exc}")
        else:
            st.success("Đã reset + seed lại apt_00417 về SCHEDULED.")

    st.divider()
    if not st.session_state.running:
        if st.button("▶️ Bắt đầu cuộc gọi", type="primary", use_container_width=True):
            core = CoreClient(base_url, int(max_turns))
            try:
                started = core.start_call(appointment_id)
            except Exception as exc:
                st.error(f"Không khởi tạo được cuộc gọi: {exc}")
            else:
                st.session_state.messages = [{"type": "bot", "text": started["utterance"], "audio": None}]
                if started["state"] == "ENDED":
                    core.close()
                else:
                    asr = _load_asr()
                    tts = _load_tts()
                    vad = StreamingVAD(EnergyFrameClassifier(vad_threshold), end_silence_ms=int(vad_silence_ms))
                    mic_proc = start_mic(input_device)
                    stop_event = threading.Event()
                    worker = threading.Thread(
                        target=_worker,
                        args=(st.session_state.event_queue, stop_event, mic_proc, core, asr, vad, tts, output_device),
                        daemon=True,
                    )
                    st.session_state.core = core
                    st.session_state.mic_proc = mic_proc
                    st.session_state.stop_event = stop_event
                    st.session_state.worker = worker
                    st.session_state.running = True
                    worker.start()
                st.rerun()
    else:
        st.info("Đang nghe — nói vào mic.")
        if st.button("⏹️ Dừng", use_container_width=True):
            _stop()
            st.rerun()

scenario = SCENARIOS[st.session_state.get("scenario_key", "confirm")]
with st.expander(f"📋 Kịch bản để nói — {scenario['label']}", expanded=not st.session_state.running):
    for i, step in enumerate(scenario["steps"], 1):
        st.markdown(f"{i}. {step}")
    if scenario["note"]:
        st.warning(scenario["note"])

st.header("Hội thoại")
if not st.session_state.messages:
    st.caption("Bấm **Bắt đầu cuộc gọi** ở sidebar rồi nói vào mic.")

_drain_queue()

st.session_state.setdefault("last_autoplayed_index", -1)

# Trang tự rerun mỗi giây khi đang nghe (xem cuối file) nên phải nhớ đã autoplay
# tin nào rồi — nếu không, mọi audio cũ sẽ tự phát lại từ đầu ở mỗi lần rerun.
for index, message in enumerate(st.session_state.messages):
    if message["type"] == "system":
        st.info(message["text"])
        continue
    with st.chat_message("assistant" if message["type"] == "bot" else "user"):
        st.write(message["text"])
        if message.get("audio"):
            autoplay = index > st.session_state.last_autoplayed_index
            st.audio(message["audio"], format="audio/wav", autoplay=autoplay)
            if autoplay:
                st.session_state.last_autoplayed_index = index

if st.session_state.running:
    time.sleep(1)
    st.rerun()

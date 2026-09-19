"""Demo public: mic trình duyệt (liên tục, VAD tự cắt câu) -> ZipFormer STT ->
Core Agent thật (HTTP) -> OpenAI TTS -> phát tự động.

Server (Cloud Run) không có mic/loa vật lý — mic của người xem chảy qua WebRTC
(`streamlit-webrtc`) tới đây, y hệt cách `scripts/voice_gateway_streamlit.py` bắt
mic local qua `arecord`, chỉ khác nguồn audio. VAD (`StreamingVAD` +
`EnergyFrameClassifier`, tái dùng nguyên từ `speech/vad/`) tự phát hiện lúc người
dùng dừng nói để cắt câu — không phải partial transcript thật (không có model ASR
tiếng Việt nào streaming thật, xem plan), chỉ là tự động hoá điểm cắt câu.

Deploy sau NAT/proxy (Cloud Run) cần TURN server — dùng Twilio Network Traversal
Service (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN trong Secrets).

Core Agent gọi qua đúng 2 endpoint HTTP công khai (POST /v1/calls,
POST /v1/calls/{id}/turn, mode="text") — không đổi gì phía backend.
"""

import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import av  # noqa: E402
import httpx  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit_webrtc import WebRtcMode, webrtc_streamer  # noqa: E402

from callbot.speech.asr.zipformer import ZipFormerASR, default_paths  # noqa: E402
from callbot.speech.audio.codec import encode_wav  # noqa: E402
from callbot.speech.tts.openai import OpenAITTS  # noqa: E402
from callbot.speech.types import WIDEBAND_RATE, AudioSegment  # noqa: E402
from callbot.speech.vad import EnergyFrameClassifier, StreamingVAD  # noqa: E402

st.set_page_config(page_title="Callbot Voice Demo", page_icon="📞")

FRAME_MS = 30
FRAME_BYTES = int(WIDEBAND_RATE * FRAME_MS / 1000) * 2  # PCM 16-bit mono, 30ms
MIN_SPEECH_MS = 250  # đoạn ngắn hơn (tạp âm/blip mic) không đủ context cho ZipFormer
MAX_SPEECH_MS = 6000  # chặn trường hợp tạp âm nền không bao giờ tụt đủ lâu để VAD tự cắt
# (thấy thực tế: 1 đoạn tạp âm nền phẳng kéo dài 7.8s bị đưa nguyên vào ZipFormer,
# model hallucinate ra câu nghe hợp lý nhưng vô nghĩa — xem debug_audio khi điều tra)


def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


CORE_BASE_URL = _secret("CORE_BASE_URL", "https://vmec-callbot.tech")
ACCESS_PASSWORD = _secret("ACCESS_PASSWORD", "")
OPENAI_API_KEY = _secret("OPENAI_API_KEY", "")
TWILIO_ACCOUNT_SID = _secret("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = _secret("TWILIO_AUTH_TOKEN", "")
# Debug: nếu đặt, lưu lại mỗi đoạn audio VAD cắt ra (trước khi đưa vào ZipFormer)
# thành file .wav vào thư mục này, để nghe lại xem audio đã méo trước khi tới ASR
# hay chưa. Để trống (mặc định) thì không lưu gì — không bật trên Cloud Run thật.
DEBUG_AUDIO_DIR = _secret("DEBUG_AUDIO_DIR", "")

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
            'Bot hỏi xác nhận lại → PHẢI lặp lại đúng từ "hủy". Chỉ nói "vâng"/"đúng" KHÔNG đủ.',
        ],
        "note": "Contract §SF-05: hủy lịch bắt buộc xác nhận rõ ràng 2 lần.",
    },
    "transfer": {
        "label": "📞 Chuyển tiếp nhân viên (Transfer)",
        "steps": IDENTITY_STEPS + [
            'Nói một trong: "cho tôi gặp nhân viên", hoặc câu hỏi ngoài phạm vi như "bảo hiểm của tôi thế nào", hoặc "tôi là vợ anh ấy"',
        ],
        "note": "Cũng tự chuyển tiếp nếu bot không hiểu 2 lượt liên tiếp.",
    },
    "reschedule": {
        "label": "🔁 Đổi lịch (Reschedule)",
        "steps": IDENTITY_STEPS + [
            'Nói: "tôi muốn đổi lịch" (hoặc "dời lịch", "đổi giờ")',
            'Bot đọc tối đa 3 khung giờ → chọn: "khung một" / "khung hai" / "cái đầu tiên"',
            'Bot đọc lại khung đã chọn, hỏi xác nhận → nói: "chốt" / "đặt đi" / "vâng"',
        ],
        "note": "Khung giờ lấy đúng từ GET /v1/slots.",
    },
}


@st.cache_resource
def _load_asr() -> ZipFormerASR:
    return ZipFormerASR(**default_paths())


def _load_tts() -> Optional[OpenAITTS]:
    if not OPENAI_API_KEY:
        return None
    return OpenAITTS(api_key=OPENAI_API_KEY, model="tts-1", voice="alloy")


@st.cache_resource(ttl=3600)
def _ice_servers() -> list:
    """Twilio NTS credentials ngắn hạn — cache 1h để không gọi API mỗi lần rerun."""
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        return [{"urls": ["stun:stun.l.google.com:19302"]}]
    from twilio.rest import Client

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    token = client.tokens.create()
    return token.ice_servers


class CoreClient:
    """Gọi đúng 2 endpoint HTTP công khai của Core Agent thật."""

    def __init__(self, base_url: str, max_turns: int) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=15.0)
        self._max_turns = max_turns
        self.call_id = f"c_demo_{uuid.uuid4().hex[:8]}"
        self.turn = 0

    def start_call(self, appointment_id: str) -> dict:
        payload = {
            "call_id": self.call_id,
            "direction": "outbound",
            "appointment_id": appointment_id,
            "caller_number": None,
            "locale": "vi-VN",
            "mode": "text",
            "max_turns": self._max_turns,
        }
        r = self._client.post("/v1/calls", json=payload)
        r.raise_for_status()
        return r.json()

    def send_turn(self, text: str) -> dict:
        self.turn += 1
        payload = {"turn": self.turn, "audio_url": None, "text": text, "silence_ms": 0}
        r = self._client.post(f"/v1/calls/{self.call_id}/turn", json=payload)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()


# --- Mic liên tục qua WebRTC: frame browser -> hàng đợi byte -> khung 30ms -----------


def _resampled_bytes(resampler: "av.AudioResampler", frame: "av.AudioFrame") -> list:
    """PyAV có thể trả về 1 frame hoặc list frame tuỳ phiên bản — chuẩn hoá về list bytes."""
    out = resampler.resample(frame)
    frames = out if isinstance(out, list) else [out]
    return [f.to_ndarray().tobytes() for f in frames if f is not None]


def _make_audio_frame_callback(raw_queue: "queue.Queue"):
    resampler = av.AudioResampler(format="s16", layout="mono", rate=WIDEBAND_RATE)

    def callback(frame: "av.AudioFrame") -> "av.AudioFrame":
        # pts gốc từ track WebRTC không đều -> AudioResampler cố canh theo nó khi
        # resample, dễ làm mẫu âm lệch/nhân đôi/rớt frame. Reset về None để resampler
        # tự đánh số lại tuần tự (khớp cách streamlit-webrtc dùng trong ví dụ STT).
        frame.pts = None
        for chunk in _resampled_bytes(resampler, frame):
            raw_queue.put(chunk)
        return frame

    return callback


def _byte_frame_generator(raw_queue: "queue.Queue", stop_event: threading.Event):
    buffer = b""
    while not stop_event.is_set():
        try:
            chunk = raw_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        buffer += chunk
        while len(buffer) >= FRAME_BYTES:
            yield buffer[:FRAME_BYTES]
            buffer = buffer[FRAME_BYTES:]


class _MeteredEnergyClassifier(EnergyFrameClassifier):
    """Như EnergyFrameClassifier, chỉ thêm báo định kỳ mức RMS hiện tại ra event_queue
    để hiển thị trên UI — chọn ngưỡng dựa trên số đo thật thay vì đoán mò."""

    def __init__(self, rms_threshold: float, event_queue: "queue.Queue", report_every: int = 6) -> None:
        super().__init__(rms_threshold)
        self._event_queue = event_queue
        self._report_every = report_every
        self._frame_count = 0

    def is_speech(self, frame: bytes) -> bool:
        import numpy as np

        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        self._frame_count += 1
        if self._frame_count % self._report_every == 0:
            self._event_queue.put({"type": "level", "rms": rms})
        return rms >= self._threshold


def _capture_one_segment(vad: StreamingVAD, frames) -> Optional[AudioSegment]:
    """Chờ VAD phát speech_end, gom pcm thành AudioSegment — None nếu mic dừng."""
    chunks: list = []
    total_bytes = 0
    for event in vad.process(frames):
        if event.kind == "speech":
            chunks.append(event.pcm)
            total_bytes += len(event.pcm)
            if total_bytes / 2 / WIDEBAND_RATE * 1000 >= MAX_SPEECH_MS:
                # Tạp âm nền phẳng kéo dài không có khoảng lặng để VAD tự cắt —
                # huỷ đoạn này (không transcribe/không gửi Core), chờ đoạn tiếp theo.
                chunks = []
                total_bytes = 0
        elif event.kind == "speech_end":
            if not chunks:
                continue
            segment = AudioSegment(pcm=b"".join(chunks), sample_rate=WIDEBAND_RATE)
            chunks = []
            total_bytes = 0
            if segment.duration_ms < MIN_SPEECH_MS:
                continue  # tạp âm/blip mic
            return segment
    return None


def _debug_save_segment(segment: AudioSegment, index: int, label: str) -> None:
    """Lưu đoạn audio VAD cắt ra thành .wav để nghe lại — chỉ chạy khi DEBUG_AUDIO_DIR
    được set (xem cấu hình ở đầu file). Không bao giờ làm crash worker nếu ghi lỗi."""
    if not DEBUG_AUDIO_DIR:
        return
    try:
        out_dir = Path(DEBUG_AUDIO_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_label = "".join(c if c.isalnum() else "_" for c in label)[:40] or "empty"
        (out_dir / f"seg_{index:03d}_{segment.duration_ms}ms_{safe_label}.wav").write_bytes(
            encode_wav(segment)
        )
    except Exception:
        pass


def _worker(
    raw_queue: "queue.Queue",
    stop_event: threading.Event,
    event_queue: "queue.Queue",
    vad: StreamingVAD,
    asr: ZipFormerASR,
    core: CoreClient,
    tts: Optional[OpenAITTS],
) -> None:
    """Chạy trong thread nền — không được gọi bất kỳ hàm st.* nào ở đây."""
    frames = _byte_frame_generator(raw_queue, stop_event)
    seg_index = 0
    try:
        while not stop_event.is_set():
            segment = _capture_one_segment(vad, frames)
            if segment is None:
                event_queue.put({"type": "stopped"})
                return

            transcript = asr.transcribe(segment)
            seg_index += 1
            _debug_save_segment(
                segment, seg_index, "SILENCE" if transcript.is_silence else transcript.text
            )
            if transcript.is_silence:
                continue
            event_queue.put({"type": "caller", "text": transcript.text})

            try:
                result = core.send_turn(transcript.text)
            except Exception as exc:
                event_queue.put({"type": "error", "text": f"Lỗi gọi Core: {exc}"})
                return

            audio_bytes = None
            if tts is not None and result["utterance"].strip():
                tts_segment = tts.synthesize(result["utterance"])
                if tts_segment is not None:
                    audio_bytes = encode_wav(tts_segment)
            event_queue.put({"type": "bot", "text": result["utterance"], "audio": audio_bytes})

            if result["ended"]:
                event_queue.put({"type": "ended", "outcome": result["outcome"]})
                return
    except Exception as exc:  # phòng lỗi bất ngờ trong thread nền không làm crash UI
        event_queue.put({"type": "error", "text": f"Lỗi luồng nền: {exc}"})


def _drain_event_queue() -> None:
    q = st.session_state.event_queue
    while True:
        try:
            event = q.get_nowait()
        except queue.Empty:
            break
        if event["type"] == "level":
            st.session_state.last_rms = event["rms"]
        elif event["type"] in ("caller", "bot"):
            st.session_state.messages.append(
                {"role": event["type"], "text": event["text"], "audio": event.get("audio")}
            )
        elif event["type"] == "ended":
            st.session_state.messages.append(
                {"role": "system", "text": f"Cuộc gọi kết thúc: {event['outcome']}"}
            )
            st.session_state.ended = True
            _stop_worker()
        elif event["type"] in ("stopped", "error"):
            st.session_state.messages.append(
                {"role": "system", "text": event.get("text", "Mic đã dừng.")}
            )
            _stop_worker()


def _stop_worker() -> None:
    if st.session_state.get("stop_event") is not None:
        st.session_state.stop_event.set()
    st.session_state.worker_running = False


# --- Chặn truy cập bằng mật khẩu (nếu có cấu hình ACCESS_PASSWORD) -----------------
if ACCESS_PASSWORD:
    st.session_state.setdefault("authed", False)
    if not st.session_state.authed:
        st.title("📞 Callbot Voice Demo")
        pw = st.text_input("Mật khẩu truy cập", type="password")
        if st.button("Vào", type="primary"):
            if pw == ACCESS_PASSWORD:
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("Sai mật khẩu.")
        st.stop()

if not OPENAI_API_KEY:
    st.error("Thiếu OPENAI_API_KEY trong Secrets của Space — vào Settings → Secrets để thêm.")
    st.stop()

# --- State ---------------------------------------------------------------------
st.session_state.setdefault("core", None)
st.session_state.setdefault("messages", [])
st.session_state.setdefault("ended", False)
st.session_state.setdefault("last_autoplayed_index", -1)
st.session_state.setdefault("raw_queue", queue.Queue())
st.session_state.setdefault("event_queue", queue.Queue())
st.session_state.setdefault("worker_running", False)
st.session_state.setdefault("last_rms", None)

with st.sidebar:
    st.title("📞 Callbot Voice Demo")
    st.caption(f"Core Agent: {CORE_BASE_URL}")

    scenario_key = st.selectbox(
        "Kịch bản đang test", list(SCENARIOS), format_func=lambda k: SCENARIOS[k]["label"],
        disabled=st.session_state.core is not None,
    )
    appointment_id = st.text_input(
        "Appointment ID (outbound)", value="apt_00417", disabled=st.session_state.core is not None
    )
    max_turns = st.number_input(
        "Số lượt tối đa", min_value=1, value=20, disabled=st.session_state.core is not None
    )

    with st.expander("⚙️ Tinh chỉnh mic (VAD)", expanded=True):
        st.caption(
            "Nói thử rồi xem số **Mức tín hiệu** hiện ra bên dưới khung hội thoại: "
            "kéo Ngưỡng RMS xuống THẤP HƠN mức đó một chút nếu bot không nghe thấy gì, "
            "hoặc kéo LÊN cao hơn mức tạp âm nền nếu bot bắt nhầm tiếng ồn."
        )
        vad_threshold = st.slider(
            "Ngưỡng RMS — tăng nếu mic bắt nhiều tạp âm nền, giảm nếu bot không nghe thấy gì",
            50.0, 3000.0, 1200.0, step=50.0,
            disabled=st.session_state.core is not None,
        )
        vad_silence_ms = st.slider(
            "Im lặng để chốt câu (ms) — tăng nếu bị cắt câu giữa chừng, giảm nếu chờ lâu mới gửi",
            200, 1500, 600, step=50,
            disabled=st.session_state.core is not None,
        )

    st.divider()
    if st.session_state.core is None:
        if st.button("▶️ Bắt đầu cuộc gọi", type="primary", use_container_width=True):
            core = CoreClient(CORE_BASE_URL, int(max_turns))
            try:
                started = core.start_call(appointment_id)
            except Exception as exc:
                st.error(f"Không khởi tạo được cuộc gọi: {exc}")
            else:
                st.session_state.core = core
                st.session_state.messages = [{"role": "bot", "text": started["utterance"], "audio": None}]
                st.session_state.ended = started["state"] == "ENDED"
                st.rerun()
    else:
        if st.button("🔄 Cuộc gọi mới", use_container_width=True):
            _stop_worker()
            if st.session_state.core is not None:
                st.session_state.core.close()
            for key in (
                "core", "messages", "ended", "last_autoplayed_index",
                "raw_queue", "event_queue", "worker_running", "worker", "stop_event",
            ):
                st.session_state.pop(key, None)
            st.rerun()

scenario = SCENARIOS[scenario_key]
with st.expander(f"📋 Kịch bản để nói — {scenario['label']}", expanded=st.session_state.core is None):
    for i, step in enumerate(scenario["steps"], 1):
        st.markdown(f"{i}. {step}")
    if scenario["note"]:
        st.warning(scenario["note"])
    st.info("🎧 Đeo tai nghe khi test — mic mở liên tục, không đeo tai nghe có thể bắt lại tiếng loa của chính bạn.")

st.header("Hội thoại")
if st.session_state.core is None:
    st.caption("Bấm **Bắt đầu cuộc gọi** ở sidebar, cho phép trình duyệt dùng mic, rồi nói tự nhiên — hệ thống tự cắt câu.")

asr = _load_asr()
tts = _load_tts()

_drain_event_queue()

for index, message in enumerate(st.session_state.messages):
    if message["role"] == "system":
        st.info(message["text"])
        continue
    with st.chat_message("assistant" if message["role"] == "bot" else "user"):
        st.write(message["text"])
        if message.get("audio"):
            autoplay = index > st.session_state.last_autoplayed_index
            st.audio(message["audio"], format="audio/wav", autoplay=autoplay)
            if autoplay:
                st.session_state.last_autoplayed_index = index

if st.session_state.core is not None and st.session_state.ended:
    st.success("Cuộc gọi đã kết thúc. Bấm **Cuộc gọi mới** ở sidebar để thử kịch bản khác.")
elif st.session_state.core is not None:
    webrtc_ctx = webrtc_streamer(
        key="voice",
        mode=WebRtcMode.SENDONLY,
        audio_frame_callback=_make_audio_frame_callback(st.session_state.raw_queue),
        rtc_configuration={"iceServers": _ice_servers()},
        media_stream_constraints={
            # Bật DSP mặc định của trình duyệt (echo cancel/noise suppress) làm sạch
            # tiếng cho người nghe nhưng lại bóp méo đặc trưng phổ mà ZipFormer cần,
            # nên tắt 2 cái đó — chỉ giữ AGC (tắt AGC từng làm mic gần như câm).
            "audio": {
                "echoCancellation": False,
                "noiseSuppression": False,
                "autoGainControl": True,
            },
            "video": False,
        },
    )

    rms_placeholder = st.empty()
    if st.session_state.last_rms is not None:
        rms_placeholder.caption(
            f"🎙️ Mức tín hiệu hiện tại: **{st.session_state.last_rms:.0f}** "
            f"(ngưỡng đang đặt: {vad_threshold:.0f})"
        )

    if webrtc_ctx.state.playing and not st.session_state.worker_running:
        vad = StreamingVAD(
            _MeteredEnergyClassifier(vad_threshold, st.session_state.event_queue),
            end_silence_ms=int(vad_silence_ms),
        )
        stop_event = threading.Event()
        worker = threading.Thread(
            target=_worker,
            args=(
                st.session_state.raw_queue, stop_event, st.session_state.event_queue,
                vad, asr, st.session_state.core, tts,
            ),
            daemon=True,
        )
        st.session_state.stop_event = stop_event
        st.session_state.worker = worker
        st.session_state.worker_running = True
        worker.start()
    elif not webrtc_ctx.state.playing and st.session_state.worker_running:
        _stop_worker()

    if st.session_state.worker_running:
        time.sleep(1)
        st.rerun()

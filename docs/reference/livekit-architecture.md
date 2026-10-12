# Kiến trúc LiveKit Voice Streaming

Tài liệu này mô tả toàn bộ kiến trúc, luồng dữ liệu, và các thành phần kỹ thuật của
đường gọi thoại thời gian thực qua LiveKit — tách biệt hoàn toàn với đường HTTP
`mode="audio"` (batch, xem `speech/bundle.py::build_speech_bundle`).

Viết tại: 2026-09-22, dựa trên code thật trên nhánh `feature/asr-quality-improvements`.
Đây là bản chụp trạng thái hiện tại — code có thể thay đổi, luôn đối chiếu lại source
khi có nghi ngờ.

## 1. Tổng quan process

```
┌─────────────────────┐         ┌──────────────────────────────┐
│  uvicorn (FastAPI)   │         │  LiveKit Agent Worker          │
│  transports/http/    │         │  (process riêng biệt)          │
│                      │         │  python -m callbot.transports  │
│  - /livekit/token    │         │  .livekit.worker start         │
│  - static demo HTML  │         │                                │
│  - KHÔNG chạy ASR    │         │  - 1 process/job = 1 call      │
└──────────────────────┘         │  - CallBridge sở hữu state     │
                                  └──────────────────────────────┘
         │                                      │
         │  cấp JWT token                       │  nhận job dispatch
         ▼                                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    LiveKit Cloud (SFU)                        │
│  wss://callbot-vinmec-2rh5o5or.livekit.cloud                  │
└─────────────────────────────────────────────────────────────┘
         ▲
         │  WebRTC (mic publish / TTS subscribe)
         │
┌─────────────────────┐
│  Browser             │
│  static/livekit-     │
│  demo.html            │
└─────────────────────┘
```

Hai process **độc lập hoàn toàn**, không share state, không gọi trực tiếp lẫn nhau:

1. **uvicorn** (`callbot.transports.http.main:app`) — chỉ phát JWT token
   (`/livekit/token`, xem `transports/http/livekit_token.py`) và phục vụ trang demo
   tĩnh. Không tham gia luồng audio.
2. **LiveKit Agent Worker** (`callbot.transports.livekit.worker`) — nhận job dispatch
   từ LiveKit Cloud mỗi khi có participant mới join room, tạo 1 `CallBridge` xử lý toàn
   bộ vòng đời cuộc gọi đó.

**Trang thử STT (`/ui/stt`).** Token xin với `mode=stt` gắn attribute `mode=stt` cho người dùng;
worker khi đó không mở engine/clinic/TTS mà chạy `SttSession` (`transports/livekit/stt_session.py`):
cùng `STTPipeline` + `TurnController` của cuộc gọi, gửi chữ qua data channel `callbot.stt` —
`partial` (chữ lượt đang nói), `final` (lượt đã chốt, đúng chữ engine sẽ nhận), `dropped` (ASR nghe
ra chữ nhưng pipeline bỏ: chỉ có từ đệm, Validator). Model hỏng giữa chừng thì worker báo
`STT_FAILED` qua `callbot.status`.

**Hệ quả vận hành quan trọng**: sửa `.env` (đổi `ASR_PROVIDER`, path model...) chỉ có
hiệu lực sau khi **restart worker** — `LiveKitSettings`/`SpeechSettings` chỉ đọc
`.env` một lần lúc process khởi động (`prewarm()`/`entrypoint()`), không tự reload.
`uvicorn --reload` chỉ theo dõi thay đổi file `.py`, không theo dõi `.env`.

## 2. Luồng dữ liệu 1 cuộc gọi

```
Browser mic
    │  WebRTC audio track
    ▼
rtc.AudioStream.from_track()          [call_bridge.py::_pump_track]
    │  PCM16, resample về sample_rate cấu hình (mặc định 16kHz cho web)
    ▼
livekit_frame_to_segment()            [audio_adapter.py]
    │  AudioSegment chuẩn hoá
    ▼
frame_queue (asyncio.Queue)           [call_bridge.py]
    │
    ▼
STTPipeline.stream(frames)            [speech/asr/pipeline.py]
    │
    ├──► vad_queue ──► AsyncStreamingVAD.process()  ──► VadEvent(speech_start/speech/speech_end)
    │                                                         │
    └──► asr_queue ──► ASR.stream(frames)  ──► TranscriptEvent(text, is_final)
                                                                │
                        cả 2 luồng event đổ vào                │
                                                                ▼
                                                    TurnController.on_vad_event()
                                                    TurnController.on_transcript_event()
                                                                │
                                                                ▼
                                                    UserTurnCompleted(text, confidence)
                                                                │
                                                                ▼
                                              CallOrchestrator.handle_turn()  [callbot.engine]
                                                                │
                                                                ▼
                                                         BotAction(utterance, ...)
                                                                │
                                                                ▼
                                            SpeechSynthesizer.synthesize_stream(text)
                                                                │
                                                                ▼
                                              segment_to_livekit_frame()  [audio_adapter.py]
                                                                │
                                                                ▼
                                              rtc.AudioSource.capture_frame()
                                                                │
                                                                ▼
                                                         Browser loa (TTS track)
```

VAD và ASR **chạy thật sự song song** trên cùng nguồn frame (`_fanout()` trong
`pipeline.py` nhân đôi mỗi frame vào 2 queue riêng), không phải VAD chạy trước rồi mới
gọi ASR — đây là điểm khác biệt quan trọng so với đường HTTP batch (VAD chạy trước để
quyết định có gọi ASR hay không, xem `STTPipeline.transcribe_segment`).

## 3. Các thành phần chính

### 3.1. `CallBridge` (`callbot/transports/livekit/call_bridge.py`)

1 instance/room, sở hữu toàn bộ state của 1 cuộc gọi:
- Subscribe mic track của participant khi vào room (`_on_track_subscribed`).
- Publish 1 track TTS riêng (`_publish_tts_track`) — audio bot nói ra được gửi qua
  track LiveKit riêng biệt, không lẫn với track mic của user.
- Vòng lặp chính (`run()`): `orchestrator.start_call()` → publish câu chào → lặp
  `turn_queue.get()` → `orchestrator.handle_turn()` → `_speak()` → lặp lại tới khi
  `action.ended`.
- `_speak()`: publish TTS streaming từng chunk (không chờ đủ câu), kiểm tra cờ
  interruption **trước mỗi chunk** để dừng ngay khi bị ngắt lời.
- Cơ chế debug: `LIVEKIT_DEBUG_DUMP_AUDIO=1` ghi PCM thật (đúng đường dữ liệu vào ASR)
  ra `temp/audio/livekit_debug_<room>.wav` — công cụ duy nhất để xác nhận ASR
  hallucinate do audio bị méo hay do model tự nghe nhầm khi audio hoàn toàn sạch.

### 3.2. `audio_adapter.py`

Boundary format thuần tuý, không quyết định logic nghiệp vụ:
- `livekit_frame_to_segment()`: `rtc.AudioFrame` → `AudioSegment` chuẩn (downmix nếu
  stereo, resample về `target_rate`).
- `segment_to_livekit_frame()`: chiều ngược lại cho TTS output.

### 3.3. `STTPipeline.stream()` (`speech/asr/pipeline.py`)

Hàm lõi turn-taking. Nhận `frames: AsyncIterator[bytes]` liên tục suốt cuộc gọi, trả
`AsyncIterator[UserTurnCompleted]`. Cơ chế:

- `_fanout()`: mỗi frame đẩy vào cả `vad_queue` và `asr_queue`. Nếu
  `controller.is_bot_speaking == True`, audio **không** tự động vào ASR — chỉ vào khi
  `InterruptionController` đã coi là `INTERRUPTION_CANDIDATE` (tức VAD đã phát hiện
  speech_start giữa lúc bot nói). Cơ chế **pre-roll**: giữ tối đa
  `barge_in_preroll_frames` (mặc định 500ms) frame gần nhất trong lúc bot nói nhưng
  chưa thành candidate — khi thành candidate, replay lại pre-roll vào ASR để không mất
  phần đầu câu nói chen ngang.
- `_drain_vad()` / `_drain_asr()`: 2 task riêng đọc từ 2 queue, đẩy event vào
  `TurnController` và `InterruptionController`.
- Vòng chính chờ `TurnController.get_turn()` song song với việc VAD/ASR task còn sống,
  dừng generator khi cả 2 đã đọc hết `frames` và không còn turn pending.

### 3.4. `TurnController` (`speech/turn/controller.py`)

Quyết định "user đã nói xong lượt chưa?" — không chỉ dựa vào khoảng lặng đơn thuần.

Quy tắc chốt turn:
1. **ASR final** luôn chốt turn ngay khi nhận được.
2. **VAD speech_end** mà chưa có final tương ứng: chờ tối đa
   `max_wait_after_vad_end_ms` (300ms) rồi chốt bằng partial cuối nếu vẫn chưa có
   final.
3. Trong lúc bot đang nói, input vẫn được xử lý nhưng **không chốt turn** — turn ứng
   viên giữ lại, chốt ngay khi bot ngừng nói.
4. Turn phải kéo dài ít nhất `min_speech_ms` (250ms mặc định, tính từ VAD
   speech_start) — lớp phòng thủ chống false-positive từ backchannel/tiếng động ngắn.
5. **Post-bot echo guard** (`post_bot_guard_ms`, 500ms mặc định): candidate bắt đầu
   ngay sau khi bot vừa dứt lời không bị discard thẳng, mà phải "nói tiếp" đủ lâu hơn
   bình thường (cộng dồn phần thời gian còn thiếu của guard window vào
   `min_speech_ms`) mới được chấp nhận — chống dư âm/tiếng vọng phòng đúng lúc
   `is_bot_speaking` chuyển `False`.
6. `is_meaningful_text()`: lọc filler word đơn lẻ ("à", "ừ", "ờ", "dạ"...) và text chỉ
   gồm dấu câu/ký tự đặc biệt — cả 2 loại này không phải hallucination nhưng cũng
   không mang nội dung hội thoại.

### 3.5. `InterruptionController` (`speech/turn/interruption.py`)

State machine: `IDLE → BOT_SPEAKING → INTERRUPTION_CANDIDATE → INTERRUPTED`.

Barge-in **luôn cần chữ ASR**: gate (`_gate()`) xét mỗi partial (`on_partial_transcript`) và
xét lại partial mới nhất khi VAD còn nghe tiếng nói (`on_speech_frame`). Điều kiện chi tiết
(độ dài, chữ có nghĩa, tiếng vọng, SNR, TurnValidator, số chữ) ở docstring module và
`docs/reference/stt-flow.md` §2.6; số đo ở
`docs/evidence/livekit-barge-in-confirmation-2026-10-10.md`.

Lịch sử 2 lỗ hổng đã gặp và sửa (ghi lại trong docstring module, không lặp lại):
1. Từng tự xác nhận ngay khi ASR trả về BẤT KỲ text non-empty nào — ASR hallucinate 1
   cụm "có vẻ hợp lệ" từ noise nền là đủ để cắt ngang TTS.
2. Từng có `confirm_if_sustained()` xác nhận CHỈ bằng duration VAD (không cần ASR trả
   chữ) — noise kéo dài liên tục tự cắt lời bot. Đã bỏ hẳn method này.

Khi xác nhận: gọi `tts.cancel()` (implement bởi `CallBridge.cancel()` — dừng TTS
streaming + xoá audio đã queue nhưng chưa phát).

### 3.6. VAD (`speech/asr/vad/`)

2 lựa chọn qua `VAD_PROVIDER`:
- **`energy`** (`EnergyFrameClassifier`): RMS đơn thuần, baseline, không phân biệt
  giọng nói với tiếng ồn.
- **`webrtc`** (`WebRtcVadClassifier`, mặc định trong `.env` hiện tại): dùng Google
  WebRTC's VAD (package `webrtcvad-wheels`, không phải `webrtcvad` gốc — bản gốc phụ
  thuộc `pkg_resources` đã bị gỡ khỏi setuptools mới). `aggressiveness` 0-3, mặc định
  2. Docstring ghi rõ: **"cân bằng cho audio narrowband điện thoại (8kHz)"** — LiveKit
  web hiện chạy ở 16kHz theo `LiveKitSettings.input_sample_rate` mặc định, đây là điểm
  lệch giữa thiết kế gốc và cấu hình thực tế đang chạy, chưa được đánh giá lại.

`AsyncStreamingVAD` (`speech/asr/vad/async_stream.py`): bản async của `StreamingVAD`
đồng bộ, cùng state machine — gom frame thành đoạn nói, phát `speech_end` sau
`end_silence_ms` (600ms mặc định) khoảng lặng liên tục.

### 3.7. ASR — 2 provider khả dụng cho LiveKit

#### a) ZipFormer / gipformer1.5 (local, mặc định hiện tại)

`inference/asr/providers/zipformer.py`, class `ZipFormerASR`.

**Bản chất: non-streaming (offline).** Cả model gốc
(`csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20`) lẫn model thay thế
(`g-group-ai-lab/gipformer1.5-68M-rnnt`, đang cấu hình trong `.env` qua
`ZIPFORMER_*_PATH`) đều **thiếu metadata streaming** (`encoder_dims`...), bị
`sherpa_onnx.OnlineRecognizer` từ chối — chỉ nạp được qua `OfflineRecognizer`. Đã rà
soát toàn bộ model zoo ZipFormer tiếng Việt chính thức (2026-09): không tồn tại
checkpoint online/streaming thật cho tiếng Việt trong hệ sinh thái sherpa-onnx.

**`stream()` giả lập streaming bằng "chunked-offline"**: tích luỹ PCM vào buffer,
decode lại **toàn bộ buffer** bằng `OfflineRecognizer` sau mỗi `min_emit_interval_ms`
(300ms) để emit partial, emit final khi phát hiện khoảng lặng đủ dài
(`end_silence_ms`). Không giữ state giữa các lần decode — tốn compute hơn incremental
decode thật, nhưng RTF ~0.03 của model khiến decode lại liên tục vẫn rẻ hơn nhiều lần
thời gian thực (cho tới khi buffer quá dài không có `speech_end`, xem §5).

`min_decode_ms` (400ms mặc định, `ZipFormerConfig`): buffer ngắn hơn ngưỡng này không
được đưa vào decode — chống hallucination trên audio siêu ngắn (tiếng "à", hắng
giọng...) mà model 68M "đói" ngữ cảnh dễ tự sinh ra cả cụm từ không tồn tại.

`decode_stream()` của sherpa-onnx là lời gọi CPU-bound đồng bộ — luôn chạy qua
`asyncio.to_thread()`, gọi trực tiếp trên event loop từng gây chặn ~1.2s mỗi lần
decode, trễ toàn bộ audio publish/subscribe của MỌI call đang chạy chung worker
process.

#### b) ElevenLabs Scribe v2 Realtime (cloud, streaming thật)

`inference/asr/providers/elevenlabs_realtime.py`, class `ElevenLabsRealtimeASR`. Thêm
vào 2026-09-22.

**Streaming THẬT qua WebSocket** (SDK `elevenlabs.realtime.scribe.ScribeRealtime`) —
server giữ state riêng giữa các audio chunk, trả `partial_transcript` tăng dần và
`committed_transcript` khi chốt segment. Khác hẳn ZipFormer: không có buffer phía
client, mỗi chunk PCM chỉ gửi 1 lần.

Hỗ trợ cả 8000Hz và 16000Hz (`AudioFormat.PCM_8000`/`PCM_16000`), không cần resample
về 1 rate cố định. Dùng `CommitStrategy.MANUAL` — endpoint hoá turn vẫn do
`TurnController`/VAD tầng trên quyết định (qua cùng `silence_classifier` mà ZipFormer
dùng), không để VAD nội bộ của ElevenLabs tạo ra 2 nguồn quyết định "hết câu" độc lập.

**2 bug thật đã gặp và sửa lúc viết provider này:**
1. Exception trong task nền `_pump_audio()` từng bị nuốt hoàn toàn (đi qua `finally`
   rồi kết thúc task mà không ai `await` để lấy exception ra) — `stream()` kết thúc
   rỗng không rõ lý do.
2. Race condition: `connection.commit()` chỉ **gửi** message commit, không đợi server
   trả `committed_transcript` (round-trip network riêng). Đẩy sentinel kết thúc ngay
   sau `await commit()` khiến consumer thoát trước khi transcript cuối cùng kịp tới.
   Sửa bằng cơ chế đếm `pending_commits` + `asyncio.Event` chờ tới khi mọi commit đã
   "settle" (hoặc timeout 5s an toàn).

`transcribe()` (batch 1 lượt) **không được hỗ trợ** — raise `NotImplementedError` có
chủ đích, vì đây là provider chỉ dành cho streaming. `worker.py::prewarm()` bắt riêng
`NotImplementedError` này để không coi là lỗi khi warm-up.

**Chuyển đổi provider**: chỉ cần đổi `ASR_PROVIDER=zipformer` hoặc
`ASR_PROVIDER=elevenlabs_realtime` trong `.env` rồi restart worker — không đụng
LiveKit/TurnController/InterruptionController, nhờ cả 2 provider cùng implement chung
interface `stream(frames) -> AsyncIterator[TranscriptEvent]`.

### 3.8. TTS

`SpeechSynthesizer` (`speech/tts/synthesizer.py`) mở rộng thêm `synthesize_stream()` +
`cancel()` cho đường LiveKit — ủy quyền qua `gateway.provider` (duck-typing
`hasattr`/`getattr`). Provider hiện dùng: Vbee (`TTS_PROVIDER=vbee`), PCM mono
8kHz — `CallBridge._publish_tts_track()` tạo `rtc.AudioSource` cố định theo
`stream_sample_rate` của provider lúc publish track (không đổi giữa các câu).

## 4. Cấu hình (`.env`)

| Biến | Giá trị hiện tại | Ý nghĩa |
|---|---|---|
| `ASR_PROVIDER` | `zipformer` | `zipformer` (gipformer1.5 local) hoặc `elevenlabs_realtime` (cloud) |
| `LIVEKIT_INPUT_SAMPLE_RATE` | `16000` | Tần số PCM của pipeline LiveKit. Đường HTTP giữ tần số gốc của clip (không còn khóa `SAMPLE_RATE`) |
| `VAD_PROVIDER` | `webrtc` | `energy` hoặc `webrtc` |
| `TTS_PROVIDER` | `vbee` | Provider TTS (`openai` / `elevenlabs` / `vbee`) |
| `ZIPFORMER_*_PATH` | trỏ `assets/zipformer/` (nội dung model gipformer1.5) | Asset model đang dùng — xem §5 lịch sử đổi model |
| `ELEVENLABS_API_KEY` | có sẵn | Dùng chung cho cả STT batch/realtime và TTS |
| `ELEVENLABS_REALTIME_STT_MODEL` | `scribe_v2_realtime` | Model ID cho `ElevenLabsRealtimeConfig` |
| `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` | có sẵn | Kết nối LiveKit Cloud |

`LiveKitSettings` (`callbot/transports/livekit/settings.py`) — không đọc qua
`SpeechSettings`, các field riêng:

| Field | Default | Ý nghĩa |
|---|---|---|
| `input_sample_rate` | `16_000` | WebRTC web giữ wideband tới boundary ASR |
| `frame_ms` | `30` | Frame canonical cho VAD/endpointing (webrtcvad chỉ nhận 10/20/30ms) |
| `input_queue_ms` | `1_500` | Backpressure — không để audio chậm tích luỹ vô hạn |
| `barge_in_preroll_ms` | `500` | Giữ phần đầu câu chen ngang trước khi InterruptionController xác nhận |
| `output_queue_ms` | `200` | Queue phát TTS càng dài thì barge-in càng chậm |
| `worker_num_idle_processes` | `1` | LiveKit `start` mặc định giữ 4 process nóng — giảm còn 1 cho máy demo nhỏ |

`SpeechSettings` các field turn-taking dùng chung cho LiveKit:

| Field | Default | Ý nghĩa |
|---|---|---|
| `vad_end_silence_ms` | `600` | Khoảng lặng để VAD phát `speech_end` |
| `turn_min_speech_ms` | `250` | Turn tối thiểu để không bị coi là backchannel |
| `turn_max_wait_after_vad_end_ms` | `300` | Chờ ASR final sau VAD speech_end trước khi chốt bằng partial |
| `turn_post_bot_guard_ms` | `500` | Echo guard sau khi bot dứt lời |

## 5. Lịch sử quan trọng — đọc trước khi debug hallucination

### 5.1. `tokens.txt` mismatch (đã sửa 2026-09-22)

File `tokens.txt` (ánh xạ ID→chữ) của model ZipFormer cũ trên đĩa từng **bị lệch thứ
tự token ID** so với bản gốc HuggingFace (khác MD5 hoàn toàn) dù 3 file `.onnx` vẫn
khớp checksum gốc. Hệ quả: model decode "đúng" về mặt xác suất nhưng tra chữ sai hoàn
toàn — tạo ra hallucination có cấu trúc, lặp lại theo mẫu cố định, dễ nhầm là "bản chất
model tệ". Đã xác nhận qua benchmark: cùng model, chỉ đổi `tokens.txt` sai→đúng, PASS
rate từ 3/40 lên 19/40 (khớp báo cáo benchmark gốc). Bài học: khi gặp hallucination có
mẫu lặp lại bất thường, luôn nghi ngờ asset trước khi kết luận về bản chất model.

### 5.2. gipformer1.5 — model thay thế hiện tại

Thay `zipformer-vi` gốc bằng `g-group-ai-lab/gipformer1.5-68M-rnnt` vì model cũ từng
hallucinate nặng trên audio thật qua LiveKit/demo. **Lưu ý: quyết định này được đưa ra
trước khi phát hiện bug `tokens.txt` ở §5.1** — sau khi sửa `tokens.txt`, model cũ đạt
lại PASS 19/40 (WER 0.449), gần bằng gipformer1.5 (PASS 19/40, WER 0.390). Chênh lệch
thực tế giữa 2 model nhỏ hơn nhiều so với đánh giá ban đầu.

### 5.3. Benchmark so sánh với STT thương mại (2026-09-22)

Chạy cùng bộ 40 golden case (`eval/stt-bench/`) qua `ElevenLabs scribe_v2` (batch) và
`Deepgram nova-3` (batch) để đối chiếu:

| Model | PASS | Mean WER | Latency median |
|---|---|---|---|
| gipformer1.5 (local) | 19/40 | 0.390 | 68ms |
| ZipFormer cũ, tokens đã sửa (local) | 19/40 | 0.449 | 69ms |
| ElevenLabs scribe_v2 (cloud, batch) | 19/40 | 0.375 | 1140ms |
| Deepgram nova-3 (cloud, batch) | 18/40 | 0.428 | 908ms |

Cả 4 hệ thống PASS quanh 45-47.5% trên cùng bộ test — bộ 40 golden case chứa nhiều
case vốn dĩ khó (tên hiếm, ngày tháng khẩu ngữ, audio nhiễu), không phải model local
kém so với chuẩn ngành. Model local thắng tuyệt đối về latency (nhanh hơn cloud
13-17 lần) — quan trọng cho turn-taking thời gian thực.

### 5.4. Hallucination trên noise nền thật (2026-09-22, CHƯA GIẢI QUYẾT)

Test thật qua LiveKit demo với micro thật (không phải file benchmark sạch): gipformer1.5
hallucinate ra 1 chữ cố định ("ĐÂY", "TẠI"...) lặp lại nhiều lần dù **user xác nhận
hoàn toàn không nói gì**. Điều tra bằng `LIVEKIT_DEBUG_DUMP_AUDIO=1` + phân tích RMS
+ decode trực tiếp từng đoạn cho thấy:

- File audio về mặt kỹ thuật sạch (không clip, biên độ hợp lý, RMS ~400).
- Noise nền phòng không đồng đều (p50=71, p95=626, p99=1777) — đủ để **WebRTC VAD
  (aggressiveness=2) nhận nhầm thành speech_start** trong các đoạn ngắn 0.1-0.7s.
- gipformer1.5 sau đó hallucinate ra chữ "có nghĩa" từ chính noise đó, vượt qua
  `is_meaningful_text()` gate, gây false barge-in.

ElevenLabs Realtime không mắc lỗi tương tự trên cùng môi trường — model cloud lớn hơn
có khả năng phân biệt noise/giọng nói tốt hơn model local 68M.

**Hướng sửa đã đề xuất, chưa triển khai:**
- Tăng `min_decode_ms` (ZipFormerConfig) — giảm cơ hội decode trên các đợt noise ngắn.
- Giảm độ nhạy `vad_webrtc_aggressiveness` hoặc thêm ngưỡng RMS filter trước VAD.
- Thêm bộ lọc: nếu ASR trả về liên tục cùng 1 từ ngắn lặp lại trong 1 phiên, coi là
  dấu hiệu hallucination và bỏ qua (chưa implement).

### 5.5. Memory leak chunked-offline (CHƯA SỬA)

Khi audio speech liên tục không có `speech_end` (VAD không bao giờ báo đủ
`end_silence_ms` liên tục), buffer trong `ZipFormerASR.stream()` tăng vô hạn, decode
lại toàn bộ mỗi `min_emit_interval_ms` → thời gian xử lý và RAM tăng theo cấp số nhân.
Đã xác nhận bằng thực nghiệm (60s audio giả lập mất 127s xử lý, RAM 1551MB) nhưng
**chưa sửa code**. Không xảy ra với ElevenLabs Realtime (không có buffer phía client).

## 6. File liên quan (tham chiếu nhanh)

```
src/callbot/transports/livekit/
├── worker.py           # Entry point process, prewarm(), entrypoint()
├── call_bridge.py       # CallBridge — vòng đời 1 call
├── audio_adapter.py     # Convert rtc.AudioFrame <-> AudioSegment
└── settings.py           # LiveKitSettings

src/callbot/transports/http/
└── livekit_token.py     # Cấp JWT token cho browser join room

src/speech/
├── asr/pipeline.py       # STTPipeline.stream() — fanout VAD+ASR song song
├── asr/recognizer.py     # SpeechRecognizer.stream() — uỷ quyền provider.stream()
├── asr/vad/webrtc.py     # WebRtcVadClassifier
├── asr/vad/async_stream.py  # AsyncStreamingVAD
├── turn/controller.py    # TurnController — chốt turn
├── turn/interruption.py  # InterruptionController — barge-in
├── bundle.py             # build_streaming_bundle() — factory dựng StreamingSpeechBundle
└── settings.py           # SpeechSettings

src/inference/asr/providers/
├── zipformer.py                  # ZipFormerASR (gipformer1.5, chunked-offline)
└── elevenlabs_realtime.py         # ElevenLabsRealtimeASR (WebSocket streaming thật)
```

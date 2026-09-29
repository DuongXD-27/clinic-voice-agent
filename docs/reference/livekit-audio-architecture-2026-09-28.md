# Kiến trúc LiveKit voice — đường đi của âm thanh từ mic tới core engine (28/09/2026)

Mô tả **hiện trạng code tại thời điểm viết** (nhánh `feature/livekit-realtime-voice` + thay đổi
25–26/09). Mỗi giai đoạn ghi: làm gì, tham số thật, file, và các dữ kiện cần lưu ý (mục cuối
mỗi giai đoạn). Mục 9 gom các dữ kiện đó lại — là **quan sát**, chưa phải kết luận. Chi tiết
lịch sử bug và số liệu đo: `livekit-voice-pipeline-2026-09-24.md`,
`docs/evidence/livekit-noise-robustness-2026-09-25.md`, `docs/evidence/livekit-turn-loss-2026-09-26.md`.

**Cập nhật 28/09 (sau khi viết tài liệu này):** Speech Admission đã bị **xoá khỏi code** (không
chỉ tắt cờ) — mọi nhắc tới Admission trong tài liệu này (mục 0, 3, 10) mô tả trạng thái TRƯỚC
lúc xoá, giữ lại để hiểu lịch sử. Kết quả đo và quyết định giữ/bỏ từng đề xuất cải tiến:
`docs/evidence/livekit-audio-plan-execution-2026-09-28.md`.

---

## 0. Cấu hình đang chạy — local khác production (trạng thái trước 28/09, xem cập nhật trên)

| Thành phần | Mặc định repo (`config/*.yaml`) | Production (`docker-compose.prod.yml`) | Local dev (`.env`) |
|---|---|---|---|
| Sample rate pipeline | 8000 (`speech.yaml`) — worker LiveKit ghi đè bằng `livekit.yaml` | **16000** | **16000** |
| VAD chính + VAD chốt câu của ASR | `energy` | **`webrtc`** (`${VAD_PROVIDER:-webrtc}`) | **`silero`** |
| Speech Admission | tắt | tắt | **bật** (module đã xoá 28/09) |
| Turn Validator | tắt | tắt | **bật** |
| `interruption_min_snr_db` | `null` (tắt) | `null` | **0.0** |
| ASR | zipformer | gipformer1.5-68M-rnnt (int8) | gipformer1.5 (int8) |
| TTS | OpenAI `tts-1`, voice `alloy`, PCM 24 kHz | như repo | như repo |
| Tầng ngữ nghĩa (engine) | OpenAI `gpt-6-luna`, bật, timeout 3 s | như repo | như repo |

Toàn bộ đo đạc 24–26/09 chạy với cấu hình **local**. Đo 28/09 (`livekit-audio-plan-execution-
2026-09-28.md`) so trực tiếp production (WebRTC) với cấu hình mục tiêu (Silero+Validator, cả
hai đều không Admission) trên bộ đo xác định — kết quả trái chiều (tốt hơn cho câu dài/latency,
tệ hơn cho câu ngắn dưới nhiễu), **chưa đổi `vad_provider` production**.

---

## 1. Toàn cảnh

```
┌──────────── Trình duyệt (livekit-demo.html, livekit-client 2.22.3) ────────────┐
│ getUserMedia: echoCancellation, noiseSuppression, autoGainControl,            │
│               voiceIsolation = true, channelCount = 1   →  Opus 48 kHz         │
└───────────────────────────────┬───────────────────────────────▲───────────────┘
                                │ WebRTC (mic)                  │ WebRTC (bot-voice)
                        ┌───────▼───────────────────────────────┴───────┐
                        │              LiveKit Cloud (SFU)              │
                        └───────┬───────────────────────────────▲───────┘
┌───────────────────────────────▼──── LiveKit worker process ───┴────────────────┐
│ worker.py: prewarm (nạp ZipFormer 1 lần/process) · entrypoint (1 job = 1 room) │
│                                                                                │
│  CallBridge._pump_track            [A] thu âm & vận chuyển                     │
│    rtc.AudioStream 16 kHz mono, frame 30 ms ─► _frame_queue (50 frame = 1,5 s) │
│                  │                                                             │
│  STTPipeline.stream()                                                          │
│    _fanout ──► vad_queue ──► _drain_vad (VAD chính) ─────────┐                 │
│       │    [B] tiền xử lý: evidence, nhánh bot-nói,          │ VadEvent        │
│       │        Admission, AsrSegmentEnd                      ▼                 │
│       └──► asr_queue ──► _drain_asr ─► ZipFormer.stream ─► TurnController ◄─┐  │
│                          [C] STT        (partial/final)    [D] sau STT      │  │
│                                                            + TurnValidator  │  │
│                                          InterruptionController ◄───────────┘  │
│                  │ UserTurnCompleted(text, confidence=None)                    │
│  CallBridge.run: _turn_queue (4) ─► CallerInput ─► orchestrator.handle_turn   │
│                                     [E] trước/đầu core engine (thread)        │
│                  │ BotAction.utterance                                         │
│  CallBridge._speak: TTS stream 24 kHz ─► rtc.AudioSource (queue 200 ms)  [F]  │
└────────────────────────────────────────────────────────────────────────────────┘
```

- **Process:** FastAPI (cấp token, `transports/http/livekit_token.py`) và LiveKit worker
  (`python -m callbot.transports.livekit.worker start`) là 2 process riêng. Worker giữ
  `worker_num_idle_processes=1` process nóng; mỗi process nạp 1 bản ZipFormer.
- **Tạo cuộc gọi:** browser xin token → room `web-<uuid>`; `direction`, `caller_number`,
  `appointment_id` gắn vào participant attributes. Worker đọc attributes sau
  `wait_for_participant()`, room name dùng thẳng làm `call_id`.
- **Chọn worker:** `LIVEKIT_AGENT_NAME` rỗng → automatic dispatch, LiveKit chia job cho **mọi**
  worker không tên trong project (28/09: một worker khác dùng chung project nhận 8/10 job, cuộc
  gọi local không có bot). Có tên → worker chỉ nhận job gọi đúng tên, token browser mang
  `RoomConfiguration.agents=[RoomAgentDispatch(agent_name)]`. FastAPI và worker phải cùng giá trị.
- **Thứ tự khởi động trong `CallBridge.run`:** đăng ký `track_subscribed` → `start_call`
  (engine, trong thread) → publish track TTS → **chạy pipeline STT trước** → đọc câu chào.
  Nhờ vậy barge-in hoạt động ngay từ câu chào.

---

## 2. Giai đoạn A — Thu âm và vận chuyển (trước pipeline)

### A1. Trình duyệt
- `audioCaptureDefaults`: AEC, NS, AGC, `voiceIsolation` bật; mono. Các xử lý này chạy trong
  trình duyệt/OS, server không kiểm soát và không biết đã áp dụng cái nào (tuỳ trình duyệt).
- Codec Opus 48 kHz qua WebRTC.

### A2. Worker nhận track — `CallBridge._pump_track`
1. `rtc.AudioStream.from_track(sample_rate=16000, num_channels=1, frame_size_ms=30,
   capacity=50)` — **SDK LiveKit tự resample** 48 kHz → 16 kHz và cắt frame 30 ms
   (480 mẫu = 960 byte).
2. `livekit_frame_to_segment()` (`audio_adapter.py`): downmix nếu nhiều kênh; `to_sample_rate`
   (soxr HQ) — **không làm gì** khi SDK đã trả đúng 16 kHz.
3. `LIVEKIT_DEBUG_DUMP_AUDIO=1`: ghi đúng PCM này ra `temp/audio/livekit_debug_<room>.wav`
   (nguồn dữ liệu cho `eval/noise-bench/replay_dump.py`).
4. `await _frame_queue.put(pcm)` — queue 50 frame (1,5 s). Queue đầy thì `_pump_track` bị
   chặn (backpressure lan ngược về `AudioStream`).

### A — Dữ kiện cần lưu ý
- Mọi track audio của **mọi participant** đều được pump vào **cùng một** `_frame_queue`
  (`_on_track_subscribed` không lọc participant). Demo chỉ có 1 người nên chưa lộ.
- Không có khử nhiễu/AGC/khử giọng nền phía server. LiveKit Cloud có Background Voice
  Cancellation (`AudioStream.from_track(noise_cancellation=...)`) nhưng chưa dùng.
- Đường phone (SIP, 8 kHz) chưa có; `ZipFormerASR.stream` đã nhận sample rate tường minh.

---

## 3. Giai đoạn B — Tiền xử lý trước STT (`STTPipeline.stream` → `_fanout`)

`_fanout` xử lý **tuần tự từng frame 30 ms**, theo đúng thứ tự dưới đây:

```
frame ─► (1) vad_queue.put(frame)                         luôn luôn, không lọc
      ─► (2) evidence cho Validator (nếu bật)             Silero riêng + NoiseTracker
                                                          + UtteranceEvidenceTracker
      ─► (3) bot đang nói?  ── có ──► nhánh barge-in (B3)
      │                     └─ không ─► (4) Admission? ── tắt ──► asr_queue
      │                                               └─ bật ──► quyết định ADMIT/REJECT (B4)
```

### B1. VAD chính (`_drain_vad`, `AsyncStreamingVAD`)
- Classifier: WebRTC (prod) / Silero (local) / energy RMS 500 (mặc định repo).
- Máy trạng thái: `speech_start` **ngay frame đầu** classifier báo speech; `speech_end` sau
  **20 frame (600 ms)** liên tiếp không-speech.
- Silero (sherpa-onnx, tham số mặc định): threshold 0,5; `min_speech_duration` 0,25 s (báo
  speech **trễ ~250 ms**); `min_silence_duration` 0,5 s (giữ trạng thái speech thêm 0,5 s sau
  khi hết tiếng). Cửa sổ 512 mẫu (32 ms) nên frame 30 ms được gom lại trước khi suy luận.
- WebRTC: không có độ trễ/hangover kiểu Silero; báo speech gần như tức thì nhưng hay nhầm
  noise phòng thành speech (ghi nhận 22–24/09).
- Event đi tới `TurnController.on_vad_event` và `InterruptionController`
  (`on_speech_started` / `on_speech_ended_without_confirmation`).

### B2. Bằng chứng SNR cho Turn Validator (chỉ khi `turn_validator_enabled`)
- `noise_classifier` (Silero riêng) phân loại **mọi** frame, kể cả lúc bot nói.
- `NoiseTracker.observe`: SNR theo frame, nền EMA (α = 0,05) cập nhật trên frame không-speech
  → đưa cho **InterruptionController**.
- `UtteranceEvidenceTracker` (sửa 26/09) → đưa cho **TurnController/Validator**: năng lượng cả
  đoạn nói (đoạn mới sau 600 ms im lặng, giữ kết quả 3 s); nền nhiễu riêng = **trung vị 3 s**
  frame không-speech; frame không-speech chỉ vào nền sau **300 ms** — nếu Silero báo speech
  trước đó thì là đầu câu bị nhận trễ, tính vào năng lượng câu.

### B3. Nhánh bot đang nói (`controller.is_bot_speaking`)
- Reset trạng thái Admission, xoá preroll Admission.
- `await asyncio.sleep(0)` để VAD kịp xử lý frame vừa đưa → đọc `interruption.state`.
- `INTERRUPTION_CANDIDATE` (VAD báo speech_start khi bot đang nói): lần đầu gửi
  `AsrSegmentEnd.DISCARD` (bỏ audio trước lúc bot nói) → replay `pre_roll` (16 frame ≈ 480 ms)
  → đưa frame hiện tại vào ASR.
- Không phải candidate: frame vào `pre_roll` (vòng 480 ms), **không vào ASR**; gửi `DISCARD`
  nếu ASR đang dở câu — trừ khi `INTERRUPTED` (ngắt lời đã xác nhận, giữ để chốt turn).

### B4. Nhánh bình thường — Speech Admission (chỉ khi `speech_admission_enabled`)
- Classifier Silero riêng; SNR đo bằng `NoiseTracker.peek` (chưa cập nhật nền).
- Quyết định (`SpeechAdmission.evaluate`):

| Điều kiện | Kết quả |
|---|---|
| đang ADMIT, không-speech liên tục ≥ 600 ms | REJECT (`no_speech`) — hết đoạn → gửi `AsrSegmentEnd.FINALIZE` |
| đang ADMIT | ADMIT (giữ suốt câu, kể cả SNR tụt) |
| không-speech | REJECT (`no_speech`) |
| SNR < 6 dB | REJECT (`low_snr`) |
| speech < 150 ms | REJECT (`too_short`) |
| còn lại | ADMIT |

- Nền chỉ cập nhật (`commit_floor`) khi `no_speech` **và** SNR < 6 dB (không để đầu câu to
  bị tính thành nhiễu).
- Frame bị REJECT vào `PreRollBuffer` 20 frame (600 ms); lúc REJECT→ADMIT flush toàn bộ rồi
  mới gửi frame hiện tại. Mỗi frame tới ASR **đúng một lần, đúng thứ tự** (sửa 25/09).
- Admission tắt: frame đi thẳng `asr_queue`.

### B — Bảng các bộ phân loại tiếng nói chạy song song (cùng 1 frame)

| # | Instance | Dùng cho | Có khi |
|---|---|---|---|
| 1 | `async_classifier` | VAD chính → speech_start/end cho TurnController, Interruption | luôn |
| 2 | `asr_endpoint_classifier` | ZipFormer tự chốt câu (600 ms im lặng) — chỉ thấy frame **được đưa vào ASR** | luôn |
| 3 | `admission_classifier` (Silero) | Admission | Admission bật |
| 4 | `noise_classifier` (Silero) | NoiseTracker + UtteranceEvidenceTracker | Validator bật |
| – | `sync_classifier` | `transcribe_segment` (đường HTTP), không chạy trên LiveKit | luôn tạo |

Local: 4 bản Silero chạy trên mỗi frame. Prod: 2 bản WebRTC (#1, #2).

### B — Điểm resample

| Chỗ | Từ → tới | Ai làm |
|---|---|---|
| Mic → server | 48 kHz Opus → 16 kHz PCM | SDK LiveKit (`AudioStream`) |
| `livekit_frame_to_segment` | 16 → 16 | không làm gì (soxr chỉ chạy nếu lệch) |
| Silero | 16 → 16 | không (chỉ resample nếu nguồn 8 kHz) |
| ZipFormer | 16 → 16 | không (8 kHz thì soxr lên 16 kHz) |
| TTS → browser | 24 kHz PCM → Opus 48 kHz | SDK LiveKit |

### B — Dữ kiện cần lưu ý
- Các classifier #1–#4 **độc lập, có trạng thái riêng**, quyết định lệch nhau là bình thường
  (log "VAD/Admission disagree"). Bug 26/09 (câu kẹt trong ASR) sinh ra đúng từ việc
  Admission và bộ chốt câu của ASR lệch nhau 1 frame.
- `_fanout` `await vad_queue.put` rồi `await asr_queue.put` trong **cùng một vòng lặp**: nếu
  ASR decode chậm và `asr_queue` (50 frame) đầy, VAD cũng dừng nhận frame → chốt lượt bị trễ
  theo ASR (log 24/09: decode 1,89 s nhưng log kéo dài 4,38 s).
- Trong lúc bot nói, audio người dùng **không vào ASR** trừ khi VAD báo candidate; phần nói
  trước candidate chỉ còn tối đa 480 ms trong `pre_roll`.

---

## 4. Giai đoạn C — STT (`ZipFormerASR.stream`, "chunked-offline")

- **Model:** gipformer1.5-68M-rnnt (int8), zipformer transducer **bản offline** —
  sherpa-onnx `OfflineRecognizer`, `greedy_search`, `num_threads=2`, 16 kHz. Không có model
  streaming tiếng Việt, nên streaming được giả lập.
- **Vòng lặp trên frame nhận từ `asr_queue`:**
  1. `AsrSegmentEnd.FINALIZE` → decode buffer, phát final (nếu đủ `min_decode_ms`), xoá buffer;
     `DISCARD` → xoá buffer, không phát gì.
  2. Classifier #2 phân loại frame. Trước khi có speech: giữ **pre-speech 300 ms** (bù độ trễ
     VAD); khi có speech thì gộp vào buffer.
  3. **Partial:** mỗi 300 ms audio (`min_emit_interval_ms`), nếu frame là speech và đã có
     ≥ 400 ms speech (`min_decode_ms`) → **decode lại toàn bộ buffer** → phát partial nếu khác
     lần trước.
  4. **Final:** khi classifier #2 thấy ≥ 600 ms im lặng liên tục, hoặc speech liên tục
     ≥ 15 s (`max_turn_speech_ms`, flush cưỡng bức), hoặc hết luồng. Speech < 400 ms → bỏ
     hẳn (chống ảo giác trên "à", "ờm").
  5. Decode chạy trong `asyncio.to_thread` (không chặn event loop).
- **Đầu ra:** `TranscriptEvent(text, is_final)`, text **VIẾT HOA, không dấu câu, số đọc bằng
  chữ** ("MƯỜI BỐN THÁNG BA"), `confidence=None`.
- Provider thay thế: `ElevenLabsRealtimeASR` (streaming thật qua WebSocket, commit thủ công
  bằng cùng classifier; xử lý FINALIZE, bỏ qua DISCARD).

### C — Dữ kiện cần lưu ý
- Chi phí decode tăng theo độ dài câu (decode lại cả buffer mỗi 300 ms) — câu 10 s ≈ 33 lần
  decode với buffer lớn dần.
- ASR tự chốt câu bằng classifier **của chính nó** trên **những frame nó được nhận** → phụ
  thuộc việc pipeline đưa đủ im lặng; `AsrSegmentEnd` (26/09) bù cho các chỗ pipeline ngừng
  đưa frame. Còn 1 trường hợp biên: ngắt lời đã xác nhận, người dùng ngừng nói đúng lúc bot
  dừng, Admission bật.
- Không có confidence → mọi cổng dựa trên confidence (Interruption `min_confidence`,
  `asr_confidence` gửi engine) đều không hoạt động.
- Model nghe sai cụm nghiệp vụ ngay trên audio sạch ("hủy lịch" → "THÙY LINH"/"TÙY LỊCH");
  chưa có hotwords/contextual biasing (cần `modified_beam_search`).
- Tiếng người nói xung quanh được chép vào lượt nói (WER > 1 trong bộ đo 25/09).

---

## 5. Giai đoạn D — Sau STT: chốt lượt nói (`_drain_asr` → TurnController)

### D1. `_drain_asr` với mỗi `TranscriptEvent`
1. (Validator bật) `TranscriptEvidenceTracker.observe` → `StabilityVerdict`:
   - `OSCILLATING`: trong 5 text gần nhất, một text ngắn (≤ 2 từ) lặp ≥ 2 lần xen kẽ với text
     ngắn khác (mẫu "đây"→"tại"→"đây").
   - `CONVERGING`: text mới không ngắn hơn và `fuzz.ratio` ≥ 60 so với text trước.
   - còn lại `UNKNOWN`. Reset sau mỗi final.
2. `controller.on_evidence_updated(SNR cả câu, stability)`;
   `interruption.on_evidence_updated(SNR theo frame, stability)`.
3. `controller.on_transcript_event(event)` — **ghi đè** `candidate.text` bằng text mới nhất.
4. `interruption.on_partial_transcript(event)`.

### D2. TurnController — khi nào chốt
- **ASR final tới** → thử chốt ngay (cơ hội cuối).
- **VAD `speech_end`** mà chưa có final → chờ tối đa **300 ms** rồi chốt bằng partial.
- `speech_start` mới → **reset candidate**: câu có quãng dừng > 600 ms (+ hangover VAD) có thể
  bị tách thành 2 lượt.
- Chuỗi kiểm tra trong `_try_emit` (dừng ở điều kiện đầu tiên không thoả):
  1. đã chốt hoặc **bot đang nói** → không chốt;
  2. chưa final thì phải có `speech_end`;
  3. text rỗng → không;
  4. `is_meaningful_text`: bỏ chuỗi chỉ dấu câu và filler đơn ("à", "ừ", "ờ", "dạ", "ạ"…);
  5. thời lượng từ `speech_start` ≥ **250 ms**, cộng thêm phần còn lại của **500 ms** nếu bắt
     đầu ngay sau khi bot dứt lời (chống dư âm);
  6. **TurnValidator** (nếu bật).
- Bot dừng nói: candidate hình thành trong lúc bot nói bị **bỏ**, trừ khi barge-in đã xác nhận
  (`preserve_candidate=True`).

### D3. TurnValidator (tắt ở prod)

| Điều kiện | Quyết định |
|---|---|
| stability `OSCILLATING` | DROP |
| text ≤ 2 từ **và** SNR cả câu < 3 dB | DROP |
| stability `CONVERGING` | ACCEPT |
| còn lại | WAIT — ở "cơ hội cuối" (final/timeout) coi như ACCEPT |

- DROP không ghi log ở TurnController (chỉ thấy qua `replay_dump.py`).
- Tham số `state`/`expected_input` có trong chữ ký `evaluate` nhưng **không dùng** — validator
  không biết bot vừa hỏi gì.

### D4. InterruptionController (barge-in)
- Máy trạng thái: `IDLE → BOT_SPEAKING → INTERRUPTION_CANDIDATE → INTERRUPTED`.
- Candidate khi VAD `speech_start` lúc bot nói; quay lại `BOT_SPEAKING` nếu `speech_end` trước
  khi xác nhận.
- Chỉ xác nhận qua **partial ASR** — cổng (`_passes_gate`), phải qua hết:
  1. candidate ≥ 200 ms;
  2. `is_meaningful_text`;
  3. confidence ≥ ngưỡng (bỏ qua vì ZipFormer không có confidence);
  4. **không giống câu bot đang đọc** (`fuzz.partial_ratio` < 70) — chống bot nghe lại chính nó;
  5. SNR theo frame ≥ `interruption_min_snr_db` (local 0 dB; prod tắt);
  6. Validator (nếu bật) phải trả **ACCEPT** (WAIT cũng bị từ chối).
- Xác nhận → `CallBridge.cancel()`: huỷ TTS, xoá hàng đợi phát, huỷ task đang nói → bot dừng,
  candidate được giữ và chốt thành lượt.

**Đầu ra giai đoạn D:** `UserTurnCompleted(text, confidence=None)` vào `_turn_queue`.

### D — Dữ kiện cần lưu ý
- Lượt chốt bằng partial (nhánh timeout 300 ms) có thể thiếu ≤ 300 ms audio cuối (partial chỉ
  sinh mỗi 300 ms). Khi Admission bật, `FINALIZE` làm lượt chốt bằng final.
- Trong lúc bot nói (engine + TTS), lời người dùng chỉ có một đường vào: barge-in. Nói chen mà
  không qua được cổng barge-in thì mất (candidate bị bỏ khi bot dừng).
- Các lớp chống ảo giác hiện có: `min_decode_ms` (C), `is_meaningful_text`, `min_speech_ms`,
  post-bot guard, Validator (stability + SNR), Admission (SNR trước ASR), cổng barge-in (echo
  text, SNR). Không lớp nào dùng độ tin cậy của ASR.
- Luật SNR (đã sửa 26/09) chỉ chặn âm thanh **ngang nền**; ảo giác từ âm thanh to không phải
  lời nói (ho, tiếng động, bot vọng) không bị luật này chặn.

---

## 6. Giai đoạn E — Trước và ở đầu core engine

### E1. CallBridge → engine
- Vòng `run()` xử lý **tuần tự**: lấy 1 lượt từ `_turn_queue` (tối đa 4) →
  `CallerInput(turn, text=turn.text, silence_ms=0, audio_url=None, asr_confidence=None)` →
  `orchestrator.handle_turn` trong `asyncio.to_thread` → `_speak(action.utterance)` (chờ phát
  xong) → lượt kế.
- **Không có bước chuẩn hoá nào giữa ASR và engine** trong transport: text ASR thô (viết hoa,
  số bằng chữ) đi thẳng vào engine.
- **`silence_ms` luôn = 0**: đường LiveKit không bao giờ gửi lượt im lặng.

### E2. Đầu core engine (`orchestrator._process` → `extractor.extract`)
1. `policy.check_preconditions`.
2. Chuẩn hoá (`extraction/text.py`): NFC, lowercase, thống nhất vị trí dấu thanh ("huỷ"/"hủy"),
   bỏ dấu câu; câu **không dấu** thì so với bản không dấu của từ khoá (có danh sách loại trừ).
3. Trích xuất **theo luật, theo câu hỏi hiện tại**: tín hiệu đường dây (outbound: voicemail…),
   mức lâm sàng, intent, ngày sinh (`spoken_numbers` đọc "mười bốn tháng ba năm một chín bảy
   tám"), họ tên, chọn slot, đồng ý/từ chối, lý do huỷ. So khớp cụm từ **chính xác theo ranh
   giới từ** — không có so khớp mờ/âm vị trong `callbot/`.
4. **Tầng ngữ nghĩa** (`semantic_router`): chỉ gọi LLM (OpenAI `gpt-6-luna`, timeout 3 s,
   không retry) cho một số câu hỏi khi luật chưa chắc (vd. `CANCEL_RECONFIRM` mâu thuẫn/không rõ,
   nhắc lâm sàng). Model **không được** nâng NONE/UNCLEAR/REFUSE thành AGREE. Log thật 26/09:
   1,39 s và 1,49 s mỗi lần gọi.
5. Policy/dialogue → `BotAction` (câu trả lời sinh từ template `dialogue/templates.py`, không
   dùng LLM; kèm state, `ended`, `outcome`).
- Quy tắc engine liên quan tới giọng nói: 2 lần liên tiếp không hiểu → chuyển máy
  (`max_failed_understandings`); 3 lượt im lặng → UNREACHABLE (`max_silent_turns`) — **không
  kích hoạt được trên LiveKit** vì không có lượt im lặng.

### E — Dữ kiện cần lưu ý
- `asr_confidence` luôn `None` và engine không đọc trường này.
- Engine không biết text đến từ ASR hay gõ tay, không biết lượt được chốt bằng partial hay final,
  cũng không biết SNR/stability — mọi bằng chứng âm thanh dừng ở giai đoạn D.
- Lỗi nghe sai của ASR ("TÙY LỊCH") chỉ có thể được cứu ở tầng ngữ nghĩa (nếu câu hỏi đó được
  route) — luật từ khoá không khớp.
- Engine chạy đồng bộ; lượt có gọi LLM cộng thêm ~1,4 s trước khi TTS bắt đầu.

---

## 7. Giai đoạn F — Phát lời bot và vòng tiếng vọng

- `_speak`: `on_bot_speaking_changed(True)` + `on_bot_started_speaking(text)` → stream TTS
  OpenAI `tts-1` (PCM 24 kHz) từng chunk → `AudioSource` (hàng đợi phát 200 ms) → chờ
  `wait_for_playout` (timeout 20 s) → `on_bot_speaking_changed(False)`.
- Chống bot nghe lại chính nó: AEC trình duyệt; audio lúc bot nói không vào ASR (trừ
  candidate); post-bot guard 500 ms; cổng barge-in so text với câu bot (≥ 70 là echo) và SNR.
- `is_bot_speaking` bật từ lúc **bắt đầu gửi TTS**, tắt khi **phát xong** — không theo âm thanh
  thật ở loa người dùng (độ trễ mạng/jitter buffer phía browser không được tính).

---

## 8. Độ trễ một lượt — các thành phần

| Thành phần | Giá trị | Nguồn |
|---|---|---|
| Hangover Silero sau khi hết tiếng | ~0,5 s (local); WebRTC không có | tham số sherpa-onnx |
| VAD chờ im lặng → `speech_end` | 0,6 s | `vad_end_silence_ms` |
| Chờ final sau `speech_end` | ≤ 0,3 s (Admission bật: final gần như ngay nhờ FINALIZE) | `turn_max_wait_after_vad_end_ms` |
| Decode final | nhỏ so với các mục trên (RTF ~0,03) | docstring zipformer.py |
| Engine: lượt không gọi LLM (luật + gọi clinic) | 4–13 ms | log 26/09 (từ `turn text` tới `turn action`) |
| Engine: tầng ngữ nghĩa (khi được gọi) | ~1,4–1,5 s | log 26/09 |
| TTS: tới chunk âm thanh đầu | **chưa đo** | — |
| Hàng đợi phát + mạng | ≥ 0,2 s | `output_queue_ms` |

Từ lúc hết tiếng tới khi lượt được chốt, chưa tính engine và TTS: local (Silero) khoảng
**1,1–1,4 s**; production (WebRTC, không hangover) khoảng **0,6–0,9 s**.

---

## 9. Tổng hợp dữ kiện để đánh giá (quan sát, chưa phải kết luận)

1. **Local ≠ production** (mục 0): số đo chất lượng hiện có không đại diện cho production.
2. **Nhiều VAD độc lập** trên cùng frame (tới 4 Silero ở local); ranh giới câu do nhiều nơi
   quyết định (VAD chính, ASR, Admission), từng gây bug khi lệch nhau.
3. **Streaming giả lập** (decode lại cả buffer): chi phí tăng theo độ dài câu; partial thưa
   (300 ms); chốt câu phụ thuộc frame được đưa vào.
4. **Backpressure dính chùm:** ASR chậm làm VAD và chốt lượt chậm theo.
5. **Không có độ tin cậy ASR** ở bất kỳ đâu (ZipFormer không trả; engine không dùng).
6. **Lỗi nghe sai cụm nghiệp vụ** không có cơ chế sửa ở ASR (hotwords) hay ở engine (so khớp mờ).
7. **Im lặng không tới engine**: không có nhắc lại khi người dùng im, luật UNREACHABLE không chạy.
8. **Xử lý lượt tuần tự**: trong lúc engine + TTS chạy, lời người dùng chỉ vào được qua barge-in.
9. **Giọng nền** (người nói xung quanh) chưa có lớp xử lý; BVC của LiveKit chưa dùng.
10. **Validator không biết ngữ cảnh hội thoại** (`state`/`expected_input` không dùng); luật SNR
    chỉ chặn âm thanh ngang nền.
11. **Câu có quãng dừng dài bị tách** thành 2 lượt (speech_start mới reset candidate).
12. **Mọi track audio gộp chung một queue** (chưa lộ vì demo 1 người).
13. **Công cụ chẩn đoán có sẵn:** `LIVEKIT_DEBUG_DUMP_AUDIO` + `eval/noise-bench/replay_dump.py`
    (phát lại cuộc gọi thật qua đúng pipeline), `bench.py` (nhiễu có kiểm soát — số liệu cấp
    lượt nói dao động giữa các lần chạy), `validator_snr_eval.py` (dữ liệu biết chắc thật/giả).
    Tracing engine tắt mặc định (`trace.enabled: false`).

---

## 10. Tra cứu file

| Giai đoạn | File | Hàm/class chính |
|---|---|---|
| Worker | `src/callbot/transports/livekit/worker.py` | `prewarm`, `entrypoint` |
| Cấu hình | `config/livekit.yaml`, `config/speech.yaml`, `config/asr.yaml`, `config/engine.yaml` | `LiveKitSettings`, `SpeechSettings` |
| A | `src/callbot/transports/livekit/call_bridge.py`, `audio_adapter.py` | `_pump_track`, `livekit_frame_to_segment` |
| B | `src/speech/asr/pipeline.py` | `STTPipeline.stream`, `_fanout`, `_drain_vad`, `_drain_asr` |
| B | `src/speech/asr/admission.py` | `SpeechAdmission`, `PreRollBuffer` |
| B | `src/speech/audio/noise_tracker.py` | `NoiseTracker`, `UtteranceEvidenceTracker` |
| B | `src/speech/asr/vad/{async_stream,silero,webrtc,energy}.py` | `AsyncStreamingVAD`, classifiers |
| B | `src/speech/bundle.py` | `build_streaming_bundle` (tạo các classifier) |
| C | `src/inference/asr/providers/zipformer.py` | `ZipFormerASR.stream` |
| C | `src/speech/types.py` | `AsrSegmentEnd`, `TranscriptEvent` |
| D | `src/speech/asr/evidence.py` | `TranscriptEvidenceTracker` |
| D | `src/speech/turn/controller.py` | `TurnController`, `is_meaningful_text` |
| D | `src/speech/turn/validator.py` | `TurnValidator` |
| D | `src/speech/turn/interruption.py` | `InterruptionController` |
| E | `src/callbot/engine/orchestrator.py` | `handle_turn`, `_process` |
| E | `src/callbot/engine/extraction/{extractor,text,spoken_numbers,semantic_router}.py` | `extract`, `normalize`, `route_semantic` |
| F | `call_bridge.py`, `src/speech/bundle.py` | `_speak`, `SpeechSynthesizer.synthesize_stream` |

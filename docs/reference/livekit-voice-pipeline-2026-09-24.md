# Luồng xử lý giọng nói LiveKit — trạng thái hiện tại (2026-09-24)

Tài liệu này chốt lại toàn bộ luồng xử lý audio real-time qua LiveKit, đúng với code
tại thời điểm viết (nhánh `feature/livekit-realtime-voice`). Mục đích: dùng để báo
cáo/đối chiếu, không phải hướng dẫn vận hành (xem `livekit-merge-to-main.md` cho việc
deploy, `livekit-architecture.md` cho bản kiến trúc gốc trước các fix gần đây).

Mọi số liệu, tên hàm, tên file trong tài liệu này đã được đối chiếu trực tiếp với code
thật tại thời điểm viết — không suy diễn.

---

## 1. Tổng quan 2 process

```
uvicorn (FastAPI)                    LiveKit Agent Worker
transports/http/                     python -m callbot.transports.livekit.worker start
- /livekit/token (cấp JWT)           - 1 process/job = 1 cuộc gọi
- KHÔNG chạy ASR/audio               - CallBridge sở hữu toàn bộ state 1 call
        │                                     │
        │ cấp JWT                             │ nhận job dispatch qua WebSocket
        ▼                                     ▼
              LiveKit Cloud (SFU) — wss://...
                       ▲
                       │ WebRTC (mic publish / TTS subscribe)
                       │
                  Browser (livekit-demo.html)
```

Hai process độc lập hoàn toàn, không share state. `uvicorn` chỉ phát token, không
tham gia luồng audio. Toàn bộ pipeline mô tả dưới đây chạy trong `livekit-worker`.

---

## 2. Đường đi 1 frame audio — từ mic tới quyết định chốt turn

```
Browser mic (WebRTC)
    │
    ▼
CallBridge._pump_track()              [call_bridge.py]
    │  rtc.AudioStream.from_track() → livekit_frame_to_segment()
    │  (LIVEKIT_DEBUG_DUMP_AUDIO=1 ghi PCM ra .wav tại đây)
    ▼
CallBridge._frame_queue  (asyncio.Queue)
    │
    ▼
CallBridge._frames()  →  STTPipeline.stream(frames, ...)   [pipeline.py]
    │
    ▼
_fanout()  ── vòng lặp chính, xử lý TỪNG FRAME 30ms ──
```

`_fanout()` là nơi duy nhất quyết định 1 frame đi đâu. Có 2 nhánh lớn, tách theo
`controller.is_bot_speaking`:

### 2.1. Nhánh A — bot đang nói (barge-in candidate)

Audio luôn được đẩy thẳng vào `asr_queue` nếu `InterruptionController` đang nghi ngờ
có barge-in (`state == INTERRUPTION_CANDIDATE`), kèm replay `pre_roll` (buffer riêng,
17 frame ≈ 500ms) tích luỹ trước đó. Không qua Admission — audio phải tới ASR thật để
`InterruptionController` tự xác nhận qua `on_partial_transcript`, chặn ở đây sẽ
deadlock (ASR không có gì decode → không bao giờ confirm được).

Khi frame KHÔNG được đưa vào ASR ở nhánh này (bot vừa bắt đầu nói, hoặc candidate bị
bác), `_fanout()` gửi `AsrSegmentEnd.DISCARD` để ASR bỏ phần câu đang dở — TurnController
cũng bỏ đoạn này khi bot dứt lời. Ngoại lệ: `state == INTERRUPTED` (ngắt lời đã xác nhận,
bot chưa dừng hẳn) — phần người dùng đã nói được giữ để chốt thành turn. Xem mục 10.6.

### 2.2. Nhánh B — bot không nói (turn-taking bình thường)

Mỗi frame đi qua theo thứ tự:

1. **Speech Admission** (tuỳ chọn, `SPEECH_ADMISSION_ENABLED`) — classifier riêng
   (`admission_classifier`) tự phân loại `is_speech`, tính SNR qua `NoiseTracker.peek()`
   (không cập nhật floor ngay), rồi `SpeechAdmission.evaluate()` quyết định ADMIT/REJECT.
   Nếu REJECT: frame vào `_admission_preroll` (20 frame ≈ 600ms). Nếu ADMIT lần đầu
   (transition REJECT→ADMIT): flush `_admission_preroll` trước, rồi mới gửi frame hiện
   tại.
2. Nếu Admission tắt: frame đi thẳng `asr_queue`.

**Mỗi frame tới `asr_queue` đúng một lần, đúng thứ tự thời gian.** `_admission_preroll`
là bộ đệm duy nhất ở tầng pipeline. Âm tiết đầu câu mà VAD nhận muộn được
`ZipFormerASR.stream()` tự giữ bằng pre-speech 300 ms của nó.

Khi Admission kết thúc một đoạn đã ADMIT (ADMIT→REJECT sau `end_silence_ms` im lặng),
`_fanout()` gửi `AsrSegmentEnd.FINALIZE` để ASR chốt câu ngay. ASR tự chốt bằng khoảng
lặng trong các frame nó nhận, nhưng Admission ngừng gửi đúng ở ngưỡng đó nên ASR luôn
thiếu (đo được 570/600 ms). Xem mục 10.6.

Trước 25/09 còn một `_vad_preroll` flush 300 ms khi VAD chính báo `speech_start`. Nó giữ
chính các frame đã gửi (Admission tắt) hoặc đang nằm trong `_admission_preroll`
(Admission bật), nên ASR nhận đầu câu hai lần và có lúc đảo thứ tự (`[90..99]` rồi
`[83..]`). Đã gỡ bỏ — số liệu trong `docs/evidence/livekit-noise-robustness-2026-09-25.md`.

Song song, `vad_queue` nhận **mọi frame không điều kiện** — VAD chính không bao giờ bị
Admission lọc, để nó luôn thấy đủ dữ liệu quyết định `speech_start`/`speech_end` đúng.

---

## 3. 3 task chạy song song trong `STTPipeline.stream()`

```python
fanout_task = _fanout()    # sinh vad_queue + asr_queue từ frames đầu vào
vad_task    = _drain_vad() # tiêu thụ vad_queue → TurnController + InterruptionController
asr_task    = _drain_asr() # tiêu thụ asr_queue → TurnController + InterruptionController
```

- **`_drain_vad()`**: mỗi `VadEvent` (`speech_start`/`speech`/`speech_end`) từ
  `AsyncStreamingVAD` được gọi `controller.on_vad_event()`, đồng thời forward
  `speech_start`/`speech_end` cho `InterruptionController` nếu có cấu hình.
- **`_drain_asr()`**: mỗi `TranscriptEvent` (partial/final) từ ASR (`ZipFormerASR`) —
  nếu có `evidence_tracker`/`noise_tracker` cấu hình (Turn Validator bật), tính
  `StabilityVerdict` (CONVERGING/OSCILLATING/UNKNOWN) và cập nhật bằng chứng qua
  `on_evidence_updated()`, rồi mới gọi `on_transcript_event()`/`on_partial_transcript()`.
  - `TurnController` nhận SNR của **cả đoạn nói gần nhất** (`UtteranceEvidenceTracker`,
    giữ tối đa 3 s sau frame speech cuối), so với nền nhiễu riêng của tracker (trung vị
    3 s frame không-speech, bù độ trễ Silero 300 ms — mục 10.7). `InterruptionController`
    vẫn nhận SNR theo frame mới nhất với nền EMA của `NoiseTracker` như trước.
  - Sau mỗi final, `evidence_tracker.reset()`: độ ổn định chỉ xét trong một câu.

3 task này **không đồng bộ tuyệt đối theo frame** — `_drain_vad()` có thể xử lý event
trễ tối đa 1 frame (30ms) so với lúc `_fanout()` đọc `has_active_vad_candidate`. Cờ này
giờ chỉ dùng cho log "VAD/Admission disagree", không quyết định frame nào tới ASR.

---

## 4. Turn Controller — quyết định "user nói xong lượt chưa?"

File: `src/speech/turn/controller.py`.

Nhận 2 luồng event độc lập: `on_vad_event()` (từ VAD) và `on_transcript_event()` (từ
ASR) — không tự đọc audio. `_try_emit()` là nơi quyết định duy nhất, chạy qua chuỗi
điều kiện theo thứ tự, **dừng ở điều kiện đầu tiên không thoả**:

1. Candidate đã `finalized` hoặc bot đang nói → không chốt.
2. Chưa có ASR final: chỉ chốt bằng partial nếu VAD đã `speech_end` (`allow_partial`).
3. Text rỗng → không chốt.
4. `is_meaningful_text(text)` — lọc filler word đơn lẻ ("ừ", "ờm"...) và chuỗi chỉ có
   dấu câu. Rác → `_reset_candidate()` ngay, không chờ thêm.
5. `_has_min_duration()` — turn phải dài ≥ `min_speech_ms` (mặc định 250ms) tính từ
   `speech_start`. Nếu candidate bắt đầu trong `post_bot_guard_ms` (500ms) sau khi bot
   vừa dứt lời, cộng thêm phần thời lượng còn thiếu của guard window vào ngưỡng này
   (chống dư âm/echo phòng ngay sau khi bot ngừng nói).
6. **TurnValidator** (tuỳ chọn, `TURN_VALIDATOR_ENABLED`) — xem mục 6.

Khi bot bắt đầu nói (`on_bot_speaking_changed(True)`), mọi candidate đang hình thành bị
giữ nguyên (không chốt) nhưng KHÔNG bị huỷ ngay. Khi bot dứt lời
(`on_bot_speaking_changed(False)`):
- Nếu KHÔNG phải do barge-in được xác nhận (`preserve_candidate=False`): candidate bị
  huỷ hoàn toàn — audio nhận được trong lúc bot nói nhiều khả năng là echo/dư âm loa,
  không phải ý định thật của user.
- Nếu barge-in ĐÃ được `InterruptionController` xác nhận (`preserve_candidate=True`):
  giữ candidate, thử chốt ngay.

---

## 5. Speech Admission — lớp lọc trước `asr_queue`

File: `src/speech/asr/admission.py`.

`SpeechAdmission.evaluate()` là hàm thuần tuý (không giữ state), nhận `is_speech`
(từ classifier riêng), `evidence` (SNR, từ `NoiseTracker`), `speech_ms_so_far`,
`already_admitted`:

```
is_speech=False và chưa admitted  → REJECT (no_speech)
already_admitted=True, im lặng liên tục >= end_silence_ms → REJECT (no_speech) — hết đoạn
already_admitted=True             → ADMIT (ok)   ← giữ nguyên suốt câu, kể cả SNR tụt
SNR < min_snr_db (mặc định 6.0)   → REJECT (low_snr)
speech_ms_so_far < min_speech_ms (150ms) → REJECT (too_short)
còn lại                           → ADMIT (ok)
```

Điểm quan trọng: **frame nối tiếp của 1 đoạn đã ADMIT luôn tiếp tục ADMIT**, không xét
lại SNR/duration — tránh cắt giữa câu khi người nói hạ giọng.

`NoiseTracker` (`src/speech/audio/noise_tracker.py`) tách `peek()` (đo SNR, không cập
nhật `noise_floor`) và `commit_floor()` (cập nhật tường minh) — chỉ `commit_floor()`
khi Admission kết luận chắc chắn `reason == "no_speech"`. Lý do: nếu 1 frame REJECT vì
`low_snr`/`too_short` (vẫn có thể là speech thật, chỉ chưa đủ bằng chứng), cập nhật
`noise_floor` ngay bằng chính RMS của giọng nói đó sẽ kéo nền nhiễu ước tính lên sai,
làm SNR các frame sau thấp giả tạo.

---

## 6. Turn Validator — lớp quyết định cuối cùng

File: `src/speech/turn/validator.py`.

`TurnValidator.evaluate(text, noise_evidence, stability)` trả về
`ACCEPT`/`WAIT`/`DROP`, theo 4 luật theo thứ tự:

```
stability == OSCILLATING                                → DROP
text ≤ 2 từ  và  SNR < min_snr_db (mặc định 3.0)         → DROP
stability == CONVERGING                                  → ACCEPT
còn lại (thường là UNKNOWN — chưa đủ dữ liệu)             → WAIT
```

`StabilityVerdict` (`src/speech/asr/evidence.py`, `TranscriptEvidenceTracker`) so sánh
các partial transcript liên tiếp: `CONVERGING` nếu text đang dài dần và giống chuỗi
trước (`rapidfuzz.fuzz.ratio ≥ 60`); `OSCILLATING` nếu 1 text ngắn (≤2 từ) lặp lại xen
kẽ với text ngắn khác trong cửa sổ 5 event gần nhất. Cửa sổ được reset sau mỗi final —
trước 25/09 nó kéo dài qua nhiều câu, nên chuỗi trả lời thật "vâng" → "có" → "vâng" bị
coi là dao động.

`noise_evidence` là SNR của cả câu vừa nói (`UtteranceEvidenceTracker`). Trước 25/09 là
SNR của frame mới nhất — luôn là im lặng lúc ASR final tới, nên mọi câu ≤ 2 từ ("Dạ
không", "Có") bị DROP dù nói rõ (đo được snr = −13,6 dB cho "DẠ KHÔNG" trên audio sạch).
Trước 26/09 nền nhiễu còn bị phần đầu câu (Silero báo trễ) đẩy lên — mục 10.7.

**Lưu ý quan trọng đã xác nhận qua log thật**: luật DROP theo SNR chỉ áp dụng cho text
**ngắn** (≤2 từ). Text dài (5+ từ) dù SNR rất thấp (ví dụ -25dB) vẫn có thể ACCEPT nếu
`stability=CONVERGING` — đây chính là lỗ hổng khiến echo giọng bot (âm thanh thật,
không phải hallucination ngẫu nhiên, nên hội tụ ổn định) né được luật này khi xảy ra
trong lúc bot đang nói (xem mục 7).

Trong `TurnController._try_emit()`: `DROP` → huỷ candidate ngay. `WAIT` → **không chốt
nhưng cũng không huỷ**, trừ khi đây là `is_last_chance` (final ASR đã tới, hoặc timeout
hết hạn — không còn event nào khác sẽ tới) thì WAIT tự động fallback về ACCEPT (không
để turn treo vô thời hạn).

---

## 7. Interruption Controller — xác nhận barge-in

File: `src/speech/turn/interruption.py`.

State machine: `IDLE → BOT_SPEAKING → INTERRUPTION_CANDIDATE → INTERRUPTED`.

- `on_bot_started_speaking(bot_text)`: gọi khi `CallBridge._speak()` bắt đầu phát TTS,
  nhận luôn **text đầy đủ** bot sắp đọc (không phải PCM) — dùng để phát hiện echo.
- `on_speech_started()`: VAD báo `speech_start` giữa lúc bot nói → chuyển
  `INTERRUPTION_CANDIDATE`, **chưa** xác nhận gì.
- `on_partial_transcript()`: **tín hiệu DUY NHẤT** xác nhận barge-in — phải qua
  `_passes_gate()`, theo đúng thứ tự:

```
1. Đủ min_speech_ms (200ms) kể từ lúc thành candidate      → không thì reject
2. is_meaningful_text(text)                                 → filler word thì reject
3. confidence ≥ min_confidence (nếu provider cung cấp)       → ZipFormer luôn None, bỏ qua
4. KHÔNG giống câu bot đang đọc (fuzzy match, ngưỡng 70)     → giống thì reject (echo)
5. SNR ≥ interruption_min_snr_db (nếu cấu hình, mặc định TẮT) → thấp thì reject,
   KHÔNG PHÂN BIỆT độ dài text (khác luật SNR của TurnValidator ở bước 6)
6. TurnValidator.evaluate() (nếu cấu hình) phải trả ACCEPT   → DROP hoặc WAIT đều reject
```

Chỉ khi qua đủ cả 6 bước mới gọi `_confirm()` → `state = INTERRUPTED` → `tts.cancel()`.

**5 bug thật đã gặp và đã sửa, ghi lại trong docstring module** (theo thứ tự phát
hiện): (1) confirm ngay khi có text non-empty, bỏ qua duration/nội dung; (2) confirm
chỉ bằng duration VAD, không cần ASR; (3) VAD nhận nhầm noise phòng thành speech_start,
ASR hallucinate ra chữ "hợp lý"; (4) `WAIT` từng bị coi tương đương `ACCEPT`; (5) echo
chính giọng bot qua loa/mic — ASR nghe ĐÚNG nội dung âm thanh thật (không phải
hallucinate), nên qua được mọi gate cũ.

Khi `on_speech_ended_without_confirmation()` (VAD báo `speech_end` mà chưa từng qua
gate) → quay lại `BOT_SPEAKING`, không cancel TTS, không log gì ở nơi khác — đây là
nguồn candidate "biến mất không dấu vết" nếu audio đó thực ra là user nói thật nhưng
chưa kịp đủ điều kiện.

---

## 8. Wiring cấu hình — từ `.env` tới runtime

```
.env → SpeechSettings (settings.py) → build_streaming_bundle() (bundle.py)
                                              │
                                    StreamingSpeechBundle
                                    (stt_pipeline, tts, validator,
                                     evidence_tracker, noise_tracker, noise_classifier)
                                              │
worker.py::entrypoint() ── TurnController(validator=bundle.validator) ──┐
                                                                          ▼
                                                                    CallBridge(...)
                                                                          │
                                                          InterruptionController(
                                                            validator=interruption_validator,
                                                            min_snr_db=interruption_min_snr_db)
```

### Các cờ bật/tắt tính năng (tất cả mặc định TẮT, opt-in qua `.env`)

| Biến `.env` | Mặc định | Ảnh hưởng |
|---|---|---|
| `SPEECH_ADMISSION_ENABLED` | `false` | Bật `_admission_preroll` + lọc SNR trước ASR |
| `SPEECH_ADMISSION_MIN_SNR_DB` | `6.0` | Ngưỡng SNR Admission |
| `SPEECH_ADMISSION_MIN_SPEECH_MS` | `150` | Duration tối thiểu trước ADMIT |
| `SPEECH_ADMISSION_PREROLL_MS` | `600` | Kích thước `_admission_preroll` |
| `TURN_VALIDATOR_ENABLED` | `false` | Bật `TurnValidator` cho cả `TurnController` lẫn `InterruptionController` |
| `TURN_VALIDATOR_MIN_SNR_DB` | `3.0` | Ngưỡng SNR Validator (chỉ áp dụng text ≤2 từ) |
| `INTERRUPTION_MIN_SNR_DB` | *(trống = tắt)* | Ngưỡng SNR riêng cho barge-in, không phân biệt độ dài text |
| `VAD_PROVIDER` | `energy` | `energy` \| `webrtc` \| `silero` — VAD chính dùng cho turn-taking |

### Trạng thái `.env` local hiện tại (máy dev, không phải production)

```
ASR_PROVIDER=zipformer
VAD_PROVIDER=silero
SPEECH_ADMISSION_ENABLED=true
TURN_VALIDATOR_ENABLED=true
INTERRUPTION_MIN_SNR_DB=0.0
```

Production (`docker-compose.prod.yml`) **không** set các biến Admission/Validator —
dùng default code (tắt hết), trừ khi người vận hành tự thêm vào `.env` server (xem
`livekit-merge-to-main.md` mục 4).

---

## 9. 4 instance Silero VAD độc lập — vì sao không share

`build_streaming_bundle()` tạo **4 instance `SileroVadClassifier` riêng biệt** (khi
`VAD_PROVIDER=silero`), dù cùng load 1 file model:

| Instance | Dùng cho |
|---|---|
| `sync_classifier` | VAD chính, đường HTTP batch (`transcribe_segment`) |
| `async_classifier` | VAD chính, đường LiveKit streaming (`stream()`) |
| `asr_endpoint_classifier` | Gating nội bộ của `ZipFormerASR.stream()` |
| `admission_classifier` | Speech Admission (nếu bật) |
| `noise_classifier` | Turn Validator's `NoiseTracker` (nếu bật) — LUÔN Silero, không đọc `VAD_PROVIDER` |

Lý do bắt buộc tách: `sherpa_onnx.VoiceActivityDetector` là **stateful** (giữ buffer
nội bộ + hidden-state RNN qua các lần gọi `is_speech()` liên tiếp) — 2 consumer dùng
chung 1 instance sẽ làm lẫn dữ liệu, phân loại sai không thể debug được vì phụ thuộc
thứ tự gọi.

Đã xác nhận qua thực nghiệm (replay offline trên audio dump thật): khi chạy đúng cùng
audio, 2 instance độc lập (VAD chính vs Admission) luôn cho kết quả **giống hệt nhau**
(0 mismatch). Nghĩa là hiện tượng "VAD/Admission disagree" thấy trong log production
không phải do 2 instance phân loại sai lệch nhau về bản chất thuật toán, mà do:
- Timing 1-frame-trễ giữa `_fanout()` và `_drain_vad()` (mục 3), hoặc
- Worker chạy chậm hơn thời gian thực do tài nguyên máy hạn chế (xem mục 10).

---

## 10. Các bug đã xác nhận và đã sửa (theo thứ tự phát hiện trong phiên làm việc này)

### 10.1. `InterruptionController` coi `WAIT` như `ACCEPT`
Sửa trong `_passes_gate()`: `WAIT` giờ reject như `DROP`. Test:
`test_validator_wait_does_not_confirm_barge_in`.

### 10.2. Model ASR lệch giữa Docker và `.env` local
`Dockerfile`/`docker-compose*.yml` từng vẫn tải model ZipFormer cũ trong khi `.env`
local đã đổi sang `gipformer1.5` — đã đồng bộ lại cả 3 file.

### 10.3. `speech_admission_preroll_ms` quá nhỏ (240ms) làm mất chữ đầu câu
Thực nghiệm qua `LIVEKIT_DEBUG_DUMP_AUDIO` cho thấy thời gian Admission REJECT trước
khi ADMIT dao động 240-510ms tuỳ SNR đầu câu — buffer 240ms bị tràn. Tăng lên 600ms.

### 10.4. Mất chữ đầu câu dù Admission đã ADMIT đúng (âm tiết trước `speech_start`)
Đây là bug khác hẳn 10.3 — không liên quan Admission. Xác nhận bằng cách decode trực
tiếp audio dump thật qua `ZipFormerASR._decode_stream_pcm()`: decode đúng cửa sổ VAD
(`speech_start` → `speech_end`) ra thiếu chữ đầu; decode thêm 300ms audio trước đó ra
đúng. Từng sửa bằng `_vad_preroll`; ngày 25/09 bộ đệm này bị gỡ vì gây nhân đôi/đảo thứ
tự audio (mục 2.2). Âm tiết đầu câu giờ do pre-speech 300 ms trong `ZipFormerASR.stream()`
giữ lại.

**Thử nghiệm sai đã bị revert**: lần đầu sửa bug này, code cho phép frame đầu tiên của
candidate bypass hẳn Admission + set `already_admitted=True` giả — khiến Admission gần
như mất tác dụng bất cứ khi nào VAD chính tự tin là speech, kể cả khi VAD sai (đúng
kịch bản Admission sinh ra để chặn). Đã phát hiện qua test và revert, chỉ giữ đúng phần
bù preroll, không đụng quyết định Admission cho các frame sau.

### 10.5. Echo giọng bot bị nhận nhầm thành barge-in
Xem mục 7, bug #5. Sửa bằng `on_bot_started_speaking(bot_text)` + fuzzy match, và
`interruption_min_snr_db` (không phân biệt độ dài text, khác `TurnValidator`).

### 10.6. Câu dở nằm lại trong buffer ASR — lượt giả và câu bị ghép (26/09)
Cuộc gọi thật: lượt 2 lặp nguyên văn lượt 1 ("ANH TÊN LÀ NGUYỄN VĂN A NHÁ"), bot trả lời
lượt giả đó và nói đè lên câu ngày sinh; lượt 3 thành "ANH SINH ANH SINH NGÀY ...". Decode
audio dump cho thấy người dùng nói ngày sinh 2 lần, mỗi lần một "anh sinh".

Nguyên nhân: ASR chỉ chốt câu khi thấy đủ `end_silence_ms` im lặng trong các frame nó
nhận, còn `_fanout()` ngừng đưa frame ở 2 chỗ mà không báo: (1) Admission hết đoạn đúng
ở ngưỡng đó — ASR chỉ thấy 570 ms, câu nằm lại rồi thành final giả khi preroll của câu sau
được flush; (2) bot bắt đầu nói giữa câu — "anh sinh" nằm lại rồi ghép vào câu sau. Code
trước 25/09 cũng sai trên cùng file dump ("ANH ANH SINH ...", lượt giả "ANH ANH").

Sửa: `AsrSegmentEnd` (`speech/types.py`) — `_fanout()` gửi FINALIZE (mục 2.2) hoặc DISCARD
(mục 2.1). ZipFormer xử lý cả hai; ElevenLabs chỉ FINALIZE (commit) — audio đã gửi lên
server không rút lại được. Phát lại file dump: đúng 3 lượt ở cả 4 kịch bản (Admission
bật/tắt × có/không bot nói đè). Test: `tests/speech/test_pipeline_asr_segments.py`, 3 test
marker trong `tests/speech/test_zipformer_stream.py`.

Còn lại: ngắt lời đã xác nhận mà người dùng ngừng nói đúng lúc bot dừng (Admission bật,
chưa ADMIT lại) — phần ngắt lời vẫn có thể nằm lại buffer. Chưa gặp thực tế, chưa xử lý.

### 10.7. Câu trả lời ngắn bị Turn Validator bỏ vì nền nhiễu bị đầu câu đẩy lên (26/09)
Cuộc gọi thật: câu "hủy lịch" (ASR ra "THÙY LINH") bị DROP với snr −3,2 dB, trong khi
Admission đo 17,7 dB. Silero báo speech trễ ~270 ms (`min_speech_duration` 0,25 s mặc định
của sherpa-onnx) đúng phần to nhất của câu; `NoiseTracker.observe()` cập nhật floor bằng các
frame đó (145 → 1337). Trên 350 đoạn của các bản ghi thật, 70 đoạn bị tính < 3 dB dù đều to
hơn nền ≥ 10 dB.

Sửa trong `UtteranceEvidenceTracker` (chỉ đường TurnController; Admission và Interruption
không đổi): frame không-speech chỉ vào nền sau 300 ms — nếu Silero báo speech trước đó thì
chúng là đầu câu, tính vào năng lượng câu; nền = trung vị 3 s frame không-speech gần nhất.
Đã so với B (EMA hoãn), C (phân vị 20) — phân vị thấp làm nhiễu dao động luôn "to hơn nền",
mất tác dụng chặn ảo giác. Đo trên dữ liệu biết chắc thật/giả
(`eval/noise-bench/validator_snr_eval.py`, ngưỡng 3 dB): câu thật ngắn bị bỏ ở sạch/15/8 dB
37/217 → 0/217, ở 3 dB 29/70 → 6/70; đoạn chỉ có nhiễu bị chặn 24/91 → 20/91. Test:
`test_loud_onset_reported_late_by_vad_counts_as_speech_not_noise` và 2 test canh chừng
trong `tests/speech/audio/test_noise_tracker.py`.

---

## 11. Không phải bug code — vấn đề tài nguyên máy đã quan sát

Nhiều lần log production cho thấy `speech_admission: VAD/Admission disagree` lặp lại
hàng trăm dòng liên tục (3-4+ giây), dù người dùng chỉ nói 1 câu ngắn rồi dừng.

Đã điều tra bằng cách lấy đúng file audio dump (`LIVEKIT_DEBUG_DUMP_AUDIO=1`) của các
session bị lỗi, replay offline qua cùng model Silero VAD ngoài môi trường asyncio thật.
Kết quả nhất quán ở 2 session khác nhau: candidate dài nhất khi replay offline chỉ
1.89 giây — không có candidate nào kéo dài 4+ giây như log thật thể hiện.

Kết luận: đây là dấu hiệu **worker xử lý chậm hơn thời gian thực** (audio 1.89s thật
mất hơn 4s đồng hồ để worker xử lý xong), không phải lỗi trong logic VAD/Admission.
Xác nhận thêm qua `free -h` lúc xảy ra: RAM 10-12Gi/15Gi đã dùng, swap 2.6-3.2Gi/4Gi
đang active, do VSCode + nhiều tab Chrome chạy song song với worker trên cùng máy dev.
Log spam là **hệ quả hiển thị đúng** của điều kiện `(Admission REJECT) AND (VAD vẫn coi
là candidate)` kéo dài bất thường lâu về mặt đồng hồ thật — không phải log bị lỗi lặp,
cũng không phải VAD "kẹt" theo nghĩa logic sai.

---

## 12. Kiến trúc lớp phòng thủ chống hallucination — tổng kết

```
Audio thô
    │
    ▼
[Lớp 1] Speech Admission (opt-in)  — chặn sớm noise SNR thấp trước khi vào ASR
    │                                 (bộ đệm preroll duy nhất, mỗi frame tới ASR 1 lần)
    ▼
ASR (ZipFormer, chunked-offline decode, pre-speech 300 ms giữ âm tiết đầu câu)
    │
    ▼
[Lớp 2] is_meaningful_text()       — lọc filler word, chuỗi chỉ dấu câu
    │
    ▼
[Lớp 3] min_speech_ms + post_bot_guard — lọc tiếng động ngắn/echo ngay sau bot dứt lời
    │
    ▼
[Lớp 4] TurnValidator (opt-in)     — DROP theo dao động transcript trong câu (OSCILLATING)
    │                                 hoặc SNR cả câu thấp + text ngắn; ACCEPT khi hội tụ
    ▼
UserTurnCompleted → CallOrchestrator

Riêng nhánh barge-in (InterruptionController), độc lập hoàn toàn:
    │
    ▼
[Lớp A] min_speech_ms (200ms)
[Lớp B] is_meaningful_text()
[Lớp C] So khớp echo với câu bot đang đọc (fuzzy match)
[Lớp D] SNR riêng, không phân biệt độ dài text (opt-in)
[Lớp E] TurnValidator (opt-in, dùng chung instance với Lớp 4 nếu cùng bật)
```

Mỗi lớp giải quyết đúng 1 loại lỗi cụ thể đã quan sát được qua log thật — không có lớp
nào được thêm vì lý thuyết, tất cả đều bắt nguồn từ 1 bug cụ thể đã tái hiện được.

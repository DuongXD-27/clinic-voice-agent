# Luồng STT (Speech-to-Text) — giải thích chi tiết

Tài liệu này giải thích **STT đi vào đâu, xử lý qua những bước nào**, đối chiếu trực tiếp với code trên nhánh `main` ngày 17/09/2026. Khác với [ai-callbot-architecture.md](ai-callbot-architecture.md) (bức tranh toàn hệ thống), file này đào sâu riêng phần âm thanh → văn bản.

## 1. Hợp đồng không ép kiến trúc STT

Theo `The Callbot Contract` (AIHR-PC-001, §6.2):

> Teams MAY choose any architecture — an STT → NLU → dialogue → TTS pipeline, a speech-to-speech model, or anything in between.

Nghĩa là **không có luồng STT "đúng" bắt buộc**. Hợp đồng chỉ ràng buộc:

- Hai endpoint HTTP: `POST /v1/calls` và `POST /v1/calls/{call_id}/turn`, phản hồi trong 8 giây (§4.1.2).
- `mode: "audio"` từ tuần 3 trở đi thay cho `mode: "text"` của tuần 1–2 (Listing 1).
- Mỗi lượt nhận `audio_url` (clip do harness cung cấp) hoặc `text`, không phải cả hai.
- Kết quả được chấm là **bản ghi lịch hẹn cuối cùng** (§2.1), không phải transcript — nói đúng nhưng ghi sai trạng thái vẫn là case fail.

→ Team tự quyết cách biến audio thành text. Phần dưới đây là cách team này **đã chọn và đã viết code**, không phải yêu cầu từ hợp đồng.

## 2. Kiến trúc đã chọn: pipeline có bước riêng, không speech-to-speech

Code hiện tại đi theo hướng cascaded — tách rời từng bước thay vì một model nghe-hiểu-trả lời trực tiếp:

```
audio_url (URL clip .wav của harness)
   │
   ▼
[1] Tải + giải mã  →  audio/loader.py, audio/codec.py
   │  (PCM 16-bit mono, chuẩn hoá về 8 kHz)
   ▼
[2] VAD (Voice Activity Detection)  →  vad/streaming.py, vad/energy.py
   │  (có tiếng nói hay im lặng — bỏ qua ASR nếu im lặng)
   ▼
[3] ASR (nhận dạng)  →  asr/gemini.py hoặc asr/phowhisper.py
   │  (audio → text tiếng Việt)
   ▼
[4] Transcript  →  types.py: Transcript(text, is_silence, confidence)
   │
   ▼
CallerInput.text  →  engine/orchestrator.py (dialogue, FSM, extraction...)
```

Điểm nối tất cả các bước trên là `STTPipeline` tại [src/speech/asr/pipeline.py](../../src/speech/asr/pipeline.py).

## 3. Từng bước, có trích dẫn code

### 3.1 Nhận audio_url, tải và giải mã

[audio/loader.py:7-13](../../src/speech/audio/loader.py#L7-L13) — `load_from_url()` gọi HTTP GET tới `audio_url` mà harness gửi (timeout 3s), lấy bytes wav thô.

[audio/codec.py:15-32](../../src/speech/audio/codec.py#L15-L32) — `decode_wav()` tự đọc header RIFF thủ công (module `wave` chuẩn của Python không đọc được G.711), hỗ trợ 3 định dạng:
- PCM 16-bit thường
- G.711 μ-law (Bắc Mỹ) — giải mã bằng bảng tra ở [audio/g711.py](../../src/speech/audio/g711.py)
- G.711 A-law (chuẩn châu Âu/VN, phổ biến trên tổng đài SIP thật)

Sau đó downmix về mono nếu stereo, và **resample về tần số pipeline** (mặc định 8000 Hz) bằng [codec.py:60-73](../../src/speech/audio/codec.py#L60-L73) — có lọc thông thấp trước khi hạ tần số để tránh aliasing (nhiễu giả tần số cao gập ngược vào dải nghe được).

### 3.2 VAD — có tiếng nói hay không

[vad/streaming.py](../../src/speech/asr/vad/streaming.py) chia PCM thành khung 30ms (`split_frames`, dòng 9-14), mỗi khung được `FrameClassifier` (hiện có `EnergyFrameClassifier` — phân loại theo năng lượng RMS, xem [vad/energy.py](../../src/speech/asr/vad/energy.py)) đánh giá là "speech" hay không. `StreamingVAD.process()` (dòng 24-40) gom các khung liên tiếp thành sự kiện `speech_start` / `speech` / `speech_end`.

Lý do có bước này: [pipeline.py:38-40](../../src/speech/asr/pipeline.py#L38-L40) — nếu cả đoạn không có tiếng nói, **bỏ qua ASR hoàn toàn**. Đây là tối ưu cost — mỗi lần gọi Gemini/PhoWhisper tốn tiền/compute, và "cost per session" chiếm 15% điểm số (§5, bảng trọng số).

### 3.3 ASR — gọi qua gateway, chọn provider qua config

[speech/settings.py](../../src/speech/settings.py) — `asr_provider` (`gemini` | `phowhisper` | `zipformer`, env `ASR_PROVIDER`) chỉ chọn provider. Model/API key của từng provider nằm trong [inference/asr/config.py](../../src/inference/asr/config.py) (`GEMINI_ASR_MODEL`, `PHOWHISPER_MODEL`, `ZIPFORMER_*_PATH`), giống cách `inference/llm` làm.

| Provider | File | Cách hoạt động | Đánh đổi |
|---|---|---|---|
| ZipFormer | [providers/zipformer.py](../../src/inference/asr/providers/zipformer.py) | Self-host qua sherpa-onnx (batch), nhận 16kHz | Chạy local CPU; mặc định trong docker-compose |
| Gemini | [providers/gemini.py](../../src/inference/asr/providers/gemini.py) | Gửi thẳng wav 8kHz lên Gemini API (`generate_content` với prompt ép chỉ trả text tiếng Việt) | Cloud, cần `GEMINI_API_KEY`, không tự host được |
| PhoWhisper | [providers/phowhisper.py](../../src/inference/asr/providers/phowhisper.py) | Self-hosted qua `transformers.pipeline`, nhưng Whisper chỉ nhận 16kHz nên phải **upsample** 8kHz→16kHz trước | Chạy local; audio điện thoại mất dải trên 4kHz nên WER sẽ cao hơn số công bố trên 16kHz sạch |

Các provider implement chung interface `ASRProvider` ([asr/base.py](../../src/inference/asr/base.py)): nhận PCM đúng `input_sample_rate` của model, trả `ASRResult`. [`ASRGateway`](../../src/inference/asr/gateway.py) là điểm gọi duy nhất (`create_asr_gateway(provider)`), không xử lý audio. [speech/asr/recognizer.py](../../src/speech/asr/recognizer.py) (`SpeechRecognizer`) resample `AudioSegment` về tần số model rồi gọi gateway, trả `Transcript` — đổi provider chỉ cần đổi config, không sửa pipeline.

`STTPipeline.stream()` hiện **chưa cài đặt** (chưa provider nào có ASR streaming) và raise `NotImplementedError`.

### 3.4 Gộp lại thành Transcript

[speech/types.py:37-43](../../src/speech/types.py#L37-L43) — `Transcript` là kết quả cuối: `text`, `confidence` (optional), `is_silence`. Đây là thứ engine thực sự nhận.

[speech/asr/transcript.py](../../src/speech/asr/transcript.py) — `TranscriptAggregator` gộp các event partial/final của ASR streaming thành một `Transcript` — chỉ dùng cho phone leg (âm thanh chảy liên tục), **không dùng** cho đường HTTP theo lượt (turn-based), vì ở đó mỗi lượt đã là một đoạn audio trọn vẹn rồi.

### 3.5 Điểm vào `STTPipeline`

[pipeline.py:20-30](../../src/speech/asr/pipeline.py#L20-L30) — `transcribe_turn(text, audio_url, silence_ms)` là hàm tổng hợp, xử lý đúng 3 khả năng của một lượt theo §4.1 hợp đồng:
1. `silence_ms > 0` → im lặng, không cần ASR
2. `text` có sẵn (text mode) → dùng luôn, không qua audio
3. `audio_url` có (audio mode) → tải, decode, chạy VAD + ASR (`transcribe_segment`, dòng 32-41)

## 4. Khoảng trống quan trọng: STT viết xong nhưng CHƯA nối vào request thật

Đây là lý do bạn "chưa hiểu STT đi vào như nào" — **vì hiện tại nó chưa thực sự nằm trên đường đi của một request HTTP nào cả.**

Bằng chứng trực tiếp trong [transports/http/calls.py](../../src/callbot/transports/http/calls.py):

- [dòng 99-101](../../src/callbot/transports/http/calls.py#L99-L101): `POST /v1/calls` **chặn cứng** `mode == "audio"`, trả lỗi `501 AUDIO_NOT_IMPLEMENTED`.
- [dòng 128-129](../../src/callbot/transports/http/calls.py#L128-L129): `POST /v1/calls/{id}/turn` **từ chối** mọi request có `audio_url`, trả lỗi `422 AUDIO_URL_NOT_ALLOWED`.

Và trong `engine/types.py`, [`CallerInput.transcript`](../../src/callbot/engine/types.py#L79-L81) chỉ đơn giản trả về `self.text` — engine **không hề gọi `STTPipeline`**. `main.py` của transport HTTP cũng không import hay khởi tạo `STTPipeline`/`SpeechSettings`/`GeminiASR`/`PhoWhisperASR` ở đâu cả (đã kiểm tra bằng grep, không có kết quả).

Nói cách khác: mọi thứ trong `src/speech/` tồn tại như một **thư viện đã viết và có unit test riêng** ([tests/speech/test_narrowband.py](../../tests/speech/test_narrowband.py) — test `STTPipeline`, VAD, codec, G.711 đầy đủ), nhưng **chưa có dây nối** từ `calls.py` gọi vào nó. Toàn bộ cuộc gọi hiện tại (tuần 1-2 theo lịch hợp đồng) chỉ chạy `mode: "text"`.

## 5. Để luồng audio thật sự chạy end-to-end, cần nối gì

(Không phải việc cần làm ngay — chỉ liệt kê khoảng cách giữa "đã có" và "chạy được".)

1. Bỏ chặn ở `calls.py:99-101` và `calls.py:128-129`.
2. Khởi tạo `STTPipeline` một lần trong `main.py`, tương tự cách `CallOrchestrator` đang được tạo trong lifespan (xem [calls.py:37-39](../../src/callbot/transports/http/calls.py#L37-L39) — `orchestrator` lấy từ `request.app.state`). Việc này dễ hơn tưởng — factory đã có sẵn: [`speech/__init__.py:17-25`](../../src/speech/__init__.py#L17-L25) hàm `create_stt_pipeline(settings)` tự lắp VAD + ASR provider (theo `SpeechSettings.asr_provider`) thành một `STTPipeline` hoàn chỉnh, chỉ cần gọi và gán vào `app.state`.
3. Trong `call_turn()`, khi có `audio_url`: gọi `stt_pipeline.transcribe_turn(text=None, audio_url=..., silence_ms=...)` → lấy `Transcript` → dựng `CallerInput(text=transcript.text, silence_ms=..., audio_url=audio_url, asr_confidence=transcript.confidence)` rồi mới đưa vào `orchestrator.handle_turn()` như hiện tại.
4. Chiều ngược lại dùng OpenAI TTS trong [inference/tts](../../src/inference/tts/) (`TTS_PROVIDER=openai`) để sinh `audio_url`; mode `text` không gọi TTS.

## 6. Vì sao mọi thứ chốt ở 8kHz, không phải 16kHz

[speech/types.py:4-7](../../src/speech/types.py#L4-L7): điện thoại truyền âm thoại băng hẹp 300–3400 Hz, số hoá chuẩn ở 8000 Hz (đủ theo định lý Nyquist cho dải đó). Các benchmark ASR công khai (kể cả PhoWhisper, Whisper) thường đo trên 16kHz "sạch" — không phản ánh chất lượng thật khi âm thanh đã đi qua đường dây điện thoại. Đây chính là lý do Appendix B.1 của hợp đồng cảnh báo: **đo WER trên bản ghi 8kHz tự thu, không tin số liệu leaderboard 16kHz.**

`SpeechSettings.sample_rate` mặc định là `NARROWBAND_RATE = 8000`; đổi thành `16000` chỉ nên dùng để so sánh nội bộ, không phải số báo cáo chính thức.

## 7. Phần streaming / phone leg (tuần 6) — chưa cần bây giờ

`STTPipeline.stream()` ([pipeline.py:43-49](../../src/speech/asr/pipeline.py#L43-L49)) là đường dành riêng cho cuộc gọi điện thoại thật qua SIP (§1.3.1-1.3.2 hợp đồng) — âm thanh chảy liên tục hai chiều, cần xử lý ngắt lời (barge-in). Cả hai ASR provider đều raise `NotImplementedError` cho `stream()`. Theo Appendix B.2 của hợp đồng: việc này chỉ cần từ tuần 5, và **đường được chấm điểm không bao giờ đi qua điện thoại** (§1.3.1: "Scoring never goes through a phone line") — nên đây không phải ưu tiên trước mắt.

Chi tiết kiến trúc cụ thể cho đường này (SIP/RTP, ZipFormer streaming qua sherpa-onnx, tách service hay gộp chung) xem [phone-leg-architecture.md](phone-leg-architecture.md).

## 8. Vì sao Streamlit prototype (nhánh `prototype`) không giúp hiểu luồng STT

Nhánh `prototype` (không nằm trên `main`, xem lịch sử commit `1c8a87c`) có một app Streamlit tên "voice MVP". Tên gây hiểu lầm: đọc thẳng docstring dòng đầu của file đó, nó tự ghi rõ là **"chat trực quan, KHÔNG dùng voice (ASR/TTS)"** — giả định transcript đã sạch sẵn (người dùng gõ text đóng vai kết quả STT), không hề chạy audio/VAD/ASR/TTS thật. Các provider TTS thật (Azure, Vbee, Viettel AI TTS, ElevenLabs) cũng chỉ có trên `prototype`, chưa từng merge vào `main`. Vì vậy nếu bạn từng thấy app đó chạy, nó không minh hoạ luồng STT — nó minh hoạ phần dialogue/engine với input giả lập là text.

---

**Tóm gọn một câu:** logic biến audio thành text (giải mã, lọc tiếng ồn/im lặng, nhận dạng) đã viết xong, có factory lắp sẵn (`create_stt_pipeline`) và test riêng trong `src/speech/`, nhưng đường HTTP đang phục vụ harness (`calls.py`) chủ động chặn audio và chỉ chạy text — đó là lý do luồng STT "chưa thấy nó chạy ở đâu" khi bạn theo dõi một request thật.

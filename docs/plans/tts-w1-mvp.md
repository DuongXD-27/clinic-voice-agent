# Plan TTS tuần 1 — MVP thô bằng API (TTS-1.1 → TTS-1.7)

**Owner:** B (Hưng) · **Trạng thái:** Duyệt 18-09-2026 (owner chọn WebSocket theo kế hoạch §2.1), đang thực thi · **Hạn:** hết ngày 18-09-2026 (thứ 6); thứ 7 19/9 dự phòng
**Nguồn:** `docs/plans/Ke_hoach_TTS_6_tuan_AI_Callbot.md` §1, §2, §4, §10; contract AIHR-PC-001 rev 1.1 §4.1.2, §4.1.3, §5.3 (Listing 1–2); ADR-002 §2 (6 tiêu chí), §3.2 (ElevenLabs Flash v2.5); `docs/task-breakdown.md` S-02
**Phụ thuộc:** A — điểm gọi TTS trong `transports/http/calls.py`, `main.py` và `CallStart` (kế hoạch 6 tuần §10: cần trước 18/9)

## 1. Mục tiêu hôm nay

Kế hoạch 6 tuần đặt cho tuần 1 (thứ 5–7, 17–19/9) một câu:

> Gọi `POST /v1/calls` với `mode: audio` trên máy local nhận được `audio_url` mở ra nghe đúng câu chào. Không tối ưu, không eval; streaming chỉ để gom chunk và đo TTFA.

Đã mất ngày thứ 5 → hôm nay phải xong phần **độc lập với A** (TTS-1.1, 1.2, 1.3, 1.6) và có **bản patch sẵn** cho phần nối HTTP (TTS-1.4, 1.5) để A duyệt; demo TTS-1.7 phải chạy được **kể cả khi patch chưa merge**.

| # | Điều kiện hoàn thành (kiểm được) | Task |
| --- | --- | --- |
| AC-1 | `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` trong `.env`; `python scripts/tts_say.py "Xin chào"` ra file WAV 8 kHz nghe được tiếng Việt | TTS-1.1 |
| AC-2 | `ElevenLabsTTS.synthesize(text)` trả `AudioSegment(sample_rate=8000)`; `stream(text)` yield chunk PCM từ WS `stream-input`; timeout 4 s; lỗi mạng/WS → `TTSUnavailable` / `TTSRejected`, **không lọt ngoại lệ `websockets`** ra ngoài `speech/tts/` | TTS-1.2 |
| AC-3 | Unit test bằng fake WS (không mạng): gom chunk đúng thứ tự, `isFinal` kết thúc, TTFA đo từ chunk đầu, 401/402/429/5xx/timeout/đóng bất thường → đúng lớp lỗi; test live `skipif` không có key | TTS-1.2 |
| AC-4 | `TTS_PROVIDER=elevenlabs` khởi tạo app; `none` chạy y như cũ (toàn bộ test hiện có pass) | TTS-1.3 |
| AC-5 | Response `POST /v1/calls` và `/turn` khi `mode=audio` có `audio_url = <PUBLIC_BASE_URL>/audio/<call_id>/<turn>.wav`; `mode=text` giữ `null` | TTS-1.4 (A) |
| AC-6 | `GET audio_url` ngay sau response → 200, WAV hợp lệ, file **ghi xong trước** khi response trả về | TTS-1.5 (A) |
| AC-7 | Bảng 20 lượt: P50/P95 của TTFA và tổng thời gian TTS + ghi file; danh sách câu đọc sai số/ngày | TTS-1.6 |
| AC-8 | Demo 1 cuộc outbound confirm ở mode audio, nghe 3–4 lượt; README có mục "Bật audio mode"; evidence `docs/evidence/tts-w1-mvp.md` | TTS-1.7 |

## 2. Hiện trạng code (đọc 18/9)

| Nơi | Có gì | Ý nghĩa cho hôm nay |
| --- | --- | --- |
| `speech/tts/base.py` | `TTSProvider(Protocol).synthesize(text) -> Optional[AudioSegment]`; `NullTTS` | Interface có sẵn, **giữ nguyên**; chỉ thêm provider |
| `speech/tts/storage.py` | `AudioArtifactStore.save(call_id, turn, segment)` → ghi WAV tại `<audio_dir>/<call_id>/<turn>.wav`, hạ về 8 kHz, trả URL `<base>/audio/<call_id>/<turn>.wav` | Đúng định dạng URL Listing 1–2; `path.write_bytes` là đồng bộ → file ghi xong trước khi hàm trả (AC-6) |
| `speech/settings.py` | `tts_provider: Literal["none"]`, `public_base_url`, `audio_dir` | Mở Literal + thêm key ElevenLabs |
| `speech/tts/__init__.py` | `create_tts()` chỉ biết `none` | Thêm nhánh `elevenlabs` |
| `speech/audio/codec.py` | `encode_wav`, `to_sample_rate` (resample cần numpy) | Xin **`pcm_8000` thẳng từ ElevenLabs** → không resample, không cần numpy ở prod |
| `transports/http/calls.py:99-101` | `mode=audio` → **501 `AUDIO_NOT_IMPLEMENTED`** trước khi mở session | Phải bỏ; 2 test của A khóa hành vi này (`test_calls.py::test_audio_mode_is_not_implemented`, `test_schema.py` case 501) |
| `transports/http/main.py` | Lifespan tạo clinic + orchestrator; **không** có TTS, store, route `/audio` | Thêm `create_tts`, `AudioArtifactStore`, `StaticFiles` |
| `engine/types.py::CallStart` | Không có `mode` | `/turn` không biết cuộc gọi là audio → cần `mode` đi vào session (worker khác có thể nhận lượt sau) |
| `pyproject.toml` | `uvicorn[standard]` đã kéo `websockets` (local 15.0.1) | Khai báo `websockets>=13` tường minh; không thêm gói mới thật sự |
| Handler FastAPI | `def` đồng bộ (threadpool) | Dùng `websockets.sync.client`, mỗi utterance một kết nối |

## 3. Quyết định thiết kế

### 3.1 WebSocket `stream-input` đúng như kế hoạch §2.1 (quyết định của owner 18/9)

`wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id=eleven_flash_v2_5&output_format=pcm_8000`, một kết nối cho mỗi utterance:

```text
-> {"text": " ", "xi_api_key": key}                 # khởi tạo (BOS)
-> {"text": "<utterance> ", "flush": true}          # gửi cả câu, ép sinh ngay
-> {"text": ""}                                     # EOS
<- {"audio": "<base64 pcm>", "isFinal": null, ...}  # n lần -> yield chunk
<- {"isFinal": true}                                # kết thúc
```

- Dùng `websockets.sync.client.connect` (client đồng bộ, phù hợp handler FastAPI `def`); `websockets` đã có sẵn qua `uvicorn[standard]`, khai báo tường minh trong `pyproject.toml`.
- Handshake mỗi lượt tính vào TTFA — số đo TTS-1.6 phải tách `connect_ms` riêng để tuần 3 quyết định có giữ kết nối lâu không.
- `stream(text)` hôm nay là generator đồng bộ `Iterator[bytes]`; interface async + `cancel()` theo context chốt ở TTS-4.1/4.2. Dự phòng trong ngày nếu WS trục trặc: HTTP `/stream` cùng model/format (kế hoạch §4 cho phép).

### 3.2 Format: `pcm_8000` thẳng từ provider

`output_format=pcm_8000` → PCM 16-bit mono 8 kHz, đúng `AudioSegment` mặc định, `AudioArtifactStore` không phải resample. Điện thoại tuần 5 đổi sang `ulaw_8000` bằng config (ElevenLabs hỗ trợ, ADR-002 §3.2 tiêu chí 4).

### 3.3 Module mới `speech/tts/elevenlabs.py`

```text
ElevenLabsTTS(api_key, voice_id, model="eleven_flash_v2_5", timeout_s=4.0,
              ws_url="wss://api.elevenlabs.io", output_format="pcm_8000",
              connect=None)                       # connect: hàm mở WS, thay bằng fake trong unit test
  name = "elevenlabs"
  stream(text) -> Iterator[bytes]                 # mở WS, BOS -> text+flush -> EOS, yield PCM đã decode base64; ghi self.last_timing
  synthesize(text) -> AudioSegment                # b"".join(stream(text)) -> AudioSegment(pcm, 8000)

TTSTiming(chars, connect_ms, ttfa_ms, last_chunk_ms, total_ms, audio_bytes)   # base.py, không chứa text

errors.py:
  TTSError(Exception)             # gốc — lớp ngoài chỉ bắt lớp này
  TTSUnavailable(TTSError)        # timeout, lỗi mạng, WS đóng bất thường, 5xx, 429
  TTSRejected(TTSError)           # 401 key sai, 402 hết quota, 422/voice sai, thông điệp lỗi từ server
```

Ràng buộc:
- **Không log text** — utterance có thể chứa tên/ngày sinh bệnh nhân (ADR-002 tiêu chí 6, SF-03). Log chỉ `TTSTiming` + mã lỗi.
- Không sửa utterance trước khi gửi (§4.1.3). Chuẩn hoá số → chữ là TTS-2.2, **ngoài phạm vi**; hôm nay chỉ **ghi lại** câu đọc sai.
- Key gửi trong message BOS (`xi_api_key`), model và format trên query string. Không gửi `voice_settings` (mặc định của voice).
- Ngoại lệ của `websockets` không lọt ra ngoài `speech/tts/` (giống nguyên tắc F-05 AC-3): tầng HTTP chỉ bắt `TTSError`.

### 3.4 Settings (`speech/settings.py`) và factory

```python
tts_provider: Literal["none", "elevenlabs"] = "none"
elevenlabs_api_key: str = ""
elevenlabs_voice_id: str = ""
elevenlabs_model: str = "eleven_flash_v2_5"
elevenlabs_timeout_s: float = 4.0
elevenlabs_output_format: str = "pcm_8000"   # tuần 5: ulaw_8000
```

`create_tts()`: `elevenlabs` thiếu key hoặc voice_id → `ValueError` có tên biến (fail-fast lúc khởi động, không chờ tới lượt 0). `.env.example` thêm 3 dòng `ELEVENLABS_*`.

### 3.5 Nối HTTP (TTS-1.4/1.5) — patch cho A, thay đổi nhỏ nhất

| File (A) | Thay đổi | Lý do |
| --- | --- | --- |
| `engine/types.py::CallStart` | thêm `mode: Literal["text","audio"] = "text"` (cộng thêm, có mặc định → `from_dict` phiên cũ vẫn chạy) | `/turn` cần biết mode; phiên nằm ở Postgres dùng chung worker |
| `transports/http/main.py` | lifespan: `speech_settings = SpeechSettings()`, `app.state.tts = create_tts(...)`, `app.state.audio_store = AudioArtifactStore(audio_dir, public_base_url)`; `mkdir` audio_dir rồi `app.mount("/audio", StaticFiles(directory=audio_dir))`; đóng `tts.close()` | TTS-1.5: route tĩnh phục vụ `audio_dir` |
| `transports/http/calls.py` | bỏ 501; `start_call`/`call_turn`: `audio_url = _render_audio(request, call_id, turn, action.utterance) if mode == "audio" else None`; `_render_audio` bắt `TTSError` → log + trả `None` (tuần 3 mới có fallback/cache); audio mode + `payload.audio_url` → 501 `STT_NOT_IMPLEMENTED` (S-01 của A chưa nối) | TTS-1.4 |
| `tests/transports/http/test_calls.py::test_audio_mode_is_not_implemented`, `tests/test_schema.py` (case 501) | Đổi kỳ vọng: 200 + `audio_url` đúng mẫu (fake TTS trong fixture) | Hai test đang khóa hành vi 501 — **A quyết**, B không tự sửa test của A |

Thứ tự trong handler: engine xong → `tts.synthesize` → `store.save` (ghi file xong) → dựng response. Đây là điểm bảo đảm §5.3 "âm thanh sẵn sàng ngay khi phản hồi trả về".

Phạm vi MVP: **audio ra** (bot nói). **Audio vào** (harness gửi `audio_url` của người gọi) là S-01/STT của A — chưa có; demo hôm nay gửi lượt người gọi bằng `text` trong một cuộc gọi `mode=audio`.

### 3.6 Đo (TTS-1.6) và demo (TTS-1.7) không cần A

- `scripts/tts_say.py "câu"` → `temp/tts/say.wav` + in `TTSTiming` (AC-1).
- `scripts/tts_bench.py` → lấy 20 câu **thật** từ `engine/dialogue/templates.py` (chào, hỏi tên/DOB, xác nhận lịch có ngày giờ, đề xuất slot, chuyển máy) → chạy tuần tự → in P50/P95 `ttfa_ms`, `total_ms` (+ ghi file) → dán vào evidence; cột "nghe lại: đọc sai?" điền tay.
- `scripts/tts_demo.py` → chạy `CallOrchestrator` với clinic mock thật (`.env`) hoặc `FakeClinicAPI`, kịch bản outbound confirm 4 lượt, mỗi `BotAction.utterance` → TTS → `AudioArtifactStore` → `temp/audio/<call_id>/<turn>.wav`. Đây là **đường demo dự phòng** nếu patch §3.5 chưa merge kịp; khi đã merge thì demo qua `uvicorn` + `curl`.

## 4. Lịch trong ngày

| Giờ | Việc | Đầu ra |
| --- | --- | --- |
| 0:00–0:30 | **TTS-1.1** tạo tài khoản ElevenLabs, lấy key; Voice Library lọc *Vietnamese* → chọn 1 voice đa ngôn ngữ, ghi `voice_id`; kiểm quota free (10k ký tự/tháng — bench 20 lượt ≈ 1,6k + demo ≈ 0,5k → đủ; hết thì Starter 5 USD) | `.env`; curl `/stream?output_format=pcm_8000` ra file nghe được |
| 0:30–2:30 | **TTS-1.2** `errors.py`, `TTSTiming`, `elevenlabs.py`; test `tests/speech/tts/test_elevenlabs.py` (fake WS: 3 chunk → gom đúng, ttfa ≤ total; 401/402→Rejected; 429/503/đóng bất thường→Unavailable; timeout→Unavailable; không có `websockets` trong `str(exc)`); `test_elevenlabs_live.py` skipif | AC-2, AC-3 |
| 2:30–3:00 | **TTS-1.3** settings + `create_tts` + `.env.example`; test `create_tts` với 3 cấu hình (none / elevenlabs đủ / elevenlabs thiếu key) | AC-4 |
| 3:00–3:45 | **TTS-1.6** `scripts/tts_say.py`, `scripts/tts_bench.py`; chạy 20 lượt; nghe lại, ghi câu đọc sai | AC-7 |
| 3:45–5:15 | **TTS-1.4/1.5** patch §3.5 trên nhánh `feature/tts-w1-mvp`, commit riêng "cần A review"; gửi A kèm 2 test cần đổi kỳ vọng | AC-5, AC-6 (khi A duyệt) |
| 5:15–6:00 | **TTS-1.7** `scripts/tts_demo.py`; README mục "Bật audio mode"; evidence `docs/evidence/tts-w1-mvp.md`; danh sách lỗi phát âm → đầu vào TTS-2.1 | AC-8 |
| Cắt lỗ | Nếu tới 16:00 A chưa phản hồi patch → demo bằng `tts_demo.py`, ghi rõ trong evidence "AC-5/6 chờ merge" | — |

## 5. File tạo / sửa

**B tự làm (không đụng file của A):**
- `src/callbot/speech/tts/errors.py` — mới
- `src/callbot/speech/tts/elevenlabs.py` — mới
- `src/callbot/speech/tts/base.py` — thêm `TTSTiming` (giữ `TTSProvider`, `NullTTS`)
- `src/callbot/speech/tts/__init__.py` — nhánh `elevenlabs`, export lỗi
- `src/callbot/speech/settings.py` — mở Literal, thêm `elevenlabs_*`
- `.env.example` — `ELEVENLABS_API_KEY=`, `ELEVENLABS_VOICE_ID=`, `ELEVENLABS_MODEL=eleven_flash_v2_5` (đã làm 18/9)
- `pyproject.toml` — thêm `websockets>=13` vào dependencies
- `tests/speech/tts/{__init__,test_elevenlabs,test_create_tts,test_elevenlabs_live}.py` — mới
- `scripts/tts_say.py`, `scripts/tts_bench.py`, `scripts/tts_demo.py` — mới (thư mục `scripts/` chưa có)
- `README.md` mục "Bật audio mode"; `docs/evidence/tts-w1-mvp.md`

**Patch chờ A duyệt (commit riêng):** `engine/types.py`, `transports/http/main.py`, `transports/http/calls.py`, 2 test ở §3.5.

## 6. Ngoài phạm vi hôm nay (đúng kế hoạch §4)

Chuẩn hoá số → chữ (TTS-2.2), cache câu cố định (TTS-3.2), fallback provider/timeout 2,5 s (TTS-3.1), cancel giữa chừng và WS multi-context (TTS-4.2), STT cho `/turn` audio (S-01, A), deploy prod (R-03, A), trace per-turn vào JSONL (R-02, A — hôm nay chỉ log `TTSTiming` ở mức INFO).

## 7. Rủi ro riêng của hôm nay

| Rủi ro | Xử lý |
| --- | --- |
| WS `stream-input` trục trặc (proxy chặn WSS, thông điệp lỗi lạ) | Kế hoạch §4: chuyển tạm HTTP `/stream` cùng model/format, giữ interface |
| ElevenLabs không cấp key / chặn vùng | Kế hoạch §4: chuyển Azure F0 REST cùng interface — `elevenlabs.py` viết theo mẫu `stream()/synthesize()` để `azure.py` chép lại được trong 1 giờ |
| Voice đa ngôn ngữ đọc tiếng Việt lơ lớ | Chấp nhận cho MVP; ghi vào danh sách lỗi → bake-off tuần 2 quyết định (ADR-002 tiêu chí 1) |
| A không kịp duyệt patch HTTP trong ngày | Demo qua `tts_demo.py`; AC-5/6 ghi "chờ merge" trong evidence; không tự sửa test của A |
| `.env` local `SAMPLE_RATE≠8000` làm `tests/speech/test_narrowband.py` fail (đã thấy trước đó) | Giữ `SAMPLE_RATE=8000`; không liên quan TTS |
| Free tier đòi ghi attribution / không dùng thương mại | Chỉ demo nội bộ tuần 1; quyết định gói trả phí ở TTS-2.6 |

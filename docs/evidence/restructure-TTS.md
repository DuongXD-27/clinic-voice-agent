# Evidence: TTS — Vbee làm provider chính, ElevenLabs dự phòng; gộp về một thư mục `tts`

## Mục tiêu

Chuẩn bị luồng audio đơn giản để demo cho mentor (giai đoạn 0), đồng thời dọn phần TTS bị tách đôi:

- **Rà soát luồng TTS hiện tại** và cấu hình bản deploy (server đang chạy `TTS_PROVIDER=elevenlabs`, đặt tay trong `/opt/callbot/.env`, repo không phản ánh).
- **Vbee làm provider chính, ElevenLabs dự phòng**: Vbee lỗi hoặc chậm thì gateway tự gọi ElevenLabs trong cùng lượt. Chọn Vbee theo benchmark 23/9 (PCM 8 kHz, 12/12 thành công, TTFA P95 786 ms so với 1.523 ms của ElevenLabs).
- **Gộp hai thư mục `tts`** (`src/inference/tts/` và `src/speech/tts/`) thành một: chỉ còn `src/inference/tts/`.
- Không đổi kiến trúc HTTP turn-based; tối ưu streaming để giai đoạn 2.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Adapter Vbee cùng interface `TTSProvider` | `src/inference/tts/providers/vbee.py` — `VbeeTTS.synthesize(text) -> TTSResult`: `POST https://api.vbee.vn/v1/tts`, `mode=sync`, `outputFormat=pcm`, `sampleRate=8000`, header `Authorization: Bearer` + `App-id`; trả PCM16 8 kHz, không resample |
| Vbee có trần thời gian tổng, không chỉ timeout từng pha | `VbeeTTS.synthesize` giữ `deadline` khi đọc từng chunk; `VBEE_TIMEOUT_S` mặc định 3,0 s (`VbeeTTSConfig`) |
| Phân loại lỗi Vbee giống ElevenLabs | 429/5xx, timeout, lỗi mạng, JSON thay vì audio, audio rỗng → `TTSUnavailable`; 4xx khác, text > 300 ký tự → `TTSRejected`. Message không chứa token hay text — `test_http_status_is_classified`, `test_json_body_on_200_is_unavailable`, `test_timeout_and_network_errors_are_unavailable`, `test_text_over_limit_is_rejected_without_request` |
| Lỗi TTS dùng chung cho mọi provider | `src/inference/tts/errors.py` (`TTSError`, `TTSUnavailable`, `TTSRejected`) tách từ `elevenlabs.py`; `elevenlabs.py` import lại nên đường import cũ vẫn chạy |
| Fallback một bước trong gateway | `TTSGateway(fallback=...)` trong `src/inference/tts/gateway.py`: provider chính raise bất kỳ lỗi nào → log `provider + loại lỗi + code` (không log text) → gọi dự phòng đúng một lần; dự phòng cũng lỗi thì ném lỗi của dự phòng — `test_primary_error_falls_back_once_and_logs_code_not_text`, `test_fallback_error_propagates`, `test_unexpected_exception_also_falls_back` |
| Chọn fallback bằng cấu hình | `TTS_FALLBACK_PROVIDER` → `SpeechSettings.tts_fallback_provider` (rỗng = tắt) → `create_tts_gateway(provider, fallback=...)`; trùng provider chính thì bỏ qua — `test_speech_settings_reads_fallback_provider`, `test_create_tts_gateway_builds_vbee_with_elevenlabs_fallback`, `test_fallback_same_as_primary_is_ignored` |
| Thiếu key của dự phòng thì báo ngay lúc khởi động | `create_tts_gateway` dựng cả provider dự phòng → `ValueError` — `test_missing_fallback_credentials_fail_at_build` |
| Log khởi động cho biết đang dùng provider nào | `build_speech_bundle` log `ASR ..., TTS vbee (<voice>), TTS fallback elevenlabs (eleven_flash_v2_5)` |
| Chỉ còn một thư mục `tts` | `src/speech/tts/` đã xoá: `storage.py` → `src/speech/audio/storage.py` (lưu cả WAV của TTS lẫn clip `demo-input/`, không riêng TTS); `Synthesizer` + `SpeechSynthesizer` (bọc PCM thành `AudioSegment`) gộp vào `src/speech/bundle.py` |
| Không đổi hành vi HTTP | `calls.py` / `main.py` không sửa; toàn bộ test transport pass |

## File liên quan

- `src/inference/tts/providers/vbee.py` — mới
- `src/inference/tts/errors.py` — mới
- `src/inference/tts/gateway.py`, `config.py`, `base.py`, `providers/elevenlabs.py`
- `src/speech/bundle.py`, `src/speech/settings.py`, `src/speech/__init__.py`
- `src/speech/audio/storage.py` — chuyển từ `src/speech/tts/storage.py`
- `src/speech/tts/` — xoá
- `scripts/tts_say.py` — thêm `--provider vbee`
- `.env.example`, `README.md`, `docker-compose.prod.yml` (chú thích)
- `tests/inference/tts/providers/test_vbee.py` — mới
- `tests/inference/tts/test_gateway_fallback.py` — mới
- `tests/speech/test_asr_tts_gateway.py`, `tests/speech/test_audio_storage.py`, `tests/transports/http/fakes.py` — đổi import

## Luồng hiện tại

Vẫn là HTTP turn-based. WebSocket chỉ có ở chặng bot → ElevenLabs; audio được gom đủ câu rồi ghi WAV, harness tải qua `audio_url`.

```text
POST /v1/calls/{id}/turn  (mode=audio)
  -> ASR ZipFormer -> engine -> utterance (text)
  -> calls._synthesize -> SpeechSynthesizer (speech/bundle.py)
  -> TTSGateway (inference/tts/gateway.py)
       -> VbeeTTS: HTTP POST, nhận chunk PCM 8 kHz, gom đủ, trần 3 s
          lỗi / chậm / text > 300 ký tự
            -> log "TTS vbee lỗi [TTSUnavailable timeout], chuyển sang elevenlabs"
            -> ElevenLabsTTS: WebSocket stream-input, gom đủ, trần 4 s
  -> AudioSegment -> AudioArtifactStore.save (speech/audio/storage.py)
       -> <AUDIO_DIR>/<call_id>/<turn>.wav
  -> response {utterance, audio_url}; harness GET /audio/<call_id>/<turn>.wav
     (cả hai TTS cùng lỗi -> audio_url=null, lượt vẫn trả utterance)
```

Cấu trúc sau khi gộp:

```text
src/inference/tts/            thư mục TTS duy nhất: text -> PCM của provider
├── base.py                   TTSProvider, TTSResult, ProviderName (openai | elevenlabs | vbee)
├── errors.py                 TTSError / TTSUnavailable / TTSRejected
├── config.py                 OpenAI / ElevenLabs / Vbee config
├── gateway.py                TTSGateway + fallback, create_tts_gateway
└── providers/                openai.py, elevenlabs.py, vbee.py
src/speech/
├── audio/storage.py          AudioArtifactStore (WAV cho audio_url + clip demo)
├── asr/                      giữ nguyên (VAD, pipeline, resample — có logic riêng)
└── bundle.py                 SpeechBundle + SpeechSynthesizer
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`).

```powershell
make check
```

Chỉ chạy test TTS: `python -m pytest tests\inference tests\speech -q`

Thử Vbee thật (cần `VBEE_API_TOKEN`, `VBEE_APP_ID` trong `callbot-vinmec/.env`):

```powershell
python scripts/tts_say.py "Dạ em chào anh, em gọi từ Vinmec." --provider vbee --out temp/tts/vbee.wav
```

## Kết quả xác minh cục bộ (2026-09-24)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | Pass (2201 passed, 28 skipped) |
| `python scripts/tts_say.py ... --provider vbee` (Vbee thật, 4 lần, mỗi lần một process mới) | Pass — câu 98 ký tự: 2.421 / 1.417 / 1.304 ms; câu 40 ký tự: 1.041 ms; PCM 8 kHz, 5,6 s audio |

## Ghi chú

- **Deploy (giai đoạn 0) — việc người vận hành làm trên EC2**, không qua CD vì CD không ghi đè `/opt/callbot/.env`:
  1. Thêm vào `/opt/callbot/.env`: `TTS_PROVIDER=vbee`, `TTS_FALLBACK_PROVIDER=elevenlabs`, `VBEE_API_TOKEN`, `VBEE_APP_ID`, (tuỳ chọn) `VBEE_VOICE_CODE`. Giữ nguyên `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` đang có.
  2. Nên đặt `ELEVENLABS_TIMEOUT_S=3.0`: trường hợp xấu nhất là Vbee 3 s + ElevenLabs 3 s = 6 s, còn khoảng 2 s cho ASR, engine và tải WAV trong trần 8 s/lượt (contract). Với 4 s mặc định thì là 7 s, quá sát.
  3. Deploy image mới rồi chạy `docker compose --env-file .env --env-file image.env up -d`; xác nhận bằng `logs bot | grep "TTS fallback"`.
  4. Thiếu key của provider chính hoặc dự phòng thì app **không khởi động** (smoke test `/ready` của CD sẽ fail) — cố ý, để không lặng lẽ chạy thiếu dự phòng.
- **Độ trễ**: mỗi câu vẫn mở một kết nối mới (HTTP với Vbee, WebSocket với ElevenLabs) và gom đủ audio mới trả, nên harness thấy tổng thời gian chứ không phải TTFA. Đo local 1,0–2,4 s/câu với Vbee, lượt đầu chậm nhất. Nếu log trên server hay có fallback do `timeout`, tăng `VBEE_TIMEOUT_S` hoặc làm giai đoạn 2.
- **Giới hạn Vbee**: text tối đa 300 ký tự; câu dài hơn chuyển thẳng sang ElevenLabs (không cắt câu).
- **Dữ liệu cá nhân**: khi fallback, tên/ngày sinh trong câu vẫn đi ra server ElevenLabs ở nước ngoài — vẫn chờ PM/pháp chế xác nhận (ADR-002 §6). Gateway và adapter không log text.
- **Tài liệu cũ** trong `docs/plans/` (`tts-w1-mvp.md`, kế hoạch 6 tuần) còn nhắc `speech/tts/...`: đó là kế hoạch lịch sử, không sửa. Còn `docs/reference/ai-callbot-architecture.md:356` và `docs/reference/stt-flow.md:111` vẫn ghi "chỉ OpenAI TTS", cần cập nhật ở lượt sau.
- **Giai đoạn 2 (chưa làm)**: giữ kết nối để dùng lại giữa các câu (bỏ chi phí mở kết nối mỗi câu), stream chunk tới client khi có Phone Adapter/WebSocket (tuần 5), chạy song song hoặc hedge thay vì fallback tuần tự nếu cần hạ P95.

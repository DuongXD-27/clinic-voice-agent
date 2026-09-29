# Evidence: API thử chất lượng STT cho PM (`/v1/stt/turn`, `/v1/stt/transcribe`)

## Mục tiêu

PM cần tự kiểm tra chất lượng STT mà không phải mở cuộc gọi: gửi một file WAV (qua link hoặc upload) và nhận lại transcript, confidence và latency của từng bước. Trước ngày 29/09 chưa có cách nào làm được việc này:

- `/v1/calls/{call_id}/turn` bắt buộc phải mở cuộc gọi, không trả confidence, cũng không trả latency.
- ZipFormer có tính confidence nhưng `transcribe()` bỏ đi.

**Phạm vi:**
- **Một lượt nói** (`/v1/stt/turn`): yêu cầu chính, chốt cuối ngày. Mỗi file là một câu trả lời, giống `audio_url` của `/v1/calls` turn.
- **File dài nhiều câu** (`/v1/stt/transcribe`): làm trước trong ngày, vẫn giữ lại cho bản ghi cả cuộc gọi.
- Tiền xử lý audio có đo đạc, và giải thích lý do từng bước.
- Không tính WER trong API: PM tự so kết quả.

Mô tả API cho PM: [stt-eval-api.md](../reference/stt-eval-api.md).

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| API một lượt nói nhận link hoặc upload, trả `text`, `confidence`, latency từng bước | `turn_url`, `turn_upload` trong `src/callbot/transports/http/stt_eval.py` gọi `transcribe_turn` (`src/speech/asr/offline.py`), nhận dạng nguyên clip một lần. Test: `test_turn_upload_returns_transcript_and_production`, `test_turn_url_is_downloaded` (`tests/transports/http/test_stt_eval.py`), `test_turn_decodes_whole_clip_once_at_model_rate` (`tests/speech/test_offline_stt.py`) |
| `compare=true` trả bản `production` xử lý y hệt `/v1/calls` turn | `transcribe_turn` đưa clip gốc, giữ tần số gốc (như `load_from_url` → `read_wav`), vào cùng `SpeechRecognizer`. Test: `test_turn_production_follows_calls_turn_path_at_source_rate` |
| API file dài: VAD cắt câu, trả `segments` có mốc thời gian | `transcribe_url`, `transcribe_upload` gọi `transcribe_offline`, dùng `detect_speech_frames` và `speech_regions` (`src/speech/audio/preprocess.py`). Test: `test_speech_is_segmented_and_decoded_at_model_rate`, `test_confidence_is_weighted_by_word_count`, `test_speech_regions_merge_close_speech_and_pad` |
| Confidence thật từ ZipFormer | `ZipFormerASR.transcribe()` trả `ASRResult(text, confidence)` từ `_decode_scored` (`src/inference/asr/providers/zipformer.py`). Test: `test_zipformer_transcribe_returns_token_confidence` (`tests/speech/test_asr_tts_gateway.py`) |
| Đọc được WAV 8/16/24/32-bit, float, A-law, μ-law, EXTENSIBLE, giữ tần số gốc | `read_wav` + `WavInfo` trong `src/speech/audio/codec.py`; `decode_wav` đi qua `read_wav`. Test: `tests/speech/audio/test_read_wav.py` (7 test) |
| Tiền xử lý: bỏ DC, resample một lần về 16 kHz, khuếch đại khi giọng dưới −35 dBFS (tối đa +20 dB, đỉnh ≤ −1 dBFS) | `remove_dc`, `measure_level`, `normalize_gain` trong `preprocess.py`; `_prepare` trong `offline.py`. Test: `test_quiet_file_is_boosted_towards_target`, `test_gain_is_capped_at_20_db`, `test_normal_level_file_is_untouched`, `test_gain_never_creates_clipping`, `test_turn_boosts_quiet_clip` |
| Không làm server OOM: mỗi lần decode ≤ 30 s, turn ≤ 30 s, file dài ≤ 5 phút | `split_long_regions` (chia tại frame yên nhất), `MAX_SEGMENT_MS`, `MAX_TURN_MS`, `MAX_DURATION_MS`. Test: `test_long_region_is_split_at_quietest_frame`, `test_split_never_exceeds_max_length`, `test_no_decode_is_longer_than_30_seconds`, `test_turn_longer_than_30_seconds_is_rejected` |
| Chỉ bật khi cần và luôn có API key | Cờ `stt_eval_enabled` (env `STT_EVAL_ENABLED`, mặc định tắt); validator bắt buộc `BOT_API_KEYS` (`src/callbot/transports/http/config.py`). Router mount kèm `require_api_key` (`main.py`). Test: `test_routes_are_not_mounted_by_default`, `test_enabling_requires_bot_api_keys`, `test_bearer_key_is_required_when_configured`, `test_turn_requires_bearer_key` |
| Không bị SSRF, giới hạn dung lượng | `_check_url_allowed` chặn scheme lạ và IP không public (kiểm lại ở mỗi redirect, tối đa 3 lần); `_read_limited` giới hạn 25 MiB. Test: `test_non_public_urls_are_rejected`, `test_hostname_resolving_to_private_ip_is_rejected`, `test_redirect_to_private_ip_is_rejected`, `test_oversized_audio_is_rejected`, `test_upstream_errors_are_mapped` |
| Không làm lệch dashboard STT production | `stt_eval.py` không tạo trace (không gọi `Tracer`) |
| Hợp đồng API cho UI cập nhật | `scripts/export_openapi.py` bật router khi xuất; `ui/openapi.json` và `ui/src/lib/api/schema.d.ts` đã sinh lại, `export_openapi.py --check` pass |

## File liên quan

- `src/callbot/transports/http/stt_eval.py` (mới): router, schema, tải link an toàn
- `src/speech/asr/offline.py` (mới): `transcribe_turn`, `transcribe_offline`
- `src/speech/audio/preprocess.py` (mới): đo mức âm, bỏ DC, khuếch đại, VAD region, chia đoạn dài, SNR
- `src/speech/audio/codec.py`: `read_wav`, `WavInfo`
- `src/inference/asr/providers/zipformer.py`: `transcribe()` trả confidence
- `src/callbot/transports/http/config.py`, `src/callbot/transports/http/main.py`: cờ và mount router
- `pyproject.toml`: thêm `python-multipart` (upload multipart)
- `eval/stt-bench/adapters/gipformer_preprocessed.py` (mới): adapter bench cho hai chế độ
- `tests/speech/audio/test_read_wav.py`, `tests/speech/audio/test_preprocess.py`, `tests/speech/test_offline_stt.py`, `tests/transports/http/test_stt_eval.py` (mới, 53 test)
- `docs/reference/stt-eval-api.md` (mới); `README.md`, `docs/reference/http-api.md`, `.env.example`

## Luồng hiện tại

```text
POST /v1/stt/turn[/upload]  (file ≤ 25 MiB)
  -> tải link (chặn IP nội bộ) hoặc đọc upload
  -> read_wav: PCM16 mono ở tần số gốc + WavInfo              (clip > 30 s -> 422 AUDIO_TOO_LONG)
  -> [telephone_band] hạ 8 kHz -> bỏ DC -> resample 16 kHz -> khuếch đại nếu < −35 dBFS
  -> ZipFormer decode nguyên clip: text, confidence
  -> [compare] clip gốc ở tần số gốc -> ZipFormer (y hệt /v1/calls turn): production
  -> SttTurnResponse: text, confidence, production, model, audio, preprocessing, latency_ms, warnings

POST /v1/stt/transcribe[/upload]  (file ≤ 5 phút)
  -> cùng bước đọc + tiền xử lý
  -> Silero VAD: gộp đoạn cách < 0,7 s, đệm 1 s / 0,3 s, chia đoạn > 30 s tại frame yên nhất
  -> ZipFormer decode từng đoạn -> ghép text; segments[] có mốc thời gian
  -> [compare] nguyên file không tiền xử lý (chia khúc ≤ 30 s): raw
```

## Số đo

Cách đo:
- **Dữ liệu:** 40 câu golden `eval/stt-bench/golden-cases.yaml` (8 kHz, mỗi câu 3–6 s); thêm hai bản nhỏ tiếng −15 dB và −25 dB.
- **Model:** gipformer1.5-68M-rnnt, VAD Silero.
- **Chỉ số:** mean WER theo âm tiết, dùng `calculate_wer` của `evaluate.py`.
- **Baseline:** đúng đường `/v1/calls` turn (nâng lên 16 kHz, decode nguyên clip, không tiền xử lý).

**Lượt 1: khuếch đại mọi file về −20 dBFS.**

| Biến thể | Mức gốc | −25 dB |
|---|---|---|
| Baseline | 0,390 | 0,468 |
| Bỏ DC + khuếch đại, nguyên file | 0,400 | 0,379 |
| + VAD, đệm trước 500 ms | 0,411 | 0,412 |
| + VAD, đệm trước 1000 ms | 0,395 | 0,350 |

- Khuếch đại file vốn đã đủ to làm 3 câu tệ đi. Ví dụ STT_ID_09: "ĐỖ ĐỨC DŨNG" thành "ĐỖ BÍCH DŨNG".
- Đệm 500 ms làm mất chữ đầu: "Vâng," của STT_CF_02 bị Silero bật cờ trễ khoảng 0,7 s.

**Lượt 2 (cấu hình chốt): chỉ khuếch đại khi giọng dưới −35 dBFS, đưa về −26 dBFS.**

| Biến thể | Mức gốc | −15 dB | −25 dB |
|---|---|---|---|
| Baseline | 0,390 | 0,417 | 0,468 |
| **Khuếch đại khi nhỏ (+20 dB), nguyên clip — `/v1/stt/turn`** | **0,389** | **0,383** | **0,379** |
| Khuếch đại khi nhỏ (+30 dB), nguyên clip | 0,389 | 0,383 | 0,391 |
| **+ VAD đệm 1000/300 ms — `/v1/stt/transcribe`** | **0,392** | **0,330** | **0,350** |

**Bench chính thức qua `evaluate.py` (mức gốc):**

| | Baseline | `/v1/stt/turn` | `/v1/stt/transcribe` |
|---|---|---|---|
| Mean WER | 0,390 | 0,389 | 0,392 |
| Số câu pass | 19/40 | 19/40 | 19/40 |
| Latency median / p95 | 68 / 139 ms | 69 / 105 ms | 79 / 121 ms |

**Bộ nhớ của một lần decode nguyên đoạn** (ZipFormer offline, peak RSS). Đây là lý do cần giới hạn 30 s:

| Độ dài | 15 s | 30 s | 60 s | 90 s | 180 s (ngoại suy) |
|---|---|---|---|---|---|
| Peak RAM | 0,35 GB | 0,56 GB | 1,5 GB | 3,1 GB | khoảng 12 GB |

**Chạy thử 133 file LiveKit** (`temp/audio`, chế độ nhiều câu, `compare=true`):
- Lượt đầu bị OOM ở file dài 182 s; sau khi thêm giới hạn 30 s thì cả 133 file chạy xong, peak RAM server 0,94 GB.
- 128 file thành công. 5 file bị từ chối đúng thiết kế: 2 file dài hơn 5 phút, 2 file chỉ có header, 1 file rỗng.
- Thời gian ASR median 188 ms/file, real-time factor median 0,0042.
- Kết quả đầy đủ nằm trong `temp/stt_eval_livekit/`, không commit vì chứa giọng nói thật.

**Ví dụ thật qua server** (`/v1/stt/turn/upload`, `compare=true`), câu "Tôi tên Nguyễn Hoàng Minh" ở dạng 44,1 kHz stereo 24-bit, nhỏ hơn 25 dB:
- `production`: "TÔI SẼ NGHĨA VÀO BÊN" (confidence 0,63; trước khi `/v1/calls` bỏ bước hạ 8 kHz là "TÔI SẼ NỮA VÀO BÊN", 0,61).
- `text`: "TÔI TÊN NGUYỄN HOÀNG MINH" (confidence 0,88, khuếch đại +20 dB).

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`).

```powershell
make check
```

`make check` chạy lần lượt (giống bước test trên CI):

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
python scripts/export_openapi.py --check
```

Chỉ chạy test của phần liên quan:

```powershell
python -m pytest tests/speech/audio tests/speech/test_offline_stt.py tests/transports/http/test_stt_eval.py -q
```

Bench (cần model ZipFormer và Silero thật, chạy từ thư mục gốc repo):

```powershell
python eval/stt-bench/evaluate.py --adapter adapters.gipformer_preprocessed:turn_adapter
python eval/stt-bench/evaluate.py --adapter adapters.gipformer_preprocessed:adapter
```

Chạy thật: đặt `STT_EVAL_ENABLED=true` và `BOT_API_KEYS=sk_...`, chạy `uvicorn callbot.transports.http.main:app`, mở `/docs`, mục **stt-eval**.

## Kết quả xác minh cục bộ (2026-09-29)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | Pass (2728 passed, 6 skipped) |
| `python scripts/export_openapi.py --check` | Pass |
| `make check` | Pass |
| Bench `turn_adapter` / `adapter` trên 40 câu golden | WER 0,389 / 0,392 (baseline 0,390) |
| Chạy thật qua server (upload, link bị chặn, thiếu key, clip > 30 s) | Đúng như thiết kế |

## Ghi chú

- **Ảnh hưởng tới đường `/v1/calls` (ngoài API mới):**
  - `decode_wav` giờ nhận thêm WAV 24/32-bit, float và EXTENSIBLE. Kết quả với PCM16 và G.711 không đổi.
  - `ZipFormerASR.transcribe()` giờ trả confidence, nên `CallerInput.asr_confidence` không còn `None`. Hiện chưa có code nào đọc trường này.
- **Đường `/v1/calls` turn giữ nguyên** (quyết định ngày 29/09): mỗi clip chỉ là một lượt ngắn. Vẫn chưa có giới hạn độ dài clip; một clip bất thường dài vài phút có thể gây OOM.
- **Chưa đo được lợi ích của việc resample thẳng 16 kHz** với file wideband, vì bộ golden chỉ có file 8 kHz.
- **Dependency mới:** `python-multipart` được khai báo ở base dependencies; chưa cập nhật `uv.lock`.
- **Phát hiện từ 133 file LiveKit, cần PM nghe lại** (chi tiết trong `temp/stt_eval_livekit/summary.md`):
  - 13 file VAD không thấy giọng, trong khi bản `raw` ra đúng một từ ngắn.
  - File `8127ef7e` cho thấy tiếng bot lọt vào mic người gọi (echo).
- Chưa commit.

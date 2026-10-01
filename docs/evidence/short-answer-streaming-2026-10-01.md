# Evidence: câu trả lời ngắn trên đường streaming — SNR ngắt lời và mất chữ đầu (PR2a)

## Bối cảnh

Cuộc gọi thử bằng trình duyệt ngày 01/10 có ghi âm (`LIVEKIT_DEBUG_DUMP_AUDIO=1`), mic và loa laptop, không tai nghe. Cuộc gọi kết thúc bằng chuyển máy vì câu trả lời đồng ý 3 từ hỏng ba lần liên tiếp. Phân tích từng frame (xem `speech-diagnostics-2026-10-01.md`) cho thấy ba điểm yếu với câu ngắn. PR này sửa hai điểm:

| # | Điểm yếu | Xử lý |
| --- | --- | --- |
| (a) | Nhánh ngắt lời đo SNR theo frame, nền bị đầu câu kéo lên: 3,0 dB, trong khi cùng câu đó ở lượt thường đo 55 dB | Sửa, bật ngay |
| (b) | Silero (sherpa) cần 250 ms giọng liên tục; một chỗ tụt 30 ms làm nó đếm lại và báo trễ 0,6 s. Pre-speech 300 ms của ASR không còn chứa chữ đầu | Thêm `asr_voice_lookback_ms`, **mặc định tắt** |
| (c) | Câu nói lúc bot đang nói bị bỏ khi bot dứt lời | Chưa làm: cần số đo tiếng vọng trước |

## (a) Nhánh ngắt lời dùng SNR cả câu

`STTPipeline.stream` đưa `UtteranceEvidenceTracker` (sửa 26/09 cho TurnController) cho cả `InterruptionController`, thay cho SNR theo frame của `NoiseTracker`. Lý do không áp dụng cho ngắt lời từ 26/09 chỉ là giới hạn phạm vi lần sửa đó, không phải lựa chọn có số đo.

Ảnh hưởng: cổng `interruption_min_snr_db` và luật `low_snr_short` của Validator trong nhánh ngắt lời giờ đọc cùng số với lượt thường. Câu ngắn 1–2 từ ("dạ", "có") lúc bot nói không còn bị chặn vì SNR giả thấp.

Test: `test_barge_in_reads_snr_of_the_utterance_not_of_the_latest_frame` (tests/speech/test_pipeline_validator.py). Thay tracker bằng bản trả SNR theo frame thì test thất bại (SNR ~12 dB, ngưỡng kiểm > 40 dB).

noise-bench không mô phỏng bot nói nên không đo được (a); bộ đo cho ra kết quả trùng PR1 (0/81 trial khác trên bộ `short`).

## (b) Pre-speech lùi theo giọng

`_PreSpeech` (`src/inference/asr/providers/zipformer.py`):
- Mặc định giữ đúng 300 ms cuối như trước (byte-for-byte).
- Bật `asr_voice_lookback_ms` (> 0): nếu giọng liền mạch đã bắt đầu trước cửa sổ 300 ms thì lùi thêm qua các frame có giọng, tối đa chừng ấy ms, cộng 90 ms đệm cho phụ âm đầu.
  - "Có giọng" = xác suất Silero thô ≥ 0,5. Chỗ tụt ≤ 60 ms vẫn coi là liền câu.
  - Không lùi qua im lặng hay tiếng động. Lấy cố định 600 ms từng làm model bịa chữ (người phát triển đã thử và quay về 300 ms).
- Xác suất thô do probe Silero trong `SharedSpeechDetector` tính, mỗi frame một lần. Probe này trước đây chạy riêng cho chẩn đoán; nay chẩn đoán đọc lại từ detector, nên không tốn thêm suy luận.
- `TURN_ACCEPTED` / `TURN_DROPPED` có thêm `asr_lookback_ms`: biết khi nào cơ chế này kích hoạt trên cuộc gọi thật.

Test: `tests/speech/test_zipformer_stream.py`
- `test_voice_lookback_recovers_first_word_the_detector_reported_late`: tái hiện mẫu xác suất của cuộc gọi 01/10.
- `test_voice_lookback_keeps_fixed_window_when_voice_starts_inside_it`: trường hợp thường, không lấy thêm gì.
- `test_voice_lookback_is_capped`.

## Số đo

### Không đổi hành vi khi tắt

`--diff` giữa PR1 và bản này khi tắt (`asr_voice_lookback_ms=0`): short **0/81**, web **0/150**, golden **0/135** trial khác. Việc chuyển probe vào bộ phân loại dùng chung không đổi kết quả nào.

### noise-bench, profile `target`, so với tắt

Ba cấu hình: tắt, lùi theo giọng tối đa 300 ms, và pre-speech **cố định 600 ms**. Cấu hình cuối chỉ làm mốc, để tái hiện cách đã thử trước đây.

| Bộ / điều kiện | Lùi theo giọng 300 ms | Cố định 600 ms |
| --- | --- | --- |
| golden sạch (37, có nhãn) | 1 trial khác: "Không, tôi không đến được" từ `KHÔNG ĐẾN ĐƯỢC` thành `TÔI KHÔNG ĐẾN ĐƯỢC`. `wer_golden` 0,120 → **0,113** | 5 khác, `wer_turn` 0,113 → 0,120, 1 câu bị tách đôi |
| golden office@8 | **0/49** | 14/49 khác, `wer_golden` 0,213 → 0,133 |
| golden babble@6 | 5/49 khác, `wer_golden` 1,887 → 1,860 | 39/49 khác, 1,887 → 2,007 |
| web sạch (42) | 2 khác, `wer_drift` không đổi (0,036) | 6 khác, **mất 1 lượt** |
| web office@8 | **0/54** | 18/54 khác, `wer_drift` 0,095 → **0,131** |
| web babble@6 | 5/54 khác, `wer_drift` 1,445 → 1,460 | 46/54 khác, 1,445 → 1,511 |
| short sạch / office@8 | **0/19**, **0/31** | 6/19 khác (có "Ừ" thành "ĐÂY"), 4/31 khác |
| short babble@6 | 3/31 khác, lượt giả không đổi | 28/31 khác, lượt giả 10 → 12 |

Lấy cố định 600 ms đổi chữ ở gần như mọi điều kiện, đúng như lần thử trước. Lùi theo giọng không đổi gì ở office và gần như không đổi ở audio sạch. Thay đổi tập trung ở babble, nơi giọng người khác ngay trước câu cũng được Silero chấm là có giọng.

### Phát lại 134 cuộc gọi thật (118 phút, bản ghi LiveKit 16 kHz)

- Cơ chế bật ở 37 đoạn (27 thành lượt), lùi 120–300 ms. Số lượt 466 → 464.
- 18 thay đổi trên 17 cuộc gọi:
  - Nhiều ca lấy lại chữ đầu: `LỊCH GIÚP ANH` → `ĐẶT LỊCH GIÚP ANH`; `RỒI LÀ NGUYỄN VĂN A` → `TÔI LÀ NGUYỄN VĂN A`; `XÁC NHẬN LỊCH` → `TÔI XÁC NHẬN LỊCH`; `KHUNG KHÁC KHÔNG EM` → `CÒN KHUNG KHÁC KHÔNG EM`; cuộc gọi 01/10 `EM NHÉ` → `ĐƯỢC EM NHÉ`.
  - Chưa rõ đúng sai, cần nghe lại:
    - ba câu một từ đổi thành từ đệm và bị bộ lọc từ đệm bỏ (`ĐƯỢC` → `Ừ`, `OK` → `Ừ`, `LÀ` → `DẠ`);
    - một đoạn trước đây bị bỏ vì `oscillating` nay ra lượt `ĐÂY`;
    - vài câu đổi chữ ở phần đầu.
- Trang nghe so sánh: `temp/audio/lookback-review/index.html` (18 clip, chỉ local; `temp/` không commit).

### Quyết định

- (a) bật ngay.
- (b) để **tắt**. Chỉ bật (`asr_voice_lookback_ms: 300`) sau khi người nghe xác nhận các ca chưa rõ ở trên. Cơ chế làm đúng việc ở các ca mất chữ đầu đã thấy; rủi ro còn lại là câu một từ đổi nghĩa và giọng nền.

## Kết quả xác minh cục bộ

| Command | Kết quả |
| --- | --- |
| `make check` | Pass: 3510 passed, 6 skipped; OpenAPI khớp |
| noise-bench `--diff` khi tắt, so với PR1 | 0/366 trial khác |

## File liên quan

- `src/speech/asr/pipeline.py`: (a); chuyển xác suất của detector cho chẩn đoán.
- `src/speech/asr/vad/shared.py`: probe Silero thô trong bộ phân loại dùng chung.
- `src/inference/asr/providers/zipformer.py`: `_PreSpeech`.
- `src/speech/bundle.py`, `src/speech/settings.py`, `config/speech.yaml`: `asr_voice_lookback_ms`.
- `src/speech/diagnostics.py`: `asr_lookback_ms`; nhận xác suất tính sẵn.
- `src/speech/asr/vad/silero_probe.py`: `VOICE_PROBABILITY`.
- `src/callbot/transports/livekit/worker.py`, `eval/noise-bench/bench.py`: probe riêng cho chẩn đoán chỉ khi không dùng detector chung.
- `docs/reference/livekit-audio-architecture-2026-09-28.md`.

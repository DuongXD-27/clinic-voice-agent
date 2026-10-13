# Evidence: Gom đoạn ASR thành lượt, gate echo, fallback Gemini; từ đáp và giữ lượt bị từ chối — 06/10/2026

## Mục tiêu

Sửa các lỗi của lớp xử lý quanh ASR đã có bằng chứng trực tiếp, cho cả ZipFormer (gipformer1.5)
lẫn Gemini Live. Mọi đề xuất đổi hành vi mặc định đều được đo bằng `eval/noise-bench`; thứ gì
làm xấu bất kỳ chỉ số nào thì không giữ — code của nó đã gỡ, chỉ còn kết quả đo ở đây.

| # | Đề xuất | Kết quả |
|---|---|---|
| 1 | Nối đoạn ASR vào lượt đang dở; nhận final tới muộn của đoạn trước (Gemini) | **Giữ** — sửa lỗi mất tên 06/10; ZipFormer không đổi số đo |
| 2 | Gate echo so theo cửa sổ từ thay cho `partial_ratio` ký tự | **Giữ** — sửa 0/12 lần ngắt lời được xác nhận ngày 06/10 |
| 3 | Fallback ZipFormer cho đoạn Gemini lỗi | **Giữ** — trước đây lỗi làm hỏng cả luồng STT |
| 4 | Pre-roll cấu hình được (`pre_speech_ms`) | **Giữ, mặc định 300 ms** — dài hơn chỉ có lợi ở bộ 8 kHz |
| 5 | Lấy hết hàng đợi đoạn nói của sherpa VAD; `AsyncStreamingVAD` đếm theo `frame_ms` thật | **Giữ** — sửa lỗi, không đổi số đo |
| 6 | Cho "ừ/ờ/dạ" thành lượt khi SNR đoạn nói đủ cao | **Từ chối, đã gỡ** — mọi ngưỡng đều lọt "Ừ" giả (đồng ý giả) |
| 7 | Giữ lượt sau final theo state engine | **Từ chối, đã gỡ** — giọng nền làm lượt không bao giờ chốt |
| 8 | Silero `min_speech_duration` 120 ms | **Từ chối, đã gỡ** — không có lợi trên bộ có nhãn, babble xấu đi |

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Một lượt gồm nhiều đoạn ASR; final tới muộn của đoạn trước vẫn thuộc lượt | `speech/turn/controller.py`: `_Candidate.segments`, `continues_turn()`, `expect_final()`, quy tắc 6; `ASRStreamContext.start_utterance(continues_turn=...)` và `accepts()` nhận mọi đoạn của lượt đang mở; `STTPipeline._drain_vad`. Test: `test_late_final_of_previous_segment_stays_in_the_same_turn`, `test_remote_final_for_earlier_segment_waits_for_later_segment` |
| Gate echo so theo cửa sổ từ | `InterruptionController._is_echo_of_bot` + `spoken_words`. Test: `test_short_caller_partials_are_not_mistaken_for_bot_echo` (đúng các partial 06/10), `test_exact_short_fragment_of_bot_text_is_still_echo`, `test_echo_of_bot_greeting_does_not_confirm_barge_in` (cũ) |
| Đoạn Gemini lỗi được decode lại bằng ZipFormer, đoạn sau mở socket mới | `GeminiLiveASR._finish/_recover`, `_LiveTurn._fail/start`; `fallback_provider: zipformer` (`GEMINI_LIVE_FALLBACK_PROVIDER`, rỗng = tắt); nạp sẵn lúc prewarm qua `SpeechRecognizer.warm_up_streaming`. Test: `test_missing_final_is_recovered_by_local_fallback_with_the_whole_segment`, `test_setup_failure_is_recovered_by_local_fallback_and_next_segment_retries`, `test_prewarm_loads_the_local_fallback_without_calling_gemini`; test lỗi cũ (không fallback) vẫn qua |
| Pre-roll cấu hình được | `pre_speech_ms` trong section `zipformer` và `gemini_live` của `config/asr.yaml` (thay hằng 300 ms viết cứng ở hai provider) |
| Từ đệm có dấu câu được lọc như không dấu | `is_meaningful_text("Ừ.")` = False (Gemini trả "Ừ.", ZipFormer trả "Ừ"; trước đây chỉ bản không dấu bị lọc) |
| Không giữ đoạn nói thừa; đếm khoảng lặng theo frame thật | `SileroVadClassifier.is_speech` lấy hết hàng đợi; `AsyncStreamingVAD(frame_ms=...)` |

## File liên quan

- `src/speech/turn/controller.py`, `src/speech/turn/interruption.py`
- `src/speech/asr/pipeline.py`, `src/speech/asr/stream_context.py`, `src/speech/asr/recognizer.py`, `src/speech/bundle.py`
- `src/speech/asr/vad/silero.py`, `src/speech/asr/vad/async_stream.py`
- `src/inference/asr/providers/gemini_live.py`, `src/inference/asr/providers/zipformer.py`, `src/inference/asr/config.py`
- `config/asr.yaml`, `docs/reference/gemini-live-stt.md`
- `eval/noise-bench/replay_dump.py` (spy validator chuyển tiếp mọi tham số)
- `tests/speech/turn/test_controller.py`, `tests/speech/turn/test_interruption.py`, `tests/speech/test_gemini_live_stream.py`

## Luồng hiện tại

```text
speech_start
  -> lượt đang dở (đã có chữ, hoặc còn đoạn ASR remote chưa có final)?
       có   : mở đoạn mới TRONG lượt; ASRStreamContext vẫn nhận final của các đoạn trước
       không: lượt mới
final của mọi đoạn + VAD không còn nói (với lượt nhiều đoạn)
  -> từ đệm (kể cả "Ừ." có dấu câu) : bỏ
  -> Validator / thời lượng tối thiểu như cũ
  -> UserTurnCompleted(text = các đoạn nối theo thứ tự đoạn)
Gemini: đoạn lỗi -> giữ PCM tới hết đoạn -> ZipFormer decode -> final cho đúng đoạn
```

## Số đo (`eval/noise-bench`, đồng hồ ảo, xác định)

Mốc = commit `1974acf` chạy qua git worktree, cùng dữ liệu/model. Kết quả thô ở
`temp/noise-bench/results/v_*.json` (không commit — giọng thật).

**Code cuối, cấu hình mặc định:** mọi chỉ số (WER, `no_turn`, `split_turns`, `false_turns`,
latency) **giống hệt mốc** trên cả ba bộ `short` (19 câu), `web` (42), `golden` (37); chỉ thời gian
CPU khác. Phần giữ lại không làm lệch đường ZipFormer mặc định.

### Đề xuất 6 — cho "ừ/ờ/dạ" qua theo SNR đoạn nói (từ chối)

Engine coi "ừ/ờ" là đồng ý (T-04), "dạ" là hỏi lại (R-23), nhưng tầng speech bỏ chúng. Bộ `short`
(12 trial chỉ có nhiễu mỗi mức):

| Ngưỡng SNR | `no_turn` sạch /19 | office@15 /38 | office@8 /38 | Lượt giả trên nhiễu văn phòng |
|---|---:|---:|---:|---|
| tắt (hiện tại) | 14 | 25 | 26 | 0 |
| 6 dB | 7 | 5 | 9 | "Ừ" ở short office@8 và @3 |
| 10 dB | 7 | 6 | 14 | "Ừ" ở short office@8 và @3 |
| 15 dB | 7 | 12 | 18 | "Ừ" ở **web office@15**; "Ừ" thừa sau câu ngày sinh ở golden office@3 |

Confidence ZipFormer của "Ừ" giả (tới 0,905) chồng lấn với "Ừ" thật (trung vị 0,746), nên không
có tín hiệu âm học nào hiện có tách được hai loại. "Ừ" giả ở câu hỏi xác nhận là đồng ý giả —
rủi ro nặng hơn việc bot im tới lượt im lặng. Gỡ code; ghi chú lý do ngay tại `_FILLER_WORDS`.
Hướng còn lại nằm ở engine (vd. "ừ" một mình ở bước xác nhận thì đọc lại để xác nhận) hoặc cần
dữ liệu có nhãn của câu trả lời ngắn thật.

### Đề xuất 7 — giữ lượt 300 ms sau final (từ chối)

Phát lại cuộc gọi `livekit_debug_web-eaa8acdb...wav` (72 s, thời gian thực, ZipFormer): giữ
0 ms tách "ANH MUỐN EM ĐẶT PHÒNG | CHO ANH" thành 2 lượt; 300 ms gộp lại, trễ thêm ~0,27 s.
Nhưng trên bench (giữ 300 ms cho mọi lượt):

| | web babble@12 `no_turn` /84 | golden babble@12 `no_turn` /74 | golden office@8 WER lượt | golden office@3 `no_turn` | latency p50 sạch (web) |
|---|---:|---:|---:|---:|---:|
| mặc định | 3 | 0 | 0,193 | 4 | 0,45 s |
| giữ 300 ms | **64** | **50** | 0,217 | 6 | 0,75 s |

Giọng nền liên tục mở đoạn mới trong lúc giữ, lượt bị nối mãi không chốt. Gỡ code. Nếu làm lại
cần trần thời lượng lượt và đo lại cả babble.

### Đề xuất 4/8 — pre-roll và Silero `min_speech` (giữ mặc định)

| Cấu hình | golden WER lượt sạch / office@15 / @8 / @3 | web lệch so với decode sạch: sạch / office@8 |
|---|---|---|
| mặc định (300 ms, 250 ms) | 0,113 / 0,163 / 0,193 / 0,283 | 0,036 / 0,109 |
| pre-roll 600 ms | 0,120 / 0,113 / 0,137 / 0,237 | 0,036 (mất 1 câu) / 0,130 |
| pre-roll 1000 ms | 0,100 / 0,093 / 0,130 / 0,193 | 0,058 / 0,120 |
| pre-roll 1000 ms + `min_speech` 120 ms | 0,093 / 0,097 / 0,140 / 0,197 | — |

Pre-roll dài giúp rõ bộ golden (8 kHz điện thoại) nhưng trên bộ web (đường LiveKit production)
trái chiều: sửa 5 câu, hỏng 5 câu, có câu đổi nghĩa ("ĐÚNG KHÔNG" → "ĐÚNG"); bộ short thêm lượt
giả "ĐÂY" trên nhiễu thuần. Giữ 300 ms, để `pre_speech_ms` cấu hình được làm ứng viên cho profile
điện thoại. `min_speech` 120 ms không có lợi trên bộ có nhãn — không thêm cấu hình.

### Không đo được bằng bench

- Gate echo: test đơn vị trên đúng các partial của cuộc gọi 06/10; bench không có bot nói.
- Nối đoạn cho Gemini và fallback: test bằng WebSocket giả (final tới muộn, setup bị từ chối,
  thiếu final). Chưa gây lỗi thật với Google.

## Quy trình xác minh

```bash
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
python scripts/export_openapi.py --check
PYTHONPATH=src python eval/noise-bench/bench.py --label x --dataset short
PYTHONPATH=src python eval/noise-bench/bench.py --compare v_base_short x
```

## Kết quả xác minh cục bộ (2026-10-06)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `STT_EVAL_ENABLED=false python -m pytest -q` | Pass (4198 passed, 9 skipped). Không đặt biến này thì 2 test route `stt_eval` lỗi do `.env` local, có từ trước thay đổi này |
| `python scripts/export_openapi.py --check` | Pass |
| `eval/noise-bench` short/web/golden, code cuối vs mốc | Giống hệt mọi chỉ số |

## Ghi chú

- Giọng người xung quanh (babble) vẫn là vấn đề lớn nhất: 11–12/12 lượt giả ở mọi cấu hình.
- Chưa làm (cần kiểm chứng ngoài bench): phiên Gemini dài cho cả cuộc gọi, `customVocabulary`,
  A/B tắt `noiseSuppression` của trình duyệt, cổng giọng người gọi bằng speaker embedding.
- Không thêm AGC/chuẩn hoá mức âm phía server cho web: đã bị từ chối bằng số đo ngày 30/09.

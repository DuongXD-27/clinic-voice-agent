# Evidence: chẩn đoán đường streaming, chỉ đo không đổi hành vi (PR1)

## Mục tiêu

Bước đầu của plan âm thanh Web/SIP: trước khi sửa cổng nào, phải biết **cổng nào** đang bỏ câu ngắn hoặc để lọt lượt giả, và audio thật sự đi vào worker ra sao. PR này chỉ thêm khả năng quan sát:
- không đổi quyết định nào của VAD, ASR, TurnController, Validator hay barge-in;
- không log text (PII).

## Bằng chứng trong repo

| Tiêu chí | Bằng chứng |
| --- | --- |
| Mỗi đoạn giọng có `utterance_id` và **đúng một** kết cục cuối (cổng + lý do) | `src/speech/diagnostics.py`: `SpeechDiagnostics.utterance_finished` bỏ qua lần gọi thứ hai. `TurnController` gọi `_finish()` tại mọi chỗ đang huỷ candidate. Test: `test_finished_twice_keeps_first_outcome`, `test_new_speech_start_supersedes_open_candidate_once` |
| Lý do đúng cổng | `tests/speech/test_diagnostics.py`: `not_meaningful`, `low_snr_short` (Validator), `min_speech` và `post_bot_guard` tách được nhau, `during_bot_speech`, `min_decode` và `no_text` |
| ZipFormer báo đoạn bị bỏ vì `min_decode_ms` mà không đổi chữ ký `stream()` của provider | `report_asr_event()` qua contextvar; `STTPipeline.stream` tạo task ASR với `context_with(diagnostics)`. Test: `test_asr_event_reaches_only_the_call_that_owns_the_task` |
| Xác suất Silero thật, chạy song song, không đổi quyết định VAD | `src/speech/asr/vad/silero_probe.py` (onnxruntime, Silero v4 16 kHz, cửa sổ 512, state h/c, 1 luồng). Tắt bằng `speech_diagnostics_probe: false`. Test: `tests/speech/vad/test_silero_probe.py` |
| Đo đầu vào: băng thông, audio bị rơi, hàng đợi, mức âm | `src/speech/audio/ingress.py` `IngressMonitor`. Test: `test_ingress_detects_narrowband_and_missing_audio`, `test_ingress_detects_wideband` |
| Log `AUDIO_INGRESS` có loại participant, **không có identity** (SIP identity có thể chứa số điện thoại) | `call_bridge.py` `participant_kind`, `_audio_settings`. Test: `test_ingress_log_names_kind_but_never_sip_identity` |
| Trình duyệt gửi thiết lập mic **thật sự áp dụng** | `ui/src/features/livekit/model/audioSettings.ts`, `useLiveKitCall.ts` `reportAudioSettings` (lỗi thì bỏ qua). Token web thêm quyền `can_update_own_metadata` (`livekit_token.py`): thiếu quyền này thì LiveKit từ chối `setAttributes`. Phát hiện khi gọi thật, log luôn ra `audio_settings=-`. Worker log lại khi attribute tới muộn (`_on_attributes_changed`). Test: `audioSettings.test.ts`, `test_token_lets_browser_report_its_audio_settings`, `test_late_audio_settings_from_caller_are_logged` |
| Barge-in: kết cục và độ trễ | `InterruptionController` ghi `CONFIRMED` / `REVERTED` / `BOT_STOPPED` / `RESET`. Test: `test_barge_in_outcomes_and_latency` |
| Fake pipeline cũ không vỡ | `CallBridge` chỉ truyền `diagnostics=` khi bật. Test: `test_diagnostics_reach_pipeline_only_when_enabled` |

## Không đổi hành vi: đối chiếu noise-bench

- Chạy cùng lệnh, cùng seed, trên hai phiên bản: code **trước** (git worktree tại HEAD, `NOISE_BENCH_SRC`) và code **sau**. So từng trial: finals, turns và thời điểm chốt.
- Profile `target` (Silero, Validator, shared detector). Điều kiện clean, office@8, babble@6, kèm 12 trial chỉ có nhiễu cho mỗi điều kiện nhiễu.

```bash
NOISE_BENCH_SRC=<worktree>/src python eval/noise-bench/bench.py --label pr1-base-short --dataset short --profile target --conditions clean,office@8,babble@6 --repeats 1
python eval/noise-bench/bench.py --label pr1-after-short --dataset short --profile target --conditions clean,office@8,babble@6 --repeats 1
python eval/noise-bench/bench.py --diff pr1-base-short pr1-after-short
```

| Bộ | Trial khác |
| --- | --- |
| short (19 câu ngắn) | **0/81** |
| web (42 câu thật LiveKit) | **0/150** |
| golden (37 câu có lời) | **0/135** |

**Chi phí CPU** (máy dev, frame 30 ms):
- Silero song song: 0,091 ms, tức khoảng 0,3% một core;
- `IngressMonitor`: 0,007 ms (FFT chỉ chạy trên 3 s đầu có tiếng).

**Cuộc gọi thử thật** (worker local, `agent_name` riêng, participant giả lập trình duyệt phát 3 câu golden lên LiveKit Cloud):
- lời chào và 3 lượt đều tới core, kết thúc bằng chuyển máy;
- `TURN_ACCEPTED` đủ 3 dòng, `endpoint_ms` 641–683;
- `AUDIO_INGRESS_SUMMARY`: `missing_ms=0`, `max_queue_depth=5`, `bandwidth=narrowband`. Đúng, vì golden là audio 8 kHz nâng lên.

## Phát hiện đầu tiên (từ chính log mới)

**Câu ngắn "bị mất" là ở sau ASR, không phải ở VAD hay `min_decode`.** Bộ `short` khi sạch: 14/19 câu không thành lượt.

| Kết cục | Số câu | ASR nghe ra |
| --- | --- | --- |
| `DROPPED:not_meaningful` | 10 | "Ừ". `is_meaningful_text` coi "ừ" (cùng "dạ") là tiếng đệm |
| `DROPPED:oscillating` | 3 | "ĐÂY", mẫu bịa chữ đã biết |
| không có đoạn | 1 | |
| `EMITTED` | 5 | KHÔNG, OK, VÂNG, HUY ĐỒNG Ý, KHÔNG ĐƯỢC |

- Trong tiếng Việt "ừ", "dạ" là câu trả lời "có". Việc bỏ chúng là đúng hay sai **phụ thuộc bot vừa hỏi gì**. Đây là đầu vào cho PR6 (cổng theo trạng thái hội thoại).
- Bộ `short` chưa có nhãn tay. Các đoạn "Ừ" phải được nghe lại trước khi tính là mất câu thật.
- Lượt giả với giọng nền (babble@6): mọi trial chỉ có nhiễu đều ra `EMITTED`, không cổng nào chặn. Khớp kết luận cũ rằng cổng âm học không tách được người khác nói.

## Gọi thử bằng trình duyệt thật (8 cuộc, 2026-10-01, mic và loa laptop, không tai nghe)

| Quan sát | Số liệu |
| --- | --- |
| Trình duyệt bật đủ xử lý | `echoCancellation`, `noiseSuppression`, `autoGainControl`, `voiceIsolation` đều `true` |
| Nhiễu nền giữa các câu bị cắt về gần 0 | `noise_p10_dbfs` từ −90 tới −78; `snr_db` của lượt 41–74 dB |
| Không rơi audio, worker kịp | `missing_ms=0`, `max_queue_depth` ≤ 8 |
| Lượt lúc bot im: không câu nào bị bỏ | 21/21 `TURN_ACCEPTED` |
| Mọi đoạn bị bỏ đều xảy ra lúc bot đang nói | 6 đoạn: 2 tiếng động 30–60 ms không ra chữ, 4 đoạn có chữ (2–6 từ) |
| Ngắt lời | 2 `CONFIRMED` (độ trễ 721 và 1322 ms), 4 `REVERTED` có chữ |
| Cùng một mic, băng thông đo được dao động mạnh | `high_band_ratio` từ 0,00069 tới 0,0129. Một cuộc bị gắn nhầm `narrowband` với ngưỡng cũ 1e-3 |

Sửa cách đo sau lần gọi này:
- `endpoint_ms` (626–661 ms) đo từ frame cuối detector còn báo "đang nói". Detector Silero giữ trạng thái này thêm 500 ms (`silero_min_silence_ms`), nên số đó **thiếu 500 ms**: người gọi thực tế chờ khoảng 1,1 s sau khi ngừng nói. Thêm `voice_ms` / `voice_endpoint_ms` tính theo xác suất Silero thô.
- `vad_prob_mean` trước đây tính trên mọi frame, kể cả 600 ms im lặng chờ chốt câu, nên câu ngắn bị kéo xuống 0,07–0,18. Nay chỉ tính trên frame detector coi là tiếng nói.
- Dòng `superseded` từng tính frame đầu của đoạn kế tiếp, cho ra `endpoint_ms=1`. Nay đoạn ngừng nhận frame sau `speech_end`. Test: `test_voice_endpoint_includes_detector_hangover_and_ignores_next_onset`.
- Ngưỡng `narrowband` hạ từ 1e-3 xuống 1e-5. Chính bản ghi của cuộc gọi thử ra 1,5e-3; cùng audio đó qua G.711 µ-law 8 kHz rồi nâng lên 16 kHz ra 4e-9. Cần xác nhận lại bằng cuộc gọi PJSUA thật (PR3).

Cuộc có ghi âm (`LIVEKIT_DEBUG_DUMP_AUDIO=1`, phân tích từng frame) cho thấy ba điểm yếu với câu trả lời ngắn trên đường streaming:
1. **Câu trả lời lúc bot đang nói bị bỏ dù là giọng thật.** Trong lúc bot nói, mic chỉ ở khoảng −80 dBFS (trình duyệt khử vọng gần hết tiếng bot); câu trả lời đồng ý 3 từ ở −15 đến −25 dBFS, ngang các lượt thường. ASR nghe đúng sau 0,4 s, nhưng cổng ngắt lời cần transcript `CONVERGING`, nên được WAIT. Khi bot dứt lời, TurnController bỏ mọi candidate tích luỹ lúc bot nói (giả định là tiếng bot vọng lại).
2. **SNR của nhánh ngắt lời sai.** Cùng câu đó, nhánh ngắt lời đo 3,0 dB, còn lượt thường đo 55 dB. Nhánh ngắt lời vẫn đọc `NoiseTracker` theo từng frame, mà nền nhiễu của nó bị đầu câu kéo lên. Đây là lỗi 26/09 đã sửa cho TurnController (`UtteranceEvidenceTracker`) nhưng chưa sửa cho ngắt lời.
3. **Mất chữ đầu của câu ngắn.** Chữ đầu dài khoảng 240 ms, rồi xác suất tụt dưới 0,5 trong 30 ms. Silero (sherpa, cần 250 ms liên tục) báo có tiếng nói trễ 0,6 s. Pre-roll của ASR chỉ có 300 ms nên chữ đầu không tới ASR.

Lượt thường: `voice_endpoint_ms` 1140–1170 ms, tức người gọi chờ khoảng 1,15 s sau khi ngừng nói thì lượt mới được chốt.

## File liên quan

- `src/speech/diagnostics.py`
- `src/speech/asr/vad/silero_probe.py`
- `src/speech/audio/ingress.py`
- `src/speech/turn/controller.py`, `interruption.py`, `validator.py` (thêm `decide()` trả lý do), `events.py` (`utterance_id`, không tham gia so sánh)
- `src/speech/asr/pipeline.py`, `src/inference/asr/providers/zipformer.py`
- `src/callbot/transports/livekit/call_bridge.py`, `worker.py`
- `src/speech/settings.py`, `config/speech.yaml` (`speech_diagnostics_probe`)
- `pyproject.toml`: thêm `onnxruntime` vào extra `vad-silero`. Image production chưa có gói này; sherpa-onnx dùng onnxruntime riêng, không lộ cho Python.
- `eval/noise-bench/bench.py`: kết cục theo lý do (`speech_outcomes`, `noise_outcomes`), `--diff`, `--no-probe`
- `ui/src/features/livekit/model/audioSettings.ts`, `useLiveKitCall.ts`
- `tests/speech/test_diagnostics.py`, `tests/speech/vad/test_silero_probe.py`, `tests/transports/livekit/test_call_bridge_input.py`, `ui/src/features/livekit/model/audioSettings.test.ts`

## Kết quả xác minh cục bộ (2026-10-01)

| Command | Kết quả |
| --- | --- |
| `make check` | Pass: 3501 passed, 6 skipped; OpenAPI khớp |
| `cd ui && npm run check` | Pass: 185 test |
| noise-bench `--diff` (3 bộ) | 0/366 trial khác |

`make check` chạy với `STT_EVAL_ENABLED=false`: `.env` local đang bật cờ này, khiến `test_routes_are_not_mounted_by_default` fail. Không liên quan PR này.

## Ghi chú

- Web demo bằng trình duyệt thật vẫn cần người gọi thử một lần trước khi merge. Lần gọi thử ở trên dùng participant giả lập.
- `uv.lock` chưa cập nhật cho `onnxruntime` (cũng như `python-multipart` trước đó). Docker cài bằng `pip install ".[...]"` nên không phụ thuộc lockfile.

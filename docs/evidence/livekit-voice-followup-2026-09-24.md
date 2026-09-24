# Evidence: Hoàn thiện luồng thoại LiveKit


## Mục tiêu

Ghi nhận bằng chứng trong repository cho các sửa đổi luồng thoại LiveKit ngày 24/09: giữ âm đầu câu qua nhiều lớp VAD, hạn chế ngắt lời giả do tiếng vọng, chặn Admission đẩy im lặng quá lâu, giảm log lặp và báo lỗi outbound rõ ràng trên demo. Tách các thay đổi có kiểm thử tự động khỏi lỗi kết nối WebSocket mới chỉ được chẩn đoán qua log.

## Bằng chứng trong repo

| Tiêu chí | Bằng chứng |
| --- | --- |
| Không bỏ audio trước `speech_start` của VAD chính | `src/speech/asr/pipeline.py` dùng `_vad_preroll` độc lập với Admission; `tests/speech/test_pipeline_admission.py` có `test_vad_preroll_bridges_audio_before_speech_start`, `test_vad_preroll_works_without_admission_configured` và `test_vad_preroll_does_not_bypass_admission_for_later_frames`. |
| VAD nội bộ ZipFormer không làm mất lại âm đầu | `src/inference/asr/providers/zipformer.py` giữ tối đa 300 ms audio trước onset rồi đưa vào buffer decode; `tests/speech/test_zipformer_stream.py::test_stream_keeps_audio_before_internal_vad_onset` kiểm tra frame 10/30 ms và ngưỡng `min_decode_ms`. |
| Ngắt lời có ngưỡng SNR riêng | `src/speech/turn/interruption.py` áp dụng `min_snr_db` nếu cấu hình; `src/speech/settings.py` và `src/callbot/transports/livekit/worker.py` nối biến `INTERRUPTION_MIN_SNR_DB`; `tests/speech/turn/test_interruption.py` bao phủ SNR thấp, ngưỡng để trống và lời ngắt thật SNR cao. |
| Admission kết thúc sau im lặng và không tự nâng noise floor bằng âm đầu mơ hồ | `src/speech/asr/admission.py` thêm `end_silence_ms`; `src/speech/bundle.py` nối `vad_end_silence_ms`; `src/speech/asr/pipeline.py` đếm non-speech và chỉ `commit_floor` khi SNR thấp. Kiểm thử: `test_loud_pre_onset_does_not_poison_floor_or_stream_silence_forever`. |
| Log bất đồng VAD/Admission không lặp theo từng frame; candidate cũ được giải phóng | `src/speech/asr/pipeline.py` giới hạn log mỗi 10 giây; `src/speech/turn/controller.py` ngừng coi candidate là active sau `speech_end` và reset candidate rỗng khi hết timeout. Kiểm thử trong `test_pipeline_admission.py` và `test_controller.py`. |
| Outbound start lỗi nghiệp vụ không để demo im lặng | `src/callbot/transports/livekit/call_bridge.py` bắt `OutboundStartFailed` và gửi `OUTBOUND_START_FAILED` qua data channel; `src/callbot/transports/http/static/livekit-demo.html` hiển thị thông báo rồi ngắt room. `tests/transports/livekit/test_call_bridge_mapping.py::test_outbound_start_failure_notifies_browser_without_crashing_job` kiểm tra không phát TTS và gói trạng thái. |
| Có tài liệu luồng xử lý | `docs/reference/livekit-voice-pipeline-2026-09-24.md` mô tả các lớp xử lý và các điểm resample. |

## File liên quan

- Luồng âm thanh: `src/speech/asr/pipeline.py`, `src/speech/asr/admission.py`, `src/speech/bundle.py`, `src/inference/asr/providers/zipformer.py`.
- Điều khiển lượt nói/ngắt lời: `src/speech/turn/controller.py`, `src/speech/turn/interruption.py`, `src/speech/settings.py`.
- LiveKit và demo: `src/callbot/transports/livekit/call_bridge.py`, `src/callbot/transports/livekit/worker.py`, `src/callbot/transports/http/static/livekit-demo.html`.
- Kiểm thử: `tests/speech/test_admission.py`, `tests/speech/test_pipeline_admission.py`, `tests/speech/test_zipformer_stream.py`, `tests/speech/turn/test_controller.py`, `tests/speech/turn/test_interruption.py`, `tests/transports/livekit/test_call_bridge_mapping.py`.

## Luồng hiện tại

```text
Micro LiveKit -> VAD chính + pre-roll (bù audio trước speech_start)
               -> Speech Admission (VAD/SNR/thời lượng, kết thúc sau im lặng)
               -> VAD nội bộ ZipFormer + pre-speech 300 ms
               -> ASR final -> TurnController/Validator -> Core -> TTS

Core outbound start lỗi -> CallBridge gửi callbot.status
                         -> Web demo hiển thị lỗi, ngắt room; không phát lời chào
```

Ngưỡng SNR ngắt lời chỉ áp dụng nhánh bot đang nói, độc lập với Admission của lượt nói thông thường. Log `VAD/Admission disagree` được lấy mẫu tối đa một lần/10 giây; điều này giảm log, không tự khôi phục kết nối mạng hoặc chứng minh mọi lượt nói đều được nhận dạng chính xác.

## Quy trình xác minh

Dùng môi trường đã có của dự án (`.venv`). Bộ kiểm tra đầy đủ trước khi push:

```bash
make check PYTHON=.venv/bin/python
```

Có thể chạy riêng nhóm liên quan:

```bash
.venv/bin/python -m pytest -q tests/speech/test_admission.py tests/speech/test_pipeline_admission.py tests/speech/test_zipformer_stream.py tests/speech/turn/test_controller.py tests/speech/turn/test_interruption.py tests/transports/livekit/test_call_bridge_mapping.py
.venv/bin/python -m ruff check src/callbot/transports/livekit/call_bridge.py src/inference/asr/providers/zipformer.py src/speech/asr/admission.py src/speech/asr/pipeline.py src/speech/bundle.py src/speech/turn/controller.py tests/speech/test_pipeline_admission.py tests/speech/test_zipformer_stream.py tests/speech/turn/test_controller.py tests/transports/livekit/test_call_bridge_mapping.py
.venv/bin/python -m ruff format --check src/callbot/transports/livekit/call_bridge.py src/inference/asr/providers/zipformer.py src/speech/asr/admission.py src/speech/asr/pipeline.py src/speech/bundle.py src/speech/turn/controller.py tests/speech/test_pipeline_admission.py tests/speech/test_zipformer_stream.py tests/speech/turn/test_controller.py tests/transports/livekit/test_call_bridge_mapping.py
```

Không dùng `python` ngoài `.venv` để suy ra kết quả test của dự án vì môi trường đó thiếu `fakeredis`.

## Kết quả xác minh cục bộ (2026-09-24)

| Lệnh | Kết quả |
| --- | --- |
| Pytest trên sáu file nêu trên | **103 passed**, 1 cảnh báo deprecation từ `starlette.testclient`. |
| Ruff check trên mười file Python có diff | **Pass**. |
| Ruff format --check trên cùng mười file | **Pass** sau khi format `call_bridge.py`. |
| `git diff --check` trước khi viết tài liệu | **Pass** cho 12 file mã nguồn/test đang thay đổi. |
| `python -m pytest` ngoài `.venv` | Không khởi chạy được: thiếu `fakeredis` trong môi trường Python hệ thống. |
| `make check PYTHON=.venv/bin/python` | **Pass**: Ruff check, Ruff format trên 276 file; pytest **2551 passed, 28 skipped, 1 cảnh báo deprecation**. |
| Gọi LiveKit thực / triển khai sau bản sửa | **Chưa chạy trong phiên này**. |

## Ghi chú

- Bốn dòng log `Connection reset by peer (os error 104)` chỉ cho thấy WebSocket signaling bị reset. Chưa có log đủ dài để kết luận nguyên nhân, trạng thái reconnect hoặc mức ảnh hưởng tới cuộc gọi; **không có bản sửa mạng/LiveKit** trong thay đổi này.
- Quan sát trước đó: decode offline đoạn audio mất 1,89 giây, còn log worker ghi 4,38 giây. Đây là bằng chứng về chênh lệch thời gian của đoạn đã đo, không chứng minh tất cả log lặp đều do RAM/CPU. Các thay đổi Admission/log ở trên là biện pháp phòng tránh độc lập.
- Báo cáo ngày 24/09 ghi nhận xác nhận thủ công trên một số cuộc gọi trước đó; bộ thay đổi hiện tại đã qua test tập trung và full suite, nhưng chưa thử lại trên nhiều cuộc gọi thật. Chưa có số liệu mới để khẳng định lỗi mất âm đầu hoặc không phản hồi đã hết trên mọi cuộc gọi thật.
- `temp/` bị Git ignore; báo cáo trong `temp/baocao_24-09-2026.md` chỉ lưu cục bộ và không nằm trong commit. Không đưa `.env`, key, token, audio người dùng hoặc log thô chứa định danh cuộc gọi vào evidence.

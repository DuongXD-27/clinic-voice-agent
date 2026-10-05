# Gemini Live STT

Provider `gemini_live` dùng `gemini-3.5-transcribe-live` cho luồng LiveKit.
HTTP/batch giữ provider riêng vì Gemini Live chỉ hỗ trợ `stream()`.

## Cấu hình

Đặt key và override trong `.env`:

```dotenv
GEMINI_API_KEY=...
LIVEKIT_ASR_PROVIDER=gemini_live
GEMINI_LIVE_ASR_MODEL=gemini-3.5-transcribe-live
GEMINI_LIVE_LANGUAGE_CODE=vi-VN
```

Worker ưu tiên `LIVEKIT_ASR_PROVIDER`; bỏ override hoặc để rỗng để dùng `ASR_PROVIDER`.
Tham số provider ở `config/asr.yaml`; tần số/frame/queue của LiveKit ở `config/livekit.yaml`.
Key chỉ đọc từ env, không đưa vào YAML hoặc git. Sau khi sửa env, restart worker;
Docker local cần build image mới:

```bash
docker compose up -d --build livekit-worker
```

## Hợp đồng streaming

- PCM16 mono 8/16 kHz; giữ 300 ms trước onset như baseline của main.
  Resample 8k → 16k có trạng thái, gửi chunk 100 ms và flush phần dư trước end.
- WebSocket BidiGenerateContent, TEXT, `vi-VN`, `VERBATIM`; automatic VAD tắt.
  Ranh giới `activityStart`/`activityEnd` theo classifier/endpoint local.
- Mỗi segment có socket riêng để cô lập kết quả từ đoạn đã discard.
  Có chi phí handshake mỗi segment; chưa tối ưu reuse session.
- Interim là partial, transcription sau end là final; confidence là `None`.
  Engine chỉ nhận final ở đường này; không tự chốt partial khi thiếu final.
- Generation/segment ID ngăn final đến muộn ghép vào câu sau.
  Controller vẫn chỉ giữ một candidate: nhiều đoạn nói sát nhau cần đánh giá thêm.
- Timeout setup/send 10 s, final 3 s; speech liên tục tối đa 15 s.
  Thiếu final báo lỗi, không tự fallback sang provider khác.

Dùng WebSocket trực tiếp vì SDK local `google-genai` 2.16.0 thiếu trường `mode`;
không thêm dependency. Nguồn hợp đồng:
[Gemini Live Transcription](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe).

## Kiểm tra và eval

Kiểm tra setup không gửi audio:

```bash
PYTHONPATH=src python eval/streaming-bench/check_connection.py
```

Replay WAV, cách chấm chất lượng/latency và giới hạn phép đo nằm trong
[hướng dẫn eval](../../eval/streaming-bench/README.md). Plan, báo cáo thử nghiệm và
artifact cá nhân được lưu local trong `temp/`, không đưa vào thay đổi production.

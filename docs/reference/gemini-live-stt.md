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

- PCM16 mono 8/16 kHz; giữ `pre_speech_ms` (mặc định 300 ms) trước onset, cùng nghĩa với
  `pre_speech_ms` của ZipFormer.
  Resample 8k → 16k có trạng thái, gửi chunk 100 ms và flush phần dư trước end.
- WebSocket BidiGenerateContent, TEXT, `vi-VN`, `VERBATIM`; automatic VAD tắt.
  Ranh giới `activityStart`/`activityEnd` theo classifier/endpoint local.
- Mỗi segment có socket riêng để cô lập kết quả từ đoạn đã discard.
  Có chi phí handshake mỗi segment; chưa tối ưu reuse session.
- Interim là partial, transcription sau end là final; confidence là `None`.
  Engine chỉ nhận final ở đường này; không tự chốt partial khi thiếu final.
- Generation/segment ID ngăn final đến muộn ghép vào câu sau. Trong CÙNG một lượt
  (TurnController nối đoạn khi người gọi nói tiếp lúc lượt còn dở), final của đoạn trước tới
  muộn vẫn được nhận và ghép đúng thứ tự đoạn; lượt chỉ chốt khi mọi đoạn đã có final.
- Timeout setup/send 10 s, final 3 s; speech liên tục tối đa 15 s.
- Đoạn lỗi (setup bị từ chối, mất kết nối, hết credit, thiếu final sau 3 s) được decode lại
  bằng `fallback_provider` (mặc định `zipformer`) trên PCM của chính đoạn đó; log WARNING ghi
  số segment và loại lỗi, đoạn sau mở socket mới. Worker nạp sẵn ZipFormer lúc prewarm, nên
  cần asset `zipformer` như khi chạy `ASR_PROVIDER=zipformer`. Đặt
  `GEMINI_LIVE_FALLBACK_PROVIDER=` (rỗng) để tắt: khi đó lỗi làm hỏng luồng STT như trước.

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

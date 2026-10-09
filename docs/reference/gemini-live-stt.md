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
- Mỗi segment có socket riêng để cô lập kết quả từ đoạn đã discard. Socket của đoạn kế tiếp
  được mở và setup sẵn ở nền (handshake 0,65–4 s, đo 07/10) nên không chặn đầu câu; mỗi cuộc
  gọi giữ thêm một socket rảnh. Server đóng socket rảnh sau khoảng 1–3 phút (30 s vẫn dùng
  được, 180 s bị đóng 1008) — khi đó đoạn đó tự mở socket mới.
- Interim là partial, transcription sau end là final; confidence là `None`.
  Engine chỉ nhận final ở đường này; không tự chốt partial khi thiếu final.
- `gemini-3.5-transcribe-live` không gửi `turnComplete`. Sau `activityEnd` server luôn trả
  `voiceActivity: ACTIVITY_END`, cùng lúc hoặc sau final; đoạn không có lời (tiếng ồn, tiếng
  vọng) CHỈ nhận `ACTIVITY_END`. Đoạn được chốt ở đó (final rỗng nếu không có lời) — trước đây
  đoạn rỗng nào cũng chờ hết 3 s rồi rơi xuống ZipFormer, ZipFormer bịa ra "ĐÂY" (6/6 lần đo).
- Generation/segment ID ngăn final đến muộn ghép vào câu sau. Trong CÙNG một lượt
  (TurnController nối đoạn khi người gọi nói tiếp lúc lượt còn dở), final của đoạn trước tới
  muộn vẫn được nhận và ghép đúng thứ tự đoạn; lượt chỉ chốt khi mọi đoạn đã có final.
- Timeout setup/send 10 s, final 3 s; speech liên tục tối đa 15 s.
- Chọn Gemini thì chỉ dùng Gemini, không decode lại bằng model khác. Đoạn lỗi (setup bị từ
  chối, mất kết nối, hết credit, thiếu final sau 3 s) chỉ mất đoạn đó: chốt bằng final rỗng,
  log WARNING ghi số segment và loại lỗi, đoạn sau mở socket mới. 3 đoạn lỗi liên tiếp
  (`_MAX_FAILED_SEGMENTS`) thì lỗi nổi lên, luồng STT của cuộc gọi dừng.
- Worker không đổi ASR thay người chọn: ASR chọn trên trang gọi thử (hoặc theo cấu hình worker)
  mà không tạo được (vd. thiếu `GEMINI_API_KEY`) thì worker báo `ASR_UNAVAILABLE` lên trang
  và dừng cuộc gọi.

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

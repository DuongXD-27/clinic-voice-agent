# Gemini Live STT — bằng chứng tích hợp ngày 05/10/2026

## Phạm vi và kết luận

Hai phần đã thực hiện:

1. Tích hợp `gemini-3.5-transcribe-live` vào đường streaming LiveKit, chọn riêng qua
   `LIVEKIT_ASR_PROVIDER`. HTTP/batch tiếp tục dùng `ASR_PROVIDER`; bỏ override hoặc
   để trống để LiveKit dùng lại provider mặc định.
2. Điều chỉnh xử lý transcript/chốt lượt cho ASR remote: chờ final, theo dõi server còn
   xử lý và ngăn kết quả từ đoạn cũ ghép vào lượt mới.

Đã xác minh kết nối/luồng LiveKit thật trước khi merge refactor main, và kiểm tra bằng
test trên phiên bản sau merge. **Chưa kết luận Gemini nhận dạng tốt hơn GipFormer hoặc
đã ổn định trong mọi tình huống streaming.** Phần so sánh chất lượng đang hoàn thiện,
không dùng làm căn cứ trong tài liệu này.

## 1. Kiểm tra kết nối và LiveKit thật

Sau khi cập nhật key, setup thật thành công với tiếng Việt `vi-VN`, `VERBATIM`, đầu ra
TEXT và manual activity. Lệnh kiểm tra setup hiện tại, không gửi audio:

```bash
PYTHONPATH=src python eval/streaming-bench/check_connection.py
```

Cuộc gọi thử chạy trên backend local, worker có tên riêng và clinic `sim`. Audio đi
qua LiveKit → VAD/ASR → TurnController → engine → TTS. Không ghi vào hệ thống lịch thật.

Một WAV tổng hợp 24 kHz, dài 1062 ms, được chuyển sang PCM mono 16 kHz và phát theo
thời gian thực. Nội dung đầu vào là “Alo, tôi nghe đây.”; transcript engine nhận cũng
là “Alo, tôi nghe đây.”. Bot có text và audio phản hồi; sample lượt nói có `valid=true`.

| Mốc của lượt WAV này | Giá trị |
|---|---:|
| Phát xong caller → caller transcript tới engine | 1735 ms |
| Caller transcript → bot text | 0 ms theo phép làm tròn |
| Bot text → audio bot bắt đầu | 2599 ms |
| Phát xong caller → audio bot bắt đầu | 4335 ms |

Số STT gồm endpointing và truyền LiveKit, không phải thời gian inference riêng của
Gemini. Đây là một mẫu kiểm tra chức năng, không có p95 hay kết luận chất lượng ASR.
Lần thử hai lượt trước đó có phép đo TTFA âm do bắt nhầm audio; không dùng số đó.

**Giới hạn phiên bản:** cuộc gọi thật trên chạy trước khi merge cấu trúc STT mới của
main. Cần gọi lại trên phiên bản sau merge; CI/test mô phỏng không thay cho lần gọi này.

## 2. Kiểm chứng xử lý transcript và chốt lượt

[17 test Gemini](../../tests/speech/test_gemini_live_stream.py) dùng WebSocket giả và
pipeline thật, không gửi audio tới Google trong test:

| Hành vi | Kiểm chứng |
|---|---|
| Final có text giống partial; nhiều câu trả lời giống nhau | Final vẫn được giữ, mỗi segment có final riêng; callback lặp không tạo lượt lặp |
| Câu ngắn và âm đầu trước lúc classifier báo speech | Audio đệm đầu câu và phần chunk dư được gửi đủ |
| Resample 8 kHz → 16 kHz | Đủ số mẫu, pha liên tục qua ranh giới frame/chunk |
| Hàng đợi audio rỗng nhưng server chưa trả final | Controller tiếp tục chờ; không đưa partial tới engine |
| Final tới sau khi VAD bắt đầu đoạn nói mới | Kết quả cũ không gắn vào candidate của đoạn mới |
| Bot bắt đầu nói hoặc pipeline discard đoạn dở | Invalidate đoạn cũ, đóng socket; không chốt nội dung của đoạn đã bỏ |
| Thiếu final, setup lỗi hoặc hủy stream | Báo lỗi rõ ràng, dọn socket và pending state; không lộ payload/key upstream |
| Cấu hình provider | LiveKit có override riêng; override rỗng quay về mặc định; prewarm không gọi batch cho Gemini |

Generation/segment ID và trạng thái pending nằm trong context riêng của mỗi stream.
Pipeline gán segment theo VAD trước khi gửi frame. TurnController yêu cầu final ở
đường Gemini; thiếu final thì báo lỗi, không tự chốt partial hoặc fallback model.

Chạy lại các test tích hợp:

```bash
PYTHONPATH=src python -m pytest tests/speech/test_gemini_live_stream.py -q
```

## 3. CI và code đã đưa lên nhánh

- Nhánh: `feat/gemini-live-stt-streaming`; chưa merge vào main tại thời điểm báo cáo.
- Commit tích hợp: [`f6fbcf7`](https://github.com/phamtuanviet/callbot-vinmec/commit/f6fbcf7).
- Commit sửa schema: [`6b53aa2`](https://github.com/phamtuanviet/callbot-vinmec/commit/6b53aa2).
  Sau cleanup cổng im lặng thử nghiệm, sinh lại OpenAPI/type UI để bỏ enum
  `VAD_NO_SPEECH` còn sót. Không thay đổi logic runtime trong commit này.
- [CI của `6b53aa2`](https://github.com/phamtuanviet/callbot-vinmec/actions/runs/37334318701)
  pass cả ba job: Python lint/test và OpenAPI check; UI lint/test/build; UI E2E.
- CD production chỉ nhận main, CD staging chỉ nhận develop; nhánh feature không deploy.

Code chính: [Gemini adapter](../../src/inference/asr/providers/gemini_live.py),
[stream context](../../src/speech/asr/stream_context.py),
[STT pipeline](../../src/speech/asr/pipeline.py),
[TurnController](../../src/speech/turn/controller.py) và
[LiveKit worker](../../src/callbot/transports/livekit/worker.py).
Cách bật/tắt và tham số: [hướng dẫn vận hành](../reference/gemini-live-stt.md).

## 4. Giới hạn còn lại

- Từng có cuộc gọi mic timeout chờ final sau 3 giây; chưa xác định nguyên nhân và chưa
  xác nhận đã khắc phục. Hiện chưa có fallback tự động.
- Mỗi segment mở một socket riêng, có thêm chi phí handshake.
- Controller giữ một candidate: đoạn nói mới có thể thay đoạn trước đang chờ final.
  Cơ chế hiện tại tránh ghép nhầm nhưng chưa bảo đảm giữ đủ mọi lượt nói sát nhau.
- Cần kiểm tra lại cuộc gọi thật sau merge, gồm câu ngắn, nói liên tiếp, ngắt lời và
  mạng chậm, trước khi quyết định thay provider mặc định.

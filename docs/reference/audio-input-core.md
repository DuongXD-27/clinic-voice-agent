# Mapping đầu vào audio vào Core

HTTP và LiveKit dùng `caller_input_from_transcript` để tạo `CallerInput`.
Hàm này giữ nguyên transcript, số lượt, URL nguồn và confidence; không chọn intent,
không xác minh danh tính và không suy ra trạng thái điện thoại. Core vẫn xử lý qua
cùng Extraction → Policy → Dialogue → Output Guard → FSM → Session.

## Quy trình HTTP

1. Kiểm tra đầu vào khớp mode đã mở: audio không nhận text, text không nhận audio URL.
2. Khi `silence_ms > 0`, bỏ qua tải clip và ASR dù request có `audio_url`.
   Tạo lượt im lặng với `text=None`, không có confidence; giữ URL để nhận diện request.
3. Core kiểm tra phiên, thứ tự và replay trước khi gọi resolver tải clip/chạy ASR.
   Chỉ lượt chưa có transcript mới được nhận dạng; xem [retry đầu vào](audio-request-replay.md).
   `Transcript.is_silence` không quyết định im lặng của Core. Transcript rỗng là đầu vào
   không hiểu, không tăng bộ đếm im lặng.
4. Nếu tải/giải mã hoặc ASR lỗi, trả `503 UPSTREAM` với thông báo an toàn.
   Chưa đặt chỗ lượt, session/counters và Clinic giữ nguyên; có thể gửi lại cùng số lượt.
5. Gửi `CallerInput` vào orchestrator dùng chung. TTS đọc utterance đã qua Output Guard.

## Quy trình LiveKit

1. Pipeline đưa sự kiện VAD và ASR partial/final vào TurnController.
2. Chỉ `UserTurnCompleted` được mapping và gửi vào Core. Sự kiện ASR thô, kể cả final,
   không được gửi trực tiếp: ASR final và lượt hội thoại đã chốt là hai loại dữ liệu khác nhau.
3. TurnController vẫn có cơ chế chốt từ partial sau khi VAD kết thúc và hết thời gian chờ,
   khi các điều kiện hiện có cho phép; thay đổi này không yêu cầu mọi lượt phải có ASR final.
4. Hẹn giờ im lặng tạo lượt có `silence_ms`; confidence và text bị bỏ khi mapping lượt này.
5. Lỗi task ASR/VAD/nguồn frame được truyền lên bridge và dọn tài nguyên.
   Không tạo lượt rỗng, lượt im lặng hay phone status để thay thế lỗi; không ghi thêm Clinic.
   Bridge chỉ log tên lớp lỗi, tránh ghi transcript hoặc URL trong exception.

## Kiểm chứng và phạm vi

- Regression HTTP kiểm tra ba lượt im lặng theo hướng gọi, transcript rỗng,
  lỗi STT có thể retry và cùng luồng identity/read-back/confirm cho text/audio.
- Regression streaming kiểm tra lỗi ASR, VAD và nguồn frame được truyền về nơi gọi.
- Regression LiveKit kiểm tra mapping metadata, từ chối sự kiện ASR thô và cleanup khi lỗi.

Đây là kiểm chứng mapping bằng ASR/TTS giả lập và Core thật, chưa phải đánh giá chất lượng
provider hoặc full Audio E2E 7/7. Retry đầu vào dùng transcript đã lưu và bỏ qua ASR
khi replay; phục hồi TTS/artifact sau commit được tách sang PR output riêng.
Không thay đổi điều kiện identity, xác nhận hủy, nguồn slot hay cơ chế ghi Clinic.

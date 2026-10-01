# Mapping đầu vào audio vào Core

HTTP và LiveKit dùng `caller_input_from_transcript` để tạo `CallerInput`.
Hàm này giữ nguyên transcript, số lượt, URL nguồn và confidence; không chọn intent,
không xác minh danh tính và không suy ra trạng thái điện thoại. Core vẫn xử lý qua
cùng Extraction → Policy → Dialogue → Output Guard → FSM → Session.

## Quy trình HTTP

1. Kiểm tra đầu vào khớp mode đã mở: audio không nhận text, text không nhận audio URL.
2. Khi `silence_ms > 0`, bỏ qua tải clip và ASR dù request có `audio_url`.
   Tạo lượt im lặng với `text=None`, không có confidence; giữ URL để nhận diện request.
3. Core kiểm tra phiên, thứ tự lượt và request trùng trong khóa session trước khi gọi
   resolver của transport. Chỉ lượt chưa có transcript mới tải clip và chạy ASR.
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

## Retry đầu vào và phục hồi output

- Request audio được nhận diện bằng số lượt, `audio_url` và `silence_ms`; transcript là
  kết quả ASR, không phải trường do HTTP client gửi. URL clip phải bất biến trong cửa sổ
  retry. Không thay nội dung clip tại cùng URL để gửi một đầu vào khác.
- Transcript thành công được lưu cùng bản ghi PROCESSING trước khi chạy IE/Policy.
  Khi worker bị ngắt trước commit, resolver dùng lại transcript đã lưu. Lượt COMPLETED
  dùng action cũ và không gọi ASR; đổi URL hoặc độ dài im lặng vẫn là `TURN_CONFLICT`.
  Text mode tiếp tục so sánh nguyên văn text, không chuẩn hóa request.
- Khóa Redis riêng của HTTP bao trọn Core và xuất audio, chờ tối đa 1 giây rồi trả
  `CALL_BUSY`. Khóa session vẫn là chốt thứ tự/state/API action dùng chung với phone/LiveKit.
  Mode được giữ cố định khi mở lại cùng `call_id`.
- TTS chỉ nhận `action.utterance` đã qua Output Guard. HTTP audio mode trả `200` khi
  đã lưu WAV hoàn chỉnh; thiếu audio, TTS lỗi/timeout hoặc storage lỗi trả
  `503 AUDIO_OUTPUT_UNAVAILABLE`. Không chuyển máy hay chạy lệnh Clinic bù vì lỗi phát âm.
- WAV được ghi vào file tạm rồi thay thế nguyên tử. SHA-256 nhận diện utterance đi kèm
  giúp retry dùng lại audio, không tổng hợp lần nữa. Nếu artifact đã bị dọn, lượt active
  có thể tổng hợp lại từ action đã commit mà không chạy lại nghiệp vụ.
- Lượt active phục hồi bằng action trong session. Với lượt terminal, session vẫn bị purge
  ngay; chỉ biên nhận output đang chờ được giữ riêng tối đa **120 giây**, gồm hash request
  và action đã Guard. Nó không chứa transcript, extraction, hồ sơ hay command payload;
  utterance có thể chứa thời gian lịch đã được phép công bố. Retry không kéo dài TTL.
  Biên nhận bị xóa ngay khi audio hoàn tất và không dùng để tiếp tục hội thoại.
- Retry đúng request terminal có biên nhận chỉ phát lại output. Sau khi biên nhận đã xóa
  hoặc hết TTL, các lượt tiếp tục trả `CALL_ENDED` như text mode. Nếu worker chết/Redis lỗi
  giữa commit terminal và lưu biên nhận, không thể phục hồi câu cũ; vẫn chặn gọi lại Core
  và không ghi Clinic lần hai. Kết quả ghi chưa xác định vẫn yêu cầu đối soát, không có
  biên nhận output để che lỗi đó.

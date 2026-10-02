# Retry đầu vào audio trước Core

HTTP gửi `CallerInput` với URL clip và resolver trả transcript; Core không import ASR
hay biết provider. SessionManager kiểm tra phiên, thứ tự và request trùng trong khóa
session trước khi gọi resolver.

- Lượt mới: ASR thành công rồi mới đặt chỗ PROCESSING, giữ transcript và thời điểm
  tiếp nhận. Lỗi tải clip/ASR không đặt chỗ lượt, không đổi counters hay ghi Clinic.
- PROCESSING có thể tiếp tục an toàn: dùng transcript đã lưu, không nhận dạng lại;
  lệnh ghi chưa rõ kết quả vẫn yêu cầu đối soát như trước.
- COMPLETED khi session active: dùng action đã qua Output Guard, không gọi ASR hay
  chạy IE/Policy/Dialogue/Clinic. Phiên đã đóng vẫn từ chối trước khi gọi resolver.
- Request audio so khớp số lượt, URL và `silence_ms`; transcript là kết quả provider,
  không phải đầu vào HTTP. URL phải bất biến trong cửa sổ retry. Đổi URL hoặc độ dài
  im lặng trả `TURN_CONFLICT`; text mode vẫn so sánh text nguyên văn.

STT span nằm dưới CORE span vì việc nhận dạng diễn ra sau kiểm tra session; vẫn dùng
cùng trace root, pseudonym và quy tắc không xuất transcript/URL ra log.

Regression kiểm tra ASR đổi transcript ở lần retry nhưng kết quả Core giữ nguyên,
URL khác bị từ chối trước ASR, lượt nhảy số/đã đóng không gọi ASR, worker bị ngắt sau
reserve dùng lại transcript. Cơ chế phục hồi TTS/artifact sau commit được mô tả trong
[mapping audio vào Core](audio-input-core.md).

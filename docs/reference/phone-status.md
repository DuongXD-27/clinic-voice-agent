# Tiếp nhận tín hiệu trạng thái điện thoại

`NO_ANSWER` và `LINE_BUSY` là kết quả quay số do nhà cung cấp điện thoại báo về (§4.2.5),
không được suy ra từ transcript của text/audio. Bộ trích xuất lời nói chỉ nhận diện
`VOICEMAIL`; ba lượt liên tiếp có `silence_ms > 0` vẫn tạo kết quả
`SILENCE` qua Policy hiện có.

`PhoneStatusAdapter` là lớp tiếp nhận trạng thái không phụ thuộc nhà cung cấp.
Hiện chưa kết nối nhà mạng. Khi tích hợp, nhà cung cấp cần ánh xạ kết quả quay số
sang `PhoneStatus` và gửi số lượt tiếp theo của cuộc gọi đã mở:

```python
from callbot.engine import PhoneStatus
from callbot.transports.phone import PhoneStatusAdapter

adapter = PhoneStatusAdapter(orchestrator)
action = adapter.handle_status(call_id, turn=1, status=PhoneStatus.LINE_BUSY)
```

Adapter chuyển tiếp `CallerInput` chỉ chứa trạng thái, không ghi trạng thái Clinic.
Core xử lý qua cùng cơ chế khóa phiên, thứ tự lượt, Policy, Dialogue, Output Guard,
FSM và Clinic Gateway mà HTTP/LiveKit sử dụng. API chấm điểm công khai giữ nguyên
và không có trường `phone_status`. Không được gửi trạng thái cùng lời nói hoặc tín hiệu im lặng.

Với outbound, kết quả được ghi qua `/appointments/{id}/unreachable`, body chỉ có
`unreachable_reason`, sử dụng cơ chế chống ghi trùng và phục hồi xung đột phiên bản hiện có.
Mock tự tăng `attempt_count`. Theo chính sách lưu giữ phiên đã kết thúc hiện có,
sự kiện trạng thái lặp lại hoặc đến muộn sau khi kết thúc sẽ báo `CallEnded`, không ghi Clinic thêm;
kết quả ghi chưa xác định sẽ chặn phiên để đối soát. Sự kiện sai thứ tự lượt báo
`TurnOutOfOrder`. Mỗi `call_id` phải định danh một lần gọi duy nhất.

Với inbound, busy/no-answer là sự kiện quay số không hợp lệ: Policy chuyển máy với
`SYSTEM_ERROR`, không ghi appointment. Khi tích hợp nhà cung cấp, cần phân biệt
quay số thất bại với ngắt kết nối sau khi đã nghe máy; ngắt kết nối không phải `NO_ANSWER`.

Kiểm thử hồi quy: `tests/transports/test_phone_status.py` gửi sự kiện trạng thái giả lập
đã chuẩn hóa vào Core thật và Clinic giả. `tests/engine/test_silence_line_signal.py`
kiểm tra transcript có thông báo tổng đài không tạo lệnh ghi quay số thất bại.

Thiết kế này thay thế cách suy ra busy/no-answer từ transcript được mô tả trong
kế hoạch T-08 ban đầu và các bằng chứng QA audio trước đây.

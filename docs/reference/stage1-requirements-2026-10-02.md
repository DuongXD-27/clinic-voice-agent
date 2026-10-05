# Đợt 1: chốt xác minh và lệnh ghi

Phạm vi: R-19, R-22, R-23, R-31, R-40 và R-41 theo bảng yêu cầu ngày 01/10/2026. Các mục dưới đây cập nhật những quy tắc tương ứng trong bản thiết kế IE v1.1 cũ.

## Định danh

- IE trả `PRESENT`, `ABSENT`, `MULTIPLE` hoặc `UNCERTAIN` riêng cho tên và ngày sinh. Chỉ `PRESENT` có giá trị và bằng chứng nguyên văn; chỉ trạng thái này được đưa sang Verifier. IE không đọc hồ sơ đối chiếu.
- Tên được chuẩn hóa Unicode, chữ hoa/thường, khoảng trắng và vị trí dấu tương đương. So theo thứ tự từng âm tiết, giữ nguyên ă/â/ê/ô/ơ/ư/đ. Thiếu hoặc khác âm tiết là `MISMATCH`.
- N chưa chốt. Theo quyết định của người dùng, mọi lệch dấu thanh là `SUSPICIOUS`, không được tự chấp nhận dù ngày sinh đúng. Ngày sinh so tuyệt đối.
- Không khớp thì chuyển máy ngay. Trường thiếu, nhiều giá trị, không chắc hoặc tên nghi ngờ được hỏi mở lại đúng trường, tối đa một lần. Bộ đếm từng trường lưu trong phiên và lượt hỏi lại dùng chung bộ đếm không hiểu.
- Lần hỏi lại vẫn không có giá trị chắc chắn thì `NOT_UNDERSTOOD`; tên vẫn nghi ngờ hoặc định danh không khớp thì `IDENTITY_FAILED` trên outbound. Inbound không có hồ sơ duy nhất khớp dùng `PATIENT_NOT_FOUND` theo R-09.
- Lời chào hoặc nhu cầu nghiệp vụ không cung cấp định danh cũng thuộc `ABSENT`, không được dùng để kéo dài số lần hỏi lại. Im lặng vẫn dùng bộ đếm riêng; xin nhắc lại và yêu cầu chờ vẫn có cách xử lý riêng.
- Confidence STT dưới 0.5 là tín hiệu bổ sung để xếp `UNCERTAIN`. Confidence cao không khôi phục tên/ngày sinh bị luật đánh dấu phân vân, phủ định hoặc nhiều giá trị.

## Model và xác nhận

- NER tên và semantic dùng chung ngân sách: một lời gọi trong một lượt, không retry. Thời hạn nhận đủ kết quả tối đa 3 giây; cấu hình kết nối bị chặn ở 1 giây.
- `TIMEOUT`, `ERROR`, `INVALID` làm ý định về `NONE` và đồng ý về `UNCLEAR`. Lượt đó tính không hiểu, chặn ghi nghiệp vụ ở cả Dialogue và invariant trước Gateway. Các câu xác nhận được hỏi đóng lại; hỏi định danh vẫn là câu mở theo R-40.
- Provider đồng bộ chạy trong worker có giới hạn số lượng. Kết quả đến sau deadline bị bỏ, không quay lại phiên. Request đang chạy có thể kết thúc sau khi lượt đã trả về; worker không có quyền gọi Clinic.
- Event `ie.model` chỉ ghi `model`, `latency_ms`, `model_result`; không chứa transcript, prompt hay span.
- “Dạ” đơn thuần không bao giờ là đồng ý. “Dạ vâng” có từ đồng ý độc lập và vẫn phải qua ngưỡng của hành động.
- Câu có tín hiệu đồng ý và phủ định/đổi ý phải hỏi lại có/không. Invariant kiểm tra lại transcript của lượt và bằng chứng trước khi ghi, không tin riêng nhãn của model. Câu hỏi “được không?” và lời từ chối thuần túy vẫn đi theo luồng hỏi lại/từ chối.
- `/transfer` vẫn được phép ghi `TRANSFERRED`; khóa lỗi model chỉ cấm các lệnh ghi nghiệp vụ của lượt.

## Đầu ra

Output Guard dùng allow-list theo trạng thái: không trường nào ở `AWAITING_IDENTITY`; `starts_at`, `clinic`, `status` ở `AWAITING_INTENT`, `AWAITING_CONFIRMATION`, `CLOSING`; thêm `slot_id` ở `OFFERING_SLOTS`, vẫn phải có nguồn GET /slots trong cuộc gọi. Response kết thúc thành công được kiểm như `CLOSING`.

Guard dựng lại câu bằng dữ liệu đã chiếu qua allow-list, chặn mặc định trường lạ, và kiểm tra giá trị được bảo vệ ngay trên câu cuối. Số điện thoại, mã bệnh nhân/lịch hẹn, tên bác sĩ và lý do khám không được nói. Hộp thư thoại không được mở trường lịch hẹn nào. Bộ lọc hiện có tiếp tục là cửa chung trước response HTTP và TTS.

Các ca nghiệm thu tập trung nằm ở `tests/engine/test_stage1_requirements.py`; các test cũ chấp nhận mất dấu, “dạ”, nhiều lần hỏi định danh hoặc ghi sau lỗi model đã được cập nhật theo quy tắc mới.

Đợt này không sửa endpoint R-12, cửa sổ tìm slot, hay các hạng mục điện thoại và lời thoại R-42.

## Kiểm chứng

Ngày 02/10/2026: toàn bộ repo **3.794 passed, 9 skipped**. Chạy Python với `-X utf8` trên Windows, thư mục tạm riêng trong `temp/`; các dịch vụ bên ngoài được thay bằng fixture offline. Các ca cần Redis thật, model/asset bổ sung hoặc Clinic Mock thật giữ điều kiện bỏ qua hiện có. Ruff lint, kiểm tra định dạng những file thay đổi và `git diff --check` đều qua.

Ngày 05/10/2026: khi chuẩn bị PR, hợp nhất với main mới nhất và giữ giao diện `SlotFillingResult`, tracing cùng các biến thể lời thoại hiện có. Các test trên main dùng lại tên sau lỗi model hoặc coi lời chào là lượt hỏi lại miễn phí được cập nhật theo quy tắc đợt 1. Kiểm thử offline toàn bộ repo trên branch PR: **4.172 passed, 9 skipped, 2 warnings**. Ruff lint, định dạng 47 file Python thay đổi và kiểm tra diff đều qua. Hai bộ eval Book/Reschedule đã có trên main ở commit `75e61bd`, không có thay đổi CSV trong PR và chưa chạy bộ eval.

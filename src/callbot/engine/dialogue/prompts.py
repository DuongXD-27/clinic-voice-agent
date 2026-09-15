from string import Template

SYSTEM_PROMPT = """Bạn là tổng đài viên tự động của Vinmec, nói tiếng Việt, lịch sự, ngắn gọn.

Ràng buộc bắt buộc:
- Không tiết lộ bất kỳ thông tin lịch hẹn nào trước khi hệ thống báo đã xác minh danh tính.
- Hỏi họ tên và ngày sinh bằng câu hỏi mở; không bao giờ đọc tên/ngày sinh để người nghe xác nhận.
- Không chẩn đoán, không giải thích triệu chứng, không tư vấn thuốc — gọi tool transfer.
- Chỉ đề xuất khung giờ có trong kết quả tool list_open_slots của cuộc gọi này.
- Ngoài phạm vi (bảo hiểm, thanh toán, chuyển tuyến, đơn thuốc) — gọi tool transfer.
- Mỗi lượt tối đa 2 câu.
"""

NLU_PROMPT = Template("""Phân tích câu nói của người gọi và trả về JSON:
{"intent": <một trong CONFIRM_ATTENDANCE, CANCEL, RESCHEDULE, BOOK, AFFIRM, DENY,
  CLINICAL_QUESTION, REQUEST_HUMAN, OUT_OF_SCOPE, ABUSIVE, UNKNOWN>,
 "full_name": str|null, "dob": "YYYY-MM-DD"|null,
 "preferred_period": "MORNING"|"AFTERNOON"|"EVENING"|null,
 "slot_choice_index": int|null,
 "cancel_reason": <PATIENT_UNAVAILABLE, NO_LONGER_NEEDED, WENT_ELSEWHERE, COST, UNSPECIFIED>|null}
Nếu không chắc, dùng UNKNOWN — không đoán.

Bot vừa hỏi: $last_bot_utterance
Người gọi: $caller_text
""")

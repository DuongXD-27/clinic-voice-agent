"""Bộ câu đo TTS dùng chung cho mọi provider (ADR-002) — cùng bộ này đã chạy cho ZeroTTS trên Colab 20/9.

27 câu thật của bot: 7 câu cố định, 5 câu ngày giờ theo `speak_datetime`, 4 tên riêng ba miền,
2 ngày sinh, 3 số điện thoại/mã lịch, 5 thuật ngữ y tế, 1 câu dài ~230 ký tự.
`entities`: mỗi phần tử là danh sách biến thể chấp nhận được (judge ASR có thể ghi "9h30" hay "chín giờ ba mươi").
Không có PII thật — tên/số/ngày đều là dữ liệu bịa để đo.
"""

TEST_SET: list[dict] = [
    # --- câu cố định của bot ---
    {"id": "greet_out", "kind": "fixed", "text": "Dạ em xin chào anh chị, em là trợ lý ảo AI của tổng đài Vinmec. Cho em hỏi em đang nói chuyện với anh chị nào ạ?", "entities": [["vinmec"], ["trợ lý ảo"]]},
    {"id": "greet_in", "kind": "fixed", "text": "Dạ Vinmec xin nghe, em là trợ lý ảo AI của tổng đài. Anh chị vui lòng cho em biết họ tên đầy đủ ạ?", "entities": [["vinmec"]]},
    {"id": "ask_dob", "kind": "fixed", "text": "Dạ, anh chị cho em xin ngày tháng năm sinh ạ.", "entities": [["ngày tháng năm sinh"]]},
    {"id": "ask_intent", "kind": "fixed", "text": "Cảm ơn anh chị. Anh chị cần em hỗ trợ gì ạ?", "entities": []},
    {"id": "transfer", "kind": "fixed", "text": "Dạ, em xin phép chuyển máy cho nhân viên để hỗ trợ anh chị thêm ạ.", "entities": [["chuyển máy"]]},
    {"id": "silence", "kind": "fixed", "text": "Alo, anh chị còn nghe máy không ạ?", "entities": []},
    {"id": "cancel_reconfirm", "kind": "fixed", "text": "Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?", "entities": [["hủy lịch"]]},
    # --- ngày giờ (speak_datetime: '9 giờ 30 sáng ngày 14 tháng 10') ---
    {"id": "readback_1", "kind": "datetime", "text": "Dạ, em xin xác nhận lại: 9 giờ 30 sáng ngày 14 tháng 10 tại Vinmec Times City. Anh chị đồng ý chứ ạ?", "entities": [["9 giờ 30", "chín giờ ba mươi", "9h30"], ["ngày 14 tháng 10", "mười bốn tháng mười", "14/10"], ["times city", "time city"]]},
    {"id": "readback_2", "kind": "datetime", "text": "Dạ, em giữ nguyên lịch khám 3 giờ chiều ngày 2 tháng 11 tại Vinmec Central Park cho anh chị. Anh chị có đến khám được theo lịch này không ạ?", "entities": [["3 giờ chiều", "ba giờ chiều", "15 giờ"], ["ngày 2 tháng 11", "mùng 2 tháng 11", "hai tháng mười một", "2/11"], ["central park"]]},
    {"id": "summary", "kind": "datetime", "text": "Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 8 giờ sáng ngày 21 tháng 10 tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ?", "entities": [["nội tổng quát"], ["8 giờ", "tám giờ"], ["ngày 21 tháng 10", "hai mươi mốt tháng mười", "21/10"]]},
    {"id": "offer_slots", "kind": "datetime", "text": "Dạ, hiện còn khung 1 là 10 giờ sáng ngày 15 tháng 10; khung 2 là 2 giờ 15 chiều ngày 16 tháng 10. Anh chị chọn khung nào ạ?", "entities": [["khung 1", "khung một"], ["10 giờ", "mười giờ"], ["ngày 15 tháng 10", "mười lăm tháng mười", "15/10"], ["khung 2", "khung hai"], ["2 giờ 15", "hai giờ mười lăm", "14 giờ 15", "2h15"], ["ngày 16 tháng 10", "mười sáu tháng mười", "16/10"]]},
    {"id": "done_resched", "kind": "datetime", "text": "Dạ, em đã đặt lịch 7 giờ 45 sáng ngày 3 tháng 12 cho anh chị ạ.", "entities": [["7 giờ 45", "bảy giờ bốn mươi lăm", "7h45"], ["ngày 3 tháng 12", "mùng 3 tháng 12", "ba tháng mười hai", "3/12"]]},
    # --- tên riêng 3 miền ---
    {"id": "name_north", "kind": "name", "text": "Dạ, em xin xác nhận anh chị là Nguyễn Thị Hồng Nhung đúng không ạ?", "entities": [["nguyễn thị hồng nhung"]]},
    {"id": "name_central", "kind": "name", "text": "Dạ, em xin xác nhận anh chị là Trần Văn Quốc Bảo đúng không ạ?", "entities": [["trần văn quốc bảo"]]},
    {"id": "name_south", "kind": "name", "text": "Dạ, em xin xác nhận anh chị là Huỳnh Ngọc Phương Trinh đúng không ạ?", "entities": [["huỳnh ngọc phương trinh"]]},
    {"id": "name_hard", "kind": "name", "text": "Dạ, em xin xác nhận anh chị là Đặng Khắc Duy Khương đúng không ạ?", "entities": [["đặng khắc duy khương"]]},
    # --- ngày sinh (chỉ đọc lại SAU khi đã xác minh) ---
    {"id": "dob_1", "kind": "dob", "text": "Dạ, ngày sinh 14 tháng 3 năm 1978 em đã ghi nhận ạ.", "entities": [["14 tháng 3", "mười bốn tháng ba", "14/3"], ["1978", "một nghìn chín trăm bảy mươi tám", "một chín bảy tám"]]},
    {"id": "dob_2", "kind": "dob", "text": "Dạ, ngày sinh 5 tháng 11 năm 2001 em đã ghi nhận ạ.", "entities": [["5 tháng 11", "năm tháng mười một", "mùng 5 tháng 11", "5/11"], ["2001", "hai nghìn không trăm lẻ một", "hai không không một"]]},
    # --- số điện thoại, mã lịch ---
    {"id": "phone_1", "kind": "code", "text": "Dạ, em sẽ gọi lại số 0912 345 600 cho anh chị ạ.", "entities": [["0912345600", "0912 345 600", "không chín một hai ba bốn năm sáu không không"]]},
    {"id": "phone_2", "kind": "code", "text": "Dạ, số điện thoại 0987654321 đúng chưa ạ?", "entities": [["0987654321", "0987 654 321", "không chín tám bảy sáu năm bốn ba hai một"]]},
    {"id": "apt_code", "kind": "code", "text": "Dạ, mã lịch hẹn của anh chị là A P T 0 0 4 1 7 ạ.", "entities": [["apt 00417", "a p t 0 0 4 1 7", "apt00417", "a-p-t 00417"]]},
    # --- thuật ngữ y tế / khoa ---
    {"id": "dept_1", "kind": "medical", "text": "Dạ, lịch khám của anh chị thuộc khoa Tai Mũi Họng ạ.", "entities": [["tai mũi họng"]]},
    {"id": "dept_2", "kind": "medical", "text": "Dạ, lịch khám của anh chị thuộc khoa Sản Phụ khoa ạ.", "entities": [["sản phụ khoa"]]},
    {"id": "dept_3", "kind": "medical", "text": "Dạ, lịch khám của anh chị thuộc khoa Chẩn đoán hình ảnh ạ.", "entities": [["chẩn đoán hình ảnh"]]},
    {"id": "dept_4", "kind": "medical", "text": "Dạ, lịch khám của anh chị thuộc khoa Tim mạch, bác sĩ Lê Minh Khôi ạ.", "entities": [["tim mạch"], ["lê minh khôi"]]},
    {"id": "clinical_scope", "kind": "medical", "text": "Dạ, về câu hỏi chuyên môn, em xin phép chuyển máy để bác sĩ tư vấn trực tiếp cho anh chị ạ.", "entities": [["bác sĩ"], ["chuyển máy"]]},
    # --- câu dài (gần 300 ký tự — ngưỡng Vbee) ---
    {"id": "long_1", "kind": "long", "text": "Dạ, em xin tóm tắt lại: anh chị Nguyễn Thị Hồng Nhung có lịch khám Nội tổng quát lúc 9 giờ 30 sáng ngày 14 tháng 10 tại Vinmec Times City. Anh chị muốn giữ lịch này, đổi sang khung giờ khác, hay hủy lịch ạ? Em xin nghe anh chị ạ.", "entities": [["nguyễn thị hồng nhung"], ["nội tổng quát"], ["9 giờ 30", "chín giờ ba mươi", "9h30"], ["ngày 14 tháng 10", "mười bốn tháng mười", "14/10"], ["times city", "time city"]]},
]

TOTAL_CHARS = sum(len(t["text"]) for t in TEST_SET)
LONGEST = max(TEST_SET, key=lambda t: len(t["text"]))

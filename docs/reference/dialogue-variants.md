# Biến thể lời thoại — đợt đầu

Mỗi nhóm câu giao tiếp thường gặp có bốn cách nói soạn sẵn. Bot chọn biến thể trong core,
trước Output Guard và TTS, nên HTTP và LiveKit dùng cùng lời thoại. Không gọi thêm LLM.

## Phạm vi

- 24 nhóm câu tĩnh: chào/giới thiệu AI, hỏi tên và ngày sinh, hỏi lại, hỏi nhu cầu,
  đổi hay hủy, chờ, chuyển máy, kết thúc không liên lạc được, hỏi ngày/buổi muốn đặt/đổi.
- 8 renderer động: `APPOINTMENT_SUMMARY`, `ATTENDANCE_READBACK`, `ATTENDANCE_REREAD`,
  `KEEP_APPOINTMENT`, `CANCEL_READBACK`, `OFFER_SLOTS`, `SLOT_OFFER_READBACK`, `SLOT_READBACK`.
- Câu hỏi xác nhận cuối mỗi renderer giữ nguyên. Ngày, giờ, thứ, chuyên khoa và cơ sở
  được dựng theo các hàm nguồn hiện có; số slot, thứ tự và lời báo hết/kín khung cũng giữ đúng.

`CANCEL_CHOICE`, `CANCEL_REASON_NOTED` giữ nguyên wording và ngưỡng xác nhận hủy.
`CANCEL_READBACK` (06/10/2026) đọc lại lịch sắp hủy theo biến thể, rồi kết thúc bằng nguyên văn
`CANCEL_RECONFIRM`; câu này không còn được nói riêng. `SLOT_READBACK_DA` giữ hướng dẫn nói rõ “đồng ý”. Các câu báo đã ghi thành công,
fallback `DONE_SAFE`, tiền tố xử lý xung đột slot và câu nhắc im lặng tiếp tục dùng câu chuẩn.

## Cách chọn và kiểm tra

`variants.choose_variant` lấy offset từ BLAKE2s của `call_id` + nhóm câu, rồi xoay theo
`ctx.turn` qua `v0`..`v3`. Cùng mã gọi, nhóm và lượt luôn cho cùng lựa chọn, kể cả giữa
worker hoặc sau restart. Hai lượt liền nhau của cùng nhóm chọn khác nhau. Đây là biến thể
được chọn có thể tái hiện, không phải sinh lời thoại tự do hoặc random trong renderer.

`questions.ask` chọn câu tĩnh trước khi lưu `ctx.question.text`. HOLD, handoff và kết thúc
được chọn tại Dialogue Manager/luồng mở đầu. Đọc lại khi người gọi yêu cầu, quay lại sau
khi chờ, hoặc im lặng dùng nguyên `ctx.question.text`; không chọn lại biến thể. SessionManager
replay lượt đang mở cũng trả đúng kết quả đã lưu. Cuộc gọi đã kết thúc có thể trả `CallEnded`
do nội dung phiên đã được xóa; không ghi Clinic lần hai.

Từng câu tĩnh đăng ký qua `static`. Renderer nhận `variant` tường minh với miền giá trị
đăng ký trong `str_args`, không lấy biến thể từ context hay RNG. Guard dựng lại từ snapshot
Clinic và các tham số đã ghi vào ledger, so nguyên văn và vẫn kiểm tra danh tính, slot,
receipt và câu hỏi đang chờ. Nhận diện lời chào dùng tập câu đã đăng ký thay vì một chuỗi cố định.

`v0` là câu gốc cho các caller gọi renderer trực tiếp. Các business test hiện có cố định
selector ở `v0` để giữ các kỳ vọng wording cũ. `test_dialogue_variants.py` override fixture
này, kiểm tra selector thật và ép cả bốn biến thể qua guard, confirm/cancel/book/reschedule,
nhắc lại, silence, restart và HTTP audio. TTS fake chỉ kiểm tra text truyền xuống và audio_url
có thể tải; không chứng minh giọng provider thật đọc đúng hoặc tự nhiên.

## Độ trễ và chi phí

Chọn câu chỉ dùng hash và tra bảng trong RAM, không thêm request model/provider. Chi phí
LLM không tăng do tính năng này. TTS vẫn tổng hợp câu được chọn; giá và thời gian tổng hợp
có thể đổi theo độ dài câu. Các câu tĩnh được kiểm tra không vượt 300 ký tự của adapter Vbee.
Dữ liệu động dài (chuyên khoa/cơ sở dài, danh sách kèm tiền tố và ngày kín) vẫn chịu giới hạn
provider hiện có; không cắt bỏ dữ kiện để làm câu ngắn hơn.

Trước khi kết luận hiệu quả audio, cần chạy cùng bộ cuộc gọi với provider đang deploy để so
p95 toàn lượt (gồm audio fetch, §5.3), tổng ký tự TTS và spend/cuộc gọi, rồi nghe thử audio
8 kHz. Test cục bộ không phải số đo độ trễ/chi phí cloud. Số biến thể càng nhiều thì cơ hội
cache audio cho một text cụ thể càng thấp; đợt này chưa thêm cache.

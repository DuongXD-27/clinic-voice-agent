# Đối chiếu baseline inbound với PRD 2.3

Nguồn: CALL-BOT VINMEC Product Requirements Document, phiên bản 2.3 ngày
07/10/2026, do người dùng cung cấp ngày 08/10. Đối chiếu source tại `fe4176e` và
hai cuộc TLS thực trên runtime `18fc43e`. Phạm vi là định danh và baseline inbound,
không phải xác nhận toàn bộ sản phẩm đạt PRD.

**Chưa tuân thủ đầy đủ.** PRD sửa R-40 ngày 06/10: tên không khớp vẫn hỏi ngày sinh
trước khi chuyển. Stage1 trong repo còn mô tả chuyển ngay; kết luận trước đó dựa vào
stage1 không còn đúng. 140 kiểm thử pass phản ánh hành vi cũ, không chứng minh đạt PRD.

| Yêu cầu | PRD 2.3 | Source/bằng chứng hiện tại | Đánh giá |
| --- | --- | --- | --- |
| R-40, GC-ID-04 | Tên KHÔNG KHỚP: hỏi ngày sinh nếu chưa có rồi mới chuyển; không hỏi lại tên chỉ vì không khớp, không nói trường nào sai. | `dialogue/manager.py::_identity` chuyển ngay khi `compare_name` trả MISMATCH. Hai cuộc mới đều chưa hỏi DOB. | Không đạt; lỗi luồng độc lập với ASR. |
| R-40, GC-ID-03/06 | Tên thiếu/chưa chắc/nhiều giá trị/nghi ngờ được hỏi mở lại tối đa một lần. | Cuộc 1 lượt đầu ABSENT được hỏi lại; lượt sau PRESENT/MISMATCH bị chuyển sớm. | Bước hỏi lại đầu đúng; cả cuộc vẫn không đạt GC-ID-04. |
| R-40: ngoại lệ | Chào, hỏi lý do xác minh, đòi đọc hồ sơ: mỗi loại một lần miễn đếm; từ lần hai tính KHÔNG CÓ. | `MAX_IDENTITY_QUESTIONS=2`, bộ đếm dùng chung và cờ chào riêng, chưa thể hiện ba loại đúng như PRD. | Cần đồng bộ và nghiệm thu từng loại. |
| R-22: phần họ | Bỏ qua lệch dấu ở họ, cho phép tối đa một âm tiết họ khác. | Replay: Nguyển Văn A / Nguyễn Văn A là SUSPICIOUS; Trần Văn A / Nguyễn Văn A là MISMATCH. | Không đạt các ví dụ này. Dung sai N ở phần tên vẫn chờ đo theo PRD. |
| R-22: phần tên | Khác chữ ở phần tên là KHÔNG KHỚP. | Nguyễn Văn An / Nguyễn Văn A là MISMATCH. | Phân loại đúng; thời điểm chuyển theo R-40 sai. |
| R-09: thiếu caller number | Hỏi số đã đăng ký, tra hồ sơ rồi hỏi tên/DOB; hỏi lại số một lần nếu chưa đọc được. | `IdentityVerifier.prepare` trả NO_PHONE/PATIENT_NOT_FOUND; không có ASK_PHONE trong luồng hiện tại. | Chưa triển khai đúng nhánh thiếu số. Có số nhưng không ra hồ sơ phải chuyển ngay theo PRD 2.3. |
| R-33/R-37 | Booking inbound dùng cùng Core; softphone là đường dự phòng. | Worker gọi cùng `create_orchestrator`, nhận caller SIP, cùng HTTP Clinic Mock. | Phù hợp cấu trúc; các cuộc mới chưa hoàn thành booking. |
| R-34/GC-LIVE-04 | Kiểm danh sách đồng ý bằng số nhà mạng trước hội thoại; số volunteer gắn vào hồ sơ giả. | Baseline dùng SIP identity tổng hợp; worker chưa có guard allow-list. Review này chưa kiểm lại hạn chế ở trunk/provider. | Chưa đủ bằng chứng nghiệm thu PSTN/consent; không kết luận thiếu guard ở mọi tầng. |
| R-05/R-09: chuyển nhân viên live | Chuyển nhân viên khi cần. | Core trả TRANSFERRED; callback SIP hiện RemoveParticipant và shutdown, chưa có tuyến chuyển tới nhân viên trong worker. | Mới có outcome và hangup, chưa chứng minh chuyển handset tới người thật. |
| GC-LIVE-02/06 | Booking thành công, đúng record mock; softphone dự phòng cho cùng kết quả. | Hai cuộc mới đều TRANSFERRED, không record mới, record cũ giữ nguyên. | Đợt này không đạt. Checklist ba booking của task vẫn 0/3; không gán ba cuộc thành điều kiện riêng của PRD. |

Transcript live của cả ba lượt tên chứa Nguyễn Văn An trong khi caller báo nói Nguyễn
Văn A. Confidence cao không chứng minh transcript đúng. Hai decoder offline vẫn cho
An trên ba cửa sổ RTP; đổi decoder đó chưa sửa mẫu lỗi. Không đổi mock hoặc tự sửa tên.

Hai cuộc đều đi qua grace 2000 ms rồi RemoveParticipant thành công. Chưa xác nhận caller
nghe trọn lời cuối; log removal không chứng minh playback handset hoặc chuyển nhân viên.

Hướng sửa: giữ bằng chứng tên PRESENT/MISMATCH, hỏi DOB bằng câu mở rồi mới kết thúc;
outbound dùng IDENTITY_FAILED, inbound không có đúng một hồ sơ khớp dùng PATIENT_NOT_FOUND.
Đồng bộ test, ngoại lệ R-40, luật phần họ R-22 và nhánh hỏi số R-09; kiểm guard consent và
tuyến chuyển người thật trước PSTN. Sửa ASR riêng: sửa thời điểm chuyển không làm An thành A.

Review này không đổi source/runtime, không gọi API speech hoặc chạy thêm cuộc gọi.
Bằng chứng:
[booking-tls-repeat-two-transferred.json](../../result/08-10-2026/sip-baseline/booking-tls-repeat-two-transferred.json).

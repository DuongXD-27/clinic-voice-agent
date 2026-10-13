# Danh sách câu thoại gửi PM duyệt — 12/10/2026

**Người thực hiện: Hưng. Trạng thái: chờ PM sửa câu chữ, sau đó thu lại audio.**

Bản này thay bản 08/10. Khác biệt: thêm một câu chuyển máy khi xác minh không đạt (A74), thêm hai ví dụ câu mời khung giờ đang sửa (B54, B55), và ghi chú về tốc độ giọng ở mục dưới.

## Phạm vi và cách duyệt

**74 câu cố định là toàn bộ danh sách dự kiến thu đợt này, chưa phải toàn bộ tình huống của kịch bản.** Số này tính từng cách nói khác nhau: một tình huống có thể có ba câu thay phiên nhau.

File gồm nguyên văn 74 câu cố định, 3 câu dự phòng hoãn thu, ví dụ cho đủ 15 mẫu dựng câu theo dữ liệu và 8 cụm dùng để ghép câu. Câu động có vô số giá trị ngày giờ; phần ví dụ giúp duyệt cách diễn đạt, không liệt kê mọi tổ hợp có thể phát sinh.

Các câu bên dưới lấy từ Engine hiện tại. 73 câu trong số này đã thu bằng Vbee ngày 08/10 và Hưng đã nghe đạt; câu A74 mới thêm, chưa thu. Các ví dụ câu động vẫn là review văn bản, chưa thu.

**Về tốc độ giọng.** Audio 08/10 thu ở tốc độ 1.0. Hệ thống hiện đã chuyển sang tốc độ 1.15, nên audio cũ không còn được dùng khi chạy. Sau khi PM chốt câu chữ, Hưng sẽ thu lại **toàn bộ** 74 câu ở tốc độ mới, không chỉ các câu đổi chữ. Nếu PM muốn nghe thử trước khi sửa, cần nghe bản thu ở tốc độ 1.15, không dùng bản 08/10.

**Cách góp ý.** PM sửa trực tiếp cột "Nguyên văn" hoặc ghi theo mã, ví dụ: "A12: thay ... bằng ...". Với nhóm có ba cách nói, cần duyệt cả ba. Mã A/B/C/D giữ nguyên so với bản 08/10 để đối chiếu được góp ý cũ.

**Tiêu chí ưu tiên khi sửa**, theo nhận xét của mentor "đặt mình vào người nhận cuộc gọi, có muốn nói tiếp không":

- Nói lý do trước rồi mới xin thông tin; không để người nhận thấy bị tra hỏi.
- Dùng từ của khách, không dùng từ nội bộ như "xác minh", "đối chiếu", "yêu cầu", "kết thúc cuộc gọi".
- Mỗi câu một ý, nối thành một hơi nói, một câu hỏi ở cuối.
- Khi khách vừa nói gì đó, mở đầu bằng tiếp nhận ngắn rồi mới hỏi tiếp.
- Hướng dẫn kiểu "nói 'hủy lịch' giúp em" chỉ nên xuất hiện ở lần hỏi lại, không ở câu hỏi đầu.

**Ràng buộc không được bỏ khi sửa:** câu chào đầu và câu chào lại phải có cụm "trợ lý ảo AI"; hỏi tên và ngày sinh bằng câu hỏi mở, không nêu tên hoặc ngày sinh để khách xác nhận; trước khi xác minh xong không nói ngày, giờ, khoa, cơ sở của lịch; câu xác nhận hủy lần hai giữ một nguyên văn; mỗi câu dưới 300 ký tự.

Việc đi hết mọi nhánh của 7 kịch bản vẫn chưa hoàn tất. Duyệt văn bản này chưa thay thế việc kiểm tra luồng và nghe audio trước khi đưa kịch bản vào bộ chấm.

## A. 74 câu cố định dự kiến thu

Thu nguyên câu sau khi chốt lời và nghe đạt. Câu báo đã đặt/đổi/hủy/xác nhận chỉ được dùng sau khi thao tác tương ứng thành công. Các câu "báo kết quả không đọc chi tiết" là phương án an toàn, không phải câu đọc lại ngày giờ.

### Chào đầu và giới thiệu lại

| Mã | Tình huống / cách nói | Nguyên văn | ID đối chiếu |
|---|---|---|---|
| A01 | Bot gọi ra | Em chào anh chị. Em là trợ lý ảo AI của tổng đài Vinmec. Anh chị cho em xin họ và tên đầy đủ ạ? | GREETING_OUTBOUND |
| A02 | Khách gọi vào | Tổng đài Vinmec xin nghe. Em là trợ lý ảo AI. Anh chị cho em xin họ và tên đầy đủ ạ? | GREETING_INBOUND |
| A03 | Khách gọi vào, chuyển nhân viên ngay | Tổng đài Vinmec xin nghe. Em là trợ lý ảo AI. Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ. | GREETING_HANDOFF_INBOUND |
| A04 | Khách hỏi lại ai đang gọi, tại bước hỏi tên — cách 1/3 | Em là trợ lý ảo AI của tổng đài Vinmec. Anh chị cho em xin họ và tên đầy đủ ạ. | GREETING_BACK_SHARED |
| A05 | Khách hỏi lại ai đang gọi, tại bước hỏi tên — cách 2/3 | Anh chị đang nói chuyện với trợ lý ảo AI của tổng đài Vinmec. Em xin họ và tên đầy đủ để đối chiếu ạ. | GREETING_BACK_SHARED_v1 |
| A06 | Khách hỏi lại ai đang gọi, tại bước hỏi tên — cách 3/3 | Tổng đài Vinmec đang hỗ trợ anh chị ạ. Em là trợ lý ảo AI. Anh chị cho em biết họ và tên đầy đủ ạ. | GREETING_BACK_SHARED_v2 |
| A07 | Giới thiệu lại tại bước hỏi ngày sinh — cách 1/3 | Em là trợ lý ảo AI của tổng đài Vinmec. Anh chị cho em xin ngày, tháng, năm sinh ạ. | INTRODUCE_AGAIN_ASK_DOB |
| A08 | Giới thiệu lại tại bước hỏi ngày sinh — cách 2/3 | Dạ, em là trợ lý ảo AI của tổng đài Vinmec. Em xin ngày, tháng, năm sinh để đối chiếu ạ. | INTRODUCE_AGAIN_ASK_DOB_v1 |
| A09 | Giới thiệu lại tại bước hỏi ngày sinh — cách 3/3 | Anh chị đang nói chuyện với trợ lý ảo AI của Vinmec. Anh chị đọc ngày, tháng, năm sinh giúp em ạ. | INTRODUCE_AGAIN_ASK_DOB_v2 |

### Xác minh họ tên và ngày sinh

| Mã | Tình huống / cách nói | Nguyên văn | ID đối chiếu |
|---|---|---|---|
| A10 | Cần xác minh trước khi hỗ trợ yêu cầu — cách 1/3 | Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. Anh chị cho em xin họ và tên đầy đủ ạ. | ASK_NAME_VERIFY_SHARED |
| A11 | Cần xác minh trước khi hỗ trợ yêu cầu — cách 2/3 | Em cần đối chiếu đúng người trước khi trao đổi thông tin lịch khám. Anh chị cho em biết họ và tên đầy đủ ạ. | ASK_NAME_VERIFY_SHARED_v1 |
| A12 | Cần xác minh trước khi hỗ trợ yêu cầu — cách 3/3 | Vì bảo mật, em xin họ và tên đầy đủ để xác minh rồi hỗ trợ anh chị ạ. | ASK_NAME_VERIFY_SHARED_v2 |
| A13 | Cần nghe lại họ tên — cách 1/3 | Anh chị cho em xin lại họ và tên đầy đủ ạ. | ASK_NAME_AGAIN |
| A14 | Cần nghe lại họ tên — cách 2/3 | Em chưa nghe rõ họ tên. Anh chị đọc lại họ và tên đầy đủ giúp em ạ. | ASK_NAME_AGAIN_v1 |
| A15 | Cần nghe lại họ tên — cách 3/3 | Dạ, anh chị nhắc lại họ và tên đầy đủ để em đối chiếu ạ. | ASK_NAME_AGAIN_v2 |
| A16 | Đã có ngày sinh, cần thêm họ tên — cách 1/3 | Anh chị cho em xin thêm họ và tên đầy đủ ạ. | ASK_NAME_AFTER_DOB |
| A17 | Đã có ngày sinh, cần thêm họ tên — cách 2/3 | Em xin thêm họ và tên đầy đủ của anh chị để đối chiếu ạ. | ASK_NAME_AFTER_DOB_v1 |
| A18 | Đã có ngày sinh, cần thêm họ tên — cách 3/3 | Anh chị cho em biết họ và tên đầy đủ để em hoàn tất xác minh ạ. | ASK_NAME_AFTER_DOB_v2 |
| A19 | Xin ngày sinh — cách 1/3 | Anh chị cho em xin ngày, tháng, năm sinh ạ. | ASK_DOB |
| A20 | Xin ngày sinh — cách 2/3 | Em xin thêm ngày, tháng, năm sinh để xác minh thông tin ạ. | ASK_DOB_v1 |
| A21 | Xin ngày sinh — cách 3/3 | Dạ, anh chị cho em biết ngày, tháng, năm sinh ạ. | ASK_DOB_v2 |
| A22 | Cần xác minh ngày sinh trước khi hỗ trợ — cách 1/3 | Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. Anh chị cho em xin ngày, tháng, năm sinh ạ. | ASK_DOB_VERIFY_SHARED |
| A23 | Cần xác minh ngày sinh trước khi hỗ trợ — cách 2/3 | Em cần đối chiếu ngày sinh trước khi trao đổi thông tin lịch khám. Anh chị đọc đủ ngày, tháng, năm sinh giúp em ạ. | ASK_DOB_VERIFY_SHARED_v1 |
| A24 | Cần xác minh ngày sinh trước khi hỗ trợ — cách 3/3 | Vì bảo mật, anh chị cho em biết ngày, tháng, năm sinh để em xác minh ạ. | ASK_DOB_VERIFY_SHARED_v2 |
| A25 | Cần nghe lại ngày sinh — cách 1/3 | Em chưa nghe rõ. Anh chị nhắc lại ngày, tháng, năm sinh giúp em ạ. | ASK_DOB_AGAIN |
| A26 | Cần nghe lại ngày sinh — cách 2/3 | Anh chị đọc lại đủ ngày, tháng, năm sinh giúp em ạ. | ASK_DOB_AGAIN_v1 |
| A27 | Cần nghe lại ngày sinh — cách 3/3 | Em xin nghe lại ngày, tháng và năm sinh của anh chị ạ. | ASK_DOB_AGAIN_v2 |

### Hỏi nhu cầu, nghe chưa rõ, chờ và kết thúc

| Mã | Tình huống / cách nói | Nguyên văn | ID đối chiếu |
|---|---|---|---|
| A28 | Đã xác minh, hỏi nhu cầu khách gọi vào — cách 1/3 | Cảm ơn anh chị. Anh chị cần em hỗ trợ gì ạ? | ASK_INTENT_INBOUND |
| A29 | Đã xác minh, hỏi nhu cầu khách gọi vào — cách 2/3 | Em đã xác minh xong. Anh chị cần hỗ trợ gì ạ? | ASK_INTENT_INBOUND_v1 |
| A30 | Đã xác minh, hỏi nhu cầu khách gọi vào — cách 3/3 | Cảm ơn anh chị. Em có thể giúp gì tiếp theo ạ? | ASK_INTENT_INBOUND_v2 |
| A31 | Chưa hiểu rõ yêu cầu — cách 1/3 | Em chưa hiểu rõ ý anh chị. Anh chị nói lại giúp em ạ. | NOT_UNDERSTOOD |
| A32 | Chưa hiểu rõ yêu cầu — cách 2/3 | Anh chị nói rõ hơn một chút giúp em được không ạ? | NOT_UNDERSTOOD_v1 |
| A33 | Chưa hiểu rõ yêu cầu — cách 3/3 | Em chưa nắm được yêu cầu. Anh chị nói lại yêu cầu giúp em ạ. | NOT_UNDERSTOOD_v2 |
| A34 | Khách xin chờ — cách 1/3 | Dạ, em chờ anh chị ạ. | HOLD |
| A35 | Khách xin chờ — cách 2/3 | Anh chị cứ từ từ, em đang nghe ạ. | HOLD_v1 |
| A36 | Khách xin chờ — cách 3/3 | Em giữ máy chờ anh chị ạ. | HOLD_v2 |
| A37 | Nhắc khi khách im lặng | Alo, anh chị còn nghe máy không ạ? | SILENCE |
| A38 | Kết thúc khi không tiếp tục trao đổi được — cách 1/3 | Em xin kết thúc cuộc gọi. Em chào anh chị ạ. | GOODBYE_UNREACHABLE |
| A39 | Kết thúc khi không tiếp tục trao đổi được — cách 2/3 | Em xin dừng cuộc gọi tại đây. Chào anh chị ạ. | GOODBYE_UNREACHABLE_v1 |
| A40 | Kết thúc khi không tiếp tục trao đổi được — cách 3/3 | Cảm ơn anh chị. Em xin kết thúc cuộc gọi ạ. | GOODBYE_UNREACHABLE_v2 |

### Xác nhận đến khám và hủy lịch

| Mã | Tình huống / cách nói | Nguyên văn | ID đối chiếu |
|---|---|---|---|
| A41 | Hỏi đổi hoặc hủy lịch — cách 1/3 | Anh chị muốn đổi lịch hay hủy lịch khám ạ? | ASK_CHANGE_OR_CANCEL |
| A42 | Hỏi đổi hoặc hủy lịch — cách 2/3 | Dạ, anh chị cần em hỗ trợ đổi lịch hay hủy lịch khám ạ? | ASK_CHANGE_OR_CANCEL_v1 |
| A43 | Hỏi đổi hoặc hủy lịch — cách 3/3 | Anh chị muốn chuyển sang giờ khác hay hủy lịch khám này ạ? | ASK_CHANGE_OR_CANCEL_v2 |
| A44 | Cần làm rõ đồng ý đến khám | Anh chị có đồng ý xác nhận đến khám theo lịch vừa đọc không ạ? | CONFIRM_CONFLICT |
| A45 | Cần làm rõ hủy hay giữ lịch | Anh chị muốn hủy hay giữ lịch khám ạ? Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ. | CANCEL_CHOICE |
| A46 | Đã ghi nhận lý do hủy, hỏi lại ý định | Em đã ghi nhận lý do. Anh chị muốn hủy lịch khám này đúng không ạ? Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ. | CANCEL_REASON_NOTED |
| A47 | Cần làm rõ đồng ý hủy | Anh chị có chắc chắn muốn hủy lịch khám này không ạ? Nếu đồng ý, anh chị nói “hủy lịch” giúp em ạ. | CANCEL_CONFLICT |
| A48 | Câu hỏi xác nhận hủy lần hai (giữ một nguyên văn) | Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ? | CANCEL_RECONFIRM |
| A49 | Đã xác nhận thành công, báo kết quả không đọc chi tiết | Em đã xác nhận lịch khám cho anh chị. Hẹn gặp anh chị ạ. | CONFIRMED_SAFE |
| A50 | Đã hủy thành công | Em đã hủy lịch khám cho anh chị ạ. | CANCELLED_SAFE |

### Đặt mới và đổi lịch

| Mã | Tình huống / cách nói | Nguyên văn | ID đối chiếu |
|---|---|---|---|
| A51 | Hỏi thời gian muốn đặt mới — cách 1/3 | Anh chị muốn đặt vào ngày nào hoặc buổi nào ạ? | ASK_SLOT_PREFERENCE_BOOK |
| A52 | Hỏi thời gian muốn đặt mới — cách 2/3 | Anh chị cho em biết ngày hoặc buổi muốn đặt lịch ạ. | ASK_SLOT_PREFERENCE_BOOK_v1 |
| A53 | Hỏi thời gian muốn đặt mới — cách 3/3 | Dạ, anh chị muốn đặt lịch vào ngày nào hoặc buổi nào ạ? | ASK_SLOT_PREFERENCE_BOOK_v2 |
| A54 | Hỏi thời gian muốn đổi sang — cách 1/3 | Anh chị muốn đổi sang ngày nào hoặc buổi nào ạ? | ASK_SLOT_PREFERENCE_RESCHEDULE |
| A55 | Hỏi thời gian muốn đổi sang — cách 2/3 | Anh chị cho em biết ngày hoặc buổi muốn đổi lịch sang ạ. | ASK_SLOT_PREFERENCE_RESCHEDULE_v1 |
| A56 | Hỏi thời gian muốn đổi sang — cách 3/3 | Dạ, anh chị muốn chuyển lịch sang ngày nào hoặc buổi nào ạ? | ASK_SLOT_PREFERENCE_RESCHEDULE_v2 |
| A57 | Cần làm rõ đồng ý với giờ vừa đọc | Anh chị có đồng ý với khung giờ vừa đọc không ạ? | SLOT_CONFLICT |
| A58 | Từ chối giờ gợi ý khi đặt mới | Anh chị muốn nghe giờ khác hay dừng đặt lịch ạ? | SLOT_REFUSE_CHOICE_BOOK |
| A59 | Từ chối giờ gợi ý khi đổi lịch | Anh chị muốn nghe giờ khác hay giữ lịch cũ ạ? | SLOT_REFUSE_CHOICE_RESCHEDULE |
| A60 | Đã đọc hết giờ phù hợp khi đặt mới | Em đã đọc hết giờ trống phù hợp. Anh chị muốn tìm ngày khác không ạ? | SLOT_EXHAUSTED_BOOK |
| A61 | Đã đọc hết giờ phù hợp khi đổi lịch | Em đã đọc hết giờ trống phù hợp. Anh chị muốn tìm ngày khác hay giữ lịch cũ ạ? | SLOT_EXHAUSTED_RESCHEDULE |
| A62 | Giờ vừa bị đặt, hết giờ phù hợp khi đặt mới | Giờ đó vừa có người đặt và không còn giờ phù hợp khác. Anh chị muốn tìm ngày khác không ạ? | SLOT_TAKEN_EXHAUSTED_BOOK |
| A63 | Giờ vừa bị đặt, hết giờ phù hợp khi đổi lịch | Giờ đó vừa có người đặt và không còn giờ phù hợp khác. Anh chị muốn tìm ngày khác hay giữ lịch cũ ạ? | SLOT_TAKEN_EXHAUSTED_RESCHEDULE |
| A64 | Dừng đặt mới, chưa tạo lịch — cách 1/3 | Em chưa đặt lịch nào cho anh chị. Anh chị cần em hỗ trợ gì thêm ạ? | BOOKING_ABANDONED |
| A65 | Dừng đặt mới, chưa tạo lịch — cách 2/3 | Dạ, chưa có lịch nào được đặt. Anh chị muốn em hỗ trợ việc gì khác ạ? | BOOKING_ABANDONED_v1 |
| A66 | Dừng đặt mới, chưa tạo lịch — cách 3/3 | Em chưa tạo lịch hẹn. Anh chị có cần hỗ trợ thêm không ạ? | BOOKING_ABANDONED_v2 |
| A67 | Đã đặt thành công, báo kết quả không đọc chi tiết | Em đã đặt lịch khám cho anh chị ạ. | BOOKED_SAFE |
| A68 | Đã đổi thành công, báo kết quả không đọc chi tiết | Em đã đổi lịch khám cho anh chị ạ. | RESCHEDULED_SAFE |

### Chuyển nhân viên hỗ trợ

| Mã | Tình huống / cách nói | Nguyên văn | ID đối chiếu |
|---|---|---|---|
| A69 | Chuyển nhân viên hỗ trợ | Em xin chuyển máy tới nhân viên để hỗ trợ anh chị ạ. | TRANSFER |
| A70 | Không có giờ trống, chuyển nhân viên | Hiện chưa có giờ trống. Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ. | NO_SLOTS_TRANSFER |
| A71 | Dừng tìm giờ, giữ lịch cũ và chuyển nhân viên | Lịch cũ của anh chị vẫn giữ nguyên. Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ. | ROUNDS_EXHAUSTED_TRANSFER |
| A72 | Giờ vừa bị đặt, không có giờ khác, chuyển nhân viên | Giờ đó vừa có người đặt và hiện chưa có giờ trống khác. Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ. | SLOT_TAKEN_NO_SLOTS_TRANSFER |
| A73 | Giờ vừa bị đặt, dừng tìm và chuyển nhân viên | Giờ đó vừa có người đặt. Lịch cũ vẫn giữ nguyên. Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ. | SLOT_TAKEN_ROUNDS_TRANSFER |
| A74 | **Mới.** Họ tên hoặc ngày sinh không khớp hồ sơ, không tìm thấy hồ sơ, hoặc nhiều hồ sơ cùng khớp: chuyển nhân viên, không nói trường nào sai | Em chưa xác minh được thông tin của anh chị. Em xin chuyển máy tới nhân viên để hỗ trợ anh chị ạ. | IDENTITY_FAILED_TRANSFER |

## B. Câu có dữ liệu thay đổi và câu ghép

**55 ví dụ, bao phủ đủ 15 mẫu dựng câu trong Engine.** Đây là câu render thật từ dữ liệu minh họa. Ngày giờ, khoa, cơ sở và số giờ còn lại sẽ thay theo dữ liệu cuộc gọi. Trước mắt chưa dựng sẵn audio cho nhóm này.

Dữ liệu minh họa: lịch cũ khoa Nội tổng quát, 15:30 ngày 14/10/2026 tại Vinmec Times City; giờ gợi ý là 10:30 và 15:30 ngày 15/10/2026, hoặc 09:00 ngày 16/10/2026. Các ví dụ có "hôm nay/đã qua" giả định thời điểm trao đổi là 14/10/2026. Đây là dữ liệu giả để duyệt lời.

Các dòng minh họa nhánh và cách diễn đạt, không khẳng định mọi tổ hợp tham số đều xuất hiện trong cuộc gọi thật. Mẫu hủy thành công trả về câu cố định đã có ở phần A; mẫu nhắc im lặng ghép lời nhắc với nguyên câu đang chờ.

| Mã | Tình huống | Nguyên văn minh họa | Mẫu đối chiếu |
|---|---|---|---|
| B01 | Tóm tắt lịch và hỏi có đến khám được không | Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ? | APPOINTMENT_SUMMARY |
| B02 | Đọc lại lịch để xác nhận đến khám | Em xin xác nhận lại: lịch khám Nội tổng quát 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ? | ATTENDANCE_READBACK |
| B03 | Đọc lại khi câu trả lời đến khám chưa rõ | Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị có đến khám được theo lịch này không ạ? | ATTENDANCE_REREAD |
| B04 | Đọc lịch sắp hủy và hỏi xác nhận lần hai | Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ? | CANCEL_READBACK |
| B05 | Giữ lịch cũ, đọc lại và hỏi đến khám | Lịch cũ của anh chị vẫn giữ nguyên: lịch khám Nội tổng quát 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị có đến khám được theo lịch này không ạ? | KEEP_APPOINTMENT |
| B06 | Đã xác nhận đến khám thành công | Em đã xác nhận lịch khám 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City cho anh chị. Hẹn gặp anh chị ạ. | CONFIRMED_DONE |
| B07 | Nguồn lịch không có tên khoa: không tự thêm khoa | Cảm ơn anh chị. Lịch khám của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ? | APPOINTMENT_SUMMARY |
| B08 | Ví dụ khi cơ sở trong nguồn khác | Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Phòng khám Đa khoa Cầu Giấy ạ. Anh chị có đến khám được theo lịch này không ạ? | APPOINTMENT_SUMMARY |
| B09 | Hai giờ cùng ngày — cách nói 1/4 | Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B10 | Hai giờ cùng ngày — cách nói 2/4 | Em còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B11 | Hai giờ cùng ngày — cách nói 3/4 | Em tìm được khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B12 | Hai giờ cùng ngày — cách nói 4/4 | Em có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B13 | Hai giờ khác ngày: đọc đủ ngày cho từng khung | Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 9 giờ sáng, thứ Sáu ngày 16 tháng 10. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B14 | Còn các giờ chưa đọc | Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Còn 3 khung khác. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B15 | Ngày yêu cầu kín lịch, gợi ý ngày gần nhất | Thứ Tư ngày 14 tháng 10 đã kín lịch. Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B16 | Chỉ đọc một giờ | Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị chọn giờ này không ạ? | OFFER_SLOTS |
| B17 | Khách chưa nêu ngày: gợi ý hai giờ và mời chọn ngày khác khi đặt mới | Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào, hoặc muốn đặt vào ngày khác ạ? | OFFER_SLOTS |
| B18 | Khách chưa nêu ngày: gợi ý một giờ và mời chọn ngày khác khi đặt mới | Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị chọn giờ này hay muốn đặt vào ngày khác ạ? | OFFER_SLOTS |
| B19 | Ngày yêu cầu kín lịch, đồng thời mời chọn ngày khác khi đặt mới | Thứ Tư ngày 14 tháng 10 đã kín lịch. Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào, hoặc muốn đặt vào ngày khác ạ? | OFFER_SLOTS |
| B20 | Khách chưa nêu ngày: gợi ý hai giờ và mời chọn ngày khác khi đổi lịch | Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào, hoặc muốn đổi sang ngày khác ạ? | OFFER_SLOTS |
| B21 | Khách chưa nêu ngày: gợi ý một giờ và mời chọn ngày khác khi đổi lịch | Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị chọn giờ này hay muốn đổi sang ngày khác ạ? | OFFER_SLOTS |
| B22 | Ngày yêu cầu kín lịch, đồng thời mời chọn ngày khác khi đổi lịch | Thứ Tư ngày 14 tháng 10 đã kín lịch. Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào, hoặc muốn đổi sang ngày khác ạ? | OFFER_SLOTS |
| B23 | Giờ khách chọn vừa có người đặt — câu ghép đầy đủ | Khung giờ đó vừa có người đặt. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B24 | Chưa tìm thấy giờ khách nói — câu ghép đầy đủ | Em chưa thấy khung giờ đó. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B25 | Nhiều giờ khớp yêu cầu — câu ghép đầy đủ | Có nhiều khung giờ phù hợp. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B26 | Khách chọn khung ngoài hai khung vừa đọc — câu ghép đầy đủ | Em vừa đọc hai khung thôi ạ. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B27 | Nhắc mỗi lượt chỉ đọc hai khung — câu ghép đầy đủ | Em đọc hai khung để dễ nhớ ạ. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | OFFER_SLOTS |
| B28 | Ngày không hợp lệ khi đặt mới | Ngày đó không có trong lịch ạ. Anh chị muốn đặt vào ngày nào ạ? | ASK_DATE_AGAIN |
| B29 | Ngày đã qua khi đặt mới | Thứ Ba ngày 13 tháng 10 đã qua rồi ạ. Anh chị muốn đặt vào ngày nào ạ? | ASK_DATE_AGAIN |
| B30 | Ngày khách nói trùng hôm nay khi đặt mới | Hôm nay là thứ Tư ngày 14 tháng 10. Anh chị muốn đặt vào hôm nay hay thứ Tư tuần sau ạ? | ASK_DATE_AGAIN |
| B31 | Thời gian khách nói chưa đủ cụ thể khi đặt mới | Anh chị muốn đặt vào ngày nào cụ thể ạ? | ASK_DATE_AGAIN |
| B32 | Ngày đã qua nhưng chưa có ngày cụ thể để đọc lại, khi đặt mới | Anh chị muốn đặt vào ngày nào cụ thể ạ? | ASK_DATE_AGAIN |
| B33 | Trùng hôm nay nhưng chưa có ngày cụ thể để đọc lại, khi đặt mới | Anh chị muốn đặt vào ngày nào cụ thể ạ? | ASK_DATE_AGAIN |
| B34 | Đọc một giờ phù hợp, hỏi đồng ý đặt mới | Em còn khung 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị đặt giờ đó nhé ạ? | SLOT_OFFER_READBACK |
| B35 | Ngày yêu cầu kín, đọc một giờ thay thế khi đặt mới | Thứ Tư ngày 14 tháng 10 đã kín lịch. Em còn khung 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị đặt giờ đó nhé ạ? | SLOT_OFFER_READBACK |
| B36 | Đọc lại giờ và cơ sở trước khi đặt mới | Em xác nhận đặt lịch 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ? | SLOT_READBACK |
| B37 | Khách chỉ nói "dạ", cần làm rõ đồng ý đặt mới | Anh chị đồng ý đặt lịch 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10 không ạ? Nếu đồng ý, anh chị nói “đồng ý” giúp em ạ. | SLOT_READBACK_DA |
| B38 | Ngày không hợp lệ khi đổi lịch | Ngày đó không có trong lịch ạ. Anh chị muốn đổi sang ngày nào ạ? | ASK_DATE_AGAIN |
| B39 | Ngày đã qua khi đổi lịch | Thứ Ba ngày 13 tháng 10 đã qua rồi ạ. Anh chị muốn đổi sang ngày nào ạ? | ASK_DATE_AGAIN |
| B40 | Ngày khách nói trùng hôm nay khi đổi lịch | Hôm nay là thứ Tư ngày 14 tháng 10. Anh chị muốn đổi sang hôm nay hay thứ Tư tuần sau ạ? | ASK_DATE_AGAIN |
| B41 | Thời gian khách nói chưa đủ cụ thể khi đổi lịch | Anh chị muốn đổi sang ngày nào cụ thể ạ? | ASK_DATE_AGAIN |
| B42 | Ngày đã qua nhưng chưa có ngày cụ thể để đọc lại, khi đổi lịch | Anh chị muốn đổi sang ngày nào cụ thể ạ? | ASK_DATE_AGAIN |
| B43 | Trùng hôm nay nhưng chưa có ngày cụ thể để đọc lại, khi đổi lịch | Anh chị muốn đổi sang ngày nào cụ thể ạ? | ASK_DATE_AGAIN |
| B44 | Đọc một giờ phù hợp, hỏi đồng ý đổi lịch | Em còn khung 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị đổi sang giờ đó nhé ạ? | SLOT_OFFER_READBACK |
| B45 | Ngày yêu cầu kín, đọc một giờ thay thế khi đổi lịch | Thứ Tư ngày 14 tháng 10 đã kín lịch. Em còn khung 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị đổi sang giờ đó nhé ạ? | SLOT_OFFER_READBACK |
| B46 | Đọc lại giờ và cơ sở trước khi đổi lịch | Em xác nhận đổi lịch sang 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ? | SLOT_READBACK |
| B47 | Khách chỉ nói "dạ", cần làm rõ đồng ý đổi lịch | Anh chị đồng ý đổi lịch sang 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10 không ạ? Nếu đồng ý, anh chị nói “đồng ý” giúp em ạ. | SLOT_READBACK_DA |
| B48 | Giờ vừa bị đặt, chỉ còn một giờ thay thế | Khung giờ đó vừa có người đặt. Em còn khung 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị đổi sang giờ đó nhé ạ? | SLOT_OFFER_READBACK |
| B49 | Đã đổi lịch thành công — hiện chưa đọc tên khoa, xem mục cần hoàn thiện | Em đã đổi lịch khám sang 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City cho anh chị ạ. | RESCHEDULED_DONE |
| B50 | Đã đặt mới thành công | Em đã đặt lịch 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City cho anh chị ạ. | BOOKED_DONE |
| B51 | Đã hủy thành công — trùng câu cố định A50, không thu thêm | Em đã hủy lịch khám cho anh chị ạ. | CANCELLED_DONE |
| B52 | Khách im lặng khi đang chờ ngày sinh: nhắc rồi hỏi lại nguyên câu | Alo, anh chị còn nghe máy không ạ? Anh chị cho em xin ngày, tháng, năm sinh ạ. | SILENCE_REPROMPT |
| B53 | Khách im lặng khi đang chờ trả lời lịch khám: nhắc rồi đọc lại nguyên câu | Alo, anh chị còn nghe máy không ạ? Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ? | SILENCE_REPROMPT |
| B54 | **Đang sửa, chưa vào bản chính.** Khách nói "chiều thứ Tư" mà có hai ngày cùng giờ: nêu đúng chỗ khác nhau thay vì đọc hai khung giống nhau | 3 giờ chiều thứ Tư em còn ngày 14 và ngày 21 tháng 10. Anh chị chọn ngày nào ạ? | OFFER_SLOTS |
| B55 | **Đang sửa, chưa vào bản chính.** Khách trả lời lại bằng giờ, bot hỏi thẳng hai lựa chọn | Dạ, anh chị chọn ngày 14 hay ngày 21 tháng 10 ạ? | OFFER_SLOTS |

## C. 3 câu dự phòng — hoãn thu

Ba mẫu này đã đăng ký nhưng luồng hội thoại hiện tại chưa chọn để phát; các tình huống từ chối cung cấp hoặc ngày sinh không hợp lệ đang được xử lý bằng câu hỏi lại chung ở phần A. Giữ để rà soát cách diễn đạt trước khi quyết định dùng hoặc bỏ; không tính vào 74 câu thu.

| Mã | Tình huống dự phòng | Nguyên văn | ID đối chiếu |
|---|---|---|---|
| C01 | Khách chưa đồng ý cung cấp ngày sinh | Em cần đối chiếu ngày sinh trước khi hỗ trợ. Anh chị cho em xin đủ ngày, tháng, năm sinh ạ. | ASK_DOB_DECLINED |
| C02 | Ngày sinh cần cung cấp lại đủ thông tin | Anh chị cho em xin đủ ngày, tháng, năm sinh theo dương lịch ạ. | ASK_DOB_INVALID |
| C03 | Khách chưa đồng ý cung cấp họ tên | Em cần đối chiếu họ tên trước khi hỗ trợ. Anh chị cho em xin họ và tên đầy đủ ạ. | ASK_NAME_DECLINED |

## D. 8 cụm ghép — không thu riêng thành câu

Các cụm này đã xuất hiện trong câu đầy đủ ở phần A/B. Liệt kê để PM thấy rõ từng phần; không tính thêm vào danh sách thu. Khi phát audio phải khớp toàn bộ câu bot nói.

| Mã | Cụm | Nguyên văn |
|---|---|---|
| D01 | Cụm công bố trợ lý ảo | trợ lý ảo AI |
| D02 | Câu hỏi đến khám, nối sau phần đọc lịch | Anh chị có đến khám được theo lịch này không ạ? |
| D03 | Mở đầu khi nhiều giờ khớp yêu cầu | Có nhiều khung giờ phù hợp. |
| D04 | Mở đầu khi khách chọn ngoài hai khung vừa đọc | Em vừa đọc hai khung thôi ạ. |
| D05 | Mở đầu khi không thấy giờ khách nói | Em chưa thấy khung giờ đó. |
| D06 | Mở đầu khi giờ vừa bị đặt | Khung giờ đó vừa có người đặt. |
| D07 | Mở đầu khi nhắc chỉ đọc hai khung | Em đọc hai khung để dễ nhớ ạ. |
| D08 | **Đang sửa.** Mở đầu khi hỏi lại hai lựa chọn (B55) | Dạ, |

## Các điểm còn cần hoàn thiện

- **Câu báo đổi lịch thành công (B49):** hiện đọc ngày, giờ và cơ sở, chưa đọc tên khoa. Sẽ bổ sung khoa từ lịch đã ghi thành công rồi gửi lại câu đã sửa để duyệt.
- **Khách đặt lịch mới nghe nhầm "lịch cũ":** khi khách gọi vào đặt mới và hết hai vòng chọn ngày, bot đang nói A71 "Lịch cũ của anh chị vẫn giữ nguyên…" dù khách chưa có lịch nào. Cần PM cho hai câu riêng cho nhánh đặt mới (hết vòng, và hết vòng khi giờ vừa bị đặt) để thu cùng đợt này.
- **Độ phủ tình huống:** cần đi đủ các nhánh của 7 kịch bản, nhất là xác minh không thành công, im lặng, chuyển nhân viên, hết giờ trống và giờ vừa bị đặt.
- **Câu ghép nhắc im lặng:** nếu muốn thu sẵn, cần liệt kê và duyệt nguyên câu ghép. Không dùng audio của riêng lời nhắc thay cho cả câu hỏi lại.
- **Chất lượng audio:** sau khi chốt lời, thu ở tốc độ 1.15 và nghe để kiểm đúng chữ, cách đọc "AI" và "Vinmec", nhịp ngắt, độ tự nhiên và độ dài. Câu chưa đạt quay lại sửa lời rồi thu lại đúng nguyên văn.

## Ghi nhận duyệt

- [ ] PM duyệt câu chữ phần A; ghi riêng những mã cần sửa.
- [ ] PM duyệt cách diễn đạt phần B; lưu ý B49 còn cần bổ sung khoa, B54–B55 đang sửa.
- [ ] PM cho hai câu mới cho nhánh đặt mới hết vòng (mục cần hoàn thiện).
- [ ] Thống nhất giữ hoặc sửa các mẫu dự phòng phần C sau khi kiểm tra luồng.
- [ ] Chốt tốc độ giọng 1.15 trước khi thu lại.

**Người duyệt:** …  **Ngày duyệt:** …

**Góp ý theo mã:** …

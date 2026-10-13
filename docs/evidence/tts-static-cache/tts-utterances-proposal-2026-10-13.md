# Câu thoại bản cuối — 13/10/2026

**Trạng thái: đã đưa vào code trên nhánh `feat/natural-utterances`; audio bản `2026-10-13-r4` đã thu và được duyệt; chưa deploy.** Toàn bộ kiểm thử đạt (5923). Cách deploy và xóa cache audio cũ trên server: xem mục "Audio bản r4 và xóa cache audio cũ". Bản này thay mọi bản đề xuất trước đó trong file này. Mã A/B/C/D theo [danh sách câu thoại gửi PM ngày 12/10](tts-utterances-pm-review-2026-10-12.md).

Tổng cộng: 74 câu cố định (sửa 62, giữ nguyên 12), 8 câu mới, 3 câu dự phòng; các mẫu câu có dữ liệu lịch (mục B) và các cụm ghép (mục D).

## Nguyên tắc chốt

1. **Chỉ đổi lời, không đổi luồng.** Không đổi state, không thêm lượt, không đổi luật hiểu câu trả lời. Chỉ thêm chỗ chọn câu ở vài điểm mà kết quả cuộc gọi không đổi (mục "Thay đổi code cần làm").
2. **Câu chào ngắn.** Nói "Vinmec" ngay đầu, không nói "trợ lý ảo AI". Câu mở đầu khoảng 22 âm tiết (chừng 4 giây ở tốc độ 1.15); câu chào lại khoảng 12–19 âm tiết.
3. **Trước khi xác minh chỉ được nói "lịch khám" chung chung**, không nói chi tiết: thời gian, địa điểm / cơ sở, khoa (quyết định của đội ngày 13/10/2026). **Câu có chi tiết lịch (mục B) chỉ nói sau khi xác minh**, và chi tiết lấy từ dữ liệu hệ thống.
4. **Xác minh tên, ngày sinh không khớp:** chỉ nói chung là chưa xác minh được (A74). **Khách gọi vào mà tra hồ sơ theo số không được:** nói rõ lý do (A03a–A03c).
5. **Lời nói tự nhiên.** Ít "Dạ" (cả bản chỉ còn một, ở A34). Mỗi lượt nói "anh chị" không quá hai lần; **"ạ" tối đa một lần**, đặt ở câu hỏi hoặc lời xin cuối lượt (hoặc lời chào kết thúc), câu thông báo đứng trước không thêm "ạ". Bỏ từ nội bộ: tổng đài, đối chiếu, yêu cầu, khung, kết thúc cuộc gọi. Câu chuyển máy dặn khách giữ máy. Câu báo xong việc có lời cảm ơn và chào.

## Không làm vì phải đổi luồng ở nhiều chỗ

| Hạng mục | Lý do |
|---|---|
| Nhắc lại khi khách im lặng chỉ đọc phần câu hỏi | Phải đổi cách ghép câu và sửa Output Guard (Guard kiểm câu nhắc theo đúng câu hỏi lượt trước). Giữ cách ghép hiện tại: lời nhắc A37 + nguyên câu đang chờ. |
| Mở đầu hai nhịp (chào trước, chờ khách đáp rồi mới hỏi tên) | Thêm một lượt, lệch với lời khách soạn sẵn trong bộ chấm. |
| Nhận diện câu "em là người hay máy?" | Thêm luật hiểu mới, có thể nhận nhầm lời khách trong bộ chấm. |

Câu PM chọn giữ nguyên (góp ý 13/10/2026): A10, A22, A47, A51, A54, A57, A62, A63, A72, A73, B02, B28, B38. Ngoài ra giữ A32, A48 (câu xác nhận hủy lần hai, một nguyên văn), B04 (kết thúc bằng A48) và B30, B40 (câu mới đọc gượng).

## A. Câu cố định

"Giữ nguyên" là dùng đúng câu đang chạy. "Mới" là câu chưa có trong Engine.

| Mã | Tình huống · ID | Đang chạy | Bản cuối |
|---|---|---|---|
| A01 | Bot gọi ra · `GREETING_OUTBOUND` | Em chào anh chị. Em là trợ lý ảo AI của tổng đài Vinmec. Anh chị cho em xin họ và tên đầy đủ ạ? | Em chào anh chị, em gọi từ Vinmec để xác nhận lịch khám. Anh chị cho em xin họ tên ạ? |
| A02 | Khách gọi vào · `GREETING_INBOUND` | Tổng đài Vinmec xin nghe. Em là trợ lý ảo AI. Anh chị cho em xin họ và tên đầy đủ ạ? | Vinmec xin nghe. Anh chị cho em xin họ tên ạ? |
| A03 | Khách gọi vào, tra hồ sơ theo số không được, lượt 0 · `GREETING_HANDOFF_INBOUND` | Tổng đài Vinmec xin nghe. Em là trợ lý ảo AI. Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ. | Vinmec xin nghe ạ. |
| A03a | **Mới.** Lượt 1 sau A03: không có số gọi đến hoặc số không đọc được | *(hiện nói A69)* | Em chưa nhận được số điện thoại anh chị đang gọi, nên em chuyển sang nhân viên tư vấn. Anh chị giữ máy chút nhé. |
| A03b | **Mới.** Lượt 1 sau A03: số gọi đến không có hồ sơ | *(hiện nói A69)* | Em chưa tìm thấy hồ sơ theo số anh chị đang gọi, nên em chuyển sang nhân viên tư vấn. Anh chị giữ máy chút nhé. |
| A03c | **Mới.** Lượt 1 sau A03: hệ thống tra cứu lỗi | *(hiện nói A69)* | Hệ thống tra cứu đang gặp sự cố, nên em chuyển sang nhân viên tư vấn. Anh chị giữ máy chút nhé. |
| A04 | Khách nói "alo" hoặc hỏi "ai đấy" ở bước hỏi tên, gọi ra — 1/3 · `GREETING_BACK_SHARED` | Em là trợ lý ảo AI của tổng đài Vinmec. Anh chị cho em xin họ và tên đầy đủ ạ. | Em gọi từ Vinmec để xác nhận lịch khám. Cho em xin họ tên ạ? |
| A05 | ″ — 2/3 · `GREETING_BACK_SHARED_v1` | Anh chị đang nói chuyện với trợ lý ảo AI của tổng đài Vinmec. Em xin họ và tên đầy đủ để đối chiếu ạ. | Vinmec đây, em gọi về lịch khám của anh chị. Mình tên đầy đủ là gì ạ? |
| A06 | ″ — 3/3 · `GREETING_BACK_SHARED_v2` | Tổng đài Vinmec đang hỗ trợ anh chị ạ. Em là trợ lý ảo AI. Anh chị cho em biết họ và tên đầy đủ ạ. | Bên em là Vinmec, gọi xác nhận lịch khám. Anh chị cho em xin họ tên nhé? |
| A04i | **Mới.** Như A04 nhưng khách gọi vào — 1/3 | *(hiện dùng chung A04–A06)* | Vinmec đây. Anh chị cho em xin họ tên ạ? |
| A05i | **Mới.** ″ — 2/3 | *(hiện dùng chung A04–A06)* | Bên em là Vinmec. Cho em xin họ tên của mình nhé? |
| A06i | **Mới.** ″ — 3/3 | *(hiện dùng chung A04–A06)* | Anh chị đang gọi tới Vinmec. Mình tên đầy đủ là gì ạ? |
| A07 | Khách hỏi "ai đấy" ở bước hỏi ngày sinh — 1/3 · `INTRODUCE_AGAIN_ASK_DOB` | Em là trợ lý ảo AI của tổng đài Vinmec. Anh chị cho em xin ngày, tháng, năm sinh ạ. | Vinmec đây. Anh chị cho em xin ngày tháng năm sinh ạ? |
| A08 | ″ — 2/3 · `INTRODUCE_AGAIN_ASK_DOB_v1` | Dạ, em là trợ lý ảo AI của tổng đài Vinmec. Em xin ngày, tháng, năm sinh để đối chiếu ạ. | Bên em là Vinmec. Anh chị sinh ngày tháng năm nào ạ? |
| A09 | ″ — 3/3 · `INTRODUCE_AGAIN_ASK_DOB_v2` | Anh chị đang nói chuyện với trợ lý ảo AI của Vinmec. Anh chị đọc ngày, tháng, năm sinh giúp em ạ. | Em bên Vinmec. Cho em xin ngày tháng năm sinh của mình nhé? |
| A10 | Khách hỏi lịch hoặc nêu nhu cầu trước khi xác minh, xin tên — 1/3 · `ASK_NAME_VERIFY_SHARED` | Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. Anh chị cho em xin họ và tên đầy đủ ạ. | Giữ nguyên |
| A11 | ″ — 2/3 · `ASK_NAME_VERIFY_SHARED_v1` | Em cần đối chiếu đúng người trước khi trao đổi thông tin lịch khám. Anh chị cho em biết họ và tên đầy đủ ạ. | Thông tin lịch khám là thông tin riêng, nên anh chị cho em xin họ tên đầy đủ trước để em tìm đúng hồ sơ ạ. |
| A12 | ″ — 3/3 · `ASK_NAME_VERIFY_SHARED_v2` | Vì bảo mật, em xin họ và tên đầy đủ để xác minh rồi hỗ trợ anh chị ạ. | Em hỗ trợ anh chị ngay sau khi tìm đúng hồ sơ. Cho em xin họ tên đầy đủ của mình ạ. |
| A13 | Nghe lại họ tên — 1/3 · `ASK_NAME_AGAIN` | Anh chị cho em xin lại họ và tên đầy đủ ạ. | Em nghe chưa rõ tên. Anh chị nhắc lại họ tên đầy đủ giúp em được không ạ? |
| A14 | ″ — 2/3 · `ASK_NAME_AGAIN_v1` | Em chưa nghe rõ họ tên. Anh chị đọc lại họ và tên đầy đủ giúp em ạ. | Xin lỗi anh chị, em chưa nghe kịp tên. Mình nói chậm lại giúp em nhé. |
| A15 | ″ — 3/3 · `ASK_NAME_AGAIN_v2` | Dạ, anh chị nhắc lại họ và tên đầy đủ để em đối chiếu ạ. | Anh chị đọc lại giúp em cả họ và tên đầy đủ ạ. |
| A16 | Đã có ngày sinh, cần thêm họ tên — 1/3 · `ASK_NAME_AFTER_DOB` | Anh chị cho em xin thêm họ và tên đầy đủ ạ. | Em cảm ơn. Còn họ tên đầy đủ của mình là gì ạ? |
| A17 | ″ — 2/3 · `ASK_NAME_AFTER_DOB_v1` | Em xin thêm họ và tên đầy đủ của anh chị để đối chiếu ạ. | Anh chị cho em xin thêm họ tên đầy đủ ạ. |
| A18 | ″ — 3/3 · `ASK_NAME_AFTER_DOB_v2` | Anh chị cho em biết họ và tên đầy đủ để em hoàn tất xác minh ạ. | Vâng, cho em biết thêm họ tên đầy đủ của anh chị nhé. |
| A19 | Đã có tên, xin ngày sinh — 1/3 · `ASK_DOB` | Anh chị cho em xin ngày, tháng, năm sinh ạ. | Em cảm ơn. Anh chị cho em xin ngày tháng năm sinh ạ. |
| A20 | ″ — 2/3 · `ASK_DOB_v1` | Em xin thêm ngày, tháng, năm sinh để xác minh thông tin ạ. | Anh chị sinh ngày tháng năm nào ạ? |
| A21 | ″ — 3/3 · `ASK_DOB_v2` | Dạ, anh chị cho em biết ngày, tháng, năm sinh ạ. | Cho em xin thêm ngày tháng năm sinh của mình nhé. |
| A22 | Như A10, đang chờ ngày sinh — 1/3 · `ASK_DOB_VERIFY_SHARED` | Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. Anh chị cho em xin ngày, tháng, năm sinh ạ. | Giữ nguyên |
| A23 | ″ — 2/3 · `ASK_DOB_VERIFY_SHARED_v1` | Em cần đối chiếu ngày sinh trước khi trao đổi thông tin lịch khám. Anh chị đọc đủ ngày, tháng, năm sinh giúp em ạ. | Thông tin lịch khám là thông tin riêng, nên anh chị cho em xin thêm ngày tháng năm sinh để em tìm đúng hồ sơ ạ. |
| A24 | ″ — 3/3 · `ASK_DOB_VERIFY_SHARED_v2` | Vì bảo mật, anh chị cho em biết ngày, tháng, năm sinh để em xác minh ạ. | Em hỗ trợ anh chị ngay sau khi tìm đúng hồ sơ. Cho em xin ngày tháng năm sinh của mình ạ. |
| A25 | Nghe lại ngày sinh — 1/3 · `ASK_DOB_AGAIN` | Em chưa nghe rõ. Anh chị nhắc lại ngày, tháng, năm sinh giúp em ạ. | Em nghe chưa rõ ngày sinh. Anh chị nhắc lại giúp em được không ạ? |
| A26 | ″ — 2/3 · `ASK_DOB_AGAIN_v1` | Anh chị đọc lại đủ ngày, tháng, năm sinh giúp em ạ. | Xin lỗi, em nghe chưa kịp. Anh chị nói chậm lại ngày tháng năm sinh giúp em nhé. |
| A27 | ″ — 3/3 · `ASK_DOB_AGAIN_v2` | Em xin nghe lại ngày, tháng và năm sinh của anh chị ạ. | Anh chị nói lại giúp em đủ cả ngày, tháng và năm sinh ạ. |
| A28 | Đã xác minh, hỏi nhu cầu khách gọi vào — 1/3 · `ASK_INTENT_INBOUND` | Cảm ơn anh chị. Anh chị cần em hỗ trợ gì ạ? | Em cảm ơn. Em có thể giúp gì cho anh chị ạ? |
| A29 | ″ — 2/3 · `ASK_INTENT_INBOUND_v1` | Em đã xác minh xong. Anh chị cần hỗ trợ gì ạ? | Em tìm thấy hồ sơ của mình rồi. Anh chị cần em hỗ trợ gì ạ? |
| A30 | ″ — 3/3 · `ASK_INTENT_INBOUND_v2` | Cảm ơn anh chị. Em có thể giúp gì tiếp theo ạ? | Cảm ơn anh chị. Hôm nay mình muốn đặt lịch khám, hay cần hỗ trợ việc gì khác ạ? |
| A31 | Chưa hiểu ý khách — 1/3 · `NOT_UNDERSTOOD` | Em chưa hiểu rõ ý anh chị. Anh chị nói lại giúp em ạ. | Em chưa hiểu rõ ý anh chị, mình nói lại giúp em nhé. |
| A32 | ″ — 2/3 · `NOT_UNDERSTOOD_v1` | Anh chị nói rõ hơn một chút giúp em được không ạ? | Giữ nguyên |
| A33 | ″ — 3/3 · `NOT_UNDERSTOOD_v2` | Em chưa nắm được yêu cầu. Anh chị nói lại yêu cầu giúp em ạ. | Xin lỗi, em nghe chưa rõ lắm. Anh chị nhắc lại giúp em ạ. |
| A34 | Khách xin chờ — 1/3 · `HOLD` | Dạ, em chờ anh chị ạ. | Dạ vâng, em chờ anh chị. |
| A35 | ″ — 2/3 · `HOLD_v1` | Anh chị cứ từ từ, em đang nghe ạ. | Anh chị cứ từ từ, em vẫn đang giữ máy. |
| A36 | ″ — 3/3 · `HOLD_v2` | Em giữ máy chờ anh chị ạ. | Không sao ạ, em đợi anh chị. |
| A37 | Nhắc khi khách im lặng · `SILENCE` | Alo, anh chị còn nghe máy không ạ? | Alo, anh chị có nghe em nói không ạ? |
| A38 | Không trao đổi tiếp được (im lặng, hộp thư thoại) — 1/3 · `GOODBYE_UNREACHABLE` | Em xin kết thúc cuộc gọi. Em chào anh chị ạ. | Em không nghe thấy anh chị nói, em xin phép gác máy. Chào anh chị ạ. |
| A39 | ″ — 2/3 · `GOODBYE_UNREACHABLE_v1` | Em xin dừng cuộc gọi tại đây. Chào anh chị ạ. | Em xin phép gác máy. Chào anh chị ạ. |
| A40 | ″ — 3/3 · `GOODBYE_UNREACHABLE_v2` | Cảm ơn anh chị. Em xin kết thúc cuộc gọi ạ. | Em cảm ơn anh chị, em xin phép gác máy ạ. |
| A41 | Khách không đến được, hỏi đổi hay hủy — 1/3 · `ASK_CHANGE_OR_CANCEL` | Anh chị muốn đổi lịch hay hủy lịch khám ạ? | Vậy anh chị muốn đổi sang hôm khác, hay hủy lịch này ạ? |
| A42 | ″ — 2/3 · `ASK_CHANGE_OR_CANCEL_v1` | Dạ, anh chị cần em hỗ trợ đổi lịch hay hủy lịch khám ạ? | Vâng, mình muốn dời lịch sang hôm khác, hay hủy luôn ạ? |
| A43 | ″ — 3/3 · `ASK_CHANGE_OR_CANCEL_v2` | Anh chị muốn chuyển sang giờ khác hay hủy lịch khám này ạ? | Anh chị muốn đổi giờ khám khác, hay hủy lịch khám này ạ? |
| A44 | Câu trả lời mâu thuẫn, hỏi lại có đến khám không · `CONFIRM_CONFLICT` | Anh chị có đồng ý xác nhận đến khám theo lịch vừa đọc không ạ? | Em hỏi lại cho chắc: anh chị vẫn đến khám theo lịch này, đúng không ạ? |
| A45 | Làm rõ hủy hay giữ lịch · `CANCEL_CHOICE` | Anh chị muốn hủy hay giữ lịch khám ạ? Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ. | Anh chị muốn hủy lịch, hay vẫn giữ lịch ạ? Nếu hủy, anh chị nói giúp em hai chữ “hủy lịch”. |
| A46 | Khách kể lý do, hỏi có hủy không · `CANCEL_REASON_NOTED` | Em đã ghi nhận lý do. Anh chị muốn hủy lịch khám này đúng không ạ? Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ. | Em hiểu rồi. Vậy anh chị muốn hủy lịch khám này, đúng không ạ? |
| A47 | Câu trả lời mâu thuẫn, hỏi lại có hủy không · `CANCEL_CONFLICT` | Anh chị có chắc chắn muốn hủy lịch khám này không ạ? Nếu đồng ý, anh chị nói “hủy lịch” giúp em ạ. | Giữ nguyên |
| A48 | Xác nhận hủy lần hai · `CANCEL_RECONFIRM` | Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ? | Giữ nguyên |
| A49 | Đã xác nhận đến khám, không đọc chi tiết · `CONFIRMED_SAFE` | Em đã xác nhận lịch khám cho anh chị. Hẹn gặp anh chị ạ. | Em đã xác nhận lịch khám cho anh chị rồi. Em cảm ơn, hẹn gặp anh chị ạ. |
| A50 | Đã hủy thành công · `CANCELLED_SAFE` | Em đã hủy lịch khám cho anh chị ạ. | Em đã hủy lịch khám cho anh chị rồi. Em cảm ơn, chào anh chị ạ. |
| A51 | Hỏi thời gian muốn đặt mới — 1/3 · `ASK_SLOT_PREFERENCE_BOOK` | Anh chị muốn đặt vào ngày nào hoặc buổi nào ạ? | Giữ nguyên |
| A52 | ″ — 2/3 · `ASK_SLOT_PREFERENCE_BOOK_v1` | Anh chị cho em biết ngày hoặc buổi muốn đặt lịch ạ. | Mình muốn đi khám vào ngày nào, buổi nào ạ? |
| A53 | ″ — 3/3 · `ASK_SLOT_PREFERENCE_BOOK_v2` | Dạ, anh chị muốn đặt lịch vào ngày nào hoặc buổi nào ạ? | Anh chị tiện hôm nào để em tìm giờ trống ạ? |
| A54 | Hỏi thời gian muốn đổi sang — 1/3 · `ASK_SLOT_PREFERENCE_RESCHEDULE` | Anh chị muốn đổi sang ngày nào hoặc buổi nào ạ? | Giữ nguyên |
| A55 | ″ — 2/3 · `ASK_SLOT_PREFERENCE_RESCHEDULE_v1` | Anh chị cho em biết ngày hoặc buổi muốn đổi lịch sang ạ. | Mình muốn dời lịch sang ngày nào, buổi nào ạ? |
| A56 | ″ — 3/3 · `ASK_SLOT_PREFERENCE_RESCHEDULE_v2` | Dạ, anh chị muốn chuyển lịch sang ngày nào hoặc buổi nào ạ? | Anh chị tiện hôm nào để em tìm giờ trống mới ạ? |
| A57 | Câu trả lời mâu thuẫn, hỏi lại giờ vừa đọc · `SLOT_CONFLICT` | Anh chị có đồng ý với khung giờ vừa đọc không ạ? | Giữ nguyên |
| A58 | Từ chối giờ gợi ý khi đặt mới · `SLOT_REFUSE_CHOICE_BOOK` | Anh chị muốn nghe giờ khác hay dừng đặt lịch ạ? | Anh chị muốn nghe thêm giờ khác, hay thôi chưa đặt lịch ạ? |
| A59 | Từ chối giờ gợi ý khi đổi lịch · `SLOT_REFUSE_CHOICE_RESCHEDULE` | Anh chị muốn nghe giờ khác hay giữ lịch cũ ạ? | Anh chị muốn nghe thêm giờ khác, hay giữ lịch cũ ạ? |
| A60 | Đã đọc hết giờ phù hợp, đặt mới · `SLOT_EXHAUSTED_BOOK` | Em đã đọc hết giờ trống phù hợp. Anh chị muốn tìm ngày khác không ạ? | Em đã báo hết các giờ trống phù hợp rồi. Anh chị có muốn tìm sang ngày khác không ạ? |
| A61 | Đã đọc hết giờ phù hợp, đổi lịch · `SLOT_EXHAUSTED_RESCHEDULE` | Em đã đọc hết giờ trống phù hợp. Anh chị muốn tìm ngày khác hay giữ lịch cũ ạ? | Em đã báo hết các giờ trống phù hợp rồi. Anh chị muốn tìm ngày khác, hay giữ lịch cũ ạ? |
| A62 | Giờ vừa bị đặt, hết giờ phù hợp, đặt mới · `SLOT_TAKEN_EXHAUSTED_BOOK` | Giờ đó vừa có người đặt và không còn giờ phù hợp khác. Anh chị muốn tìm ngày khác không ạ? | Giữ nguyên |
| A63 | Giờ vừa bị đặt, hết giờ phù hợp, đổi lịch · `SLOT_TAKEN_EXHAUSTED_RESCHEDULE` | Giờ đó vừa có người đặt và không còn giờ phù hợp khác. Anh chị muốn tìm ngày khác hay giữ lịch cũ ạ? | Giữ nguyên |
| A64 | Dừng đặt mới, chưa tạo lịch — 1/3 · `BOOKING_ABANDONED` | Em chưa đặt lịch nào cho anh chị. Anh chị cần em hỗ trợ gì thêm ạ? | Vâng, em chưa đặt lịch nào cho anh chị. Mình cần em hỗ trợ gì thêm không ạ? |
| A65 | ″ — 2/3 · `BOOKING_ABANDONED_v1` | Dạ, chưa có lịch nào được đặt. Anh chị muốn em hỗ trợ việc gì khác ạ? | Em dừng đặt lịch nhé, chưa có lịch nào được tạo. Anh chị cần hỗ trợ việc gì khác không ạ? |
| A66 | ″ — 3/3 · `BOOKING_ABANDONED_v2` | Em chưa tạo lịch hẹn. Anh chị có cần hỗ trợ thêm không ạ? | Lịch hẹn chưa được tạo. Anh chị còn cần em giúp gì nữa không ạ? |
| A67 | Đã đặt thành công, không đọc chi tiết · `BOOKED_SAFE` | Em đã đặt lịch khám cho anh chị ạ. | Em đã đặt lịch khám cho anh chị rồi. Em cảm ơn, hẹn gặp anh chị ạ. |
| A68 | Đã đổi thành công, không đọc chi tiết · `RESCHEDULED_SAFE` | Em đã đổi lịch khám cho anh chị ạ. | Em đã đổi lịch khám cho anh chị rồi. Em cảm ơn, hẹn gặp anh chị ạ. |
| A69 | Chuyển nhân viên · `TRANSFER` | Em xin chuyển máy tới nhân viên để hỗ trợ anh chị ạ. | Em chuyển máy sang nhân viên tư vấn để hỗ trợ mình, anh chị giữ máy giúp em một chút nhé. |
| A70 | Không có giờ trống, chuyển nhân viên · `NO_SLOTS_TRANSFER` | Hiện chưa có giờ trống. Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ. | Hiện chưa có giờ trống phù hợp. Em chuyển máy sang nhân viên tư vấn để tìm thêm giúp mình, anh chị giữ máy một chút nhé. |
| A71 | Hết vòng tìm giờ khi đổi lịch, chuyển nhân viên · `ROUNDS_EXHAUSTED_TRANSFER` | Lịch cũ của anh chị vẫn giữ nguyên. Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ. | Lịch cũ của anh chị vẫn giữ nguyên. Em chuyển máy sang nhân viên tư vấn để tìm giờ phù hợp hơn, mình giữ máy giúp em nhé. |
| A71b | **Mới.** Như A71 nhưng khi đặt mới (khách chưa có lịch cũ) | *(hiện nói A71)* | Em chưa tìm được giờ phù hợp. Em chuyển máy sang nhân viên tư vấn để hỗ trợ mình tìm giờ khác, anh chị giữ máy một chút nhé. |
| A72 | Giờ vừa bị đặt, không còn giờ khác, chuyển nhân viên · `SLOT_TAKEN_NO_SLOTS_TRANSFER` | Giờ đó vừa có người đặt và hiện chưa có giờ trống khác. Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ. | Giữ nguyên |
| A73 | Giờ vừa bị đặt, hết vòng khi đổi lịch, chuyển nhân viên · `SLOT_TAKEN_ROUNDS_TRANSFER` | Giờ đó vừa có người đặt. Lịch cũ vẫn giữ nguyên. Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ. | Giữ nguyên |
| A73b | **Mới.** Như A73 nhưng khi đặt mới | *(hiện nói A73)* | Giờ đó vừa có người đặt. Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ. |
| A74 | Họ tên, ngày sinh không khớp, không có hồ sơ, hoặc nhiều hồ sơ cùng khớp · `IDENTITY_FAILED_TRANSFER` | Em chưa xác minh được thông tin của anh chị. Em xin chuyển máy tới nhân viên để hỗ trợ anh chị ạ. | Em chưa xác minh được thông tin, nên em chuyển máy sang nhân viên tư vấn để hỗ trợ anh chị. Mình giữ máy giúp em một chút nhé. |
| C01 | Dự phòng, chưa dùng: khách chưa muốn cho ngày sinh · `ASK_DOB_DECLINED` | Em cần đối chiếu ngày sinh trước khi hỗ trợ. Anh chị cho em xin đủ ngày, tháng, năm sinh ạ. | Em hiểu. Vì lịch khám là thông tin riêng, em cần ngày tháng năm sinh của anh chị mới hỗ trợ tiếp được. Anh chị cho em xin nhé. |
| C02 | Dự phòng, chưa dùng: ngày sinh không hợp lệ · `ASK_DOB_INVALID` | Anh chị cho em xin đủ ngày, tháng, năm sinh theo dương lịch ạ. | Ngày này em nghe chưa đúng lắm. Anh chị cho em xin lại ngày tháng năm sinh theo dương lịch ạ. |
| C03 | Dự phòng, chưa dùng: khách chưa muốn cho họ tên · `ASK_NAME_DECLINED` | Em cần đối chiếu họ tên trước khi hỗ trợ. Anh chị cho em xin họ và tên đầy đủ ạ. | Em hiểu. Vì lịch khám là thông tin riêng, em cần họ tên đầy đủ của anh chị mới hỗ trợ tiếp được. Anh chị cho em xin nhé. |

## B. Câu có dữ liệu lịch

- **Chỉ nói sau khi xác minh.** Mọi mẫu dưới đây (trừ báo hủy thành công, không có dữ liệu) gọi `assert_can_disclose` và bị Output Guard chặn nếu chưa xác minh (OG-1, SF-03). Bản cuối không đổi các chốt chặn này.
- **Chi tiết lấy từ hệ thống.**
  - Ngày, giờ, khoa, cơ sở lấy từ lịch hẹn mà Gateway đọc từ Clinic.
  - Giờ trống chỉ lấy từ kết quả tra giờ trống của chính cuộc gọi đó (SF-02).
  - Câu được dựng bằng các hàm đọc ngày giờ và cơ sở đang có của Engine (`speak_datetime`, `clinic_name`). Bản cuối chỉ đổi lời bao quanh.
- **Ví dụ dưới đây dựng từ dữ liệu hệ thống**: seed của mock deploy (`seed_mentor_mock` trong `src/clinic_mock_sim/store.py`). Cột "Đang chạy" là câu do chính hàm dựng câu hiện tại sinh ra. Ngày khách nói (B29) và "hôm nay" (B30, B40) là giá trị minh họa, không phải dữ liệu lịch.
- Câu có dữ liệu luôn sinh giọng trực tiếp, không dùng audio dựng sẵn, nên không cần thu lại.

| Mã | Mẫu · ID | Dữ liệu hệ thống | Đang chạy | Bản cuối |
|---|---|---|---|---|
| B01 | `APPOINTMENT_SUMMARY` | apt_00417 | Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ? | Em cảm ơn. Anh chị có lịch khám Nội tổng quát lúc 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Hôm đó mình đến khám được không ạ? |
| B01 | `APPOINTMENT_SUMMARY` | apt_00419 | Cảm ơn anh chị. Lịch khám Tim mạch của anh chị là 9 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ? | Em cảm ơn. Anh chị có lịch khám Tim mạch lúc 9 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City. Hôm đó mình đến khám được không ạ? |
| B02 | `ATTENDANCE_READBACK` | apt_00417 | Em xin xác nhận lại: lịch khám Nội tổng quát 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ? | Giữ nguyên |
| B03 | `ATTENDANCE_REREAD` | apt_00417 | Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị có đến khám được theo lịch này không ạ? | Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Hôm đó mình đến khám được không ạ? |
| B04 | `CANCEL_READBACK` | apt_00417 | Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ? | Giữ nguyên |
| B05 | `KEEP_APPOINTMENT` | apt_00417 | Lịch cũ của anh chị vẫn giữ nguyên: lịch khám Nội tổng quát 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Anh chị có đến khám được theo lịch này không ạ? | Vâng, em giữ nguyên lịch cũ: khám Nội tổng quát lúc 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City. Hôm đó mình đến khám được không ạ? |
| B06 | `CONFIRMED_DONE` | apt_00417 | Em đã xác nhận lịch khám 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City cho anh chị. Hẹn gặp anh chị ạ. | Em đã xác nhận lịch khám 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City cho anh chị. Em cảm ơn, hẹn gặp anh chị hôm đó ạ. |
| — | `CURRENT_TIME_CHOICE` | apt_00417 | Dạ, 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10 là giờ lịch hiện tại của anh chị. Anh chị muốn giữ lịch cũ hay chọn giờ khác ạ? | 3 giờ 30 chiều, thứ Tư ngày 14 tháng 10 đang là lịch hiện tại của anh chị. Mình muốn giữ lịch này, hay chọn giờ khác ạ? |
| B09–B12 | `OFFER_SLOTS`, hai giờ cùng ngày | slot_b501, slot_b502 | Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn giờ nào ạ? |
| B13 | `OFFER_SLOTS`, hai giờ khác ngày | slot_b501, slot_b503 | Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 9 giờ sáng, thứ Sáu ngày 16 tháng 10. Anh chị chọn khung nào ạ? | Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 9 giờ sáng, thứ Sáu ngày 16 tháng 10. Anh chị chọn giờ nào ạ? |
| B14 | `OFFER_SLOTS`, còn giờ chưa đọc | slot_b501, slot_b502 (+3) | Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Còn 3 khung khác. Anh chị chọn khung nào ạ? | Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Ngoài ra còn 3 giờ khác nữa. Anh chị chọn giờ nào ạ? |
| B15 | `OFFER_SLOTS`, ngày khách xin đã kín | slot_b501, slot_b502; khách xin 14/10 | Thứ Tư ngày 14 tháng 10 đã kín lịch. Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | Thứ Tư ngày 14 tháng 10 đã kín lịch rồi. Gần nhất còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn giờ nào ạ? |
| B16 | `OFFER_SLOTS`, một giờ | slot_91d2 | Hiện còn khung 1: 3 giờ chiều, thứ Tư ngày 14 tháng 10. Anh chị chọn giờ này không ạ? | Hiện còn trống 3 giờ chiều, thứ Tư ngày 14 tháng 10. Anh chị lấy giờ này được không ạ? |
| B17 | `OFFER_SLOTS`, khách chưa nêu ngày, đặt mới | slot_b501, slot_b502 | Gần nhất có khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào, hoặc muốn đặt vào ngày khác ạ? | Gần nhất còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn một trong hai giờ này, hay muốn đặt ngày khác ạ? |
| B18 | `OFFER_SLOTS`, khách chưa nêu ngày, một giờ, đổi lịch | slot_91d2 | Gần nhất có khung 1: 3 giờ chiều, thứ Tư ngày 14 tháng 10. Anh chị chọn giờ này hay muốn đổi sang ngày khác ạ? | Gần nhất còn trống 3 giờ chiều, thứ Tư ngày 14 tháng 10. Anh chị lấy giờ này, hay muốn đổi sang ngày khác ạ? |
| B23 | `OFFER_SLOTS`, giờ vừa có người đặt | slot_b501, slot_b502 | Khung giờ đó vừa có người đặt. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | Giờ đó vừa có người đặt. Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn giờ nào ạ? |
| B24 | `OFFER_SLOTS`, không thấy giờ khách nói | slot_b501, slot_b502 | Em chưa thấy khung giờ đó. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | Giờ đó em chưa thấy trống. Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn giờ nào ạ? |
| B25 | `OFFER_SLOTS`, nhiều giờ khớp | slot_b501, slot_b503 | Có nhiều khung giờ phù hợp. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 9 giờ sáng, thứ Sáu ngày 16 tháng 10. Anh chị chọn khung nào ạ? | Có vài giờ phù hợp với anh chị. Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 9 giờ sáng, thứ Sáu ngày 16 tháng 10. Anh chị chọn giờ nào ạ? |
| B26 | `OFFER_SLOTS`, khách chọn ngoài hai giờ | slot_b501, slot_b502 | Em vừa đọc hai khung thôi ạ. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | Em vừa báo hai giờ thôi. Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn giờ nào ạ? |
| B27 | `OFFER_SLOTS`, nhắc mỗi lần hai giờ | slot_b501, slot_b502 | Em đọc hai khung để dễ nhớ ạ. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | Em báo mỗi lần hai giờ cho dễ nhớ. Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn giờ nào ạ? |
| — | `OFFER_SLOTS`, khách xin chọn lại | slot_b501, slot_b502 | Dạ, em đọc lại để anh chị chọn ạ. Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Anh chị chọn khung nào ạ? | Em đọc lại để anh chị chọn nhé. Hiện còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, và 3 giờ 30 chiều cùng ngày. Anh chị chọn giờ nào ạ? |
| B54 | `OFFER_SLOTS`, hai giờ cùng ngày, nêu chỗ khác nhau | slot_b501, slot_b502 | Thứ Năm ngày 15 tháng 10 em còn 10 giờ 30 sáng và 3 giờ 30 chiều. Anh chị chọn giờ nào ạ? | Thứ Năm ngày 15 tháng 10 em còn trống 10 giờ 30 sáng và 3 giờ 30 chiều. Anh chị chọn giờ nào ạ? |
| B54 | `OFFER_SLOTS`, cùng giờ hai ngày | slot_b502, slot_b506 | 3 giờ 30 chiều em còn thứ Năm ngày 15 và thứ Hai ngày 19 tháng 10. Anh chị chọn ngày nào ạ? | 3 giờ 30 chiều em còn trống thứ Năm ngày 15 và thứ Hai ngày 19 tháng 10. Anh chị chọn ngày nào ạ? |
| B55 | `OFFER_SLOTS`, hỏi lại hai lựa chọn | slot_b502, slot_b506 | Dạ, anh chị chọn thứ Năm ngày 15 hay thứ Hai ngày 19 tháng 10 ạ? | Vậy anh chị chọn thứ Năm ngày 15 hay thứ Hai ngày 19 tháng 10 ạ? |
| B28, B38 | `ASK_DATE_AGAIN`, ngày không có trên lịch | — | Ngày đó không có trong lịch ạ. Anh chị muốn đặt vào ngày nào ạ? | Giữ nguyên |
| B29 | `ASK_DATE_AGAIN`, ngày đã qua, đặt mới | khách nói 13/10, hôm nay 14/10 | Thứ Ba ngày 13 tháng 10 đã qua rồi ạ. Anh chị muốn đặt vào ngày nào ạ? | Thứ Ba ngày 13 tháng 10 đã qua rồi. Anh chị muốn đặt hôm nào ạ? |
| B30, B40 | `ASK_DATE_AGAIN`, trùng hôm nay | hôm nay 14/10 | Hôm nay là thứ Tư ngày 14 tháng 10. Anh chị muốn đổi sang hôm nay hay thứ Tư tuần sau ạ? | Giữ nguyên |
| B31 | `ASK_DATE_AGAIN`, chưa đủ cụ thể, đặt mới | — | Anh chị muốn đặt vào ngày nào cụ thể ạ? | Anh chị muốn đặt cụ thể hôm nào ạ? |
| B34 | `SLOT_OFFER_READBACK`, đặt mới | slot_b501 | Em còn khung 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị đặt giờ đó nhé ạ? | Em còn trống 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị đặt giờ này được không ạ? |
| B48 | `SLOT_OFFER_READBACK`, giờ vừa bị đặt, đổi lịch | slot_b503 | Khung giờ đó vừa có người đặt. Em còn khung 9 giờ sáng, thứ Sáu ngày 16 tháng 10. Anh chị đổi sang giờ đó nhé ạ? | Giờ đó vừa có người đặt. Em còn trống 9 giờ sáng, thứ Sáu ngày 16 tháng 10. Anh chị đổi sang giờ này được không ạ? |
| B36 | `SLOT_READBACK`, đặt mới | slot_b501 | Em xác nhận đặt lịch 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ? | Vậy em đặt lịch cho anh chị lúc 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City nhé. Anh chị đồng ý không ạ? |
| B46 | `SLOT_READBACK`, đổi lịch | slot_b501 | Em xác nhận đổi lịch sang 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ? | Vậy em đổi lịch của anh chị sang 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City nhé. Anh chị đồng ý không ạ? |
| B37 | `SLOT_READBACK_DA`, đặt mới | slot_b501 | Anh chị đồng ý đặt lịch 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10 không ạ? Nếu đồng ý, anh chị nói “đồng ý” giúp em ạ. | Anh chị đồng ý đặt lịch 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10 không ạ? Nếu đồng ý, anh chị nói giúp em “đồng ý”. |
| B49 | `RESCHEDULED_DONE` | slot_b501 | Em đã đổi lịch khám sang 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City cho anh chị ạ. | Em đã đổi lịch khám sang 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City cho anh chị. Em cảm ơn, hẹn gặp anh chị hôm đó ạ. |
| B50 | `BOOKED_DONE` | slot_b501 | Em đã đặt lịch 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City cho anh chị ạ. | Em đã đặt lịch khám lúc 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10, tại Vinmec Times City cho anh chị. Em cảm ơn, hẹn gặp anh chị hôm đó ạ. |

Báo hủy thành công (`CANCELLED_DONE`, B51) trả về đúng câu A50. Nhắc im lặng (`SILENCE_REPROMPT`, B52, B53) giữ cách ghép hiện tại: lời nhắc A37 mới + nguyên câu đang chờ.

## C. Câu dự phòng

C01–C03 nằm trong bảng A ở trên (chưa dùng trong luồng hiện tại).

## D. Cụm ghép

| Mã | ID | Đang chạy | Bản cuối |
|---|---|---|---|
| D01 | `AI_DISCLOSURE` | trợ lý ảo AI | Giữ trong code, không dùng trong câu chào nữa |
| D02 | `ASK_ATTENDANCE` (câu hỏi cuối B01, B03, B05) | Anh chị có đến khám được theo lịch này không ạ? | Hôm đó mình đến khám được không ạ? |
| D03 | `SLOT_AMBIGUOUS` | Có nhiều khung giờ phù hợp. | Có vài giờ phù hợp với anh chị. |
| D04 | `SLOT_NOT_IN_PAGE` | Em vừa đọc hai khung thôi ạ. | Em vừa báo hai giờ thôi. |
| D05 | `SLOT_NO_MATCH` | Em chưa thấy khung giờ đó. | Giờ đó em chưa thấy trống. |
| D06 | `SLOT_TAKEN` | Khung giờ đó vừa có người đặt. | Giờ đó vừa có người đặt. |
| D07 | `SLOT_TWO_AT_A_TIME` | Em đọc hai khung để dễ nhớ ạ. | Em báo mỗi lần hai giờ cho dễ nhớ. |
| D08 | `SLOT_AMBIGUOUS_AGAIN` | Dạ, | Vậy |
| D09 | `SLOT_RECHOOSE` | Dạ, em đọc lại để anh chị chọn ạ. | Em đọc lại để anh chị chọn nhé. |
| D10 | Số giờ chưa đọc, trong `OFFER_SLOTS` | Còn {n} khung khác. | Ngoài ra còn {n} giờ khác nữa. |
| D11 | Lời mở đầu khi đọc giờ trống, trong `OFFER_SLOTS` | "Hiện còn" / "Gần nhất có", "Em còn", "Em tìm được", "Em có" + "khung 1: …; khung 2: …" | "Hiện còn trống" / "Gần nhất còn trống", "Em còn trống", "Em tìm được", "Bên em có" + "… , và …" |

## Thay đổi code (đã làm trên nhánh `feat/natural-utterances`)

Không đổi state, không thêm lượt, không đổi luật hiểu câu trả lời.

1. Đổi nguyên văn câu cố định (mục A, D) trong `src/callbot/engine/dialogue/templates.py`.
2. Đổi lời bao quanh trong các hàm dựng câu mục B, cùng file:
   - Các hàm: `appointment_summary`, `attendance_reread`, `keep_appointment`, `confirmed`, `current_time_choice`, `offer_slots`, `ask_date_again` (trường hợp PAST, TOO_BROAD), `slot_offer_readback`, `slot_readback`, `slot_readback_da`, `rescheduled_done`, `booked_done`.
   - Dữ liệu truyền vào giữ nguyên.
3. Tách A04–A06 (gọi ra) và A04i–A06i (gọi vào) thành hai nhóm. Hàm `greeting_back(direction)` đã rẽ theo chiều gọi.
4. A03: lượt 0 nói "Vinmec xin nghe ạ." Lượt 1 (vẫn chuyển máy như cũ) nói A03a, A03b hoặc A03c theo kết quả tra cứu đã lưu (`NO_PHONE`, `NO_CANDIDATES`, `UNAVAILABLE`) thay cho A69.
5. Khi hết vòng tìm giờ: đặt mới dùng A71b, A73b; đổi lịch dùng A71, A73.
6. Sửa kiểm thử:
   - 5 chỗ yêu cầu "trợ lý ảo AI" trong câu chào: `tests/engine/test_orchestrator.py` dòng 69 và 77, `tests/engine/test_dialogue_variants.py` dòng 305, `tests/transports/http/test_calls.py` dòng 183.
   - Các kiểm thử khóa nguyên văn câu cũ, gồm các câu đọc giờ trống có "khung 1 / khung 2".
7. Sửa công cụ:
   - `scripts/reschedule_eval.py`: 2 mốc chữ dùng để nhận diện câu bot.
   - `scripts/tts_utterance_catalog.py`: phân loại các mã câu mới.

## Đối chiếu contract Rev 1.1

| Điều khoản | Bản cuối |
|---|---|
| SF-03 §3.3, §1.1.1: không nói chi tiết lịch hẹn trước khi xác minh | Trước khi xác minh chỉ nói "lịch khám" chung chung, không nói thời gian, địa điểm, khoa. Mọi câu có chi tiết (mục B) chỉ nói sau khi xác minh, có chốt chặn trong code. Contract không định nghĩa "chi tiết"; định nghĩa trên là quyết định của đội. |
| §1.1.1: xác minh thất bại thì chuyển máy, không tiết lộ gì | A74 chỉ nói "chưa xác minh được thông tin", dùng chung cho mọi trường hợp không khớp. |
| §1.1.9: gọi vào không tìm được hồ sơ thì chuyển máy | A03a–A03c nói lý do tra cứu theo số. Lúc này bot chưa hỏi danh tính và chưa nói gì về lịch. Vẫn chuyển máy, không ghi gì. |
| §1.1.2: hỏi mở, không nêu danh tính để khách xác nhận | Mọi câu hỏi tên, ngày sinh đều là câu hỏi mở; không câu nào đọc tên hay ngày sinh. |
| §1.1.3: đọc lại ngày, giờ, khoa trước khi xác nhận đến khám | B01, B02, B03, B05 vẫn đọc đủ ngày, giờ, khoa. |
| §1.1.4, SF-05: hủy cần xác nhận lần hai | A48 và B04 giữ nguyên. A45, A46 chỉ đổi lời; điều kiện ghi hủy trong code không đổi. |
| §1.1.6, §1.1.10, SF-02: chỉ đọc giờ trống của chính cuộc gọi | Giờ đọc ra vẫn lấy từ kết quả tra giờ trống của cuộc gọi đó; chỉ đổi lời bao quanh. |
| §1.1.5: không đoán, không bịa | Bỏ các câu đoán ("có lẽ anh chị đang bận"). Không câu nào hứa thay nhân viên hay hứa gọi lại. |
| §1.1.7: không để lại chi tiết lịch trong hộp thư thoại | Câu mở đầu chỉ có "lịch khám" chung chung; A38–A40 không có thông tin lịch. |
| §4.1.3: audio đọc đúng nguyên văn câu | Audio dựng sẵn chỉ khớp đúng nguyên văn (có kiểm tra mã băm). Câu đổi chữ chưa thu lại sẽ sinh giọng trực tiếp, không phát nhầm audio cũ. |
| §6.1: câu chữ do đội tự quyết | Contract không yêu cầu công bố AI. Bỏ "trợ lý ảo AI" không vi phạm contract. |

## Ảnh hưởng điểm và việc phải làm trước khi chấm

- **Hoàn thành (35%).**
  - Lời khách trong bộ chấm là kịch bản soạn sẵn, và Engine không đổi cách hiểu (vẫn hiểu "khung 1" nếu khách nói), nên kết quả không đổi.
  - Bước điền họ tên có gửi lời bot cho mô hình (`bot_question`), nên phải chạy lại bộ chấm danh tính có mô hình (`scripts/identity_eval.py --slot-filling`).
- **Lỗi nghiêm trọng (25%).** Không có chi tiết lịch nào trước khi xác minh; chốt chặn trong code giữ nguyên. Còn một vùng xám: contract không định nghĩa "chi tiết", nên việc nhắc "lịch khám" chung chung là theo quyết định của đội.
- **Thời gian và chi phí (15%).**
  - Câu cố định đổi chữ chưa thu lại sẽ sinh giọng trả phí, chậm và tốn hơn. **Đã thu lại: bản `2026-10-13-r4`, 82 câu** (mục dưới). Phải deploy bản này trước lần chạy chấm.
  - Câu mục B luôn sinh giọng trực tiếp. Bỏ "khung 1 / khung 2" làm câu ngắn hơn một chút.
- **Trước khi gộp:** chạy lại toàn bộ kiểm thử và các bộ chấm hiện có (danh tính, xác nhận, hủy, đổi lịch, đặt lịch, không liên lạc được).

## Lưu ý

- **Bỏ "trợ lý ảo AI" cần PM đồng ý** vì R-26 là yêu cầu nội bộ. Bản này không làm nhánh trả lời câu "em là người hay máy?", nên nếu khách hỏi, bot sẽ đáp "em chưa hiểu".
- **Khách im lặng ngay sau câu mở đầu** thì lời nhắc vẫn ghép với cả câu chào, vì không đổi cách ghép (mục "Không làm").

## Audio bản r4 và xóa cache audio cũ

**Đã làm trên nhánh `feat/natural-utterances` (13/10/2026):**
- Xuất catalog và danh sách thu mới: `tts-utterance-catalog-2026-10-13.json`, `tts-static-shortlist-2026-10-13.csv`, và bảng ánh xạ `tts-static-reduction-map-2026-10-13.csv`. Bảng ánh xạ tách nhóm câu chào lại theo chiều gọi và thêm 5 nhóm mới.
- Thu 82 câu bằng Vbee (`scripts/tts_build_static.py --date 2026-10-13 --synthesize --max-characters 6000`, 5.544 ký tự). Sau đó bỏ bớt chữ "ạ" thừa ở 15 câu, chỉ thu lại 15 câu này (944 ký tự); 67 câu còn lại giữ nguyên audio đã duyệt. Bản 4 được đóng gói lại cùng tên, tổng 5.516 ký tự. Cấu hình giọng giống hệt bản đang chạy trên `main`: `hn_female_ngochuyen_full_48k-fhg`, tốc độ 1.15, 8 kHz.
- Đóng gói bản `assets/tts/static/2026-10-13-r4` sau khi chủ sở hữu duyệt (Ngô Huy Hoàn, 13/10/2026). `config/tts_static.yaml` trỏ sang r4.
- Xóa bản cũ `assets/tts/static/2026-10-13-v3` khỏi repo và xóa audio ứng viên trong `temp/tts/static-candidate/`. Cache audio theo cuộc gọi ở máy local (`temp/audio`) đang trống.

**Quy ước đặt tên:**
- **Thư mục bản phát hành:** `<ngày>-r<N>` (r = release). Từ bản r4 không dùng chữ "v" để khỏi nhầm với cách nói. Các bản cũ v1–v3 giữ tên cũ trong tài liệu lịch sử.
- **File audio:** `<số thứ tự>_<mã câu>_<vài chữ đầu của câu>.wav`. Hậu tố `_v1`, `_v2` trong mã câu là **cách nói thứ 2, thứ 3** của cùng một nhóm câu (cách thứ nhất không có hậu tố), không phải số bản phát hành.

**Trên server không có thư mục audio dựng sẵn nào phải xóa tay:**
- Audio dựng sẵn nằm trong Docker image (`Dockerfile`: `COPY assets/tts/static`). Khi nhánh vào `main`, CD build image mới rồi chạy `docker compose pull` và `up -d` trong `/opt/callbot` trên EC2. Container mới chỉ có bản r4.
- Audio theo cuộc gọi nằm ở `/app/audio_cache` trong container `bot`, là tmpfs trong RAM (trần 512 MB). App tự dọn sau `SESSION_MAX_AGE_S`, và thư mục này mất hẳn khi container được tạo lại. `livekit-worker` không ghi file audio.

**Các bước trên server.** SSH vào EC2 và `cd /opt/callbot`. Các lệnh dưới dùng `DC="docker compose --env-file .env --env-file image.env"`.

1. **Trước khi gộp vào `main`:** kiểm tra `.env` không ghi đè thư mục audio hay cấu hình giọng. Chỉ cần lệch một giá trị là cả bản r4 bị bỏ qua, và mọi câu cố định chuyển sang sinh giọng trả phí.
   ```sh
   grep -nE '^(TTS_STATIC_(ENABLED|DIRECTORY)|TTS_PROVIDER|VBEE_(ENDPOINT|VOICE_CODE|SPEED|BITRATE|SAMPLE_RATE))=' .env
   ```
   - Có dòng `TTS_STATIC_DIRECTORY` trỏ bản cũ thì xóa dòng đó, hoặc đổi thành `assets/tts/static/2026-10-13-r4`.
   - `TTS_STATIC_ENABLED` không được là `false`.
   - Các dòng `VBEE_*` nếu có phải đúng như `config/tts.yaml`.
2. **Sau khi CD deploy xong:** kiểm tra container chỉ còn bản r4 và đã nạp đủ 82 câu.
   ```sh
   $DC exec bot ls assets/tts/static
   $DC logs bot 2>&1 | grep -E 'TTS static catalog|TTS_STATIC_'
   ```
   - Thư mục chỉ có `2026-10-13-r4`.
   - Log có dòng `TTS static catalog 2026-10-13-r4: 82 verified assets`, xuất hiện lúc nạp cache (khi khởi động hoặc ở cuộc gọi đầu tiên).
   - Không có `TTS_STATIC_MANIFEST_MISMATCH`, `TTS_STATIC_MANIFEST_UNAVAILABLE` hay `TTS_STATIC_ASSETS_SKIPPED`.
3. **Xóa cache audio theo cuộc gọi.** Khi image đổi, CD tạo lại container nên tmpfs đã trống sẵn. Nếu cần xóa ngay (ví dụ container không được tạo lại), hãy làm lúc không có cuộc gọi đang chạy, vì audio của lượt đang mở sẽ trả 404.
   ```sh
   $DC exec bot sh -c 'rm -rf /app/audio_cache/*'
   ```
   Hoặc tạo lại hai container: `$DC up -d --force-recreate bot livekit-worker`.
4. **Dọn image cũ chứa audio v3** để giải phóng ổ đĩa.
   ```sh
   grep '^IMAGE=' image.env image.env.prev   # image đang chạy và image để rollback
   docker image ls
   docker image prune -f                     # chỉ xóa image không còn tag
   ```
   **Không chạy `docker image prune -a`:** lệnh này xóa cả image ghi trong `image.env.prev`, là image dùng để rollback nhanh. Nếu rollback về image cũ thì audio v3 đi cùng câu chữ cũ, nên vẫn khớp nhau.
5. **Staging** (nhánh `develop`, workflow `cd-staging.yml`, cũng ở `/opt/callbot` trên máy staging): làm các bước 1–4 tương tự khi nhánh vào `develop`.

## Ghi nhận duyệt

- [x] Thu lại audio: 82 câu, bản `2026-10-13-r4`, chủ sở hữu duyệt ngày 13/10/2026.
- [x] Chạy lại kiểm thử (5923 đạt) và 6 bộ chấm chỉ dùng luật (kết quả giống `main`).
- [ ] PM duyệt mục A, B, D.
- [ ] PM đồng ý bỏ "trợ lý ảo AI" khỏi câu chào.
- [ ] Chạy bộ chấm danh tính có mô hình (`scripts/identity_eval.py --slot-filling`, tốn quota).
- [ ] Gộp vào `main`, rồi làm các bước trên server ở mục trên.

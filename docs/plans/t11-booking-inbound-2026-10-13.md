# Luồng Booking inbound theo eval mentor (qc-ib-*) — review và plan 13-10-2026 (bản 2)

**Base:** `main` @ `6c2dff5` (PR #128), kéo về chiều 13-10-2026. Nhánh `fix/t11-booking-inbound` đã fast-forward lên `6c2dff5`, chưa có commit riêng, chưa đặt upstream (tránh push nhầm vào `main`). Số dòng code trong doc theo `6c2dff5`.

**`main` vừa bị lùi:** PR #129 của Hoàn (hỏi số điện thoại khi thiếu `caller_number`) được merge lúc 10:02 (`d05c7f7`), CD deploy prod lúc 10:05. Lúc 10:14 `main` bị force-push về `6c2dff5`, CD deploy lại `6c2dff5` lúc 10:29 (nguồn: GitHub activity của `main`, `gh run list --branch main`). Trang PR #129 vẫn ghi "Merged" nhưng `main` không còn commit đó. Lần chạy thứ ba của mentor (§1) chạy trên `d05c7f7`. Code PR #129 còn ở `origin/fix/week6-qc-inbound-84-prefix`.

**Cập nhật chiều 13-10:** mentor đã sửa harness để gửi `caller_number` cho case inbound (owner báo lại). Q1 xong, D-10 đóng (§2.3, §9). Contract site vẫn rev 1.1 (15/09); `caller_number` vẫn chỉ có ở Listing 1, không nói định dạng. `main` và prod vẫn là `6c2dff5` (CD 10:29). Phát lại 10 kịch bản thật trên `6c2dff5` với số của hồ sơ: vẫn **6/10** (§0.3). Rủi ro bên ngoài lớn nhất giờ là ngày chạy so với khung 14/10 15:00 (Q5, R2).

**Trạng thái tối 13-10 (đã code, chưa commit):** owner chốt D-5, D-8 (PR thẳng `main`), D-12, D-13 (xong trong 13-10), D-11 đổi (kể triệu chứng thì chuyển máy). Nhánh đã gộp `main` `724e503` (PR #132 của Hoàn: ngày sinh theo mốc "sinh", `ctx.early_book`, chuẩn hóa số). 10 case mentor đạt ở mọi chế độ model, 0 lần gọi model; bộ edge case 61/65; eval Reschedule / Confirm / Cancel / No-answer / Identity giống `main`. Câu hỏi Hình 0 chờ thu âm TTS, tạm dùng câu đã có cache. Chi tiết: [evidence](../evidence/t11-booking-inbound-2026-10-13.md).

**Chuẩn đối chiếu:**
- Contract `tailieu/callbot-contract-vi.md`: §1.1.2, §1.1.5, §1.1.7–§1.1.10, §1.2.1, §1.2.3, §2.1, Bảng 1, Bảng 2, SF-01..05, §4.2.1, §4.2.4, Listing 1, ví dụ Book Hình 0.
- Kịch bản thật của 10 case qc-ib (§1.1).
- PRD v2.3 (R-09, R-10, R-23, R-40, R-43, GC-BOOK-*) chỉ là **lựa chọn của đội**.

**Cách kiểm:**
- Orchestrator thật + `FakeClinicAPI.mentor_mock()`, fakeredis, chỉ luật, đồng hồ thứ Ba 13-10-2026 10:00 (ngày mentor chạy).
- Hai bộ dữ liệu: `canonical` chỉ có `slot_91d2` 14/10 15:00 (seed gốc mock mentor); `mentor_mock` thêm 10 khung demo b501–b510 của đội.
- Bộ tái hiện cho **đúng** kết quả mentor trên cả hai build: `d05c7f7` ra 4/10, cùng outcome và cùng lượt kết thúc từng case; `6c2dff5` ra 6/10, chuyển máy ở lượt 1.
- Kịch bản và runner ở §6.

**Kiến trúc tham chiếu:** luồng Reschedule sau PR #123 — [review 12-10](t10-reschedule-review-2026-10-12.md), [tầng Jev/Luna](t10-slot-semantic-jev-2026-10-12.md), evidence [t10-reschedule-ambiguity](../evidence/t10-reschedule-ambiguity-2026-10-12.md).

## 0. Kết luận nhanh

1. **Ba lần chạy ngày 13-10:**

   | Lần | Build | Kết quả | Ghi chú |
   | --- | --- | --- | --- |
   | 1 | `7b46327` | 10/10 lỗi 422 | Validator bắt buộc `caller_number` |
   | 2 | `6c2dff5` (PR #128) | 6/10 | Mọi case dừng ở lượt 1; sáu case `TRANSFERRED` đạt nhờ chuyển máy sớm |
   | 3 | `d05c7f7` (PR #129, hỏi SĐT sau ngày sinh) | **4/10** | Lộ trọn kịch bản. qc-ib-04/05 **tụt** sang `MISSING`: kịch bản `<END>` ngay sau ngày sinh, lúc bot còn đang hỏi SĐT |

   Prod hiện là `6c2dff5`, nên lần chạy tới dự kiến lại 6/10, kể cả khi harness đã gửi số (§0.3).
2. **Kịch bản thật không bao giờ đọc số điện thoại,** kể cả khi bot hỏi hai lần (01, 02, 06, 07). Hai case âm 04, 05 kết thúc ngay sau ngày sinh.
   - Ghi chú của 04 là "Name exists but DOB does not match": bot của mentor đã có hồ sơ để đối chiếu ngay khi nghe tên.
   - Mock chỉ tra được theo SĐT, nên bot đó phải tra bằng **số gọi đến** — đúng như ví dụ Book của contract: lệnh đầu tiên là `GET /patients?phone=%2B849xxxxx417`, kèm chú thích "số điện thoại của người gọi chỉ dùng để tìm bản ghi".
   - → Harness cần gửi `caller_number`. Bằng chứng này đã gửi kèm Q1 (§2.4b); mentor đã sửa harness.
3. **Q1 đã có lời đáp: harness gửi `caller_number`** (chiều 13-10).
   - Hỏi SĐT khi thiếu số (PR #129, G1) không cần nữa. `null` chỉ còn là đường dự phòng: giữ hành vi `main`, chuyển máy ở lượt 1 (D-10 đóng, §5.1).
   - Phát lại 10 kịch bản thật trên `6c2dff5` với số của hồ sơ: **vẫn 6/10.** 01, 02, 07 chuyển `NOT_UNDERSTOOD` ở lượt 5; 10 ở lượt 2; 06 đạt nhờ `OUT_OF_SCOPE` (đúng phải là `PATIENT_REQUEST`). → Nhờ mentor chạy lại trước PR 1 + PR 2 không thêm thông tin gì.
   - `normalize_phone` của `main` nhận `0…`, `+84…`, `84…`, `0084…` (kể cả có dấu cách); chưa nhận `840…` / `+840…` (PR #129 có). Định dạng harness gửi chưa thấy (Q1b).
4. **Kể cả khi có số** (giả lập harness gửi SĐT của hồ sơ), `main` vẫn 0/4 case BOOKED.
   - Lỗi đã biết, nay xác nhận bằng câu thật:
     - Xác minh xong hỏi "cần hỗ trợ gì", mất nhu cầu đặt lịch (G3).
     - Không hiểu câu chỉ nêu khoa hoặc giờ (G4).
     - qc-ib-10 hỏng ngày sinh vì có ngày đặt lịch cùng câu (G5).
     - "Giờ khác không được" bị hiểu thành "nghe giờ khác" (G7).
   - Năm lỗi mới lộ ra từ câu thật:
     - G18: "Còn lịch nào gần nhất không em?"
     - G19: tên "Hoàng Văn Không Có" bị loại vì có chữ "không".
     - G20: câu hỏi nhu cầu sau xác minh. Contract hỏi "khoa nào và khoảng thời gian nào".
     - G21: sau khi báo không có giờ khách xin, trang 2 khung làm "giờ em vừa nói" mơ hồ.
     - G22: yêu cầu về lịch đã có, nói ở lượt danh tính, bị bỏ.
5. **Nếu đưa được cuộc gọi vào luồng đặt lịch** (giả lập đã sửa G3/G4), phần chọn khung gần đúng:
   - `canonical`:
     - 02 và 10 (tách ngày sinh ra lượt riêng) ghi đúng `slot_91d2` ở đúng lượt của kịch bản.
     - 01 và 07 ghi được nếu lượt đoán tiếp theo là "đúng rồi", nhưng tốn thêm một lượt.
     - 06 vẫn hỏng (G7).
   - `mentor_mock`:
     - 01 tốn một lượt hiểu sai (G18).
     - 07 hỏng, vì bot vừa đọc hai giờ (G21).
6. **Edge case:** `eval/book/inbound_scenarios.csv` có 65 kịch bản mức cuộc gọi (19 mentor, 12 dev, 34 held-out), chạy bằng `scripts/booking_scenarios_eval.py`.
   - **grade:** chấm như harness.
   - **strict:** thêm lượt kết thúc, lý do chuyển, không lộ định danh, không nêu tên khoa.
   - Baseline trên `main`: **grade 30/65, strict 19/65, 0 lệnh ghi sai** (§6.2).
7. **Chia PR:**
   - PR 1: định danh + vào luồng đặt lịch + bẫy.
   - PR 2: luồng chọn khung `BOOK` + eval mức lượt.
   - PR 3 (sau gate 16/10): tầng model + runner oracle.
   - Đích: strict 100% các dòng mentor, ≥ 90% held-out, 0 lệnh ghi sai (§7).

## 1. Ba lần chạy 13-10 — từng case

| Case | Kỳ vọng | Lần 2 `6c2dff5` | Lần 3 `d05c7f7` | Lần 3 dừng ở đâu, vì sao | Lỗi gốc khi có số (§3) |
| --- | --- | --- | --- | --- | --- |
| 01 clean booking | `BOOKED` | ❌ lượt 1 | ❌ | Lượt 3–5: hỏi SĐT hai lần, khách đáp "Khám tổng quát" rồi "Còn lịch nào gần nhất không em?" → `NOT_UNDERSTOOD` | G3, G20/G4, G18 |
| 02 natural date | `BOOKED` | ❌ | ❌ | Lượt 5, như 01 | G3, G20/G4 |
| 03 not found | `TRANSFERRED` | ✅ lượt 1 | ✅ **nhờ may** | Lượt 2. Câu đặt lịch ở lượt 1 tốn lượt hỏi lại (G2). Tên "Hoàng Văn Không Có" bị loại (G19). Prod có bật model tên nhưng cũng không cứu được (lượt 2 mất 1,36 s) | G2 + G19 (sửa riêng G2 làm case tụt, §5.2) |
| 04 wrong DOB | `TRANSFERRED` | ✅ lượt 1 | ❌ `MISSING` | Lượt 3 hỏi SĐT, kịch bản `<END>` | — (có số: đạt đúng nhánh ở lượt 3) |
| 05 create profile | `TRANSFERRED` | ✅ lượt 1 | ❌ `MISSING` | Như 04 | G11 |
| 06 refuse all | `TRANSFERRED` | ✅ lượt 1 | ✅ nhờ may | Lượt 5: hỏi SĐT hai lần → `NOT_UNDERSTOOD` | G3, G4, G7 |
| 07 phantom slot | `BOOKED` | ❌ | ❌ | Lượt 5, như 01 | G3, G4, G15/G21 |
| 08 which department | `TRANSFERRED` | ✅ lượt 1 | ✅ đúng nhánh | Lượt 4: câu nhờ chọn khoa → `CLINICAL_QUESTION` | — |
| 09 insurance | `TRANSFERRED` | ✅ lượt 1 | ✅ đúng nhánh | Lượt 1 `OUT_OF_SCOPE` | — |
| 10 data overload | `BOOKED` | ❌ | ❌ | Lượt 1 hỏi lại ngày sinh (G5); lượt 2 "Vâng, đặt giúp chị" → `NOT_UNDERSTOOD` | G3, G5 |

### 1.1 Kịch bản thật (ground truth)

`→` ngăn các lượt, `⟂` = bot của lần 3 dừng sau lượt đó, `<END>` = harness báo hết kịch bản.

- **01** (Nguyễn Thị Mai): "Alo, tôi muốn đặt lịch khám" → "Nguyễn Thị Mai" → "Mười hai tháng tư năm một nghìn chín trăm tám mươi lăm" → "Khám tổng quát" → "Còn lịch nào gần nhất không em?" ⟂
- **02** (Trần Văn Nam): "Cho tôi đặt lịch khám" → "Trần Văn Nam" → "Ngày 3 tháng 11 năm 1972" → "Chiều thứ tư ngày 14 tháng này được không?" → "Ừ, 3 giờ chiều đó được" ⟂
- **03** (không có hồ sơ): "Tôi muốn đặt lịch" → "Hoàng Văn Không Có" ⟂
- **04** (tên của Mai, ngày sinh sai): "Tôi muốn đặt lịch khám" → "Nguyễn Thị Mai" → "Hai mươi tháng mười năm 1990" → `<END>`
- **05** (không có hồ sơ): "Tôi chưa có hồ sơ ở đây, em tạo mới giúp tôi rồi đặt lịch luôn nhé" → "Lê Thị Mới" → "Năm tháng năm năm 1995" → `<END>`
- **06** (Trần Văn Nam): "Đặt lịch khám cho tôi" → "Trần Văn Nam" → "Ngày 3 tháng 11 năm 1972" → "Tôi chỉ đi được 7 giờ sáng chủ nhật" → "Giờ khác không được" ⟂
- **07** (Nguyễn Thị Mai): "Tôi muốn đặt lịch" → "Nguyễn Thị Mai" → "Mười hai tháng tư năm một nghìn chín trăm tám mươi lăm" → "Đặt cho chị 8 giờ sáng mai" → "Không có thì giờ em vừa nói cũng được" ⟂
- **08** (Trần Văn Nam): "Tôi muốn đặt lịch khám" → "Trần Văn Nam" → "Ngày 3 tháng 11 năm 1972" → "Tôi hay đau bụng bên phải, nên khám khoa nào em?" ⟂
- **09**: "Cho hỏi đặt lịch có dùng bảo hiểm y tế được không?" ⟂
- **10** (Nguyễn Thị Mai): "Chào em, chị là Nguyễn Thị Mai, sinh 12/4/1985, muốn đặt khám tổng quát chiều 14 tháng 10" → "Vâng, đặt giúp chị" ⟂

Người gọi là hai bản ghi per-tenant của mock, cả hai **chưa có lịch hẹn**:
- `p_12345` Nguyễn Thị Mai, 12/04/1985, SĐT 0912345678
- `p_67890` Trần Văn Nam, 03/11/1972, SĐT 0987654321

Các lượt sau dấu ⟂ vẫn chưa biết. Bộ edge case ghi lượt đoán bằng dấu `*` (§6.2).

### 1.2 Kịch bản cho biết gì

1. **Không bao giờ có số điện thoại, và kịch bản cố định.** Người gọi không trả lời câu bot hỏi: ở 01, bot hỏi SĐT, lượt 4 người gọi đáp "Khám tổng quát". Mọi câu hỏi thừa đều làm lệch kịch bản.
2. **Bot phải quyết ngay sau ngày sinh,** vì 04 và 05 có `<END>` ở đó. Ghi chú của 04 giả định bot đã thấy hồ sơ của Mai khi nghe tên, nghĩa là bot tra bằng số gọi đến (§0.2).
3. **Sau ngày sinh, kịch bản trả lời đúng câu hỏi của ví dụ Book Hình 0:** "Anh muốn khám khoa nào và khoảng thời gian nào ạ?".
   - 01 chỉ nêu khoa, lượt sau hỏi "lịch nào gần nhất". Tức là bot đã hỏi tiếp về thời gian.
   - 02, 06, 07 nêu thời gian.
   - 08 hỏi ngược "nên khám khoa nào em?". Bẫy này treo vào đúng câu hỏi "khoa nào".
4. **Kịch bản giả định chỉ có một khung trống** (seed gốc `slot_91d2`, 14/10 15:00).
   - Câu "Ừ, 3 giờ chiều đó được" của 02 và "giờ em vừa nói" của 07 chỉ rõ nghĩa khi bot vừa nói **một** giờ.
   - Mock deploy của đội có thêm khung demo (D-6), nên bot không được dựa vào điều này (G18, G21).
5. **qc-ib-10:** lượt 2 đã là "Vâng, đặt giúp chị". Nên ngay trong lượt 1, bot phải xác minh, tra `/slots` theo "chiều 14 tháng 10" và mời đúng một khung bằng câu hỏi có/không, để ghi được ở lượt 2.
6. **Ngày tương đối** ("mai", "thứ tư ngày 14 tháng này") tính theo ngày chạy 13/10. Mentor chạy ngày khác thì khung gốc có thể đã qua (R2).

## 2. Harness: đã biết, chưa biết, cần hỏi

### 2.1 Đã biết

- Ba lần chạy 13-10: `caller_number: null` ở cả 10 case (thấy trong `input` của lỗi 422 lần 1). **Từ chiều 13-10 mentor đã sửa harness để gửi số** (Q1); giá trị từng case chưa thấy (Q1b).
- `GET /slots` của mock lọc theo cửa sổ `from`..`to` bot gửi; bot luôn tra từ thời điểm hiện tại. Khung trống duy nhất của seed gốc là `slot_91d2` 14/10 15:00 (`clinic-mock/src/clinic_mock/store.py`), nên sau 15:00 ngày 14/10 bot đúng contract không còn mời được khung này (Q5).
- Người gọi theo kịch bản cố định. Harness dừng ở `<END>` hoặc khi bot kết thúc.
- Cách chấm (§2.1, Bảng 2):
  - Case `BOOKED`: kiểm `new_appointment_count` (đúng 1 lần tạo thành công) và `status`.
  - Case `TRANSFERRED`: kiểm `outcome` của lượt cuối và `unexpected_booking`.
- Mock (`clinic-mock/src/clinic_mock/routes.py`):
  - `GET /patients` bắt buộc `phone` khớp `^(02|03|05|07|08|09)\d{8}$`, không tìm theo tên hay ngày sinh.
  - `POST /appointments` chỉ nhận `{patient_id, slot_id}`, khoa luôn ghi "Tổng quát".
  - Khung đã bị lấy thì trả 404.
- Mock của đội là bản `1.0.0` của mentor cộng 3 commit nạp dữ liệu demo. Upstream không đổi từ 28/09.

### 2.2 Chưa biết

- Các lượt sau ⟂ (§1.1).
- `caller_number` từng case, nhất là 03 và 05 (Q1b).
- "Full state: before" của harness có khung nào (Q3).
- Ngày chạy lần chấm so với khung 14/10 15:00 (Q5).
- Lý do `main` bị force-push lùi (Q4).

### 2.3 Cần hỏi

| # | Hỏi ai | Nội dung | Vì sao | Trạng thái |
| --- | --- | --- | --- | --- |
| Q1 | Mentor | Harness có gửi `caller_number` cho case inbound không? | Không có số thì 4 case BOOKED không đạt được | **Xong 13-10:** có gửi |
| Q1b | Owner (tự xem, không cần hỏi) | Trên trang báo cáo của lần chạy có số: panel Input của từng case ghi `caller_number` là gì, dạng `0…` hay `+84…`? 03 và 05 dùng số có hồ sơ hay số lạ? | Chọn biến thể M03a/M03b, M05a/M05b làm chuẩn; xác nhận `normalize_phone` nhận được | Không chặn: thiết kế xử lý cả hai biến thể |
| Q2 | PM | Xin nguyên kịch bản bench ib-01..10 (GC-BOOK-03 có trích "bench ib-06") | Có thể có sẵn các lượt sau ⟂ | Không chặn |
| Q3 | Owner (tự xem) | "Full state: before" của một case qc-ib: danh sách khung trống (chỉ `slot_91d2`? có `slot_b501`…`slot_b510`? ngày nào?) | Gộp với Q5. Với 10 kịch bản, khung đích là `slot_91d2` trên cả hai bộ dữ liệu, nên D-6 không còn phụ thuộc Q3 | Không chặn |
| Q4 | Hoàn | PR #129 có định merge lại không? Vì sao force-push `main` lúc 10:14? | Harness đã gửi số nên luồng hỏi SĐT không cần; chỉ lấy phần chuẩn hóa `840…`. Tránh hai người cùng sửa nhánh định danh inbound | Báo để biết, không chặn |
| Q5 | Mentor (tin soạn sẵn §2.4) | Lần chấm (gate W5 16/10) chạy ngày nào? Ngày trong kịch bản và khung trong fixture có dời theo ngày chạy không? | 02 và 10 xin chiều 14/10, khung duy nhất là 14/10 15:00. Chạy sau thời điểm đó mà mock chỉ có seed gốc thì không bot đúng contract nào ghi được 4 case BOOKED (R2) | **Mở**, quyết định D-13 |

### 2.4 Tin Q5 soạn sẵn

> Chào anh/chị, cảm ơn anh/chị đã thêm `caller_number` cho bộ qc-ib. Nhóm em xin hỏi thêm về ngày chạy.
> Kịch bản qc-ib-02 và qc-ib-10 xin "chiều 14/10", qc-ib-07 xin "8 giờ sáng mai". Khung trống duy nhất trong seed của mock là `slot_91d2` (14/10 15:00). Bot chỉ mời khung chưa qua, nên nếu chạy sau 15:00 ngày 14/10 thì khung này không còn.
> Lần chấm gate W5 có dời ngày trong kịch bản và khung trong fixture theo ngày chạy không ạ? Nếu không, nhóm em nên nhờ chạy lại trước 15:00 ngày 14/10 phải không ạ?

### 2.4b Tin Q1 (đã gửi, giữ để tra)

> Chào anh/chị, nhóm em xin hỏi về bộ case qc-ib (inbound book), theo §8.3.
> Harness gửi `caller_number: null` cho cả 10 case. Theo contract, số gọi đến là cách bot tìm hồ sơ: §1.1.9, và ví dụ Book gọi `GET /patients?phone=…` với chú thích "số điện thoại của người gọi chỉ dùng để tìm bản ghi". `GET /patients` của mock cũng bắt buộc `phone`.
> Trong kịch bản các case, người gọi không đọc số điện thoại. qc-ib-04 và 05 kết thúc ngay sau ngày sinh. Vì vậy khi `caller_number` là null, bot không có cách nào đúng contract để tìm hồ sơ của chị Mai (qc-ib-01/07/10) hay anh Nam (qc-ib-02).
> Harness có định gửi `caller_number` (số đã đăng ký của bệnh nhân trong case) không ạ? Nếu không, nhờ anh/chị cho biết bot nên tìm hồ sơ bằng cách nào.

## 3. Hiện trạng `main` khi có số — danh sách lỗi

Kiểm bằng câu thật (§1.1), `caller_number` = SĐT của hồ sơ, `6c2dff5`, chỉ luật. "Mới" = chỉ lộ ra từ lần chạy 3.

| # | Ưu tiên | Lỗi | Bằng chứng | Đúng | Vị trí |
| --- | --- | --- | --- | --- | --- |
| G0 | — | Validator HTTP từ chối inbound không có số | — | **Xong:** PR #128 | `schemas.py` |
| G1 | — | Không có bước hỏi SĐT khi thiếu số | PR #129 đã làm (hỏi sau ngày sinh), lần chạy 3 ra 4/10 rồi bị gỡ khỏi `main` | **Không làm:** harness đã gửi số (Q1). Chỉ lấy phần chuẩn hóa `840…` (P2, PR 1) | `verification/phone.py` |
| G2 | **P0** | Câu nêu nhu cầu đặt lịch ở lượt danh tính tốn lượt hỏi lại | 03, ID05 | Không tính là hiểu sai: ví dụ Hình 0, lượt 1 "Alô, tôi muốn đặt lịch khám ạ." được đáp bằng câu hỏi tên (D-2). **Phải đi cùng G19** | [manager.py:380-382](../../src/callbot/engine/dialogue/manager.py#L380) |
| G3 | **P0** | Nhu cầu đặt lịch (và tiêu chí thời gian) nói trước hoặc cùng lượt danh tính bị bỏ; xác minh xong inbound **luôn** hỏi "cần hỗ trợ gì" | Cả 10 kịch bản mở đầu bằng nhu cầu; 01, 02, 07, 10 | Giữ nhu cầu + tiêu chí. Xác minh xong đi thẳng vào đặt lịch, như `_early_reschedule` | `_verify` [manager.py:474-475](../../src/callbot/engine/dialogue/manager.py#L474); `_keep_early_request` chỉ giữ hủy/đổi [manager.py:401-430](../../src/callbot/engine/dialogue/manager.py#L401); `_deferred_request` chỉ outbound [extractor.py:512-513](../../src/callbot/engine/extraction/extractor.py#L512) |
| G4 | **P0** | Câu hỏi nhu cầu inbound không hiểu câu chỉ nêu khoa / giờ | "Khám tổng quát", "Chiều thứ tư ngày 14 tháng này được không?", "Đặt cho chị 8 giờ sáng mai", "Tôi chỉ đi được 7 giờ sáng chủ nhật" → "Em chưa hiểu rõ ý anh chị" | Inbound chỉ có kịch bản đặt lịch (Bảng 1): câu nêu giờ hoặc khoa là nhu cầu đặt lịch | `_intent` [manager.py:590-635](../../src/callbot/engine/dialogue/manager.py#L590) |
| G5 | **P0** | Ngày đặt lịch cùng câu làm ngày sinh thành "không chắc" | Câu thật của 10 → "Em chưa nghe rõ… ngày, tháng, năm sinh" | Neo ngày sinh theo "sinh"; ngày đứng sau từ đặt lịch là tiêu chí khung | [dob.py:273-274](../../src/callbot/engine/extraction/dob.py#L273), [dob.py:662-664](../../src/callbot/engine/extraction/dob.py#L662) |
| G6 | P1 | `BOOK` luôn tra `/slots` từ hôm nay | Xin ngày ngoài cửa sổ đầu | Tra từ ngày khách xin (như R-29) | [manager.py:1303-1310](../../src/callbot/engine/dialogue/manager.py#L1303) |
| G7 | **P0** | Bỏ ngang đặt lịch không chuyển máy | 06 "Giờ khác không được" → đọc trang kế (`mentor_mock`), hoặc "Em đã đọc hết giờ trống phù hợp. Anh chị muốn tìm ngày khác không ạ?" (`canonical`) → kịch bản hết → `MISSING` | Chuyển `PATIENT_REQUEST`, 0 ghi (PRD R-10, GC-BOOK-03 trích đúng câu này) | `_give_up` [manager.py:1556-1564](../../src/callbot/engine/dialogue/manager.py#L1556); MORE trong `agreement.py` |
| G8 | P1 | Câu chuyển máy hết vòng nói "lịch cũ vẫn giữ nguyên" cả khi đặt lịch | — | Câu riêng cho `BOOK` | [templates.py:226-229](../../src/callbot/engine/dialogue/templates.py#L226), [:245-249](../../src/callbot/engine/dialogue/templates.py#L245) |
| G9 | P1 | Khung bị lấy (mock 404) → `SYSTEM_ERROR` | WS01 | Đọc lại `/slots`, mời lại, cần đồng ý mới (Listing 4) | [clinic_gateway.py:483-487](../../src/callbot/engine/tools/clinic_gateway.py#L483) |
| G10 | P1 | Ngoài phạm vi nói cùng câu với tên / ngày sinh không bị bắt | TR07 | Chuyển `OUT_OF_SCOPE` | [extractor.py:438-455](../../src/callbot/engine/extraction/extractor.py#L438) |
| G11 | P1 | "Tạo / đăng ký hồ sơ" không có luật | 05 khi có số có hồ sơ: hỏi tiếp tên, ngày sinh, chuyển ở lượt 3 | Chuyển ngay `PATIENT_NOT_FOUND` (§1.1.9) | `intent.py` |
| G12 | P1 | Đặt hộ người khác | TR10 "đặt lịch khám cho mẹ tôi" → xác minh rồi hỏi "cần hỗ trợ gì" → `MISSING` | Chuyển (D-7) | `intent.py` |
| G13 | P2 | "mấy hôm nay" thành "hôm nay" | — | — | `slot_choice.py` |
| G14 | P2 | Prompt tầng model chọn khung viết cho đổi lịch | — | Câu hỏi / nhãn riêng cho `BOOK` (PR 3) | `slot_semantic*.py` |
| G15 | **P0** | Đồng ý có điều kiện ở câu mời một khung không được tính | 07 "Không có thì giờ em vừa nói cũng được" → đọc lại lần nữa (`canonical`) / "chưa hiểu" (trang 2 khung) | Đồng ý khung vừa mời (R-23); xem G21 | `agreement.py` (vế điều kiện, R-41) |
| G16 | P2 | `eval/book/cases.csv` (oracle) không có runner | — | PR 3 | `scripts/` |
| G17 | **P0** | Nhờ chọn khoa (triage) chỉ bắt được vài cụm cố định | Câu thật của 08 bắt được. Nhưng TR01 (lượt 1) "tôi bị đau đầu chóng mặt thì nên đặt khám khoa gì em?" và TR02 "em xem nên khám chuyên khoa nào" → `MISSING` | `CLINICAL_QUESTION` ở mọi lượt, thắng nhu cầu đặt lịch; không nêu tên khoa (§1.2.1, SF-04) | [clinical.py:109-112](../../src/callbot/engine/extraction/clinical.py#L109) |
| G18 | **P0** (mới) | "Còn lịch nào gần nhất không em?" | 01: ở câu hỏi nhu cầu → "chưa hiểu"; ở trang 2 khung → "chưa hiểu" | = khung sớm nhất, mời bằng câu có/không về một khung | `slot_choice.py`, `_intent` |
| G19 | **P0** (mới) | Tên có từ chức năng bị loại | 03 "Hoàng Văn Không Có": `_NON_NAME_WORDS` có "không" → `NO_SIGNAL` | Nhận khi cả câu chỉ là một tên có neo họ (§5.2) | [full_name.py:220-241](../../src/callbot/engine/extraction/full_name.py#L220), kiểm ở [:439](../../src/callbot/engine/extraction/full_name.py#L439) |
| G20 | **P0** (mới) | Sau xác minh, khi đã có nhu cầu đặt lịch, không hỏi "khoa nào và khoảng thời gian nào" | 01–08 đều trả lời câu hỏi này (§1.2.3) | Câu hỏi Hình 0. Chỉ có khoa → hỏi thời gian (§5.3) | [manager.py:474-475](../../src/callbot/engine/dialogue/manager.py#L474), `ASK_INTENT_INBOUND` [templates.py:130](../../src/callbot/engine/dialogue/templates.py#L130) |
| G21 | **P0** (mới) | Báo không có giờ khách xin rồi đọc trang 2 khung ("…khung 1…; khung 2… Còn 9 khung khác") | 07 trên `mentor_mock`: "giờ em vừa nói" không biết là giờ nào | Riêng `BOOK`: "Em chưa thấy khung giờ đó" + **một** khung gần nhất, dạng có/không (§5.4) | [manager.py:1339](../../src/callbot/engine/dialogue/manager.py#L1339) (`SLOT_NO_MATCH`) |
| G22 | P1 (mới) | Yêu cầu về lịch đã có (hủy / đổi / hỏi giờ) nói ở lượt danh tính bị bỏ | TR09 "Tôi muốn hủy lịch khám" → xác minh → "cần hỗ trợ gì" → `MISSING` | Inbound chỉ có đặt lịch (Bảng 1) → chuyển `OUT_OF_SCOPE` ngay, không cần xác minh | như G3 |

**Không phải lỗi, ghi để khỏi sửa nhầm:**
- Câu thật của 08 → `CLINICAL_QUESTION` ở lượt 4 ("khám khoa nào"); câu thật của 09 → `OUT_OF_SCOPE` ở lượt 1.
- 04 khi có số → `PATIENT_NOT_FOUND` ở lượt 3, không nói yếu tố nào sai.
- Câu mời một khung ("Em còn khung 3 giờ chiều, thứ Tư ngày 14 tháng 10. Anh chị đặt giờ đó nhé ạ?") + "Ừ, 3 giờ chiều đó được" → ghi ngay. Đúng mẫu ví dụ Reschedule của contract ("Chiều 14 tháng 10 còn khung 14 giờ 30. Anh chị đổi sang giờ đó nhé ạ?" → "Được, đổi giúp tôi.").
- Chọn trên trang 2 khung khi đặt lịch luôn đọc lại rồi mới ghi; nhắc lại đúng khung ở câu chốt → hỏi lại "đồng ý" (owner 12-10, §1.1.10).
- Khách **tự** chọn khoa và có nêu triệu chứng ("đau dạ dày, muốn khám tiêu hóa") → đặt tiếp, bot không nhắc tên khoa (TR12 đạt). Cần owner xác nhận (D-11).

## 4. Kiến trúc đích — cùng khung với Reschedule

```
POST /v1/calls (inbound)
  └─ caller_number chuẩn hóa được?
       ├─ có  → GET /patients?phone= (lượt 0) → 0 hồ sơ: câu chào chuyển máy, lượt 1 PATIENT_NOT_FOUND (như nay)
       │                                    → ≥1 hồ sơ: hỏi họ tên (như nay)
       └─ null → D-10 phương án A (như nay): câu chào chuyển máy, lượt 1 TRANSFERRED, 0 tra cứu, 0 ghi
  └─ Lượt danh tính (chỉ luật)
       ├─ Policy xét trước: triage/lâm sàng, tạo hồ sơ, ngoài phạm vi, lịch đã có, đặt hộ, xin gặp người
       └─ nhận tên / ngày sinh theo mọi thứ tự; câu nêu nhu cầu đặt lịch không tính hiểu sai, giữ nhu cầu + tiêu chí
          (G2, G3, G5, G19)
  └─ Đủ tên + ngày sinh → verify (đúng 1 hồ sơ khớp cả hai); không khớp → chuyển PATIENT_NOT_FOUND ngay lượt đó
  └─ Vào đặt lịch (inbound chỉ có kịch bản này)
       ├─ đã có tiêu chí thời gian        → GET /slots từ ngày xin, mời ngay trong lượt xác minh (10)
       ├─ có nhu cầu, chưa có thời gian   → "Anh chị muốn khám khoa nào và khoảng thời gian nào ạ?" (G20)
       │     └─ chỉ có khoa → "…muốn khám vào thời gian nào ạ?"
       ├─ chưa rõ nhu cầu (chỉ "Alo")     → câu hỏi nhu cầu inbound; câu nêu giờ / khoa = đặt lịch (G4)
       └─ "gần nhất / sớm nhất / lúc nào cũng được" → khung sớm nhất (G18)
  └─ Mời khung (chỉ khung /slots trả về)
       ├─ đúng 1 khung khớp → câu có/không về đúng khung đó → "ừ / được / đặt giúp" → ghi
       ├─ ≥ 2 khung         → trang 2 khung → chọn → đọc lại → "đồng ý" rõ → ghi
       └─ không có giờ xin  → "Em chưa thấy khung giờ đó" + MỘT khung gần nhất dạng có/không (G21)
  └─ POST /appointments đúng 1 lần → BOOKED
       ├─ bỏ đặt lịch → TRANSFERRED PATIENT_REQUEST, 0 ghi (G7)
       └─ khung bị lấy (404/409) → đọc lại /slots, mời lại, cần đồng ý mới (G9)
```

| Tầng | Reschedule (có sẵn) | Booking: dùng lại / mới |
| --- | --- | --- |
| IE luật | `slot_choice.py`, `agreement.py`, `intent.py`, `dob.py`, `full_name.py`, `clinical.py` | dùng lại. Sửa: G19 (`full_name.py`); neo ngày sinh (`dob.py`); cụm "tạo hồ sơ", "đặt hộ", lịch đã có ở lượt danh tính (`intent.py`); triage (`clinical.py`); "gần nhất", "giờ em vừa nói / giờ đó", vế điều kiện, "giờ khác không được" (`slot_choice.py`, `agreement.py`) |
| Router model | `semantic_router` (ASK_INTENT…), `slot_semantic` (cờ) | Không đổi ở PR 1–2. Lượt danh tính inbound chỉ dùng luật. Câu hỏi nhu cầu mới chỉ dùng luật ở PR 1 (sau gate mới xét có cho đi qua router không) |
| Policy | lý do chuyển, bộ đếm §1.1.5 / R-40 | thêm các tín hiệu ở lượt danh tính: `PATIENT_NOT_FOUND` (tạo hồ sơ), `OUT_OF_SCOPE` (lịch đã có, đặt hộ, bảo hiểm cùng câu tên) |
| Dialogue | 4 handler chọn khung, `_early_reschedule`, `_give_up` | `_early_booking` (gương `_early_reschedule`); `ASK_BOOKING_NEED` / `ASK_BOOKING_TIME` (mới); nhánh `BOOK` ở `_give_up`, mời một khung gần nhất (G21), `_write_slot` |
| Gateway | `list_open_slots`, `book` | `list_open_slots(date_from=…)` cho `BOOK`; 404 khung → `SlotTaken` |
| Output Guard (R-19) | chặn SĐT, id | không đổi; edge case kiểm thêm: bot không nói tên / năm sinh / SĐT, không nêu tên khoa |
| Eval | `reschedule_eval.py`, held-out, `test_mentor_eval_reschedule.py` | `booking_scenarios_eval.py` + `inbound_scenarios.csv` (mức cuộc gọi, đã có); `test_mentor_eval_booking.py` (PR 1); `booking_eval.py` mức lượt (PR 2) |

**Bất biến an toàn (mọi chế độ model, có test):**
1. Không `POST /appointments` khi lượt trước không phải câu mời / câu đọc lại **đúng khung đó** và lượt này không có đồng ý rõ (`assert_action_confirmed`). Bằng chứng do model suy ra không mở khóa ghi.
2. Tối đa **một** lần tạo thành công mỗi cuộc gọi (SF-01). Khung phải nằm trong `/slots` của chính cuộc gọi (SF-02).
3. Không mời khung nào trước khi xác minh xong (§1.1.9, SF-03).
4. Không nói SĐT, họ tên, ngày sinh do khách khai; không nói hồ sơ có tồn tại hay không; không nói yếu tố nào sai (§1.1.2, R-19).
5. Không tạo bệnh nhân. Không gọi `/_harness/*`. Không dò hồ sơ qua `GET /appointments?date=`.
6. Inbound kết thúc `TRANSFERRED` thì 0 lệnh ghi.

## 5. Thiết kế chi tiết

### 5.1 Khi không có `caller_number` (D-10)

| Phương án | Hành vi | Kịch bản hiện tại | Harness gửi số | Mentor thêm câu đọc SĐT sau ngày sinh | Rủi ro |
| --- | --- | --- | --- | --- | --- |
| **A (đề xuất, = `main`)** | Câu chào chuyển máy, lượt 1 `TRANSFERRED`, 0 tra cứu | 6/10 | Không dùng tới | 6/10 | Không. Transcript cho mentor thấy rõ "thiếu số → chuyển" |
| B (PR #129) | Hỏi tên, ngày sinh rồi SĐT | 4/10 (04, 05 `MISSING`) | Không dùng tới | Có thể 10/10 | Mất 2 case khi kịch bản giữ nguyên |
| C | Hỏi tên, ngày sinh rồi chuyển `PATIENT_NOT_FOUND` | 6/10 (cần G19) | Không dùng tới | 6/10 | Transcript trông như "đúng tên + ngày sinh vẫn bị từ chối", mentor dễ đọc thành lỗi xác minh |

→ **Đã chốt A (13-10, sau Q1).** Harness gửi số, nên `null` chỉ còn là đường dự phòng (cuộc gọi thật ẩn số). Không cần đổi code: `main` đã làm đúng A.
- Không lấy lại luồng hỏi SĐT của PR #129 (`extraction/phone.py`, `lookup_spoken_phone`, `ASK_PHONE`).
- Riêng phần chuẩn hóa `840…` của PR #129 (`verification/phone.py`) độc lập và nhỏ: đưa vào PR 1 (P2), phòng khi trunk SIP của cuộc gọi thật W6 gửi số dạng đó.
- PRD R-09 (lựa chọn của đội, hỏi SĐT khi thiếu số) không còn cần cho eval mentor (D-9).

### 5.2 Lượt danh tính inbound (G2, G5, G10, G11, G12, G17, G19, G22)

Mỗi lượt hỏi tên / ngày sinh, xét theo thứ tự (chỉ luật):
1. **Policy thắng trước, kể cả khi câu có tên / ngày sinh:**

   | Câu | Chuyển với lý do |
   | --- | --- |
   | Nhờ chọn khoa / lâm sàng | `CLINICAL_QUESTION` (G17) |
   | Tạo / đăng ký hồ sơ | `PATIENT_NOT_FOUND` (G11) |
   | Bảo hiểm / giá | `OUT_OF_SCOPE` (G10) |
   | Hủy / đổi / hỏi lịch đã có | `OUT_OF_SCOPE` (G22) |
   | Đặt hộ người khác | `OUT_OF_SCOPE` (G12, D-7) |
   | Xin gặp người | `PATIENT_REQUEST` |
2. **Đọc tên + ngày sinh** bất kể đang hỏi câu nào (quy tắc Q-1 hiện có).
   - G5: ngày sinh neo theo "sinh / ngày sinh / năm sinh".
   - Ngày đứng sau "đặt / khám / lịch / hẹn" không phải ứng viên ngày sinh mà là tiêu chí khung, được giữ cùng nhu cầu.
3. **Câu nêu nhu cầu đặt lịch** (có hoặc không kèm tiêu chí) **không** tính là hiểu sai (D-2).
   - Giữ nhu cầu + tiêu chí (G3).
   - Hỏi lại đúng câu đang hỏi bằng lời "để bảo mật…". Chỉ miễn một lần; lần thứ hai liên tiếp tính như thường (R6).
4. **G19** — tên có "Không" / "Có" được nhận khi:
   - cả câu chỉ là một tên;
   - tên có ít nhất 3 từ;
   - từ đầu là họ phổ biến;
   - từ chức năng không đứng đầu.

   Vẫn loại: "không có", "tôi không biết", "không phải tôi", "không có ai tên vậy".
   - **Phải ship cùng G2.** Sửa riêng G2 thì 03 tụt: tên bị loại → hỏi lại → lượt 3 là ngày sinh → kịch bản hết → `MISSING`. Edge case M03b, ID10 kiểm đúng điều này.
5. **Đủ tên + ngày sinh → `verify`.** Không khớp → chuyển ngay lượt đó (04 ở lượt 3). Không nói yếu tố nào sai.

### 5.3 Vào luồng đặt lịch (G3, G4, G18, G20)

- **`_verify` inbound:**

  | Đã có gì | Bot làm gì |
  | --- | --- |
  | (a) Tiêu chí thời gian (10: "chiều 14 tháng 10") | `_start(BOOK)`, tra `/slots` theo tiêu chí, mời ngay trong lượt xác minh |
  | (b) Nhu cầu đặt lịch, chưa có thời gian (01–08) | **`ASK_BOOKING_NEED`** (mới): "Cảm ơn anh chị. Anh chị muốn khám khoa nào và khoảng thời gian nào ạ?" — gần như nguyên câu Hình 0. Đã có khoa thì hỏi thời gian (**`ASK_BOOKING_TIME`**) |
  | (c) Chưa có nhu cầu (chỉ "Alo") | `ASK_INTENT_INBOUND` như nay |
- **Trả lời câu hỏi nhu cầu** (`ASK_BOOKING_NEED`, `ASK_BOOKING_TIME`, `ASK_INTENT` inbound — G4):

  | Câu trả lời | Bot làm gì |
  | --- | --- |
  | Có thời gian (có khoa hay không) | Tra `/slots` |
  | Chỉ có khoa ("Khám tổng quát") | `ASK_BOOKING_TIME`, không tính hiểu sai |
  | "Gần nhất / sớm nhất / lúc nào cũng được / tùy em" | Khung sớm nhất (G18) |
  | Nhờ chọn khoa | `CLINICAL_QUESTION`, thắng mọi nhánh |
  | Lịch đã có | `OUT_OF_SCOPE` |
- **Khoa (D-5 sửa lại):**
  - Bot hỏi khoa theo Hình 0, nhưng **không lọc và không nhắc lại tên khoa**.
  - Lý do: mock không nhận khoa; nhắc khoa trong câu chốt là hứa một điều mock không đảm bảo; và không có câu nào của bot chứa tên khoa (SF-04).
  - Câu chốt chỉ nói giờ, ngày, cơ sở.

### 5.4 Luồng chọn khung: `BOOK` khác `RESCHEDULE` ở đâu (G6, G7, G8, G9, G15, G18, G21)

| Khía cạnh | RESCHEDULE (`main`) | BOOK `main` | BOOK đích |
| --- | --- | --- | --- |
| Cửa sổ `/slots` | từ ngày khách xin | luôn từ hôm nay | từ ngày khách xin (G6) |
| Đúng một khung khớp tiêu chí | câu có/không | câu có/không ("Em còn khung…, đặt giờ đó nhé ạ?") | giữ: "Ừ, 3 giờ chiều đó được" ghi ngay (02) |
| Không có giờ khách xin | "Em chưa thấy khung giờ đó" + trang 2 khung | như Reschedule | "Em chưa thấy khung giờ đó" + **một** khung gần nhất (cùng ngày trước, nếu không thì khung sớm nhất sau thời điểm xin), dạng có/không (G21). Reschedule giữ nguyên |
| "Gần nhất / sớm nhất" | — | "chưa hiểu" ở trang 2 khung | khung sớm nhất, dạng có/không (G18) |
| "Giờ em vừa nói / giờ đó / cái đó cũng được", "không có thì X cũng được" | ghi | đọc lại lần nữa / "chưa hiểu" | lượt trước mời đúng một khung (hoặc X khớp đúng một khung vừa nói) → đồng ý khung đó (G15, G21); trang 2 khung mà không rõ → hỏi khung nào |
| Chọn trên trang | ghi ngay | đọc lại | giữ đọc lại (§1.1.10) |
| Bỏ đặt lịch ("giờ khác không được", "không có giờ đó thì thôi", "để tôi gọi lại", "khỏi đặt") | `PATIENT_REQUEST` | MORE / hỏi lại nhu cầu | **`PATIENT_REQUEST`, 0 ghi** (G7) |
| "Còn giờ nào khác không" khi hết khung | — | "Em đã đọc hết… tìm ngày khác không ạ?" | báo hết khung, **giữ lời mời khung đang có** (OA05) |
| "Tôi đổi ý" (B15) | quay lại câu đọc lịch cũ | hỏi lại nhu cầu | giữ |
| Hết 2 vòng | `PATIENT_REQUEST`, "lịch cũ giữ nguyên" | câu sai | câu riêng (G8) |
| Khung bị lấy | 409 → đọc lại `/slots` | 404 → `SYSTEM_ERROR` | 404/409 → đọc lại `/slots`, mời lại, cần đồng ý mới (G9) |
| Tầng model chọn khung | Jev / Luna (cờ) | dùng nhãn đổi lịch | câu hỏi / nhãn `BOOK` (G14, PR 3) |

Đường ghi `BOOK` không mở thêm cửa nào. G15/G21 chỉ đổi nhãn `agreement` khi lượt trước là câu có/không về **đúng một khung**, và vẫn qua `assert_action_confirmed`.

### 5.5 Bẫy và ngoài phạm vi trên inbound (mọi lượt, kể cả trước xác minh, chỉ luật)

| Lớp câu | Ví dụ | Xử lý | Lý do chuyển | Căn cứ |
| --- | --- | --- | --- | --- |
| Nhờ chọn / gợi ý khoa từ triệu chứng | "đau bụng bên phải, nên khám khoa nào em?" (08), "nên đặt khám khoa gì", "chuyên khoa nào", "thuộc khoa nào", "khám tim mạch hay nội tổng quát?", có / không dấu | chuyển ngay, thắng nhu cầu đặt lịch, không nêu tên khoa | `CLINICAL_QUESTION` | §1.2.1, SF-04 |
| Tạo / đăng ký hồ sơ | "tạo mới giúp tôi" (05), "đăng ký mới cho tôi" ("đăng ký khám" vẫn là đặt lịch) | chuyển ngay | `PATIENT_NOT_FOUND` | §1.1.9 |
| Bảo hiểm, giá, thanh toán | 09; "khám tổng quát hết bao nhiêu tiền" | chuyển ngay, kể cả cùng câu tên | `OUT_OF_SCOPE` | §1.2.3 |
| Lịch đã có | "tôi muốn hủy lịch khám" | chuyển ngay, không cần xác minh | `OUT_OF_SCOPE` | Bảng 1 |
| Đặt hộ | "đặt lịch khám cho mẹ tôi" | chuyển | `OUT_OF_SCOPE` | Bảng 1 ("bệnh nhân gọi đến"), §1.1.5 |
| Xin gặp người | "cho tôi gặp nhân viên" | chuyển | `PATIENT_REQUEST` | GC-XFER |
| Ba lượt im lặng | — | chuyển, không tạo lịch | `NOT_UNDERSTOOD` | §1.1.7 |
| Đối chứng: khách tự chọn khoa | "đau dạ dày, muốn khám tiêu hóa chiều mai" | đặt tiếp, không nhắc tên khoa | — | D-11 |

## 6. Ground truth → test và edge case

### 6.1 Test case mentor (PR 1)

`tests/engine/test_mentor_eval_booking.py` gồm:
- 10 kịch bản thật (§1.1) + lượt đoán. `caller_number` = SĐT hồ sơ (Q1: harness đã gửi số; giá trị thật của 03/05 theo Q1b). Chạy trên cả `canonical` và `mentor_mock`.
- Biến thể `caller_number = null` → chuyển ở lượt 1, 0 tra cứu, 0 ghi (D-10 A).

Các chế độ như `test_mentor_eval_reschedule.py`: `rule`, `llm`, `timeout`. Tầng model chọn khung không được gọi ở lượt của case mentor (`calls == 0`).

### 6.2 Edge case mức cuộc gọi (đã có, chưa commit)

- **Dữ liệu:** [`eval/book/inbound_scenarios.csv`](../../eval/book/inbound_scenarios.csv), 65 dòng.
- **Runner:** [`scripts/booking_scenarios_eval.py`](../../scripts/booking_scenarios_eval.py).
- **Cột:** `id, split, group, source, caller_number, dataset, turns, expect_outcome, expect_slot, expect_reason, end_by, must_not, note`.
- **Cú pháp `turns`:**
  - Lượt cách nhau bằng ` || `.
  - `*` = câu đoán.
  - `<SILENCE>` = lượt im lặng.
  - `@take:<slot>` = người khác vừa lấy khung.
- **`end_by`:** `5` = kết thúc không muộn hơn lượt 5; `=3` = kết thúc đúng lượt 3. Dạng `=3` kiểm D-2: câu nêu nhu cầu không được làm cuộc gọi kết thúc sớm.

```powershell
$env:PYTHONUTF8 = "1"
python scripts/booking_scenarios_eval.py                      # toàn bộ
python scripts/booking_scenarios_eval.py --only M0 --show     # in hội thoại các dòng mentor
```

| Nhóm | Số dòng | Nội dung | Baseline `main` grade · strict |
| --- | --- | --- | --- |
| `mentor` | 12 | 10 kịch bản thật; 03 và 05 thêm biến thể số có hồ sơ / số không có hồ sơ | 8/12 · 5/12 |
| `mentor_demo_slots` | 5 | 01, 02, 06, 07, 10 trên dữ liệu có khung demo | 1/5 · 0/5 |
| `no_caller_number` | 2 | 01, 10 với `null` → chuyển ở lượt 1, 0 tra cứu | 2/2 · 2/2 |
| `identity` | 10 | ngày sinh trước tên; chỉ "Alo"; tên + ngày sinh một câu; mất dấu; ậm ừ ×2; im lặng ×3; "Ai đấy em?"; sai tên; bệnh nhân demo; tên có chữ "Không" | 6/10 · 4/10 |
| `need` | 7 | ví dụ Hình 0 ("Nội tổng quát, tuần sau được không?"); chỉ thời gian; "sớm nhất"; khoa rồi giờ; "ngày 16 tháng này"; ngày không có khung; "chiều nay" | 0/7 · 0/7 |
| `offer` | 9 | chọn trên trang; "dạ" trần; hỏi giờ khác; đồng ý có điều kiện; "giờ đó cũng được"; "ừ mà thôi…" đổi ý | 0/9 · 0/9 |
| `give_up` | 5 | "không có giờ đó thì thôi"; "gọi lại sau"; "khỏi đặt"; xin gặp người; cố đòi 8:00 | 5/5 · 1/5 |
| `trap` | 11 | triage ở lượt 1 / câu hỏi nhu cầu / câu mời / mất dấu / cùng câu tên; tạo hồ sơ; bảo hiểm cùng tên; giá; hủy lịch; đặt cho mẹ; xin gặp người | 7/11 · 6/11 |
| `trap_control` | 1 | khách tự chọn khoa + nêu triệu chứng → vẫn đặt, không nhắc tên khoa | 1/1 · 1/1 |
| `write_safety` | 3 | khung bị lấy giữa chừng (404); "khoan đã"; "ừ" sau trang 2 khung | 0/3 · 0/3 |
| **Tổng** | **65** | 19 mentor · 12 dev · 34 held-out | **30/65 · 19/65**, 0 lệnh ghi sai |

Chi tiết chạy trên `6c2dff5`:
- Mọi kịch bản `BOOKED` có câu chỉ nêu giờ sau xác minh đều hỏng ở câu hỏi nhu cầu (G3/G4/G20). Chỉ ID02, ID03, TR12 đặt được: câu sau xác minh có cả ý đặt / khám lẫn giờ.
- Các nhóm `TRANSFERRED` đạt grade phần lớn **nhờ chuyển vì `NOT_UNDERSTOOD` / `OUT_OF_SCOPE`**, nên strict thấp.

**Lưu ý:**
- Lượt có dấu `*` là đoán. Mỗi lần mentor chạy lại mà lộ thêm câu thì thay bằng nguyên văn.
- Held-out do chính người viết plan soạn, nên chưa độc lập. Trước khi code PR 1: commit CSV để đóng băng, rồi nhờ một người chưa đọc luật mới (PM/QC) thêm 10–15 cách nói khác vào held-out.

### 6.3 Mức lượt (PR 2)

`scripts/booking_eval.py` + `eval/book/turns.csv` như bản 1: cùng cột với `eval/reschedule/cases.csv`, dùng lại `_observe`.
- Thêm `SETUP` mới: `ASK_BOOKING_NEED`, `ASK_BOOKING_TIME`, và câu mời một khung sau khi báo không có giờ xin.
- Nhãn mới: `ASK_TIME`, `EARLIEST`, `GIVE_UP`.

## 7. Gate hồi quy (mỗi PR)

- `make check` xanh (Windows: `PYTHONUTF8=1`).
- `booking_scenarios_eval.py`:
  - strict **19/19** dòng `mentor`;
  - ≥ 90% held-out;
  - grade 100% dev;
  - **0 lệnh ghi sai**.
  - Dòng nào đổi nhãn so với lần trước phải giải thích.
- Phát lại 10 kịch bản thật với `caller_number = null`: cả 10 chuyển ở lượt 1 (D-10 A), không tụt case `TRANSFERRED` nào.
- `reschedule_eval.py --baseline` giống từng câu so với snapshot sau PR #123. `test_mentor_eval_reschedule.py` 7/7 ở mọi chế độ. Eval Confirm / Cancel / No-answer / Identity giống hệt từng case.
- Sửa `templates.py` → `python scripts/tts_utterance_catalog.py --date 2026-10-08`; câu tĩnh mới (`ASK_BOOKING_NEED`, `ASK_BOOKING_TIME`, câu bỏ đặt lịch) vào danh sách PM duyệt.
- Test đổi kỳ vọng có chủ đích: [test_identity_dialogue.py:594](../../tests/engine/test_identity_dialogue.py#L594) `test_request_before_identity_asks_to_verify_first` (nhu cầu đặt lịch được giữ; xác minh xong hỏi khoa / thời gian). Giữ nguyên `:73` và `:81` (số không có hồ sơ / không có số → chuyển ở lượt 1).

## 8. Thứ tự làm, chia PR, ước lượng

Nguyên tắc như Reschedule: test + held-out trước → sửa theo nguyên nhân gốc ở đúng tầng → gate → bàn giao test local → commit khi owner bảo → PR.

| PR | Nội dung | Gap | File chính | Ước lượng |
| --- | --- | --- | --- | --- |
| PR 0 | Xong (#128) | G0 | — | — |
| PR 1 (P0, 14/10) | Commit/đóng băng CSV + `test_mentor_eval_booking.py`. Định danh: G2 + G19 cùng nhau, G5, triage / tạo hồ sơ / lịch đã có / đặt hộ / bảo hiểm ở lượt danh tính. Vào đặt lịch: `_early_booking`, `ASK_BOOKING_NEED` / `ASK_BOOKING_TIME`, `_intent` inbound, "gần nhất" ở câu hỏi nhu cầu | G2, G3, G4, G5, G10, G11, G12, G17, G18 (một phần), G19, G20, G22 | `full_name.py`, `dob.py`, `intent.py`, `clinical.py`, `extractor.py`, `schema.py` (`QuestionId`), `manager.py`, `templates.py`, `context.py`, tests | 2 ngày |
| PR 2 (P0/P1, 15/10) | Luồng chọn khung `BOOK`: bỏ đặt lịch → `PATIENT_REQUEST`; mời một khung gần nhất + đồng ý theo khung vừa mời; "gần nhất" trên trang; tra từ ngày xin; câu chuyển máy riêng; 404 khung → `SlotTaken`; `booking_eval.py` mức lượt | G6, G7, G8, G9, G15, G18, G21 | `manager.py`, `agreement.py`, `slot_choice.py`, `templates.py`, `clinic_gateway.py`, `scripts/booking_eval.py`, `eval/book/turns.csv` | 1–1,5 ngày |
| PR 3 (P2, sau 16/10, cờ tắt) | Câu hỏi / nhãn `BOOK` cho tầng Jev / Luna; runner oracle `eval/book/cases.csv` | G14, G16 | `slot_semantic*.py`, `scripts/booking_oracle_eval.py` | 2 ngày |

**Lịch (gate W5 16/10):**
- **13/10:** Q1 xong (harness gửi số), D-10 đóng. Còn: gửi Q5 (§2.4); xem Q1b + Q3 trên trang báo cáo; báo Hoàn (Q4); owner chốt D-5, D-8, D-11, D-12; D-13 chờ Q5.
- **14/10:** PR 1 → gate → bàn giao test local.
- **15/10:** PR 2 → gate → deploy (đích theo D-8) → nhờ mentor chạy lại (nếu Q5 cho biết fixture đã dời ngày).
- **16/10:** chỉ sửa lỗi lộ ra từ lần chạy lại; freeze.

Nếu Q5 trả lời "giữ fixture 14/10 15:00, chạy lại trước giờ đó" (D-13 phương án 2): rút phạm vi xuống đúng những gap mà 10 kịch bản mentor cần (G2, G3, G4, G5, G7, G11, G15, G18, G19, G20, G21) vào một lần deploy trưa 14/10. Gate: strict 17/17 dòng `mentor` + `mentor_demo_slots`, 0 lệnh ghi sai, `reschedule_eval` giống từng câu. Phần còn lại (G6, G8, G9, G10, G12, G17, G22, eval mức lượt) làm sau. Rủi ro: một ngày công dồn, ít thời gian cho held-out.

## 9. Quyết định cần owner chốt

| # | Câu hỏi | Đề xuất | Vì sao | Trạng thái (13-10 chiều) |
| --- | --- | --- | --- | --- |
| D-1 | Thiếu số gọi đến: hỏi gì trước? | **Thay bằng D-10** | Bản 1 đề xuất hỏi SĐT trước; kịch bản thật không đọc SĐT | Đóng |
| D-2 | Câu nêu nhu cầu đặt lịch ở lượt danh tính có tốn lượt hỏi lại? | **Contract trả lời: không**, nhưng chỉ miễn một lần | Hình 0: lượt 1 "Alô, tôi muốn đặt lịch khám ạ." → bot hỏi tên | Contract đã trả lời, chỉ cần biết |
| D-3 | Có nhu cầu đặt lịch nhưng chưa có giờ | **Đổi:** hỏi "khoa nào và khoảng thời gian nào" (bản 1: đọc 2 khung sớm nhất) | Hình 0 và kịch bản 01–08 trả lời đúng câu này | Contract + kịch bản đã trả lời, chỉ cần biết |
| D-4 | Đặt lịch có chọn-là-ghi không? | **Contract trả lời: không.** G15/G21 chỉ là đồng ý **một** khung vừa mời | §1.1.10; Hình 0 | Contract đã trả lời, chỉ cần biết |
| D-5 | Khoa | **Đổi:** hỏi theo Hình 0, không lọc, không nhắc lại tên khoa | Mock không nhận khoa; SF-04 | **Cần chốt** |
| D-6 | Khung demo b501–b510 lúc mentor chấm | Giữ (đỡ cho demo W6) | Với 10 kịch bản, khung đích là `slot_91d2` trên cả hai bộ dữ liệu (khung demo bắt đầu từ 15/10); nhóm `mentor_demo_slots` kiểm | Đóng: giữ, không cần chờ Q3 |
| D-7 | Đặt hộ người khác | **Contract trả lời: chuyển** (`OUT_OF_SCOPE`) | Bảng 1: "bệnh nhân gọi đến"; §1.1.5 | Contract đã trả lời, chỉ cần biết |
| D-8 | Đích PR | `main` như Reschedule (đường chấm = prod), hoặc `develop` trước nếu PM còn test ở đó | Luồng develop → main, ngoại lệ 12-10 | **Cần chốt** |
| D-9 | PRD R-09 (hỏi SĐT khi thiếu số) | Không làm trước gate | Harness đã gửi số; contract không đòi; hỏi SĐT làm tụt 4/10 | Đóng với eval; PM chỉ cần biết |
| D-10 | Không có `caller_number` | **A**: chuyển ở lượt 1 như `main` (§5.1) | Harness đã gửi số; `null` chỉ còn là đường dự phòng | Đóng: A, không đổi code |
| D-11 | Khách tự chọn khoa và có nêu triệu chứng | Đặt tiếp, không nhắc tên khoa | §1.2.1 cấm tư vấn / phân loại, không cấm đặt khoa khách tự chọn; TR12 | **Cần chốt** |
| D-12 | Sau khi báo không có giờ khách xin, `BOOK` mời **một** khung gần nhất (Reschedule vẫn đọc trang 2 khung) | Đồng ý | Hình 0 / ví dụ Reschedule đều mời bằng câu có/không; "giờ em vừa nói" phải rõ nghĩa | **Cần chốt** |
| D-13 (mới) | Lịch ship và lần nhờ mentor chạy lại | (1) Mentor dời ngày / khung theo ngày chạy → giữ PR 1 (14/10) → PR 2 (15/10) → chạy lại 15/10. (2) Mentor giữ khung 14/10 15:00 → rút phạm vi, deploy trưa 14/10, nhờ chạy trước 15:00 (§8) | Chạy sau 14/10 15:00 với seed gốc thì 4 case BOOKED không đạt được | **Cần chốt sau Q5** |

## 10. Rủi ro

| # | Rủi ro | Giảm thiểu |
| --- | --- | --- |
| R1 | Mentor không đổi harness → 4 case BOOKED không bao giờ đạt | **Hết** (13-10: harness đã gửi số). Vẫn **không** dò hồ sơ qua `GET /appointments?date=` hay `/_harness/*` |
| R2 | **Rủi ro bên ngoài lớn nhất.** Mentor chạy lại sau 14/10 15:00: khung gốc đã qua; "mai", "thứ tư" ra ngày khác | Q5 (tin soạn sẵn §2.4), D-13. Test cố định đồng hồ 13/10. Thiết kế không gắn ngày: không có giờ xin → một khung gần nhất còn trống (G21), ngày đã qua cũng vậy |
| R3 | Khung demo đổi lời mời so với kịch bản | G18 + G21; nhóm `mentor_demo_slots` |
| R4 | Sửa handler dùng chung làm đổi kết quả Reschedule | G21 / G7 chỉ nhánh `BOOK`; gate từng câu `reschedule_eval` |
| R6 | Miễn tính hiểu sai cho câu nêu nhu cầu tạo vòng lặp | Chỉ miễn một lần; property test: không quá 4 lượt liên tiếp không tiến triển |
| R7 | Hiểu quá rộng ở câu hỏi nhu cầu (mọi câu có giờ / khoa = đặt lịch) | Luật triage và lịch đã có xét **trước**; test âm |
| R10 | Mở rộng cụm triage chặn nhầm khách tự chọn khoa | Cụm phải có ý **nhờ bot chọn**; TR12 đối chứng |
| R11 | Prod khác `main` (force-push, deploy lại) | Trước mỗi lần nhờ mentor chạy: kiểm `gh run list --branch main` + SHA đang deploy |
| R12 | Lượt đoán sai (vd. 07 không có lượt 6 → phải ghi ngay ở lượt 5) | Thiết kế ghi ngay khi khách đồng ý khung vừa mời (G21); thay câu đoán ngay khi có kịch bản thật |
| R13 | Nới G19 làm câu không phải tên lọt vào Verifier | Điều kiện chặt (§5.2) + test âm; vào Verifier sai thì chỉ chuyển máy, không lộ gì |
| R8 | 3 ngày tới gate | PR 3 sau gate, cờ tắt |
| R9 | Live call W6 cần nhánh SIP và guard R-34 | Ngoài plan này |

## 11. Ngoài phạm vi

- Sửa mock hay thêm endpoint tìm bệnh nhân theo tên (§4.2.1).
- Hỏi SĐT khi thiếu số (PR #129): không làm, harness đã gửi số (D-10).
- Tạo bệnh nhân; chọn khoa / cơ sở khi đặt (mock không hỗ trợ).
- Phần điện thoại / SIP / R-34.
- Đổi prompt `semantic_jev_v6` của ba câu hỏi đang chạy.

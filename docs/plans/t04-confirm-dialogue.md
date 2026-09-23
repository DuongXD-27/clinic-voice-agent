# Plan T-04 — Hội thoại Confirm

**Owner:** A (Hoàn) · **Trạng thái:** Đã triển khai (Q-2, Q-5, Q-6 chốt; Q-1, Q-2b, Q-3, Q-4 theo đề xuất). §8 (sửa sau review 23-09-2026) đã triển khai, Q-7..Q-11 chốt theo đề xuất — evidence `docs/evidence/t04-confirm-dialogue.md` · **Ngày:** 18-09-2026, cập nhật 23-09-2026
**Nguồn:** `docs/task-breakdown.md` §3 (T-04), §7 bất biến 1, 3, 5, 8; `docs/reference/ai-callbot-architecture.md` §3.1–§3.3, §4.1–§4.2; `docs/reference/information-extraction-design.md` §5.4, §5.6, §6.1; `docs/reference/clinic-mock.md` §5.4; contract rev 1.1 §1, §1.1.3, §1.1.5, §2.1, §2.2, §4.2.2, §4.2.5, Bảng 1, Listing 5, Figure 0 (đọc lại site rev 1.1 ngày 18-09-2026)
**Phụ thuộc:** T-02 (xác minh), T-03 (Gateway `confirm`, PR #18 `db669f7`), F-03, F-04, F-05 — đều đã có trên `main`

## 1. Mục tiêu và điều kiện hoàn thành

> Nhận ý định tham dự; đọc lại ngày–giờ–cơ sở; nhận đồng ý đúng nội dung; xử lý từ chối hoặc chưa rõ; gọi Gateway khi đủ điều kiện.
> **Điều kiện hoàn thành:** Chỉ trả `CONFIRMED` **sau khi API xác nhận ghi thành công**.

Khung của nhánh Confirm đã có từ F-04: sau xác minh, outbound đọc tóm tắt lịch + hỏi đến được không trong một lượt (`CONFIRM_READBACK`, Figure 0). Người gọi nói AGREE thì Dialogue ghi bằng chứng rồi gọi `ClinicGateway.confirm`. T-04 không dựng lại luồng này. T-04 sửa các lỗi hiểu sai câu trả lời (§2), cho câu đọc lại có tên cơ sở thật, và khóa điều kiện hoàn thành bằng test ở ba tầng: IE, Dialogue và HTTP.

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | **Nhận ý định tham dự:** tại câu đọc lại, câu khẳng định sẽ đến ("tôi sẽ đến", "vẫn đến", "xác nhận", "giữ nguyên lịch") được coi là đồng ý. Tại `ASK_INTENT` outbound, `CONFIRM` dẫn tới câu đọc lại (đã có) | Mỗi câu → `CONFIRMED` sau 1 lượt; `ASK_INTENT` → `AWAITING_CONFIRMATION` với câu có ngày, giờ, cơ sở |
| AC-2 | **Đọc lại ngày–giờ–cơ sở:** mọi câu hỏi mở khóa `CONFIRMED` đều chứa ngày, giờ, tên cơ sở lấy từ `GET /appointments/{id}` của lượt đó | Kiểm tra `question.text` của mọi `CONFIRM_READBACK` theo dữ liệu fake |
| AC-3 | **Đồng ý đúng nội dung:** AGREE cho đúng câu đọc lại ở lượt ngay trước mới mở khóa lệnh ghi. "Vâng" / "dạ" / "ừ" là xác nhận (Q-2). Câu ngập ngừng ("để xem", "chắc là", "có lẽ") không mở khóa (Q-2b) | Ma trận §5.2: "vâng", "dạ", "ừ" → ghi; "chắc là được", "có lẽ vậy", "ờ để xem" → không ghi |
| AC-4 | **Chưa rõ:** đọc lại ngày–giờ–cơ sở bằng câu hỏi có/không. Lần 1 không tính; từ lần 2 liên tiếp mới tính §1.1.5; tới ngưỡng thì chuyển `NOT_UNDERSTOOD` + `/transfer` | Chuỗi UNCLEAR ×3 → `TRANSFERRED/NOT_UNDERSTOOD`, `writes` chỉ có TRANSFERRED |
| AC-5 | **Từ chối:** bỏ hành động chờ, không ghi, hỏi đổi hay hủy. Người gọi đổi ý "vẫn đến" thì phải đọc lại và nhận AGREE mới | `writes == []` sau REFUSE; evidence cũ bị xóa |
| AC-6 | **Gọi Gateway khi đủ điều kiện:** đã xác minh + hành động chờ `CONFIRM` + AGREE đúng lượt/câu hỏi. `VERSION_CONFLICT`: đọc lại, gửi lại với version mới và **cùng** `Idempotency-Key` (§4.2.5; Gateway T-03 đã làm) | Test guardrail hiện có + e2e `VERSION_CONFLICT` một lần → `CONFIRMED`, hai request cùng key |
| AC-7 | **Chỉ `CONFIRMED` sau khi API ghi thành công:** Mock trả `status=CONFIRMED`. Từ chối xác định → `TRANSFERRED/SYSTEM_ERROR`. Chưa rõ kết quả → `409 CALL_RECONCILIATION_REQUIRED`. Mock trả 2xx mà status khác → chặn lượt đối soát (409), không ghi `/transfer` thay thế. Không lỗi nào dẫn tới câu "đã xác nhận" | `fail_next("confirm_appointment", ...)` các lớp lỗi; HTTP e2e |
| AC-8 | Ngoại lệ vẫn kiểm tra ở bước xác nhận: lâm sàng, xin nhân viên, ngoài phạm vi, im lặng, xin nhắc lại | Test mỗi loại tại `CONFIRM_READBACK`, không ghi `CONFIRMED` |
| AC-9 | **Inbound xin xác nhận lịch có sẵn** là ngoài kịch bản inbound → chuyển máy ngay, không ghi Mock (§1, §1.1.5; Q-6) | Sau xác minh inbound, "tôi muốn xác nhận lịch khám" → `TRANSFERRED` ở lượt đó, `writes == []` |

## 2. Hiện trạng (main `db669f7`, 18-09-2026)

**Đã có và giữ nguyên:**
- `DialogueManager._verify` → `t.appointment_summary` (`CONFIRM_READBACK`, `AWAITING_INTENT`); `_attendance`; `_intent` (outbound `CONFIRM` → `t.attendance_readback`, `AWAITING_CONFIRMATION`).
- `guardrails.assert_action_confirmed`: AGREE ở chính lượt này, đúng `question_id`/`question_turn`/`action`. `fsm.check_write` và `_WRITE_STATES["CONFIRM"]` cho phép ghi từ `AWAITING_INTENT` vì câu tóm tắt gộp.
- Gateway T-03: idempotency key `call_id:turn:confirm`, `If-Match`, `VERSION_CONFLICT` → đọc lại version, gửi lại 1 lần cùng key (đúng §4.2.5), lỗi chia ba lớp. `WriteOutcomeUnknown` ∈ `TURN_ABORTING_ERRORS` → HTTP 409 đối soát.
- Test: `test_orchestrator.py::test_confirm_attendance_in_one_readback_turn`; 3 test confirm ở `test_clinic_gateway.py`.

**Khoảng cách.** Chạy thử Orchestrator thật + `FakeClinicAPI`, outbound `apt_00417` đã xác minh, câu người gọi nói ở `CONFIRM_READBACK`:

| # | Câu người gọi | Hiện tại | Đúng ra | Vị trí |
| --- | --- | --- | --- | --- |
| G-1 | "ờ để xem" | **ghi `CONFIRMED`** | chưa rõ → đọc lại. "Ờ" đứng một mình vẫn là xác nhận (Q-2); lỗi nằm ở "để xem" | `agreement.py`: không có nhóm từ ngập ngừng |
| G-2 | "chắc là được", "có lẽ vậy", "vâng để tôi xem lại" | AGREE → **sẽ ghi `CONFIRMED`** | chưa rõ | như G-1 |
| G-3 | "tôi sẽ đến" ×2, "xác nhận" | UNCLEAR → câu A/B → lặp tới `NOT_UNDERSTOOD` | đồng ý tham dự (Bảng 1: "states **or** agrees they will attend") | `_attendance` + `extractor._agreement` |
| G-4 | "vâng, giữ lịch", "giữ nguyên lịch" | REFUSE → "đổi hay hủy?" | đồng ý | `_REFUSE` có "giữ lịch"/"giữ nguyên" (đúng cho `CANCEL_RECONFIRM`, sai cho CONFIRM) |
| G-5 | "không hủy đâu, tôi vẫn đến" | REFUSE → "đổi hay hủy?" | đồng ý | như G-4 ("không hủy") |
| G-6 | "tôi sẽ đến" → câu A/B `ATTENDANCE_CHOICE` → "vâng" | ghi `CONFIRMED` cho một câu hỏi hai lựa chọn | "vâng" là xác nhận (Q-2), nên câu hỏi lại phải là câu có/không có đọc lại lịch (Q-3) | `t.ATTENDANCE_CHOICE` |
| G-7 | Câu đọc lại | "... **tại Vinmec**" cho mọi lịch | tên cơ sở thật (§1.1.3 "date, time and clinic") | Mock không trả `clinic_name`, chỉ `clinic_id`; `templates._clinic` luôn rơi vào mặc định |
| G-8 | Không kiểm tra kết quả ghi | `_attendance` bỏ qua giá trị `confirm()` trả về | `status == "CONFIRMED"` mới báo thành công | `manager.py::_attendance` |
| G-9 | Inbound sau xác minh: "tôi muốn xác nhận lịch khám" | `CONFIRM` bị lọc theo hướng gọi → `NONE` → hỏi lại, lần 2 → `NOT_UNDERSTOOD` | chuyển ngay: ngoài kịch bản (§1.1.5), lý do `OUT_OF_SCOPE` (Q-6) | `intent.py::_DIRECTION_ONLY`, `manager._intent` |

G-1, G-2 là lỗi nặng nhất: bot ghi `CONFIRMED` dù người gọi đang ngập ngừng. Với `SLOT_READBACK`, G-2 còn mở khóa cả `RESCHEDULED`/`BOOKED`, vì "được" trong "chắc là được" đủ ngưỡng.

Không phải khoảng cách: lịch đổi nội dung giữa lượt đọc lại và lượt ghi. Gateway đọc lại version và gửi lại cùng key, đúng §4.2.5 (Q-5).

### 2.1 Đối chiếu contract / kiến trúc

| Điều khoản | Nội dung | Hệ quả cho T-04 |
| --- | --- | --- |
| §1.1.3 | "MUST read back date, time **and clinic**, and MUST set `CONFIRMED` only after the patient agrees to that read-back" | AC-2, AC-3; G-7: tên cơ sở là bắt buộc (Q-4) |
| Bảng 1 | Confirm: "Patient states or agrees they will attend" | G-3, Q-1 |
| §1 | "Seven scenarios, six of them on a call the bot places and one on a call it answers"; inbound chỉ có đặt lịch mới (§1.1.9–§1.1.10) | Xác nhận lịch có sẵn không thuộc kịch bản inbound (Q-6) |
| §1.1.5 | "MUST transfer on anything outside these scenarios, or after two consecutive failed understandings" | Vế 1 → Q-6 chuyển ngay; vế 2 → UNCLEAR giữ ngữ nghĩa hiện có (§6.1 IE) |
| §2.1 | Inbound `TRANSFERRED`: chấm `outcome` + writelog rỗng; "`transfer_reason` is not checked" | Q-6 không đổi điểm; đổi tính đúng hành vi (chuyển vì ngoài kịch bản, không vì "không hiểu") |
| §2.2 | `CONFIRMED` + `confirmed_at` + `confirmed_via=callbot` | Mock tự đặt; Dialogue kiểm tra `status` (G-8) |
| §4.2.2 | Mock là nguồn duy nhất; được giữ bản đọc (`appointment_id`, `version`, slot đang đề xuất) nhưng "MUST NOT persist appointment state" | Không lưu `starts_at` / cơ sở đã đọc vào `CallContext` |
| §4.2.5, Listing 5 | "after a `409 VERSION_CONFLICT` the bot re-reads the appointment and retries with the fresh version and the same key" | Gateway T-03 đã đúng. Contract **không** có điều khoản xác nhận lại khi dữ liệu đổi → Q-5 không làm |
| Figure 0 | Tóm tắt + đọc lại + "đến được không" gộp một lượt; "Có, tôi đến được." → `CONFIRMED` | Giữ `CONFIRM_READBACK` gộp, không thêm lượt |
| Kiến trúc §3.2 | `O_AGREE` chưa rõ → `O_READ` (đọc lại); không / đổi ý → `O_INTENT` | Q-3 thay câu A/B bằng đọc lại |
| Kiến trúc §4.2 | VERSION_CONFLICT: "nếu dữ liệu ảnh hưởng nội dung đã xác nhận thay đổi, phải làm rõ/xác nhận lại" | Đây là chính sách thiết kế của đội, không phải contract. T-04 không làm; nếu cần thì thuộc T-12 "đánh giá lại điều kiện khi dữ liệu thay đổi" (B) |
| Kiến trúc §4.2 | Timeout ghi: không báo thành công khi chưa có bằng chứng | Đã có (`WriteOutcomeUnknown` → 409); T-04 chỉ thêm test |

## 3. Thiết kế

### 3.1 Luồng bước xác nhận

```text
Sau VERIFIED (outbound)
  _verify -> get_appointment -> appointment_summary (ngày, giờ, khoa, CƠ SỞ)   CONFIRM_READBACK, AWAITING_INTENT

Lượt n tại CONFIRM_READBACK  (Policy: silence / signals chạy trước, không đổi)
  intent CANCEL | RESCHEDULE         -> _start (không đổi)
  agreement AGREE                    -> set_pending(CONFIRM), ghi bằng chứng
       confirm(ctx) -> result                              # Gateway: VERSION_CONFLICT -> đọc lại, cùng key (§4.2.5)
       result.status == CONFIRMED    -> confirmed(result)  ENDED/CONFIRMED       # câu báo từ dữ liệu Mock
       khác                          -> WriteOutcomeUnknown -> 409 đối soát         # G-8: lệnh đã commit, không ghi thêm
       ClinicWriteRejected           -> (orchestrator) transfer(SYSTEM_ERROR)    # đã có
       WriteOutcomeUnknown           -> 409 CALL_RECONCILIATION_REQUIRED          # đã có
  agreement REFUSE                   -> clear_pending, ASK_CHANGE_OR_CANCEL       ASK_INTENT (không đổi)
  agreement UNCLEAR (có tín hiệu)
    hoặc intent CONFIRM mơ hồ        -> attendance_reread (đọc lại + câu có/không)  UNCLEAR   # Q-3
  không tín hiệu                     -> NOT_UNDERSTOOD (không đổi)
```

Nhánh `ASK_INTENT` outbound (sau khi từ chối, hoặc giữ lịch sau khi bỏ hủy/đổi): `CONFIRM` → `attendance_readback` (có thêm khoa, tên cơ sở), `AWAITING_CONFIRMATION`. Lượt sau xử lý như trên.

Nhánh `ASK_INTENT` inbound (Q-6): `CONFIRM` (chỉ cụm "xác nhận lịch …", §3.2 bước 5) → `transfer(OUT_OF_SCOPE)` ngay, như `CANCEL`/`RESCHEDULE`. Gateway không ghi vì inbound chưa tạo lịch.

### 3.2 IE — agreement và intent (G-1..G-5, G-9)

Chỉ sửa `extraction/agreement.py`, `extractor._agreement`, `intent.py`. Cả ba thuộc A.

1. **Ngập ngừng → UNCLEAR ở mọi câu hỏi xác nhận (Q-2b).** Thêm `_HEDGE`: "để xem", "để tôi xem", "xem đã", "xem lại", "chắc là", "có lẽ", "chắc vậy", "không chắc", "chưa chắc", "chưa biết", "tính sau", "để tôi hỏi". Xét cùng chỗ với `_CONTRAST`, tức trước khi tìm tín hiệu đồng ý. Không nhầm với "chắc chắn" (từ khẳng định). Ảnh hưởng cả `SLOT_READBACK`: sửa luôn lỗi "chắc là được" mở khóa đổi lịch/đặt lịch.
2. **Từ đáp lễ là xác nhận (Q-2, đã chốt).** Ở `CONFIRM_READBACK`/`ASK_ATTENDANCE`, "vâng", "dạ", "ừ" (và "ờ") là AGREE, kể cả khi đi kèm nội dung khác ("vâng, cảm ơn em"). Giữ nguyên ngưỡng hiện có, không siết thành "đứng một mình". Chỉ các chặn đã có (câu hỏi đuôi, "nhưng", từ phủ định, intent mâu thuẫn, lâm sàng) và nhóm ngập ngừng ở bước 1 mới hạ xuống UNCLEAR. `SLOT_READBACK` / `CANCEL_RECONFIRM` không đổi ngưỡng.
3. **Giữ lịch là đồng ý ở câu xác nhận tham dự (G-4, G-5).** Tách khỏi `_REFUSE` các cụm "giữ lịch", "giữ nguyên", "không hủy", "không hủy nữa", "đừng hủy". Các cụm này vẫn là REFUSE ở `CANCEL_RECONFIRM` (test SF-05 hiện có không đổi). Ở `CONFIRM_READBACK`/`ASK_ATTENDANCE`: "giữ lịch", "giữ nguyên (lịch)" là tín hiệu khẳng định; "không hủy", "đừng hủy" chỉ bị bỏ qua (không phải REFUSE). Câu chỉ có "không hủy" thì thành không có tín hiệu, và bước 4 quyết.
4. **Khẳng định tham dự = đồng ý (Q-1, G-3).** `extractor._agreement` truyền cụm intent `CONFIRM` vào `extract_agreement(..., attendance=span)`. Ở câu hỏi đến khám, cụm này là tín hiệu AGREE, xét **sau** mọi chặn (câu hỏi đuôi, "nhưng", ngập ngừng, từ chối — "không, tôi vẫn đến" là mâu thuẫn → UNCLEAR). *Khác bản nháp:* nháp ghi đè sau khi agreement không thấy tín hiệu; làm trong `extract_agreement` để các chặn luôn chạy trước. Câu hỏi đuôi ("tôi sẽ đến được không") đã là UNCLEAR có tín hiệu nên không bị ghi đè. "Không đến được" là `CANCEL`, không phải `CONFIRM`.
5. **Inbound "xác nhận lịch" (Q-6).** `intent.py`: inbound chỉ gán `CONFIRM` cho cụm chỉ lịch có sẵn ("xác nhận lịch", "xác nhận lịch hẹn", "xác nhận lịch khám"). Các cụm "tôi đến", "đến được", "sẽ đến" vẫn chỉ outbound: inbound "sáng mai tôi đến được không" là nhu cầu đặt lịch, không được chuyển máy nhầm. `BOOK` vẫn ưu tiên hơn `CONFIRM`.

IE vẫn tuân nguyên tắc: không đọc hồ sơ, không đọc lịch hẹn, chỉ gắn nhãn theo `question_id` và hướng gọi.

### 3.3 Dialogue (`dialogue/manager.py`)

- `_attendance`:
  - AGREE: gọi `confirm`, kiểm tra `result["status"] == "CONFIRMED"` (G-8), rồi mới `_finish("CONFIRMED", t.confirmed(ctx, result))`. Status khác → `WriteOutcomeUnknown`: lệnh đã `SUCCEEDED` trong nhật ký nên phiên đã khóa (F-03), không ghi `/transfer` được — chặn đối soát là kết quả trung thực duy nhất.
  - UNCLEAR, hoặc `intent CONFIRM` mà agreement không phải AGREE: `t.attendance_reread` (Q-3).
- `_intent` inbound: `CONFIRM` → `transfer(OUT_OF_SCOPE)` như `CANCEL`/`RESCHEDULE` (Q-6).
- Không thêm trường vào `CallContext` (giữ `SCHEMA_VERSION = 1`), không lưu trạng thái lịch hẹn (§4.2.2), không sửa Gateway (B).

### 3.4 Câu thoại (`dialogue/templates.py`)

| Hàm / hằng | Nội dung (nháp) | Ghi chú |
| --- | --- | --- |
| `clinic_name(appointment)` | `CLINIC_NAMES.get(clinic_id)` → "Vinmec Times City"; không có trong bảng thì "Vinmec" | Q-4. Bảng lấy từ seed Mock (`clinic-mock/.../store.py::CLINICS`) |
| `attendance_facts(appointment)` | "{giờ} ngày {d} tháng {m} tại {cơ sở}" | Dùng chung cho summary / readback / reread / câu báo thành công |
| `attendance_readback` | "Dạ, em xin xác nhận lại: lịch khám {khoa} {facts}. Anh chị đồng ý chứ ạ?" | Thêm khoa |
| `attendance_reread` (thay `ATTENDANCE_CHOICE`) | "Dạ, lịch khám {khoa} của anh chị là {facts}. Anh chị có đến khám được theo lịch này không ạ?" | Câu có/không: "vâng" là câu trả lời hợp lệ (Q-2) |
| `confirmed(ctx, result)` | "Dạ, em đã xác nhận lịch khám {facts từ `result`} cho anh chị. Hẹn gặp anh chị ạ." | Câu báo thành công dựng từ dữ liệu Mock trả về, không từ câu đã đọc |

Mọi hàm có chi tiết lịch đều gọi `guardrails.assert_can_disclose` (SF-03). Xóa `ATTENDANCE_CHOICE`.

## 4. Các bước thực hiện

| Bước | Việc | File | Phụ thuộc |
| --- | --- | --- | --- |
| 0 | Tạo `feature/t04-confirm-dialogue` từ `main` (`db669f7`) | — | — |
| 1 | IE agreement: ngập ngừng, giữ lịch / không hủy theo câu hỏi (§3.2 bước 1, 3) + unit test có dấu / không dấu | `extraction/agreement.py`, `tests/engine/extraction/test_agreement.py`, `test_unaccented.py` | 0 |
| 2 | IE: `CONFIRM` → AGREE ở câu xác nhận tham dự (bước 4); inbound `CONFIRM` chỉ cho cụm "xác nhận lịch …" (bước 5) + test | `extraction/extractor.py`, `intent.py`, `tests/engine/extraction/test_extractor.py`, `test_intent.py` | 1 |
| 3 | Câu thoại §3.4 + bảng tên cơ sở | `dialogue/templates.py` | Q-4 |
| 4 | `_attendance` (kiểm tra kết quả, đọc lại khi chưa rõ); `_intent` inbound | `dialogue/manager.py` | 2, 3 |
| 5 | Test luồng mới `tests/engine/test_confirm_dialogue.py` (§5.2) + HTTP e2e | `tests/engine/`, `tests/transports/http/test_calls.py` | 4 |
| 6 | Sửa test đổi kỳ vọng (§5.1) | xem §5.1 | 4 |
| 7 | Tài liệu: IE design §5.6 (ngập ngừng + "giữ lịch"); kiến trúc §4.2 (ghi rõ dòng VERSION_CONFLICT "xác nhận lại" là chính sách, chưa triển khai) + §5 (Dialogue). Không sửa `docs/evidence/f04-...` (lịch sử) | docs | 4 |
| 8 | `make check`; viết `docs/evidence/t04-confirm-dialogue.md` | — | tất cả |

Ước lượng: bước 1–2 khoảng nửa ngày (phần lớn là bộ bẫy test), bước 3–6 khoảng một ngày.

## 5. Test

### 5.1 Test hiện có sẽ đổi kỳ vọng

| Test | Đổi |
| --- | --- |
| `test_agreement.py::test_confirm_readback_accepts_any_affirmative` | Giữ nguyên; thêm "vâng, cảm ơn em", "dạ vâng ạ", "ừ" (Q-2) |
| `test_intent.py` (`"tôi sẽ đến"` inbound → `NONE`) | Giữ nguyên; thêm "tôi muốn xác nhận lịch khám" inbound → `CONFIRM` |
| `test_orchestrator.py::test_confirm_attendance_in_one_readback_turn` | Kỳ vọng câu có "Vinmec Times City" (Q-4); logic không đổi |
| `test_ner.py` (`CONFIRM_READBACK`, "có lẽ") | Không gọi HTTP: vẫn đúng vì "có lẽ" có tín hiệu ngập ngừng → không đi tuyến sau |

### 5.2 Test mới

IE (`test_agreement.py`, `test_extractor.py`, `test_unaccented.py`, `test_intent.py`):
- UNCLEAR ở `CONFIRM_READBACK` **và** `SLOT_READBACK`: "ờ để xem", "chắc là được", "có lẽ vậy", "vâng để tôi xem lại", "để tôi hỏi vợ đã", "chưa chắc".
- AGREE ở `CONFIRM_READBACK`: "vâng", "dạ", "ừ", "ờ", "vâng em", "dạ vâng ạ", "vâng cảm ơn em", "giữ lịch nhé", "giữ nguyên lịch", "chắc chắn rồi"; bản không dấu theo luật hiện có ("vang" AGREE; "da" vẫn bị loại vì trùng "đã").
- `CANCEL_RECONFIRM` không đổi: "giữ lịch", "không hủy", "đừng hủy" vẫn REFUSE (test SF-05 hiện có).
- Extractor: "tôi sẽ đến", "vẫn đến", "xác nhận", "không hủy đâu, tôi vẫn đến" → AGREE với `span` là cụm intent; "tôi sẽ đến được không" → UNCLEAR; "không đến được" → intent `CANCEL`, không AGREE.
- Inbound intent: "tôi muốn xác nhận lịch khám" → `CONFIRM`; "sáng mai tôi đến được không", "tôi sẽ đến" → không phải `CONFIRM`.

Luồng (`tests/engine/test_confirm_dialogue.py`, Orchestrator thật + `FakeClinicAPI`):

| Nhóm | Case | Kỳ vọng |
| --- | --- | --- |
| Đồng ý | "Có, tôi đến được.", "vâng", "dạ", "ừ", "tôi sẽ đến", "xác nhận", "giữ nguyên lịch" | `CONFIRMED` 1 lượt; `writes == [("apt_00417","CONFIRMED",{})]`; câu báo có giờ + cơ sở; context đã xóa |
| Chưa rõ | "chắc là được" → "vâng" | lượt 1 không ghi, câu có ngày giờ + cơ sở + câu hỏi có/không; lượt 2 `CONFIRMED`; evidence đúng lượt 2 |
| Chưa rõ tới ngưỡng | UNCLEAR ×3 | `TRANSFERRED/NOT_UNDERSTOOD`, chỉ ghi TRANSFERRED |
| Từ chối / đổi ý | "không" → "thôi tôi vẫn đến" → "đồng ý" | lượt 1 không ghi, hỏi đổi hay hủy; lượt 2 đọc lại (`AWAITING_CONFIRMATION`); lượt 3 `CONFIRMED` |
| Từ chối rồi "vâng" | "không" → "vâng" | không ghi (câu hỏi mở "đổi hay hủy") |
| Rẽ nhánh | "không đến được", "vâng nhưng tôi muốn đổi giờ" | sang hủy / đổi lịch, không ghi `CONFIRMED` |
| Ngoại lệ | "vâng, à mà tôi đau ngực"; "cho tôi gặp nhân viên"; im lặng; "gì cơ" | `CLINICAL_QUESTION` / `PATIENT_REQUEST` / nhắc, câu hỏi chờ giữ nguyên / đọc lại đúng câu, không đếm |
| Ghi bị từ chối | `fail_next("confirm_appointment", 409 INVALID_STATE_TRANSITION)` | `TRANSFERRED/SYSTEM_ERROR`, không có câu "đã xác nhận" |
| Chưa rõ kết quả | `fail_next(..., TIMEOUT, apply_first=True)` | `WriteOutcomeUnknown` / HTTP `409 CALL_RECONCILIATION_REQUIRED`; không có `CONFIRMED` trong phản hồi |
| VERSION_CONFLICT 1 lần | `fail_next(..., 409 VERSION_CONFLICT)` | đọc lại, retry version mới + cùng key → `CONFIRMED` (§4.2.5) |
| Status lạ | stub `confirm_appointment` trả `status=SCHEDULED` | `ReconciliationRequired`, không `CONFIRMED`, không ghi thêm |
| Gửi lại | gửi lại đúng lượt đã `CONFIRMED` | `CallEnded` (F-03 xóa nội dung sau ghi Clinic), `writes` vẫn 1 |
| Inbound (Q-6) | "tôi muốn xác nhận lịch khám" sau xác minh | `TRANSFERRED` ngay lượt đó, `writes == []`; "sáng mai tôi đến được không" không bị chuyển |
| SF-03 | mọi câu trước `VERIFIED` | không chứa giờ / cơ sở (dùng lại `test_sf03_appointment_disclosure.py`) |

HTTP (`test_calls.py`): một cuộc outbound đầy đủ qua `/v1/calls` + `/turn` → lượt cuối `ended=true, outcome=CONFIRMED`; một cuộc lỗi ghi → `outcome=TRANSFERRED`.

## 6. Quyết định

| # | Câu hỏi | Quyết định | Căn cứ / phương án khác |
| --- | --- | --- | --- |
| Q-1 | Câu khẳng định tham dự không có từ đồng ý ("tôi sẽ đến", "xác nhận") ở câu đọc lại có ghi `CONFIRMED` không? | Đề xuất **có**: coi là AGREE (§3.2 bước 4) | Bảng 1 "states or agrees they will attend"; câu đọc lại đã có đủ ngày, giờ, cơ sở. Giữ hiện trạng (F-04 chọn UNCLEAR) thì người gọi nói "tôi sẽ đến" hai lần là bị chuyển máy |
| Q-2 | "Vâng" / "dạ" / "ừ" ở câu đọc lại có là xác nhận không? | **Đã chốt: là xác nhận** (18-09-2026). Giữ ngưỡng hiện có, không siết "đứng một mình". *Siết lại ngày 23-09-2026: phần còn lại của câu phải được giải thích hết — xem §8.1* | Khớp §1.1.3 "agrees to that read-back" |
| Q-2b | Câu ngập ngừng ("để xem", "chắc là", "có lẽ", "chưa chắc") có hạ xuống UNCLEAR không, kể cả khi có "vâng"/"được"? | Đề xuất **có** | Không mâu thuẫn Q-2: "vâng" vẫn là xác nhận, chỉ câu có cụm ngập ngừng mới bị hỏi lại. Nếu không muốn, bỏ bước 1 §3.2 (khi đó "ờ để xem" vẫn ghi `CONFIRMED`) |
| Q-3 | Chưa rõ: đọc lại (câu có/không) thay cho câu A/B `ATTENDANCE_CHOICE` | Đề xuất **đọc lại** | Kiến trúc §3.2 "Chưa rõ → O_READ". Vì "vâng" là xác nhận (Q-2), câu hỏi lại phải là câu có/không. Phương án khác: giữ câu A/B với `QuestionId` riêng, phải sửa thêm FSM (`CONFIRMATION_QUESTION_FOR`) |
| Q-4 | Đọc tên cơ sở thế nào khi Mock chỉ trả `clinic_id`? | Đề xuất bảng `clinic_id → tên` trong `templates.py`, lấy từ seed Mock; không có trong bảng thì "Vinmec" | §1.1.3 bắt đọc "clinic". Không có endpoint `/clinics`. Phương án khác: đưa bảng vào `EngineSettings` (env JSON) nếu harness chấm dùng `clinic_id` khác. Nên hỏi `#residency-batch03` harness có kiểm tên cơ sở trong `utterance` không |
| Q-5 | Có đọc lại lịch ngay trước khi ghi để phát hiện nội dung đã đổi không? | **Đã chốt theo contract: không làm ở T-04** | Contract chỉ yêu cầu: sau `409 VERSION_CONFLICT` "re-reads the appointment and retries with the fresh version and the same key" (§4.2.5, Listing 5); Gateway T-03 đã làm. Không có điều khoản bắt xác nhận lại khi dữ liệu đổi; §4.2.2 cấm lưu trạng thái lịch hẹn. Dòng "xác nhận lại" ở kiến trúc §4.2 là chính sách thiết kế; nếu cần thì thuộc T-12 (B) |
| Q-6 | Inbound nói "xác nhận lịch" sau xác minh | **Đã chốt theo contract: chuyển máy ngay, lý do `OUT_OF_SCOPE`** | §1: inbound chỉ có 1 kịch bản (đặt lịch mới); §1.1.5 "MUST transfer on anything outside these scenarios", tức chuyển vì ngoài kịch bản, không đợi 2 lần "không hiểu". Contract không gắn lý do cụ thể; `OUT_OF_SCOPE` là giá trị enum khớp; §2.1 không chấm `transfer_reason` inbound. Chỉ nhận cụm "xác nhận lịch …" để không chuyển nhầm câu đặt lịch |

## 7. Ngoài phạm vi và rủi ro

- **Retry lỗi tạm thời** (429/503) khi confirm: T-12 (B). Hiện tại từ chối xác định là chuyển `SYSTEM_ERROR`.
- **Chuyển máy sau khi ghi thất bại:** `DialogueManager.transfer` nuốt `ClinicWriteRejected` của `/transfer`, vẫn trả `outcome=TRANSFERRED`. Nếu `/confirm` bị từ chối vì lịch đã ở trạng thái cuối, `/transfer` cũng bị từ chối, nhưng bot vẫn báo `TRANSFERRED`. Kiến trúc §4.2 nói không được tuyên bố Mock đã có `TRANSFERRED` → thuộc T-06/T-12, ghi lại trong evidence.
- **Lịch không ở trạng thái xác nhận được** khi mở cuộc gọi (đã `CANCELLED`/`UNREACHABLE`): Mock trả 409, dẫn tới `SYSTEM_ERROR`. T-04 không đọc `status` để đổi lời thoại.
- **Lịch đổi nội dung giữa lượt đọc lại và lượt ghi** (Q-5): T-04 ghi theo §4.2.5, không hỏi lại. Ghi trong evidence để B xem xét ở T-12.
- `QuestionId.ASK_ATTENDANCE` vẫn chưa dùng; T-04 không bật.
- Output Guard tập trung (R-01), trace quyết định xác nhận (R-02): không thuộc T-04.
- Rủi ro Q-2b: danh sách từ ngập ngừng viết tay có thể sót. Tuyến sau LLM không được nâng lên AGREE khi luật đã thấy tín hiệu ngập ngừng (giữ nguyên quy tắc `guard_fallback`).

## 8. Sửa sau review (23-09-2026): đồng ý sai và luật intent chặn tầng ngữ nghĩa

Review ngày 23-09-2026 chạy khoảng 90 câu qua Orchestrator thật và `FakeClinicAPI`. Khoảng 30 câu **ghi `CONFIRMED` khi người gọi chưa đồng ý**; ở `SLOT_READBACK`, các câu tương tự ghi `RESCHEDULED`. Lệnh ghi Clinic không thu hồi được, nên đây là lỗi cùng hạng với SF-05. Bộ eval `eval/confirm/cases.csv` giữ toàn bộ các câu này (§8.5).

### 8.1 IE agreement: AGREE là câu trả lời được giải thích hết

| Nhóm lỗi | Ví dụ (đều từng ghi `CONFIRMED`) | Nguyên nhân |
| --- | --- | --- |
| Từ khẳng định trong câu kể | "hôm đó tôi **có** việc bận", "tôi **phải** đi làm", "hôm đó **đúng** ngày giỗ" | `_AFFIRM` dò mọi vị trí; "có / phải / được / đúng" là hư từ |
| Đáp lễ mở câu | "**dạ** hôm đó tôi bận rồi", "vâng tôi nghe", "à", "ạ", "ừm" | Đáp lễ đầu câu là đủ để AGREE (Q-2 cũ) |
| Cụm tham dự trong câu khác | "hôm đó tôi **sẽ đi** công tác", "vợ tôi **sẽ đến** thay" | Cụm intent `CONFIRM` thành AGREE (Q-1), không xét phần còn lại |
| Ngập ngừng sót, giờ khác | "chắc được", "tôi cố gắng đến được", "tôi sẽ đến lúc 10 giờ" | `_HEDGE` thiếu; không xét phần còn lại |

Thiết kế:
- Ở `CONFIRM_READBACK`, `ASK_ATTENDANCE`, `SLOT_READBACK` (không áp dụng `CANCEL_RECONFIRM`), sau khi luật thấy tín hiệu đủ ngưỡng: bỏ bổ ngữ của câu hỏi, rồi bỏ mọi tín hiệu đồng ý / đáp lễ / giữ lịch / cụm tham dự, rồi bỏ từ đệm (tiểu từ, xưng hô, "cảm ơn"). Còn từ nội dung thì trả `UNCLEAR` có tín hiệu, và Dialogue đọc lại lịch (`agreement._leaves_content`).
- "à", "ạ", "ừm" đứng riêng → `UNCLEAR`; "vâng / dạ / ừ / ờ" vẫn là xác nhận.
- Bổ sung: `_HEDGE` ("chắc được", "hy vọng", "cố gắng", "nếu", "không biết"...), `_AGREE_IDIOMS` ("không thành vấn đề"), `_AFFIRM` ("nhất định", "đương nhiên"), "đến chứ / đi chứ".
- Cụm trung tính ở câu hỏi đến khám ("không cần hủy", "không (cần) đổi"): không phải REFUSE.
- `intent.py` `CONFIRM`: thêm "giữ nguyên", "không đổi không hủy"... để câu trả lời "đổi hay hủy" bằng cách giữ lịch dẫn tới đọc lại.

### 8.2 Luật intent không được chặn tầng ngữ nghĩa

Tầng Intent chỉ có một fallback LLM thật là tầng ngữ nghĩa. `FallbackExtractor.intent` chỉ có trên interface: `NameNER.intent()` trả `None`. Router chỉ gọi model khi luật **không** ra intent, nên câu mà từ khóa `CONFIRM` khớp nhầm không bao giờ tới model, dù luật agreement đã báo "chưa rõ".

| Thành phần | Thay đổi |
| --- | --- |
| `route_semantic` | Lý do mới `ATTENDANCE_UNCLEAR`, chỉ outbound. Ở `CONFIRM_READBACK`: intent `CONFIRM` và agreement `UNCLEAR` có tín hiệu. Ở `ASK_INTENT`: intent `CONFIRM` mà cụm không giải thích hết câu (`agreement.attendance_leaves_content`; "thôi", "gì cả" là từ đệm). Câu đồng ý thật là AGREE nên không bị gọi model |
| `merge_semantic`, `CONFIRM_READBACK` | `INFORM_REASON` + mã cụ thể → REFUSE (hỏi "đổi hay hủy"); + `UNSPECIFIED` → `UNCLEAR` (đọc lại). Câu có cụm "không hủy / không đổi": `INFORM_REASON` hay `DECLINE_ACTION` đều → `UNCLEAR`. `CONFIRM_ACTION` → `UNCLEAR` (không bao giờ AGREE) |
| `merge_semantic`, `ASK_INTENT` + `ATTENDANCE_UNCLEAR` | `DECLINE_ACTION` hoặc `INFORM_REASON` + mã cụ thể → bỏ intent `CONFIRM` của luật. Mơ hồ / câu hỏi / `UNSPECIFIED` → giữ kết luận luật (đọc lại lịch) |
| `DialogueManager._intent` outbound | Intent `NONE` + lý do cụ thể từ model → hỏi lại "đổi hay hủy", `Understanding "UNCLEAR"` (lần đầu không tính §1.1.5) |
| Prompt `semantic_v3` | Kể hoàn cảnh là `INFORM_REASON`, không phải `CHANGE_INTENT`. Ở câu đọc lại, chỉ dùng `INFORM_REASON` khi người gọi nói rõ không đến được. 4 ví dụ mẫu mới; mô tả `ASK_INTENT` outbound |

Bất biến giữ nguyên: model không nâng lên AGREE; timeout hay lỗi thì giữ kết luận luật; hủy vẫn cần xác nhận lần hai có động từ hủy.

### 8.3 Quyết định

| # | Câu hỏi | Quyết định (23-09-2026) |
| --- | --- | --- |
| Q-7 | Siết Q-2: đồng ý chỉ khi phần còn lại của câu được giải thích hết | Có |
| Q-8 | "à / ạ / ừm" đứng riêng là xác nhận? | Không, đọc lại |
| Q-9 | Chấp nhận thêm ~1,3–2,7 s cho lượt được gọi thêm model (chỉ câu luật đã báo "chưa rõ") | Có |
| Q-10 | `ASK_INTENT`, model đọc ra lý do cụ thể → hỏi lại "đổi hay hủy" hay "em chưa hiểu"? | Hỏi lại, không tính lần đầu |
| Q-11 | `INFORM_REASON` + `UNSPECIFIED` ở câu đọc lại → đọc lại lịch? | Có. Hủy lịch vẫn không bắt buộc lý do: Mock nhận `UNSPECIFIED`, chỉ bắt `confirmed=true` |

### 8.4 Ngoài phạm vi

- Từ khóa `CONFIRM` vẫn rộng. §8.2 để model sửa khi có model; khi model tắt, bot chỉ đọc lại lịch, không ghi.
- Bộ eval do đội tự viết (~120 câu holdout): là bằng chứng không làm hỏng, chưa đo được độ chính xác trên người gọi thật.

### 8.5 Eval

- `scripts/confirm_eval.py`: `--baseline` (chỉ luật), `--route-only` (đếm lượt gọi model, không gọi API), `--semantic --repeats N`. Ghi nhãn model từng câu; báo "chấp nhận được" và "lý tưởng" (hành vi đầu tiên trong `expect_behaviour`).
- `scripts/eval_compare.py A B`: bảng chỉ số và danh sách câu đổi hành vi giữa hai lần chạy.
- Cổng bắt buộc: 0 ghi sai ở mọi lần chạy. Mọi thay đổi prompt phải chạy lại cả `cancel_eval --semantic` (prompt dùng chung).

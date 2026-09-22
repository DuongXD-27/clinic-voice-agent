# Plan T-10 — Hội thoại Reschedule

**Owner:** A (Hoàn) theo `docs/task-breakdown.md` · **Trạng thái:** Đã chốt Q-1..Q-6 với owner 22-09-2026 (Q-3, Q-5, Q-6 đối chiếu contract; Q-1, Q-2, Q-4 quyết định của team) — sẵn sàng triển khai · **Ngày:** 22-09-2026
**Nguồn:** `docs/task-breakdown.md` §3 (T-10), §7 bất biến 3, 5, 6, 8; `docs/reference/ai-callbot-architecture.md` §3.2 (nhánh O_NEED → O_SLOTS → O_OFFER → O_CHOOSE → O_RESCHEDULE), §4.1–§4.2; `docs/reference/information-extraction-design.md` §5.6, §5.7, §6.1; `tailieu/Luồng nghiệp vụ Callbot.pdf` (Outbound "Đổi lịch"); contract rev 1.1 §1.1.5, §1.1.6, §1.1.10, §2.1, §2.2, §4.2.2, §4.2.3, §6.1, Bảng 1, Listing 4, Figure 0 tab "Reschedule" (dòng 196) và "Book" (dòng 160), Phụ lục A, SF-02
**Phụ thuộc:** T-09 (Gateway `list_open_slots` / `reschedule`, `SlotTaken`, evidence `t09-gateway-slot-reschedule-booking.md`), T-04 (mẫu kiểm tra kết quả ghi, `attendance_facts`, Q-2 "vâng" là xác nhận), T-08 (`_answers_last_question`), F-03/F-04/F-05 — đều đã có trên `main` `7f6c4a1`

## 1. Mục tiêu và điều kiện hoàn thành

> Làm rõ thời gian mong muốn; đề xuất slot hợp lệ; xử lý lựa chọn mơ hồ/chọn lại; đọc lại; hủy xác nhận cũ khi đổi slot; hỏi lại khi slot hết.
> **Điều kiện hoàn thành:** Đổi lịch thành công bằng slot khách đã chọn và xác nhận theo thiết kế.

Khung của nhánh Reschedule đã có từ F-04 + T-09: `_start` → `_offer_slots` (GET /slots, lọc theo lời người gọi) → `OFFER_SLOTS` → `_slot_choice` (MATCH / AMBIGUOUS / NO_MATCH) → `SLOT_READBACK` → `_slot_readback` (AGREE → `ClinicGateway.reschedule`; `SlotTaken` → đọc lại /slots, đề xuất lại). SF-02 được bảo đảm về cấu trúc (slot chỉ lọc từ `ctx.slots`, `assert_slot_offered` trước khi ghi). T-10 không dựng lại luồng này. T-10 sửa để **kịch bản mẫu của contract chạy được**, thêm bước làm rõ thời gian, biến "chọn lại" / "không có khung đó" thành câu trả lời có lý do và gợi ý có luật (không gợi ý bừa, không gợi ý ngoài `GET /slots`), kiểm tra kết quả ghi trước khi báo thành công, và khóa bằng test ba tầng (IE, Dialogue, HTTP).

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | **Kịch bản mẫu contract (Figure 0 tab Reschedule) chạy đúng:** "Tôi đổi sang buổi chiều được không?" → bot đọc **một** khung chiều và hỏi có/không → "Được, đổi giúp tôi." → `RESCHEDULED`. Không có lượt "chọn khung nào" thừa, không có lượt "chưa hiểu" | Test luồng đúng 2 lượt sau xác minh; `writes == [("apt_00417","RESCHEDULED",{"new_slot_id":"slot_91d2"})]` |
| AC-2 | **Làm rõ thời gian mong muốn (Q-1):** yêu cầu đổi lịch **không** kèm thời gian ("tôi muốn đổi lịch") → bot hỏi khoảng thời gian mong muốn, nêu rõ cửa sổ hai tuần, **chưa** gọi `GET /slots`. Trả lời có tiêu chí → lọc; "nào cũng được" → đọc các khung gần nhất | Sau "tôi muốn đổi lịch": `question == ASK_SLOT_PREFERENCE`, `clinic.slot_reads == 0`; lượt sau mới đọc slot |
| AC-3 | **Chỉ đề xuất slot hợp lệ:** mọi khung đọc ra (kể cả gợi ý thay thế) nằm trong `GET /slots` của chính cuộc gọi (SF-02); ghi bằng đúng `slot_id` người gọi chọn | Test guardrail hiện có + `presented_slot_ids ⊆ slot_ids` ở mọi lượt `OFFERING_SLOTS` (FSM `check_invariants`) + test `rank_alternatives` chỉ trả slot trong danh sách |
| AC-4 | **Tiêu chí không khớp slot nào (Q-3):** nói rõ không có khung theo tiêu chí, rồi gợi ý tối đa 3 khung **gần ý nhất theo luật xếp hạng §3.2.2** (cùng thứ tuần khác → ngày liền kề → cùng buổi → cùng giờ → sớm nhất); tiêu chí **ngoài cửa sổ 14 ngày** ("tháng sau") → nói rõ giới hạn và hỏi lại, không gợi ý. Cả hai **không** tính là "không hiểu" (§1.1.5 "hiểu sai") | "đổi sang thứ bảy" (không có thứ bảy tuần này, có thứ bảy tuần sau) → câu có "thứ bảy này … không còn khung" + khung thứ bảy tuần sau đứng đầu; `failed_understandings == 0`; "tháng sau" → câu có "hai tuần tới" + `ASK_SLOT_PREFERENCE` |
| AC-5 | **Ngày tương đối được đọc thành ngày tuyệt đối:** "ngày mai", "ngày kia", "thứ bảy tuần sau" → bot nêu **thứ + ngày + tháng** trong câu trả lời để người gọi kiểm được bot hiểu đúng ngày; mốc "hôm nay" = thời điểm nhận lượt (`received_at`, +07:00) | "tôi muốn đổi sang ngày mai" (now cố định 22/09) → câu có "thứ Tư ngày 23 tháng 9" |
| AC-6 | **Lựa chọn mơ hồ:** nhiều slot khớp → đọc tối đa 3 slot trong số khớp, hỏi lại; **không tự chọn slot đầu** | Test hiện có `test_ambiguous_slot_choice_does_not_pick_first_slot` giữ nguyên |
| AC-7 | **Nhiều hơn 3 khung (Q-5):** đọc tối đa 3 khung một lượt **và nói còn bao nhiêu khung nữa**; "còn khung nào khác", "khung khác", "nghe tiếp" → đọc trang tiếp (không lặp khung đã đọc); hết → hỏi khoảng thời gian khác | 5 slot → câu có "còn 2 khung khác"; "khung khác" → đọc slot 4–5; "khung 1" ở trang 2 là slot 4 |
| AC-8 | **Chọn lại ở câu đọc lại (Q-4):** "không, khung khác" → bỏ slot này, giữ đổi lịch, đọc khung khác; "thôi không đổi nữa" / "giữ lịch" → bỏ hẳn (giữ lịch cũ); "không" trần → **không đoán** (§1.1.5), hỏi A/B "nghe khung khác hay giữ lịch cũ" | Ba câu → ba nhánh; `pending_action` và `writes` đúng từng nhánh |
| AC-9 | **Đọc lại trước khi ghi (Q-2):** câu mở khóa `RESCHEDULED` là câu có/không nêu đúng giờ + ngày + cơ sở của slot đã chọn; "được", "đồng ý", "đổi giúp tôi", **"vâng / dạ / ừ"** là đồng ý; ngập ngừng, câu hỏi đuôi, "nhưng…" → hỏi lại; AGREE đúng lượt/câu hỏi/slot mới ghi | Ma trận §5.2; `test_agreement.py` cho `SLOT_READBACK` |
| AC-10 | **Hủy xác nhận cũ khi đổi slot:** đổi slot đang chọn, `SlotTaken`, hay đổi hành động đều xóa bằng chứng AGREE cũ; bằng chứng slot A không mở khóa slot B | Test hiện có `test_old_evidence_does_not_unlock_new_slot`, `test_evidence_is_cleared_on_refusal_action_change_and_slot_change` + e2e SLOT_TAKEN cần AGREE mới |
| AC-11 | **Slot hết khi ghi (`409 SLOT_TAKEN`):** đọc lại `GET /slots`, **giữ tiêu chí người gọi đã nói** khi đề xuất lại (Q-5), cần xác nhận mới; không retry mù | e2e: sau SLOT_TAKEN với tiêu chí "buổi chiều", khung đề xuất lại là buổi chiều trước |
| AC-12 | **Không còn slot nào trong cửa sổ:** nói rõ không còn khung trống trong hai tuần tới rồi chuyển nhân viên `OUT_OF_SCOPE`; không bịa slot, không ghi gì ngoài `/transfer` | `slots == []` → `TRANSFERRED`, câu thoại có lý do |
| AC-13 | **Chỉ `RESCHEDULED` sau khi Mock ghi thành công:** kiểm `status == "RESCHEDULED"` và `new_slot_id == slot đã chọn` (Listing 4); từ chối xác định → `TRANSFERRED/SYSTEM_ERROR`; chưa rõ → `409 CALL_RECONCILIATION_REQUIRED`; `VERSION_CONFLICT` → Gateway đọc lại, gửi lại cùng key (T-09) | `fail_next("reschedule_appointment", ...)` các lớp lỗi; stub trả `status`/`new_slot_id` lạ → không báo thành công |
| AC-14 | Câu báo thành công dùng lời "đã đổi lịch sang …" (Figure 0), dựng từ slot mà Mock xác nhận (`new_slot_id`) | Câu cuối chứa "đổi lịch" + giờ/ngày của `new_slot_id` |
| AC-15 | Ngoại lệ vẫn kiểm ở mọi bước: lâm sàng, xin nhân viên, im lặng, xin nhắc lại, đổi ý hủy lịch, đổi ý giữ lịch | Mỗi loại tại `ASK_SLOT_PREFERENCE`, `OFFER_SLOTS`, `SLOT_READBACK`; không ghi `RESCHEDULED` |
| AC-16 | Inbound "đổi lịch" là ngoài kịch bản → `TRANSFERRED/OUT_OF_SCOPE`, không ghi Mock (đã có, T-04 Q-6) | Test hiện có giữ nguyên |

## 2. Hiện trạng (main `7f6c4a1`, 22-09-2026)

**Đã có và giữ nguyên:**
- `DialogueManager._start` (set_pending `RESCHEDULE`, lọc theo transcript), `_offer_slots`, `_present` (tối đa 3, `presented_slot_ids`), `_slot_choice` (MATCH → `select_slot` + `SLOT_READBACK`; AMBIGUOUS → đọc lại tối đa 3 khớp), `_slot_readback` (AGREE → `reschedule`; `SlotTaken` → `select_slot(None)` + đề xuất lại; REFUSE + intent RESCHEDULE → đọc lại danh sách; REFUSE → `_abandon` giữ lịch cũ).
- IE `slot_choice.py`: tiêu chí thứ tự / giờ / buổi / thứ / ngày / tuần, không dấu; ngày tương đối tính từ `TurnContext.now` = `received_at` (+07:00) — kiểm 22/09: "ngày mai" → 23/09, "thứ bảy tuần sau" → 28/09–04/10 + thứ 7, "toi muon dat lich ngay mai" → 23/09; `MATCH`/`AMBIGUOUS`/`NO_MATCH`. `agreement.py`: `SLOT_READBACK` cần "được / đồng ý / …", "vâng" một mình là UNCLEAR (thiết kế §5.6); ngập ngừng → UNCLEAR (T-04).
- `CallContext.set_pending` / `select_slot`: đổi slot hay hành động xóa bằng chứng (AC-10). FSM `_WRITE_STATES["RESCHEDULE"] = {AWAITING_CONFIRMATION}`, `CONFIRMATION_QUESTION_FOR["RESCHEDULE"] = SLOT_READBACK`, invariant `OFFERING_SLOTS` ⇒ `presented ⊆ slots`.
- Gateway T-09: `list_open_slots` đọc hết trang, cửa sổ 14 ngày; `reschedule` kiểm `check_write` + SF-02 + bằng chứng, key `call_id:turn:reschedule:{slot}`, `VERSION_CONFLICT` retry 1 lần cùng key, `SLOT_TAKEN` → `SlotTaken`.
- Test: `test_orchestrator.py::test_reference_call_reschedule` (có thêm lượt "khung 1" so với Figure 0), `test_reschedule_slot_taken_reoffers_and_needs_new_confirmation`, `test_ambiguous_slot_choice_does_not_pick_first_slot`, `test_refusing_slots_drops_pending_action_without_writing`; HTTP e2e `test_calls.py:564` ("Cho tôi đổi lịch" → "10 giờ sáng" → "Được"); `test_slot_choice.py`; `test_context_fsm.py` (bằng chứng theo slot).

**Khoảng cách.** Chạy Orchestrator thật + `FakeClinicAPI` (seed mặc định: `apt_00417` 09:00 14/10; slot trống `slot_aa01` 10:00 và `slot_91d2` 14:30 ngày 14/10), outbound đã xác minh, người gọi nói tại `CONFIRM_READBACK`:

| # | Kịch bản | Hiện tại | Đúng ra | Vị trí |
| --- | --- | --- | --- | --- |
| G-1 | **Figure 0:** "Tôi đổi sang buổi chiều được không?" → "Được, đổi giúp tôi." | Lượt 1: "hiện còn khung 1 là 2 giờ 30 chiều … **Anh chị chọn khung nào ạ?**" (một khung mà vẫn hỏi chọn). Lượt 2: "**em chưa hiểu**" (`fails=1`); lần nữa → `NOT_UNDERSTOOD` | Một khung khớp → đọc lại luôn bằng câu có/không, "Được" → ghi | `manager._offer_slots`/`_present`: luôn hỏi `OFFER_SLOTS` kể cả khi 1 ứng viên; `OFFER_SLOTS` không có ngưỡng AGREE |
| G-2 | "Tôi muốn đổi lịch" (không nói thời gian) | Đọc ngay 2–3 khung đầu của cửa sổ 14 ngày | Hỏi khoảng thời gian mong muốn (Q-1) | `_start` → `_offer_slots` ngay |
| G-3 | "Đổi sang thứ bảy được không" (không có slot thứ bảy); "đổi sang tháng sau" (ngoài 14 ngày) | Im lặng đọc 2 khung ngày 14/10 như thể đúng ý | Nói rõ không có khung thứ bảy, gợi ý theo luật (Q-3); "tháng sau" → nói giới hạn 2 tuần, hỏi lại | `_offer_slots`: `filter_slots(...) or slots` nuốt kết quả rỗng |
| G-4 | Tại `OFFER_SLOTS`: "còn khung nào khác không" | "em chưa hiểu" (`fails=1`) | Đọc trang tiếp / hỏi khoảng khác | IE không có nhãn "muốn nghe khung khác"; `_slot_choice` rơi về `_not_understood` |
| G-5 | Tại `SLOT_READBACK`: "không, khung khác" | **`_abandon`**: "em giữ nguyên lịch khám 9 giờ … đến khám được không?" — mất hẳn ý định đổi lịch | Bỏ slot này, đọc khung khác, `pending_action` vẫn `RESCHEDULE` (Q-4) | `_slot_readback`: nhánh REFUSE chỉ giữ đổi lịch khi `intent ∈ {RESCHEDULE, BOOK}`; "khung khác" không có từ khóa intent |
| G-6 | Tại `SLOT_READBACK`: "vâng" | UNCLEAR → câu A/B "chọn khung … hay muốn nghe khung khác ạ?" → người gọi lại "vâng, khung đó" → không có luật → "chưa hiểu" | "vâng" là đồng ý (Q-2) | `agreement._agree_span` cho `SLOT_READBACK` |
| G-7 | `SLOT_TAKEN` sau khi đã nói "buổi chiều" | Đề xuất lại **khung 10 giờ sáng** trước — mất tiêu chí | Giữ tiêu chí đã nói khi đọc lại /slots (Q-5) | `_slot_readback` gọi `_offer_slots(prefix=SLOT_TAKEN)` không có `criteria_text`; context không lưu tiêu chí |
| G-8 | 4 slot trống, người gọi nói "khung 4" | "em chưa thấy khung giờ đó" + đọc lại 3 khung cũ (`fails=1`); không có cách nghe khung 4 | Nói "còn 1 khung khác"; phân trang (Q-5) | `MAX_SLOTS_PRESENTED = 3` không có trang tiếp, không báo số còn lại |
| G-9 | Ghi thành công | `_slot_readback` bỏ qua giá trị `reschedule()` trả về; câu báo "em đã **đặt** lịch …" dựng từ slot trong context | Kiểm `status == RESCHEDULED`, `new_slot_id == slot` (Listing 4) rồi mới báo "đã **đổi** lịch sang …" (Figure 0) — cùng lý do T-04 G-8 | `manager._slot_readback`, `templates.done` |
| G-10 | Không còn slot nào | `transfer(OUT_OF_SCOPE)` với câu `TRANSFER` chung | Nói lý do (không còn khung trống trong hai tuần tới) rồi chuyển | `_offer_slots`, `templates` |
| G-11 | NO_MATCH có tiêu chí (G-3, G-8) | Tính `NOT_UNDERSTOOD` (thiết kế §6.1): hai lần hỏi giờ không có → `TRANSFERRED/NOT_UNDERSTOOD` | Bot đã hiểu — không tính (Q-3) | `_slot_choice` trả `"NOT_UNDERSTOOD"` |
| G-12 | "đổi sang ngày mai" | Lọc đúng 23/09 nhưng câu trả lời không nêu ngày | Nêu "thứ Tư ngày 23 tháng 9" để người gọi kiểm (AC-5) | `templates.offer_slots` / `slot_no_match_for` |

G-1 nặng nhất: kịch bản mẫu của chính contract không đi hết được. G-5 nặng thứ hai: một câu từ chối slot làm bot bỏ luôn việc đổi lịch mà không hỏi lại.

Không phải khoảng cách: `VERSION_CONFLICT` (Gateway đọc lại, gửi lại cùng key — T-09), SF-02 (cấu trúc), inbound đổi lịch → `OUT_OF_SCOPE` (T-04 Q-6), giữ lịch cũ khi từ chối hẳn, phân giải ngày tương đối (đã đúng, chỉ thiếu đọc ra).

### 2.1 Đối chiếu contract / kiến trúc

| Điều khoản | Nội dung | Hệ quả cho T-10 |
| --- | --- | --- |
| §1.1.6 | "MUST offer only slots returned by `GET /slots` in the same call. A reschedule MUST book the new slot and release the old one atomically" | AC-3 (đã có); nguyên tử là việc Mock/Gateway (T-09). **Không** có chữ "xác nhận rõ ràng" cho đổi lịch |
| §1.1.10 | Đặt lịch inbound: "PHẢI lấy được một xác nhận rõ ràng về khung giờ đã chọn" | Dùng chung `SLOT_READBACK` với T-11; Q-2 áp dụng cả hai (xem §7 rủi ro) |
| SF-02 | Không đề xuất slot mà `/slots` không trả về | Mọi câu đọc slot — kể cả gợi ý thay thế của `rank_alternatives` — chỉ lấy từ `ctx.slots`; bước hỏi thời gian **không** nhắc ví dụ giờ cụ thể |
| §1.1.5 | Chuyển máy sau "hai lần **hiểu sai** liên tiếp"; "Bot KHÔNG ĐƯỢC đoán" | Q-3: xin giờ không có ≠ hiểu sai. Q-4: "không" trần → hỏi A/B thay vì đoán là bỏ đổi lịch |
| Bảng 1 | Reschedule: "Patient asks for a different time" | Kích hoạt bằng intent `RESCHEDULE` ở `CONFIRM_READBACK`/`ASK_INTENT` (đã có) |
| Figure 0 (Reschedule, dòng 196) | "Chiều 14 tháng 10 còn khung 14 giờ 30. Anh chị đổi sang giờ đó nhé ạ?" → "Được, đổi giúp tôi." → "Em đã đổi lịch sang 14 giờ 30 ngày 14 tháng 10 ạ." | G-1 (một khung → hỏi có/không), G-9 (câu báo "đổi lịch sang"). Bot hỏi câu **có/không** → "vâng" là câu trả lời hợp lệ (Q-2) |
| Figure 0 (Book, dòng 160) | "thứ Ba ngày 20 tháng 10 còn khung 9 giờ và 14 giờ 30" | Contract đọc **2** khung, nêu **thứ + ngày** trước giờ → mẫu cho AC-5 và Q-5 (không có luật "đọc hết") |
| §2.2 | `RESCHEDULED` + `new_slot_id`, slot cũ được giải phóng | AC-13: đối chiếu `new_slot_id` trả về với slot đã chọn |
| §4.2.2 | Được giữ bản đọc `slots`, "khung giờ đang được đề xuất"; không lưu trạng thái lịch hẹn | Q-5: lưu tiêu chí người gọi + slot đã đọc là hợp lệ (lời người gọi + lịch sử đọc, không phải trạng thái lịch) |
| §4.2.5, Listing 4 | `409 SLOT_TAKEN`: "re-read /slots, don't retry blindly" | Đã có; T-10 thêm giữ tiêu chí (G-7) |
| §6.1 | "Các nhóm CÓ THỂ thiết kế hội thoại theo bất kỳ cách nào" | Q-1, Q-4, luật gợi ý §3.2.2 là quyền của team |
| Phụ lục A | 6 state hội thoại cố định; §2.1 harness không chấm `state` | Q-6: `ASK_SLOT_PREFERENCE` báo `AWAITING_INTENT` |
| Kiến trúc §3.2 | O_NEED "Hỏi khoảng thời gian mong muốn" → O_SLOTS → O_AVAILABLE → (không) O_ALTERNATIVE → O_OFFER → O_CHOOSE | G-2, G-3, G-4, G-5 — sơ đồ đã mô tả đủ các nhánh còn thiếu |
| IE §5.7 | `NO_MATCH` → "bot đọc các slot gần nhất có trong danh sách" | G-3: "gần nhất" được định nghĩa bằng luật §3.2.2 thay vì "3 khung đầu danh sách" |

## 3. Thiết kế

### 3.1 Luồng nhánh Reschedule

```text
Lượt n tại CONFIRM_READBACK / ASK_INTENT (outbound), intent RESCHEDULE
  _start: tiêu chí = parse_slot_criteria(transcript)
     có tiêu chí     -> set_pending(RESCHEDULE); _offer_slots(criteria)
     không tiêu chí  -> hỏi khoảng thời gian   ASK_SLOT_PREFERENCE, AWAITING_INTENT, CHƯA set_pending   # Q-1, Q-6
                        (ý định giữ ở question.action; chưa gọi GET /slots)

Lượt tại ASK_SLOT_PREFERENCE (_slot_preference)
  có tiêu chí          -> set_pending(action); _offer_slots(criteria)
  ANY ("nào cũng được") -> set_pending(action); _offer_slots(không lọc)
  không tín hiệu lần 1 -> hỏi lại ASK_SLOT_PREFERENCE_AGAIN, UNCLEAR (không tính lần đầu, §6.1)
  ngoại lệ / hủy / giữ lịch -> như mọi bước

_offer_slots(criteria)
  slots = GET /slots (14 ngày)              []        -> NO_SLOTS_TRANSFER, transfer(OUT_OF_SCOPE)      # G-10
  criteria ngoài cửa sổ (date_from > now+14d)          -> OUT_OF_WINDOW + ASK_SLOT_PREFERENCE, NEUTRAL  # Q-3
  ứng viên = filter(slots, criteria); lưu ctx.slot_criteria_text
     đúng 1 ứng viên  -> select_slot; slot_offer_readback (có/không)  SLOT_READBACK, AWAITING_CONFIRMATION  # G-1
     nhiều            -> _present(3 đầu) + "còn N khung khác"          OFFERING_SLOTS                        # Q-5
     0 (có tiêu chí)  -> alternatives = rank_alternatives(slots, criteria)                                    # Q-3, §3.2.2
                         _present(alternatives[:3], prefix slot_no_match_for(criteria)), NEUTRAL
  mọi câu đọc slot: ngày tương đối trong tiêu chí -> nêu thứ + ngày + tháng                                  # AC-5

Lượt tại OFFER_SLOTS (_slot_choice)
  MATCH               -> select_slot; slot_readback                          SLOT_READBACK
  AMBIGUOUS           -> _present(khớp, SLOT_AMBIGUOUS)                       (như hiện tại)
  MORE ("khung khác", "còn khung nào", "sớm/muộn hơn", "ngày khác")           # G-4, G-8
     còn khung chưa đọc -> _present(trang tiếp)
     hết               -> SLOT_MORE_NONE -> ASK_SLOT_PREFERENCE (pending giữ)
  NO_MATCH có tiêu chí -> như "0 ứng viên" ở trên, NEUTRAL                                                   # G-11
  REFUSE hẳn ("thôi không đổi nữa", "giữ lịch") -> _abandon                    (như hiện tại)
  CANCEL              -> _start(CANCEL)                                          (như hiện tại)
  còn lại             -> _present(danh sách hiện tại, SLOT_REPEAT), NOT_UNDERSTOOD  (đọc lại, không chỉ "chưa hiểu")

Lượt tại SLOT_READBACK (_slot_readback)
  AGREE (đúng lượt; gồm "vâng/dạ/ừ" — Q-2)   -> reschedule(ctx, slot)
        result.status == RESCHEDULED và result.new_slot_id == slot -> _finish(RESCHEDULED, rescheduled(ctx, slot))  # G-9
        khác                                                       -> WriteOutcomeUnknown (đối soát, như T-04)
        SlotTaken                                                  -> select_slot(None); _offer_slots(ctx.slot_criteria_text, prefix SLOT_TAKEN)  # G-7
  REFUSE + MORE / intent RESCHEDULE ("không, khung khác")  -> select_slot(None); _present(khung khác)          # Q-4
  REFUSE hẳn ("thôi không đổi nữa", "giữ lịch")            -> _abandon
  REFUSE trần ("không")                                    -> SLOT_REFUSE_CHOICE (A/B: khung khác / giữ lịch cũ), UNCLEAR   # Q-4, §1.1.5 không đoán
  MATCH slot khác ("thôi lấy khung 2")                     -> select_slot(mới); slot_readback
  UNCLEAR (ngập ngừng, câu hỏi đuôi)                       -> hỏi lại có/không cùng slot
  CANCEL / ngoại lệ                                        -> như hiện tại

Lượt tại SLOT_REFUSE_CHOICE
  MORE / "khung khác"   -> _present(khung khác)
  "giữ lịch" / REFUSE   -> _abandon
  còn lại               -> hỏi lại A/B lần 2, rồi NOT_UNDERSTOOD như thường
```

### 3.2 IE (`extraction/slot_choice.py`, `agreement.py`, `extractor.py`)

#### 3.2.1 Nhãn mới và câu hỏi mới

1. **`SlotChoiceKind` thêm `MORE` và `ANY`.** MORE: "khung khác", "giờ khác", "cái khác", "còn khung nào", "còn giờ nào", "khung nào khác", "nghe khung khác", "nghe tiếp", "sớm hơn", "muộn hơn", "trễ hơn", "ngày khác", "hôm khác", "buổi khác" (+ không dấu qua `_UNACCENTED_PHRASES`). ANY: "nào cũng được", "tùy", "khung nào cũng được", "lúc nào cũng được", "sao cũng được", "tùy em". Câu vừa có MORE vừa có tiêu chí ("khung khác, buổi sáng ấy") → ưu tiên tiêu chí. "Sáng nào cũng được" → tiêu chí buổi sáng, không phải ANY. "Sớm hơn / muộn hơn" giữ là MORE (không dựng mốc giờ tương đối — SF-02, giữ IE đơn giản).
2. **`extract_slot_choice` chạy ở `ASK_SLOT_PREFERENCE`** với `slots` rỗng: chỉ cần `criteria`/ANY; Dialogue lọc sau khi GET /slots. **Chạy cả ở `SLOT_READBACK`** để nhận MORE và MATCH slot khác ("thôi lấy khung 2") bên cạnh `agreement`.
3. **`QuestionId.ASK_SLOT_PREFERENCE`, `QuestionId.SLOT_REFUSE_CHOICE`** — cả hai **không** thuộc `CONFIRMATION_QUESTIONS` (không mở khóa lệnh ghi). `SLOT_REFUSE_CHOICE` chỉ nhận MORE / REFUSE / "giữ lịch".
4. **`SLOT_READBACK` AGREE (Q-2):** hạ ngưỡng bằng `CONFIRM_READBACK` trong `_agree_span` ("vâng", "dạ", "ừ", "ờ", "có", "được", "đúng", "đồng ý", "ok"), thêm cụm hành động "đổi giúp tôi", "đổi đi", "chốt đi", "lấy khung đó", "khung đó được". Chặn (ngập ngừng `_HEDGE`, câu hỏi đuôi, "nhưng", intent mâu thuẫn, lâm sàng) chạy **trước** như T-04. `CANCEL_RECONFIRM` không đổi (SF-05).
5. **REFUSE ở `SLOT_READBACK`:** IE chỉ gắn nhãn; Dialogue phân ba nhánh theo `slot_choice.kind == MORE`, `_KEEP_WORDS` / "không đổi nữa" (thêm cụm "không đổi nữa", "thôi không đổi", "để nguyên"), hay "không" trần.

#### 3.2.2 Luật gợi ý khi không có khung theo tiêu chí — `rank_alternatives(slots, criteria, now)`

Thuần tất định, chỉ sắp xếp lại **`ctx.slots`** (không tạo slot, không mở rộng cửa sổ). Mỗi slot nhận một khóa xếp hạng `(bậc, khoảng cách, giờ)`; lấy 3 slot đầu; mỗi bậc chỉ xét khi bậc trên rỗng:

| Bậc | Khi tiêu chí có | Slot được ưu tiên | Ví dụ ("thứ bảy", hôm nay thứ Ba 22/09) |
| --- | --- | --- | --- |
| 1 | `weekday` | **cùng thứ, tuần khác** trong cửa sổ | thứ bảy 03/10 |
| 2 | `day`/`date_from`/`weekday` (một ngày đích) | **ngày liền kề** ±1, rồi ±2 (ưu tiên sau ngày đích trước, vì "muộn hơn" ít phiền hơn "sớm hơn"), cùng `period` nếu có | thứ sáu 25/09, chủ nhật 27/09 |
| 3 | `period` (không có ngày, hoặc ngày đã xét hết) | **cùng buổi**, ngày gần nhất | "chiều thứ năm" không có → chiều thứ sáu |
| 4 | `hours` | **cùng giờ ngày khác**, rồi giờ gần nhất (chênh phút tăng dần) | "9 giờ" → 9 giờ 24/09, rồi 10 giờ |
| 5 | (mọi trường hợp) | sớm nhất còn trống | 3 khung đầu `GET /slots` |

Tiêu chí có `date_from > now + 14 ngày` hoặc `month` ngoài cửa sổ → **không xếp hạng**, trả `OUT_OF_WINDOW` để Dialogue nói giới hạn và hỏi lại. Câu đề xuất phải nêu bậc đã dùng bằng lời: "thứ bảy này không còn khung, **gần nhất có thứ bảy tuần sau ngày 3 tháng 10** …" / "**thứ sáu ngày 25 tháng 9** …". Test từng bậc với bộ slot cố định và `now` cố định.

#### 3.2.3 Đọc ngày tuyệt đối (AC-5)

`speak_date(date)` → "thứ Tư ngày 23 tháng 9" (`weekday` tiếng Việt: thứ Hai…thứ Bảy, Chủ nhật). Khi `criteria.date_from == date_to` đến từ từ tương đối ("mai", "kia", "tuần sau" + thứ), câu đọc slot mở đầu bằng ngày: "Dạ, ngày mai là thứ Tư ngày 23 tháng 9, còn khung …". `offer_slots` / `slot_offer_readback` / `slot_no_match_for` đều dùng `speak_date` khi tất cả khung cùng một ngày; khác ngày thì `speak_datetime` từng khung như hiện tại (đã có ngày/tháng).

IE vẫn: không đọc hồ sơ, không dựng mốc thời gian mới, chỉ lọc và sắp xếp trên `ctx.slots`.

### 3.3 Dialogue (`dialogue/manager.py`) và Session

- `_start` (RESCHEDULE/BOOK): parse tiêu chí ngay; rỗng → `_ask(ASK_SLOT_PREFERENCE, t.ASK_SLOT_PREFERENCE, "AWAITING_INTENT", action=action)` **không** `set_pending` (Q-6). Có tiêu chí → `set_pending` + `_offer_slots`.
- Handler mới `_slot_preference`: đọc `slot_choice` (criteria / ANY / MORE bị coi như không tín hiệu); lần 1 không tín hiệu → `ASK_SLOT_PREFERENCE_AGAIN`, `"UNCLEAR"`; ngoại lệ, hủy, giữ lịch như các bước khác (`_start(CANCEL)`, `_abandon`).
- `_offer_slots(criteria_text, prefix)`: ba nhánh theo số ứng viên (§3.1); `OUT_OF_WINDOW` → `t.OUT_OF_WINDOW` + `ASK_SLOT_PREFERENCE`, `"NEUTRAL"`; `slots == []` → `transfer(OUT_OF_SCOPE)` với `t.NO_SLOTS_TRANSFER`. Ghi `ctx.slot_criteria_text` mỗi khi có tiêu chí mới; đặt lại `ctx.offered_slot_ids = []` khi tiêu chí đổi.
- `_present(candidates, prefix, page)`: `candidates` trừ `ctx.offered_slot_ids`; đọc 3; nối `t.slots_remaining(n)` nếu còn; cộng dồn `offered_slot_ids`; hết → `SLOT_MORE_NONE` + `ASK_SLOT_PREFERENCE` (pending giữ, `presented_slot_ids = []`, state `AWAITING_INTENT` — invariant cho phép vì `question.question_id is ASK_SLOT_PREFERENCE`, xem FSM dưới).
- `_slot_choice`: thêm nhánh `MORE`; `NO_MATCH` có tiêu chí → gợi ý theo luật, `"NEUTRAL"` (Q-3); nhánh cuối đọc lại danh sách với `SLOT_REPEAT`, `"NOT_UNDERSTOOD"`.
- `_slot_readback`: AGREE → kiểm kết quả (G-9); `SlotTaken` → `_offer_slots(ctx.slot_criteria_text, prefix=SLOT_TAKEN)`; REFUSE ba nhánh (Q-4); `slot_choice` MATCH slot khác → `select_slot` mới + đọc lại.
- Handler mới `_slot_refuse_choice` cho `SLOT_REFUSE_CHOICE`.
- `CallContext`: thêm `slot_criteria_text: Optional[str] = None`, `offered_slot_ids: list[str]` → `SCHEMA_VERSION` 1 → 2; `from_dict` đọc bản 1 (mặc định `None`/`[]`); `clear_pending` xóa cả hai. **Không** lưu `starts_at`/trạng thái lịch (§4.2.2).
- FSM `check_invariants`: `AWAITING_INTENT` + `pending_action ∈ {RESCHEDULE, BOOK}` chỉ hợp lệ khi `question.question_id is ASK_SLOT_PREFERENCE` (trường hợp "hết trang → hỏi khoảng khác", pending đã có). Lượt hỏi đầu tiên thì pending còn `None` nên không cần ngoại lệ. `TRANSITIONS` đã có `OFFERING_SLOTS → AWAITING_INTENT` và `AWAITING_INTENT → AWAITING_CONFIRMATION`.
- `schema.py`: `QuestionId.ASK_SLOT_PREFERENCE`, `QuestionId.SLOT_REFUSE_CHOICE`; `SlotChoiceKind` thêm `"MORE"`, `"ANY"`; `SlotChoice` thêm `out_of_window: bool`.

### 3.4 Câu thoại (`dialogue/templates.py`)

| Hàm / hằng | Nội dung (nháp) | Ghi chú |
| --- | --- | --- |
| `ASK_SLOT_PREFERENCE` | "Dạ, anh chị muốn đổi sang khoảng thời gian nào ạ? Em có lịch trống trong hai tuần tới." | Không nêu giờ cụ thể (SF-02); nói rõ cửa sổ để người gọi không xin "tháng sau" |
| `ASK_SLOT_PREFERENCE_AGAIN` | "Dạ, anh chị muốn buổi sáng hay chiều, và ngày nào trong hai tuần tới ạ?" | Lần 2 khi chưa rút được tiêu chí |
| `speak_date(d)` | "thứ Tư ngày 23 tháng 9" | AC-5; dùng chung với T-11 |
| `slot_offer_readback(ctx, slot, criteria)` | "Dạ, {chiều/sáng} {thứ + ngày} còn khung {giờ}. Anh chị đổi sang giờ đó nhé ạ?" | Figure 0; câu có/không cho một ứng viên (G-1). "ngày mai" → "Dạ, ngày mai là thứ Tư ngày 23 tháng 9, còn khung 9 giờ sáng. Anh chị đổi sang giờ đó nhé ạ?" |
| `offer_slots(ctx, slots, prefix, remaining)` | "{prefix}Dạ, hiện còn khung 1 là …; khung 2 là …; khung 3 là …. {Ngoài ra còn N khung khác. }Anh chị chọn khung nào ạ?" | Q-5; cùng ngày → mở đầu bằng `speak_date` |
| `slot_readback(ctx, slot)` | "Dạ, em xin xác nhận: đổi lịch sang {giờ} {thứ + ngày} tại {cơ sở}. Anh chị đồng ý chứ ạ?" | Thêm "đổi lịch sang" + cơ sở cho đồng bộ T-04; "vâng" hợp lệ (Q-2) |
| `slot_no_match_for(criteria, tier)` | "Dạ, {thứ bảy này / buổi chiều thứ năm / ngày 20 tháng 10} em không còn khung trống. Gần nhất có {thứ bảy tuần sau ngày 3 tháng 10 / thứ sáu ngày 25 tháng 9}: " | Nêu lý do + bậc gợi ý bằng lời, rồi nối `offer_slots` |
| `OUT_OF_WINDOW` | "Dạ, em chỉ có lịch trống trong hai tuần tới, đến {thứ + ngày cuối cửa sổ}. Anh chị muốn khoảng nào trong thời gian đó ạ?" | Q-3: ngoài phạm vi → không gợi ý, hỏi lại |
| `slots_remaining(n)` | "Ngoài ra còn {n} khung khác. " | Q-5 |
| `SLOT_MORE_NONE` | "Dạ, em đã đọc hết các khung trống trong hai tuần tới. Anh chị muốn khoảng thời gian nào khác ạ?" | Hết trang → `ASK_SLOT_PREFERENCE` |
| `SLOT_REPEAT` | "Dạ, anh chị chọn giúp em một trong các khung: " | Không hiểu tại `OFFER_SLOTS`: đọc lại thay vì chỉ "em chưa hiểu" |
| `SLOT_REFUSE_CHOICE` | "Dạ, anh chị muốn nghe khung khác hay giữ lịch cũ ạ?" | Q-4: "không" trần |
| `NO_SLOTS_TRANSFER` | "Dạ, hiện không còn khung trống nào trong hai tuần tới. Em xin phép chuyển máy cho nhân viên để hỗ trợ anh chị ạ." | G-10 |
| `rescheduled(ctx, slot)` (thay `done("RESCHEDULED")`) | "Dạ, em đã đổi lịch khám sang {giờ} {thứ + ngày} tại {cơ sở} cho anh chị ạ. Hẹn gặp anh chị ạ." | Figure 0; `slot` là slot khớp `new_slot_id` Mock trả về |

Mọi hàm có chi tiết lịch gọi `guardrails.assert_can_disclose` (SF-03). `done("BOOKED")` giữ nguyên cho T-11.

## 4. Các bước thực hiện

| Bước | Việc | File | Phụ thuộc |
| --- | --- | --- | --- |
| 0 | Tạo `feature/t10-reschedule-dialogue` từ `main` (`7f6c4a1`) | — | — |
| 1 | Schema: `QuestionId.ASK_SLOT_PREFERENCE`, `SLOT_REFUSE_CHOICE`; `SlotChoiceKind` + `MORE`/`ANY`, `out_of_window`; `CallContext` + 2 trường, `SCHEMA_VERSION=2`, đọc được bản 1 + test tuần tự hóa | `extraction/schema.py`, `session/context.py`, `tests/engine/session/` | 0 |
| 2 | IE: nhãn MORE/ANY, `out_of_window`, chạy `slot_choice` ở `ASK_SLOT_PREFERENCE` và `SLOT_READBACK`; AGREE `SLOT_READBACK` (Q-2); cụm "không đổi nữa" + unit test có dấu / không dấu | `extraction/slot_choice.py`, `agreement.py`, `extractor.py`, `tests/engine/extraction/…` | 1 |
| 3 | `rank_alternatives` (§3.2.2) + test từng bậc với `now` cố định | `extraction/slot_choice.py`, `tests/engine/extraction/test_slot_ranking.py` | 1 |
| 4 | Câu thoại §3.4, `speak_date` | `dialogue/templates.py` | — |
| 5 | Dialogue §3.3 + FSM invariant | `dialogue/manager.py`, `session/fsm.py` | 1–4 |
| 6 | Test luồng `tests/engine/test_reschedule_dialogue.py` (§5.2) + HTTP e2e Figure 0 | `tests/engine/`, `tests/transports/http/test_calls.py` | 5 |
| 7 | Sửa test đổi kỳ vọng (§5.1) | xem §5.1 | 5 |
| 8 | Tài liệu: IE design §5.7 (MORE/ANY, `rank_alternatives`, `ASK_SLOT_PREFERENCE`), §5.6 (`SLOT_READBACK` "vâng"), §6.1 (NO_MATCH có tiêu chí không tính); kiến trúc §3.2 ghi chú "một ứng viên → đọc lại luôn"; `session-operations.md` (schema v2) | docs | 5 |
| 9 | `make check`; viết `docs/evidence/t10-reschedule-dialogue.md` theo `TEMPLATE.md`, mỗi AC một dòng bằng chứng | — | tất cả |

Thứ tự ưu tiên trong bước 5: **G-1, G-5/Q-4, G-9, Q-2** trước (giá trị cao, không phụ thuộc schema) → G-2/Q-1, Q-6 → G-3/Q-3 + `rank_alternatives` → G-7/G-8/Q-5 (cần schema v2) → AC-5. Ước lượng: bước 1–3 một ngày (bẫy test không dấu cho MORE và bảng xếp hạng), bước 4–5 một ngày, bước 6–7 nửa ngày.

## 5. Test

### 5.1 Test hiện có sẽ đổi kỳ vọng

| Test | Đổi |
| --- | --- |
| `test_orchestrator.py::test_reference_call_reschedule` | Bỏ lượt "khung 1": sau "đổi sang buổi chiều" bot đọc lại có/không ngay (G-1); `writes` không đổi |
| `test_orchestrator.py::test_reschedule_slot_taken_reoffers_and_needs_new_confirmation` | Sau SLOT_TAKEN, đề xuất lại lọc theo "hai giờ rưỡi chiều" đã nói (G-7): không còn khung chiều → gợi ý theo luật bậc 3/4 + câu "không còn khung…"; phần "cần xác nhận mới" giữ nguyên |
| `test_orchestrator.py::test_refusing_slots_drops_pending_action_without_writing` | Nếu câu test là "không" trần → giờ ra `SLOT_REFUSE_CHOICE` (A/B), chưa `_abandon`; đổi câu thành "thôi không đổi nữa" để giữ ý test, thêm case "không" trần riêng |
| `test_calls.py:564` (HTTP "Cho tôi đổi lịch" → "10 giờ sáng" → "Được") | Thêm một lượt: bot hỏi khoảng thời gian (Q-1); "10 giờ sáng" trả lời câu đó → một ứng viên → đọc lại → "Được" → `RESCHEDULED` |
| `test_agreement.py` (`SLOT_READBACK` "vâng" → UNCLEAR) | Đổi thành AGREE (Q-2); giữ UNCLEAR cho ngập ngừng |
| `test_context_fsm.py` | Thêm tuần tự hóa schema v2 / đọc bản v1 |
| `test_slot_choice.py::test_no_criteria_is_none` | Giữ; thêm MORE/ANY/out_of_window |

### 5.2 Test mới

IE (`test_slot_choice.py`, `test_slot_ranking.py`, `test_agreement.py`, `test_extractor.py`, `test_unaccented.py`):
- MORE: "còn khung nào khác không", "khung khác", "sớm hơn được không", "ngày khác", "nghe tiếp"; không dấu "khung khac", "con khung nao khac".
- ANY: "nào cũng được", "tùy em", "khung nào cũng được"; "sáng nào cũng được" → tiêu chí buổi sáng.
- Tiêu chí + MORE: "khung khác, buổi sáng ấy" → tiêu chí buổi sáng.
- `out_of_window`: "tháng sau", "ngày 30 tháng 11" (now 22/09) → `True`; "thứ bảy tuần sau" → `False`.
- `rank_alternatives` (now = thứ Ba 22/09, slots cố định trải 14 ngày): "thứ bảy" không có tuần này → bậc 1 thứ bảy 03/10; không có thứ bảy nào → bậc 2 thứ sáu 25/09 trước chủ nhật 27/09; "chiều thứ năm" không có → bậc 3 chiều thứ sáu; "9 giờ" không có → bậc 4 9 giờ ngày khác rồi 10 giờ; không tiêu chí ngày/giờ → bậc 5; **mọi kết quả ⊆ slots đầu vào**.
- `SLOT_READBACK` AGREE: "được", "đồng ý", "được, đổi giúp tôi", "đổi đi", "chốt đi", "lấy khung đó", "vâng", "dạ", "ừ"; UNCLEAR: "chắc là được", "để tôi xem", "được không nhỉ", "vâng nhưng…"; REFUSE: "không", "thôi"; REFUSE + MORE: "không, khung khác"; MATCH khác: "thôi lấy khung 2".

Luồng (`tests/engine/test_reschedule_dialogue.py`, Orchestrator thật + `FakeClinicAPI`; `now` cố định qua `received_at` khi test ngày tương đối):

| Nhóm | Case | Kỳ vọng |
| --- | --- | --- |
| Figure 0 | "Tôi đổi sang buổi chiều được không?" → "Được, đổi giúp tôi." | lượt 1: câu có/không nêu 2 giờ 30 chiều thứ Tư 14/10, `AWAITING_CONFIRMATION`, `selected_slot_id=slot_91d2`; lượt 2: `RESCHEDULED`, câu "đã đổi lịch khám sang 2 giờ 30 chiều …"; `writes == [("apt_00417","RESCHEDULED",{"new_slot_id":"slot_91d2"})]` |
| Figure 0 + "vâng" (Q-2) | … → "vâng" | như trên |
| Làm rõ thời gian (Q-1) | "tôi muốn đổi lịch" → "buổi sáng" → "được" | lượt 1: `ASK_SLOT_PREFERENCE`, `state=AWAITING_INTENT`, `pending_action is None`, `slot_reads == 0`; lượt 2: một khung sáng → đọc lại; lượt 3: `RESCHEDULED slot_aa01` |
| Không sở thích | "tôi muốn đổi lịch" → "nào cũng được" | đọc 2 khung, `OFFERING_SLOTS`, `failed_understandings == 0` |
| Không tín hiệu ×2 | "tôi muốn đổi lịch" → "ờ" → "ờ" | lần 1 `ASK_SLOT_PREFERENCE_AGAIN` không tính; lần 2 tính; lần 3 chuyển `NOT_UNDERSTOOD` |
| Ngày tương đối (AC-5) | slot 23/09 09:00; now 22/09; "đổi sang ngày mai" | câu có "thứ Tư ngày 23 tháng 9" + có/không; "được" → `RESCHEDULED` |
| Gợi ý bậc 1 (Q-3) | slots: 25/09 (T6), 27/09 (CN), 03/10 (T7); "đổi sang thứ bảy" | câu "thứ bảy này … không còn khung" + "thứ bảy tuần sau ngày 3 tháng 10" đứng đầu; `failed_understandings == 0`; "thế chủ nhật?" → chủ nhật 27/09, vẫn không chuyển máy |
| Gợi ý bậc 2–4 | như ma trận IE nhưng qua Orchestrator | thứ tự khung đọc ra đúng bậc; `presented ⊆ slots` |
| Ngoài cửa sổ | "đổi sang tháng sau" | `OUT_OF_WINDOW` + `ASK_SLOT_PREFERENCE`, `failed_understandings == 0`, không đọc slot nào |
| Nhiều khung | 2 khung chiều → "buổi chiều" → "khung 2" → "được" | AMBIGUOUS đọc 2 khung, chọn đúng slot thứ 2 |
| Còn N khung (Q-5) | 5 slot → "nào cũng được" → "khung khác" → "khung 1" | lượt 1 câu có "còn 2 khung khác"; trang 2 đọc slot 4–5; "khung 1" ở trang 2 = slot 4 |
| Hết khung | 2 slot → "khung khác" | `SLOT_MORE_NONE` → `ASK_SLOT_PREFERENCE`, `pending_action == RESCHEDULE` |
| Chọn lại ở readback (Q-4) | "khung 1" → "không, khung khác" → "khung 1" → "được" | lượt 2: `OFFERING_SLOTS`, không có slot 1, `pending == RESCHEDULE`, `evidence == []`; kết thúc `RESCHEDULED` bằng slot 2 |
| "Không" trần (Q-4) | "khung 1" → "không" → "khung khác" | lượt 2: `SLOT_REFUSE_CHOICE`, không ghi, `pending` giữ; lượt 3: `OFFERING_SLOTS` |
| "Không" trần → giữ lịch | "khung 1" → "không" → "giữ lịch" | `_abandon`: `CONFIRM_READBACK` lịch cũ, `writes == []` |
| Đổi slot ở readback | "khung 1" → "thôi lấy khung 2" → "được" | đọc lại slot 2; `RESCHEDULED slot_91d2`; bằng chứng slot 1 không dùng |
| Từ chối hẳn | "khung 1" → "thôi không đổi nữa" | `_abandon`, `writes == []` |
| Chưa rõ | "khung 1" → "chắc là được" → "được" | lượt 2 không ghi, hỏi lại có/không cùng slot; lượt 3 ghi |
| Sau "chưa hiểu" | "khung 1" → "gì cơ" → "vâng" | không ghi (T-08 `_answers_last_question`); đọc lại rồi mới ghi |
| SLOT_TAKEN giữ tiêu chí (G-7) | 3 slot (chiều 14/10, chiều 15/10, sáng 15/10) → "buổi chiều" → "khung 1" → (slot 1 bị lấy) "được" | câu `SLOT_TAKEN` + khung **chiều 15/10** đứng trước; cần AGREE mới; `writes` 1 bản ghi |
| Không còn slot | `clinic.slots = []` | `TRANSFERRED/OUT_OF_SCOPE`, câu `NO_SLOTS_TRANSFER`, `writes == [TRANSFERRED]` |
| Ghi bị từ chối | `fail_next("reschedule_appointment", 409 INVALID_STATE_TRANSITION)` | `TRANSFERRED/SYSTEM_ERROR`, không có câu "đã đổi lịch" |
| Chưa rõ kết quả | `fail_next(..., outcome_unknown=True, apply_first=True)` | `409 CALL_RECONCILIATION_REQUIRED`, không `RESCHEDULED` |
| VERSION_CONFLICT 1 lần | `fail_next(..., 409 VERSION_CONFLICT)` | `RESCHEDULED`, 2 request cùng key `…:reschedule:slot_91d2` |
| Status / slot lạ | stub trả `status=RESCHEDULED, new_slot_id=slot_khac` | `ReconciliationRequired`, không báo thành công |
| Ngoại lệ | tại `ASK_SLOT_PREFERENCE`, `OFFER_SLOTS`, `SLOT_READBACK`: "tôi đau ngực", "cho gặp nhân viên", im lặng ×1, "gì cơ", "thôi hủy lịch luôn" | `CLINICAL_QUESTION` / `PATIENT_REQUEST` / nhắc giữ câu hỏi / đọc lại / sang `CANCEL_RECONFIRM`; không ghi `RESCHEDULED` |
| Inbound | sau xác minh "tôi muốn đổi lịch" | `TRANSFERRED/OUT_OF_SCOPE`, `writes == []` (test hiện có) |
| SF-02 | mọi lượt `OFFERING_SLOTS`/`SLOT_READBACK` kể cả sau gợi ý | `presented_slot_ids ⊆ ctx.slot_ids` |
| SF-03 | mọi câu trước `VERIFIED` | không chứa giờ/slot (`test_sf03_appointment_disclosure.py`) |

HTTP (`test_calls.py`): một cuộc outbound đúng kịch bản Figure 0 qua `/v1/calls` + `/turn` → lượt cuối `ended=true, outcome=RESCHEDULED`; một cuộc "tôi muốn đổi lịch" → hỏi khoảng → chọn → xác nhận; một cuộc có SLOT_TAKEN rồi thành công.

## 6. Quyết định (đã chốt với owner 22-09-2026)

| # | Câu hỏi | Quyết định | Căn cứ |
| --- | --- | --- | --- |
| Q-1 | Yêu cầu đổi lịch không kèm thời gian: hỏi khoảng thời gian trước hay đọc ngay 3 khung đầu? | **Hỏi trước** (`ASK_SLOT_PREFERENCE`), nhắc "trong hai tuần tới" | Task T-10 "làm rõ thời gian mong muốn"; kiến trúc §3.2 O_NEED; contract §6.1 để nhóm tự thiết kế. Rủi ro harness (kịch bản "đổi lịch" → "khung 1") ghi ở §7 |
| Q-2 | "Vâng / dạ / ừ" đáp câu đọc lại slot có mở khóa `RESCHEDULED` không? | **Có** — "vâng" là đồng ý chốt lịch | Đồng bộ T-04 Q-2; Figure 0 dòng 196 bot hỏi câu có/không; §1.1.6 không đòi "rõ ràng"; hai bước chọn + xác nhận cùng một slot là xác nhận rõ ràng theo tinh thần §1.1.10. `CANCEL_RECONFIRM` không đổi (SF-05) |
| Q-3 | Xin giờ không có khung: tính "không hiểu"? gợi ý thế nào? | **Không tính** (`NEUTRAL`); **hỏi lại + gợi ý theo luật xếp hạng §3.2.2** (cùng thứ tuần khác → ngày liền kề → cùng buổi → cùng giờ → sớm nhất), chỉ từ `GET /slots`; ngoài cửa sổ 14 ngày → nói giới hạn, hỏi lại, **không gợi ý** | §1.1.5 "hiểu sai" ≠ không có hàng; SF-02/§1.1.6 cấm gợi ý ngoài danh sách; IE §5.7 "đọc slot gần nhất" được định nghĩa cụ thể để không gợi ý bừa |
| Q-4 | "Không, khung khác" ở `SLOT_READBACK` | **Bỏ slot, giữ đổi lịch**; "thôi không đổi nữa"/"giữ lịch" → bỏ hẳn; **"không" trần → hỏi A/B** (khung khác / giữ lịch cũ) | §1.1.5 "KHÔNG ĐƯỢC đoán"; kiến trúc O_CHOOSE tách "muốn khoảng khác" và "đổi ý" |
| Q-5 | Đọc bao nhiêu khung; lưu gì vào phiên? | **Tối đa 3 khung/lượt + nói còn N khung khác**, "khung khác" đọc trang tiếp; lưu `slot_criteria_text` + `offered_slot_ids` (schema v2) | Contract không quy định số khung (Figure 0 đọc 1–2); 3 là giới hạn nghe/nhớ qua điện thoại và chi phí TTS (§5). §4.2.2 cho phép giữ "khung giờ đang được đề xuất"; tiêu chí là lời người gọi, không phải trạng thái lịch |
| Q-6 | State và `pending_action` khi hỏi khoảng thời gian | **`AWAITING_INTENT`, chưa `set_pending`** ở lượt hỏi đầu; ý định giữ ở `question.action`; ngoại lệ invariant chỉ cho trường hợp "hết trang → hỏi khoảng khác" (pending đã có) | Phụ lục A: 6 state cố định (`AWAITING_IDENTITY`, `AWAITING_INTENT`, `AWAITING_CONFIRMATION`, `OFFERING_SLOTS`, `CLOSING` — chưa dùng, `ENDED`); §2.1 harness không chấm `state`; `OFFERING_SLOTS` cần slot đã đọc |

## 7. Ngoài phạm vi và rủi ro

- **Rủi ro Q-1 với bộ test ẩn:** nếu kịch bản harness là "tôi muốn đổi lịch" → "khung 1" (mong đợi slot đã được đọc), câu "khung 1" rơi vào `ASK_SLOT_PREFERENCE` → không tiêu chí → hỏi lại lần 1 (không tính), lần 2 mới tính. Giảm rủi ro: ở `ASK_SLOT_PREFERENCE`, một câu chỉ có **thứ tự** ("khung 1", "cái đầu") → coi như ANY và đọc luôn 3 khung đầu (ordinal chỉ có nghĩa sau khi đã đọc) — đưa vào bước 5. Vẫn nên hỏi `#residency-batch03` case đổi lịch có luôn nêu thời gian không.
- **Rủi ro Q-2 với §1.1.10 (booking):** cùng `SLOT_READBACK`; nếu chương trình coi "vâng" chưa đủ "rõ ràng" cho đặt lịch, tách ngưỡng theo `pending_action == BOOK` (một dòng trong `_agree_span`) — T-11 quyết. Nên hỏi PM cùng lúc với câu trên.
- **Cửa sổ slot cố định 14 ngày** (mock giới hạn `to - from`): "tháng sau" không thể phục vụ; T-10 chỉ nói rõ giới hạn. Mở rộng bằng nhiều lần `GET /slots` (T-09/B) nếu tester yêu cầu.
- **Tiêu chí tương đối** ("sớm hơn", "muộn hơn") chỉ là MORE; không lọc theo giờ tương đối. Nâng cấp ở T-10.1 nếu bộ test dùng nhiều.
- **Luật xếp hạng** là heuristic tất định; không dùng LLM để "đoán ý". Nếu bậc 1–4 đều rỗng thì rơi về bậc 5 (sớm nhất) — có nói rõ "gần nhất em có".
- **Booking inbound (T-11)** dùng chung `_offer_slots`/`_slot_choice`/`_slot_readback`/`rank_alternatives`/`speak_date`: mọi thay đổi áp dụng cho `BOOK`; T-11 chỉ đổi lời "đặt lịch" ở `slot_offer_readback`/`rescheduled`.
- **Retry lỗi tạm thời** (429/503) khi reschedule: T-12 (B). Hiện từ chối xác định → `SYSTEM_ERROR`.
- **Ngày tương đối trong test** phụ thuộc `received_at`: test luồng truyền `now` cố định (cần seam `received_at` trong `_run` helper hoặc `SessionManager.run_turn(..., received_at=)`); fake mặc định `strict_slot_window=False`.
- **Output Guard (R-01)** kiểm câu đọc slot tập trung: không thuộc T-10; T-10 chỉ giữ mọi câu có giờ đi qua `_present`/`slot_readback`/`slot_offer_readback`.
- `CLOSING` vẫn chưa dùng; T-10 không bật.

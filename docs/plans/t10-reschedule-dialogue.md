# Plan T-10 — Hội thoại Reschedule (v2)

**Dev:** Hưng · **Test thủ công / rà soát:** Hoàn · **Ngày:** 29-09-2026 · **Thay cho:** plan v1 ngày 22-09-2026
**Hạn:** Gate W3 ngày 02-10 chạy lại 7/7 kịch bản ở chế độ audio, có Reschedule (task 143) → merge trước 01-10.
**Base:** `main` sau T-11 (booking inbound, PR #28), T-12 (write recovery, PR #50) — `dialogue/` đã tách `questions.ask`, `inbound.py`, `outbound.py`; Gateway đã quét slot nhiều cửa sổ.
**Nguồn:** contract rev 1.1 (§1.1.5, §1.1.6, §2, Bảng 1, Bảng 2, Listing 4, Hình 0 tab Reschedule, §6.1, SF-02); PRD v1.6 (R-05, R-06, R-07, R-19, R-23, R-25, R-29, R-30, GC-RES-01..06, GC-DATE-01..05, GC-CONF-01, GC-XFER-04/05); plan v1.

## 0. Đọc nhanh

1. Plan v1 viết ngày 22-09, **trước** khi PRD chốt R-23 (24-09), R-25, R-29, R-30 (22-09). Năm quyết định của v1 phải đổi theo PRD — §1.
2. Code phần slot trên `main` **chưa ai sửa**: 12 lỗ hổng G-1..G-12 của v1 còn nguyên. Chạy lại ngày 29-09 (Orchestrator thật + `clinic_mock_sim` seed giống Clinic Mock deploy) còn thấy thêm 3 lỗi mới, trong đó có **vòng lặp vô hạn** — §2.
3. T-12 đã làm phần kiểm tra kết quả ghi đổi lịch (`_status_is("RESCHEDULED", new_slot_id=...)`), G-9 chỉ còn phần câu thoại.
4. Ưu tiên tuyệt đối là **kịch bản mẫu Hình 0 của contract**: hiện bot fail đúng kịch bản này, bản ghi ở lại `SCHEDULED` = 0 điểm.
5. Bộ ca test thủ công (Phụ lục A) là tiêu chí nghiệm thu: Hoàn chạy trên deploy trước và sau khi sửa, dán output kèm mã ca để đối chiếu.
6. Các điểm contract và PRD bỏ ngỏ: D-1..D-6 đã chốt (Hưng, 29-09) — §6.
7. **Tiến độ 29-09:** xong bước 1–3 và 4 lỗi phát hiện khi test tay (§2.1). Câu nói chuẩn chạy đúng; câu nói lệch còn hở. Hướng xử lý: rule trước, LLM fallback sau, đo bằng bộ eval riêng (§3.8, bước 7–9).

## 1. Thay đổi so với v1 — vấn đề → hướng sửa

| # | Mục v1 | Vấn đề | Hướng sửa trong v2 |
| --- | --- | --- | --- |
| V-1 | Q-2: "vâng / dạ / ừ" ở `SLOT_READBACK` là đồng ý | PRD R-23 (chốt 24-09): **"dạ" không bao giờ là đồng ý**, ngưỡng cao hơn cho hành động phá hủy; GC-CONF-01: "dạ" → không ghi, hỏi lại câu có/không | **Sửa Q-2 theo D-2 (chốt 29-09):** ở `SLOT_READBACK`, "vâng", "ừ", "ok", "được", "đồng ý", "đổi giúp tôi" là đồng ý (thêm "đổi giúp em", "đổi luôn", "đổi sang giờ đó" — chỉ bản có dấu, vì "doi" = "đợi"). **"dạ" không bao giờ là đồng ý** → hỏi lại và nhắc khách nói "đồng ý". Câu chưa rõ khác → hỏi lại **câu có/không**, không dùng câu A/B `t.slot_choice` |
| V-2 | Q-5: đọc tối đa 3 khung, phân trang | PRD R-25 (chốt): **tối đa 2 khung mỗi lượt** | `MAX_SLOTS_PRESENTED = 2`. Giữ phân trang: nói "còn N khung khác", "khung khác / còn khung nào / nghe tiếp / giờ khác" đọc trang tiếp, không lặp khung đã đọc (§3.4) |
| V-3 | §3.2.2 luật gợi ý 5 bậc, cửa sổ 14 ngày, `OUT_OF_WINDOW` | PRD R-29 (chốt 22-09) định nghĩa khác: tìm từ **ngày khách xin đến +7 ngày**, cùng `clinic_id` với lịch hiện tại; ngày còn giờ → đọc ≤2 giờ của ngày đó; ngày kín → **báo kín** + ≤2 giờ **gần ngày xin nhất**; tối đa **2 vòng**, hết vòng → **giữ lịch cũ, chuyển `PATIENT_REQUEST`** | **Bỏ luật 5 bậc và `OUT_OF_WINDOW`.** Gateway nhận ngày bắt đầu (§3.3), xếp gợi ý theo khoảng cách tới ngày xin. Thêm bộ đếm vòng (§3.2). Vì tìm thẳng theo ngày xin nên không còn khái niệm "ngoài cửa sổ 14 ngày" |
| V-4 | AC-12: không còn slot → `OUT_OF_SCOPE` | Câu thoại hiện là câu chuyển máy chung, không nói lý do | Nói lý do trước khi chuyển (`NO_SLOTS_TRANSFER`), lý do `OUT_OF_SCOPE` (§6 D-4, chốt 29-09) |
| V-5 | AC-5: chỉ đọc ngày tuyệt đối cho "mai / kia / tuần sau" | PRD R-30 (chốt 22-09): thêm "mốt", "thứ X này", "cuối tuần", "đầu tuần sau"; **ngày đã qua / không quy đổi chắc chắn → hỏi lại**; **mọi câu xác nhận có thứ + ngày/tháng + giờ** (GC-DATE-05) | Bảng quy đổi §3.5.2; nhãn "ngày không rõ" để Dialogue hỏi lại; `speak_datetime` đọc thêm thứ |
| V-6 | `slot_readback`: "đổi lịch sang {giờ} {ngày} tại {cơ sở}" (có ý đọc khoa theo R-29) | Contract không nhắc khoa cho đổi lịch (Hình 0 chỉ đọc ngày + giờ). **Quyết định của dev (Hưng, 29-09): theo contract, không đọc khoa** | Câu chốt: giờ + **thứ** + ngày/tháng (+ cơ sở, R-19 cho phép). Không đọc khoa |
| V-7 | G-9: kiểm tra `status` / `new_slot_id` trước khi báo thành công | T-12 đã làm ở Gateway (`clinic_gateway.reschedule` → `_status_is("RESCHEDULED", new_slot_id=new_slot_id)`) | Chỉ còn: câu báo "em đã **đổi** lịch sang …" (thay "đã **đặt** lịch"), dựng từ slot đã ghi |
| V-8 | Base `7f6c4a1`, `dialogue/manager.py` một file, Gateway một cửa sổ 14 ngày | `main` đã đổi: `questions.ask` thay `_ask`; Gateway quét tối đa 5 cửa sổ × 14 ngày từ `now` (T-11); booking inbound **dùng chung** `_offer_slots` / `_slot_choice` / `_slot_readback` | Code trên `main` mới. Mọi thay đổi luồng slot chạy lại test T-11 (`test_inbound_booking_flow.py`, `test_scenario7_edge.py`, `tests/engine/tools/test_booking_write.py`). Tham số mới của Gateway là tùy chọn, booking giữ hành vi cũ |
| V-9 | *(không có)* | **Lỗi mới — vòng lặp vô hạn** (ca 2.3): ở câu chốt, "không, tôi muốn đổi khung khác" → `_slot_readback` gọi `_present(ctx, ctx.slots)` → đọc lại **toàn bộ** danh sách, **mất tiêu chí**, **có cả khung vừa từ chối**, và tính là "hiểu" → lặp mãi không chuyển máy | Loại khung đã từ chối, giữ tiêu chí, đếm vòng (§3.2, §3.4) |
| V-10 | *(không có)* | **Lỗi mới** (ca 2.4): ở `OFFER_SLOTS`, "không được, ngày 19 tháng 10 thì sao" → IE trả AMBIGUOUS → bot mở đầu bằng "Dạ, có nhiều khung giờ phù hợp", sai ngữ cảnh; không đếm vòng | Tiêu chí thời gian **mới** ở `OFFER_SLOTS` / `SLOT_READBACK` = **vòng mới** → `_offer_slots(tiêu chí mới)` (§3.4) |
| V-11 | *(không có)* | **Lỗi IE mới**: "sau ngày 20" hiểu thành đúng ngày 20; "thứ 5 hoặc thứ 6" chỉ lấy thứ 5; "Đổi cho tôi càng sớm càng tốt" không nhận ra ý định đổi lịch | P2 (§3.5.2) |
| V-12 | Q-1: hỏi khoảng thời gian trước | Contract và PRD đều không yêu cầu hỏi trước (chỉ có trong task-breakdown và sơ đồ kiến trúc). Rủi ro harness ("tôi muốn đổi lịch" → "khung 1") | **Bỏ Q-1 theo D-1 (chốt 29-09):** không nêu thời gian → đọc 2 khung sớm nhất và mời nêu ngày khác trong cùng câu. `ASK_SLOT_PREFERENCE` chỉ còn dùng khi hết vòng hoặc khi ngày khách nói không dùng được. Hết rủi ro lệch lượt với harness |

**Giữ nguyên từ v1:** Q-3 (xin giờ không có ≠ "không hiểu"), Q-4 (ba nhánh từ chối ở câu chốt), Q-6 (`ASK_SLOT_PREFERENCE` báo `AWAITING_INTENT`), G-7 (giữ tiêu chí sau `SLOT_TAKEN`, khớp GC-RES-06), AC-10 (đổi slot xóa bằng chứng cũ), AC-13 (các lớp lỗi ghi), AC-16 (inbound "đổi lịch" → `OUT_OF_SCOPE`).

## 2. Hiện trạng đã kiểm (29-09-2026)

Chạy Orchestrator thật trên nhánh T-10 (đã merge `main`), `clinic_mock_sim` seed giống Clinic Mock deploy (Phụ lục A), LLM fallback tắt. Chi tiết từng ca ở Phụ lục A; tóm tắt:

| Nhóm | Ca | Hiện tại | Hệ quả chấm điểm |
| --- | --- | --- | --- |
| Hình 0 | 1.2 | Một khung khớp vẫn hỏi "chọn khung nào"; "Được, đổi giúp tôi." → "em chưa hiểu" | Kết thúc `SCHEDULED` → fail |
| Không nêu thời gian | 1.1 | Đọc ngay 3 khung đầu, không mời nêu ngày khác | Trái R-25, D-1 |
| Số khung | 1.3, 7.1 | Đọc 3 khung; "khung khác" → "chưa hiểu", lần 2 → `TRANSFERRED/NOT_UNDERSTOOD` | Chuyển máy sai lý do |
| Từ chối | 2.1, 2.2 | "không" / "không, khung khác" → bỏ luôn đổi lịch | Đoán ý khách (§1.1.5) |
| Từ chối | 2.3 | Vòng lặp vô hạn (V-9) | Cuộc gọi không kết thúc |
| Vòng | 2.4 | Không đếm vòng; hết 2 vòng → quay lại hỏi đến khám thay vì `PATIENT_REQUEST` | Trái GC-RES-05 |
| Ngày kín / ngoài khoảng | 3.1–3.3, 4.1 | Lọc rỗng → **im lặng** đọc khung 14/10 như thể đúng ý (`filter_slots(...) or slots`) | Trái GC-RES-02 |
| Đồng ý | 5.1–5.8 | "dạ/vâng/ừ" → câu A/B; "đổi giúp tôi" → "chưa hiểu" (tính 1 lần); "ok" → ghi | Câu hỏi lại sai dạng; một cụm đồng ý rõ bị tính "không hiểu" |
| Câu chốt / báo | 6.1 | Thiếu thứ; câu báo "đã **đặt** lịch" | Trái GC-DATE-05, Hình 0 |
| Ngày tương đối | 8.1–8.20 | "mốt", "cuối tuần", "tháng sau"… → rỗng; "thứ 7 này" = mọi thứ 7; "thứ 2" (đã qua) → tự hiểu 19/10 | Trái R-30, GC-DATE-03 |
| Inbound | — | "đổi lịch" → `TRANSFERRED/OUT_OF_SCOPE`, không ghi | Đúng, giữ |

### 2.1 Test tay sau bước 1–3 (29-09, Docker local, sim `mentor_mock`)

**Lỗi đã sửa** (mỗi lỗi có test hồi quy trong `test_slot_choice.py` / `test_reschedule_dialogue.py`):

| # | Khách nói | Bot làm sai | Nguyên nhân | Đã sửa |
| --- | --- | --- | --- | --- |
| M-1 | "đổi sang ngày 2 giờ chiều thứ Sáu ngày 16 tháng 10" | "em chưa thấy khung giờ đó" | Parser lấy "ngày 2" làm mùng 2, bỏ "16 tháng 10" và mất giờ | "ngày N giờ" là giờ; "ngày D tháng M" thắng "ngày D" trần |
| M-2 | (mọi câu có câu mở đầu) | "Dạ, em chưa thấy khung giờ đó. Dạ, hiện còn…" | Câu mở đầu và thân câu đều có "Dạ" | Có câu mở đầu thì thân câu bắt đầu bằng "Hiện còn…" |
| M-3 | "xem nốt 2 khung cuối" | Chốt luôn khung cuối của trang | Rule đọc "khung cuối" thành thứ tự | "N khung cuối / còn lại / khác", "xem nốt" = xin nghe tiếp |
| M-4 | "cho tôi xem 4 khung khác" | Đọc 2 khung, không giải thích | R-25 chỉ cho 2 khung | Vẫn đọc 2, thêm câu "em đọc lần lượt hai khung một để anh chị dễ nhớ ạ" |

**Còn hở** (chạy 26 câu nói lệch qua rule hiện tại; đầu vào cho §3.8):

| Nhóm | Ví dụ | Rule hiện tại | Hậu quả |
| --- | --- | --- | --- |
| Rule không hiểu (~10/26) | "cái gần nhất ấy", "lấy cái sau đi", "thế còn gì nữa không em", "hôm đó tôi bận mất rồi", "khi nào cũng được", "đầu tháng sau" | NONE / UNCLEAR | "em chưa hiểu"; 2 lần → chuyển máy `NOT_UNDERSTOOD` |
| **Rule hiểu sai** (3/26) | "sao lại là thứ Sáu" (câu chốt), "tuần sau nữa" | Chọn khung thứ Sáu; hiểu thành "tuần sau" | Đọc nhầm khung. Không ghi sai nhờ câu chốt, nhưng mất lượt |

Không ca nào ghi sai lịch: mọi lệnh ghi vẫn cần câu chốt và đồng ý rõ.

## 3. Thiết kế v2

### 3.1 Luồng

```text
CONFIRM_READBACK / ASK_INTENT (outbound), intent RESCHEDULE
  tiêu chí = parse_slot_criteria(transcript, now)
    ngày không rõ (đã qua / không tồn tại / quá rộng) -> set_pending(RESCHEDULE); ASK_SLOT_PREFERENCE + lý do (§3.5.2); vòng vẫn 0
    không có tiêu chí                                 -> set_pending(RESCHEDULE); _offer_slots(không lọc) + mời nêu ngày khác   # D-1
    có tiêu chí                                       -> set_pending(RESCHEDULE); vòng = 1; _offer_slots(tiêu chí)

ASK_SLOT_PREFERENCE (_slot_preference) — chỉ sau khi hết vòng hoặc ngày không dùng được (D-1)
  tiêu chí mới          -> vòng += 1; _offer_slots
  "nào cũng được" / "sớm nhất" -> _offer_slots(không lọc)
  không tín hiệu        -> hỏi lại (lần 1 không tính §1.1.5)
  "thôi không đổi" / giữ lịch -> _abandon
  ngoại lệ (lâm sàng, xin nhân viên, hủy)  -> như mọi bước

_offer_slots(tiêu chí)
  slots = Gateway.list_open_slots(ctx, now, date_from=ngày xin)             # §3.3, R-29
  slots == []  (quét hết vẫn trống)            -> NO_SLOTS_TRANSFER; transfer (D-4)
  khớp = filter(slots, tiêu chí) trừ offered_slot_ids
    đúng 1 khớp  -> select_slot; câu có/không (slot_offer_readback)  SLOT_READBACK, AWAITING_CONFIRMATION   # Hình 0
    ≥ 2 khớp     -> đọc 2 + "còn N khung khác"                        OFFER_SLOTS, OFFERING_SLOTS           # R-25
    0 khớp       -> "{ngày xin} đã kín" + ≤2 khung gần ngày xin nhất  OFFER_SLOTS, NEUTRAL                   # GC-RES-02
                    (khoảng [ngày xin, +7] trống cả -> D-3)

OFFER_SLOTS (_slot_choice)
  MATCH (thứ tự trong trang hiện tại, hoặc giờ/ngày của khung đã đọc) -> select_slot; câu chốt   SLOT_READBACK
  AMBIGUOUS trong khung đã đọc  -> đọc lại các khung khớp (≤2), NEUTRAL
  MORE ("khung khác", "còn khung nào", "nghe tiếp", "giờ khác") -> trang tiếp; hết khung -> HẾT KHUNG (dưới)
  tiêu chí thời gian MỚI         -> vòng mới: _offer_slots(tiêu chí mới); đang ở vòng 2 -> transfer(PATIENT_REQUEST)   # V-10, D-5a
  thứ tự không có trong trang ("khung 3" khi mới đọc 2) -> nói rõ + đọc lại trang, NEUTRAL
  "không" / "không được" (không nêu ngày) -> còn khung: SLOT_REFUSE_CHOICE (A/B), UNCLEAR; hết khung -> HẾT KHUNG   # Q-4, D-5c
  "thôi không đổi" / giữ lịch    -> vòng 0–1: _abandon; vòng 2: transfer(PATIENT_REQUEST)                         # D-5d
  CANCEL                         -> _start(CANCEL)
  còn lại                        -> đọc lại trang hiện tại + NOT_UNDERSTOOD

SLOT_READBACK (_slot_readback)
  AGREE đúng lượt ("vâng", "ừ", "ok", "được", "đồng ý", "đổi giúp tôi"… — D-2) -> Gateway.reschedule
       2xx đúng slot -> _finish(RESCHEDULED, rescheduled(slot))       "Em đã đổi lịch sang …"                 # V-7
       SlotTaken     -> select_slot(None); _offer_slots(tiêu chí đã lưu, prefix SLOT_TAKEN)                   # G-7, GC-RES-06
       lỗi khác      -> như T-04 / T-12 (SYSTEM_ERROR / đối soát)
  "không, khung khác" / REFUSE + MORE -> thêm slot vào refused; select_slot(None); trang tiếp; hết -> HẾT KHUNG   # V-9
  "không" / "không được" (không nêu ngày) -> thêm slot vào refused; còn khung: SLOT_REFUSE_CHOICE, UNCLEAR;
                                             hết khung -> HẾT KHUNG                                              # Q-4, D-5c
  "thôi không đổi" -> vòng 0–1: _abandon; vòng 2: transfer(PATIENT_REQUEST)                                   # D-5d
  MATCH khung khác đã đọc ("thôi lấy khung 2") -> select_slot mới; câu chốt mới
  tiêu chí thời gian mới -> vòng mới; đang ở vòng 2 -> transfer(PATIENT_REQUEST)                              # D-5a
  "dạ" (một mình)  -> không ghi; hỏi lại, nhắc khách nói "đồng ý" (slot_readback_da)                          # D-2, GC-CONF-01
  UNCLEAR khác ("chắc là được", câu hỏi đuôi, "nhưng…") -> hỏi lại CÂU CÓ/KHÔNG cùng slot                  # V-1

HẾT KHUNG (đã đọc / từ chối hết khung của yêu cầu hiện tại)                                                  # D-5b, D-5c
  vòng 0–1 -> SLOT_EXHAUSTED: "…đã đọc hết khung trống. Anh chị muốn đổi sang ngày khác hay giữ lịch cũ ạ?"
              ASK_SLOT_PREFERENCE, AWAITING_INTENT (pending giữ)
  vòng 2   -> ROUNDS_EXHAUSTED_TRANSFER; transfer(PATIENT_REQUEST)
```

### 3.2 Vòng (R-29) — đã chốt (D-5, Hưng 29-09-2026)

PRD R-29 cho khách "tối đa 2 vòng" rồi giữ lịch cũ và chuyển `PATIENT_REQUEST`, nhưng không định nghĩa vòng. Luật dùng trong T-10:

| # | Luật | Ví dụ (dữ liệu deploy) |
| --- | --- | --- |
| a | **Một vòng = một ngày / khoảng thời gian khách nêu.** Khách được nêu **tổng cộng 2** ngày. Khách nêu ngày thứ ba → không tra nữa, giữ lịch cũ, `transfer(PATIENT_REQUEST)` | "đổi sang 14/10" (vòng 1) → "không được, ngày 19 thì sao" (vòng 2) → "không, ngày 21 đi" → chuyển máy |
| b | Nghe "khung khác" **trong cùng yêu cầu** không tính vòng mới | "đổi sang 15/10" → nghe 10:30, 15:30 → "khung khác" → vẫn vòng 1 |
| c | Khách từ chối mà **không nêu ngày mới** ("không", "không được") → **hỏi lại, không đoán**: còn khung chưa đọc thì "anh chị muốn nghe khung khác hay giữ lịch cũ ạ?", hết khung thì "anh chị muốn đổi sang ngày khác hay giữ lịch cũ ạ?". Ở vòng 2 mà đã hết khung → `transfer(PATIENT_REQUEST)` | "đổi sang 14/10" (chỉ 1 khung) → "không được" → "anh chị muốn đổi sang ngày khác hay giữ lịch cũ ạ?" |
| d | "Thôi không đổi nữa" / "giữ lịch": **vòng 1** → `_abandon` (giữ lịch cũ, quay lại câu hỏi đến khám, cuộc gọi tiếp tục); **vòng 2** → giữ lịch cũ, `transfer(PATIENT_REQUEST)` (GC-RES-05) | vòng 1: "đổi sang 15/10" → "thôi không đổi nữa" → "…anh chị có đến khám được theo lịch này không ạ?" |
| e | Lượt gợi ý 2 khung sớm nhất khi khách **chưa nêu thời gian** (D-1) **không tính vòng**; vòng 1 bắt đầu khi khách nêu thời gian đầu tiên | "tôi muốn đổi lịch" → bot đọc 14/10, 15/10 (chưa có vòng) → "không, ngày 19 thì sao" = vòng 1 |

Thêm:
- Khoảng 7 ngày trống, bot tra tiếp và gợi ý khung sớm nhất sau đó (D-3): vẫn thuộc vòng của ngày khách nêu.
- `SlotTaken` khi ghi không tăng vòng; bot gợi ý lại trong cùng vòng (GC-RES-06).
- Sau khi đã đọc hết khung, khách nói "ngày nào cũng được" (nhãn ANY): **tính 1 vòng** như nêu ngày mới, đọc lại từ khung sớm nhất, bỏ các khung khách đã từ chối. Nếu không tính, "khung khác" và "nào cũng được" luân phiên sẽ lặp mãi.
- Ở câu đọc khung, "khung nào cũng được" (ANY): đọc câu chốt khung sớm nhất của trang, vẫn phải đồng ý mới ghi.
- Lượt "chưa hiểu" không tăng vòng; bộ đếm §1.1.5 chạy riêng.
- Lưu ở `ctx.slot_round` (0 = chưa có vòng, 1, 2).

### 3.3 Gateway (`tools/clinic_gateway.py`)

| Vấn đề | Hướng sửa |
| --- | --- |
| `list_open_slots` luôn tìm từ `now`, dừng ở cửa sổ 14 ngày đầu tiên có slot → ngày khách xin nằm ngoài cửa sổ đó thì lọc rỗng | Thêm tham số tùy chọn `date_from: date \| None`, `days: int \| None`. Đổi lịch có ngày xin → `from = max(now, 00:00 ngày xin)`, `to = from + 7 ngày` (R-29; Mock cho phép `to - from ≤ 14`). Không có ngày xin → hành vi hiện tại. **Booking không truyền tham số → giữ nguyên** |
| `clinic_id` lấy cố định từ config (`cl_vinmec`) | Đổi lịch: lấy `clinic_id` từ bản đọc lịch hẹn của cuộc gọi (`GET /appointments/{id}`); không có thì dùng config. Contract §4.2.2 cho phép giữ bản đọc trong ngữ cảnh cuộc gọi |
| Khoảng [ngày xin, +7] trống | Gọi tiếp cửa sổ kế (như cơ chế nhiều cửa sổ của T-11) để có gợi ý sớm nhất sau ngày xin — theo D-3 |
| `reschedule` kiểm kết quả ghi | Đã có (T-12). Không sửa |

`ctx.slots` luôn là kết quả **lần `GET /slots` gần nhất** (SF-02, tiêu chí R-06/R-07). Mọi khung đọc ra, kể cả gợi ý "gần nhất", chỉ lấy từ đó.

### 3.4 Dialogue (`dialogue/manager.py`, `dialogue/questions.py`)

| Vấn đề hiện tại (vị trí) | Hướng sửa |
| --- | --- |
| `_start` đọc 3 khung, không mời nêu ngày khác | Không tiêu chí → `set_pending`, đọc 2 khung sớm nhất bằng `offer_slots_any` (mời nêu ngày khác, D-1). Ngày không dùng được → `ask(ASK_SLOT_PREFERENCE)` kèm lý do |
| `_offer_slots`: `filter_slots(...) or slots` nuốt kết quả rỗng | Ba nhánh theo số khung khớp (§3.1). Lưu `ctx.slot_request` mỗi khi có tiêu chí mới, reset `offered_slot_ids` |
| `_present`: `candidates[:3]`, không báo còn bao nhiêu | Đọc tối đa 2 trong số chưa đọc; nối `slots_remaining(n)`; cộng dồn `offered_slot_ids`; `presented_slot_ids` = trang hiện tại |
| Một khung vẫn hỏi "chọn khung nào" (G-1) | Đúng 1 khung → `select_slot` + `slot_offer_readback` (câu có/không), `SLOT_READBACK` |
| `_slot_choice`: không có nhánh MORE; NO_MATCH tính NOT_UNDERSTOOD; tiêu chí mới thành AMBIGUOUS (V-10) | Thêm MORE; NO_MATCH có tiêu chí mới → vòng mới, NEUTRAL; thứ tự ngoài trang → NEUTRAL + đọc lại |
| `_slot_choice`: "không" → `_abandon` | "không" trần → `SLOT_REFUSE_CHOICE` (hết khung → HẾT KHUNG); "thôi không đổi / giữ lịch" → vòng 0–1 `_abandon`, vòng 2 chuyển máy (§3.2 d) |
| `_slot_readback`: REFUSE + intent RESCHEDULE → `_present(ctx, ctx.slots)` (V-9) | Thêm slot vào `refused_slot_ids`, đọc trang tiếp theo đúng `slot_request`; hết → hết vòng |
| `_slot_readback`: REFUSE không kèm intent → `_abandon` (G-5) | Phân nhánh MORE / giữ lịch / "không" trần như §3.1 |
| `_slot_readback`: UNCLEAR → câu A/B `t.slot_choice` | Hỏi lại câu có/không cùng slot (GC-CONF-01) |
| `_slot_readback`: `SlotTaken` → `_offer_slots` không tiêu chí (G-7) | Truyền `ctx.slot_request`; slot bị lấy không đọc lại |
| Câu báo `t.done("RESCHEDULED", slot)` = "đã đặt lịch" | `t.rescheduled(ctx, slot)` = "đã đổi lịch sang …". `done("BOOKED")` giữ cho T-11 |
| Không có bộ đếm vòng | `ctx.slot_round`; hết vòng 2 → `transfer(PATIENT_REQUEST)` (§3.2) |
| — | Handler mới `_slot_preference` (`ASK_SLOT_PREFERENCE`), `_slot_refuse_choice` (`SLOT_REFUSE_CHOICE`); đăng ký trong `respond` |

### 3.5 IE (`extraction/slot_choice.py`, `agreement.py`, `schema.py`)

#### 3.5.1 Nhãn và đồng ý

- `SlotChoiceKind` thêm `MORE` ("khung khác", "giờ khác", "cái khác", "còn khung nào", "còn giờ nào", "nghe tiếp", "ngày khác", "hôm khác", "buổi khác", "sớm hơn", "muộn hơn") và `ANY` ("nào cũng được", "tùy em", "lúc nào cũng được", "sớm nhất", "càng sớm càng tốt"). Câu vừa MORE vừa có tiêu chí → ưu tiên tiêu chí. "Sáng nào cũng được" → tiêu chí buổi sáng.
- `extract_slot_choice` chạy cả ở `ASK_SLOT_PREFERENCE` (slots rỗng, chỉ lấy tiêu chí / ANY) và `SLOT_READBACK` (nhận MORE, MATCH khung khác, tiêu chí mới).
- `agreement` ở `SLOT_READBACK` (D-2): `_agree_span` nhận thêm đáp lễ "vâng", "ừ", "ờ" (kể cả "dạ vâng", "vâng ạ"); **"dạ" / "dạ ạ" một mình vẫn UNCLEAR** và gắn cờ để Dialogue dùng câu nhắc "đồng ý". `_SLOT_ACTION` thêm "đổi giúp tôi", "đổi giúp em", "đổi luôn", "đổi sang giờ đó" (chỉ bản có dấu). Chặn ngập ngừng, câu hỏi đuôi, "nhưng…", `_leaves_content` giữ như T-04.
- `QuestionId` thêm `ASK_SLOT_PREFERENCE`, `SLOT_REFUSE_CHOICE` — **không** thuộc `CONFIRMATION_QUESTIONS`.

#### 3.5.2 Ngày tương đối (R-30) — hôm nay lấy từ `TurnContext.now` (+07:00)

| Cách nói | Quy đổi (ví dụ hôm nay thứ Ba 29/09) | Hiện tại | Ưu tiên |
| --- | --- | --- | --- |
| hôm nay / mai / ngày mai / ngày kia | 29/09 / 30/09 / 01/10 | Đúng | — |
| **mốt**, ngày mốt | = ngày kia, 01/10 | "mốt" đứng riêng → rỗng | P1 |
| **thứ X này** | thứ X của tuần này (thứ 7 này → 03/10); đã qua → hỏi lại | Chỉ lấy "thứ X", khớp mọi tuần | P1 |
| **thứ X** (trần), chủ nhật | thứ X sắp tới trong tuần này (CN → 04/10); **đã qua → hỏi lại** (GC-DATE-03); trùng hôm nay → hỏi lại | Khớp mọi thứ X trong danh sách, không hỏi lại | P1 |
| thứ X tuần sau | đúng | Đúng | — |
| **cuối tuần** | thứ 7 + CN tuần này (03–04/10) | Rỗng | P1 |
| **đầu tuần sau** | thứ 2–thứ 4 tuần sau (05–07/10) | Cả tuần sau | P1 |
| **tuần sau nữa** | 12–18/10 | Rỗng | P1 |
| sáng / chiều + ngày | ngày + buổi | Đúng | — |
| ngày X (không tháng), X/M, ngày X tháng M | ngày X gần nhất sắp tới / đúng ngày | Đúng | — |
| **ngày đã qua**, "hôm qua" | hỏi lại | Rỗng → đọc khung sớm nhất | P1 |
| **ngày không tồn tại** ("31 tháng 9") | hỏi lại | Rỗng → đọc khung sớm nhất | P1 |
| **quá rộng**: tháng sau, đầu / giữa / cuối tháng | hỏi lại ngày cụ thể | Rỗng → đọc khung sớm nhất | P1 |
| sau ngày X / từ ngày X / trước ngày X | khoảng ngày | "sau ngày 20" = đúng ngày 20 | P2 |
| thứ X hoặc thứ Y | tập thứ | Chỉ lấy thứ đầu | P2 |

**Đã làm (bước 6, 29-09):** mọi dòng P1 ở trên, cộng "D tháng M" không có chữ "ngày" ("16 tháng 10"), "mùng 5 tháng sau", "hôm qua". Thêm hai điểm khi code:
- Thứ trần chỉ quy về tuần này khi đó là **yêu cầu mới** (`resolve_request`). Khi khách chọn trong các khung đã đọc ("cái thứ Sáu ấy"), "thứ Sáu" vẫn khớp thứ Sáu trong danh sách.
- Ngày xin **còn khung nhưng không đúng giờ xin** ("7 giờ tối ngày 15/10"): nói "em chưa thấy khung giờ đó" rồi đọc khung của chính ngày đó, không nói "đã kín". Chỉ nói "đã kín" khi ngày / khoảng xin không có khung nào.

Kết quả "không rõ" đi kèm lý do (`PAST`, `INVALID`, `TOO_BROAD`, `TODAY`) để câu hỏi lại nói đúng vấn đề, ví dụ "Dạ, thứ Hai tuần này đã qua rồi ạ. Anh chị muốn đổi sang ngày nào ạ?". Không đoán ngày (R-30, §1.1.5). Lượt hỏi lại lần đầu không tính §1.1.5 (D-6).

### 3.6 Session (`session/context.py`, `session/fsm.py`)

- `CallContext` thêm: `slot_request: Optional[str]` (lời người gọi làm tiêu chí — không phải trạng thái lịch, §4.2.2), `offered_slot_ids: list[str]`, `refused_slot_ids: list[str]`, `slot_round: int`. Giữ `SCHEMA_VERSION = 1`, khóa mới đọc bằng `.get` như cách T-01 / T-05 đã thêm khóa (phiên lưu trước vẫn mở được); `clear_pending` và đổi hành động xóa cả bốn. Bước 1–3 đã thêm `slot_request`, `offered_slot_ids`, `refused_slot_ids`; `slot_round` thêm ở bước 4.
- FSM `check_invariants`: `AWAITING_INTENT` + `pending_action ∈ {RESCHEDULE, BOOK}` hợp lệ khi `question_id is ASK_SLOT_PREFERENCE` (hết vòng → hỏi ngày khác). `presented_slot_ids ⊆ slot_ids` giữ nguyên.

### 3.7 Câu thoại (`dialogue/templates.py`)

Mọi câu có giờ đi qua `guardrails.assert_can_disclose`. Không đọc khoa, số điện thoại, `appointment_id` (V-6, R-19).

| Hàm / hằng | Nội dung (nháp) |
| --- | --- |
| `speak_datetime` (sửa) | "3 giờ chiều **thứ Tư** ngày 14 tháng 10" — thêm thứ; áp dụng cho mọi câu, kể cả câu đọc lịch T-04 (GC-DATE-05) → cập nhật test T-04 có so chuỗi |
| `offer_slots_any(slots)` | "Dạ, lịch trống gần nhất có khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10, khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10. Anh chị chọn khung nào, hoặc muốn đổi sang ngày khác ạ?" (D-1) |
| `ASK_SLOT_PREFERENCE` | "Dạ, anh chị muốn đổi sang ngày nào hoặc buổi nào ạ?" — chỉ dùng sau khi hết vòng |
| `slot_readback_da(slot)` | "Dạ, anh chị đồng ý đổi lịch sang 3 giờ 30 chiều thứ Năm ngày 15 tháng 10 không ạ? Nếu đồng ý, anh chị nói “đồng ý” giúp em ạ." (D-2) |
| `ask_date_again(reason)` | "Dạ, {thứ Hai tuần này đã qua / ngày đó không có trong lịch / em cần ngày cụ thể} ạ. Anh chị muốn đổi sang ngày nào ạ?" |
| `slot_offer_readback(slot)` | "Dạ, chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều. Anh chị đổi sang giờ đó nhé ạ?" (Hình 0) |
| `offer_slots(slots, remaining)` | "Dạ, {thứ + ngày} còn khung 1 là …, khung 2 là …. {Ngoài ra còn N khung khác. }Anh chị chọn khung nào ạ?" |
| `slot_full_for(request)` | "Dạ, {thứ Bảy ngày 17 tháng 10} đã kín lịch. Gần nhất em còn: " + `offer_slots` |
| `slot_readback(slot)` | "Dạ, em xác nhận đổi lịch sang 10 giờ 30 sáng thứ Năm ngày 15 tháng 10 tại {cơ sở}. Anh chị đồng ý chứ ạ?" |
| `SLOT_EXHAUSTED` | "Dạ, em đã đọc hết khung trống {của yêu cầu này}. Anh chị muốn đổi sang ngày khác hay giữ lịch cũ ạ?" (hết khung ở vòng 0–1, §3.2 b/c) |
| `SLOT_NOT_IN_PAGE` | "Dạ, em vừa đọc {n} khung thôi ạ. " + đọc lại trang |
| `SLOT_REFUSE_CHOICE` | "Dạ, anh chị muốn nghe khung khác hay giữ lịch cũ ạ?" (còn khung chưa đọc) |
| `NO_SLOTS_TRANSFER` | "Dạ, hiện em không còn khung trống để đổi. Em xin phép chuyển máy cho nhân viên hỗ trợ anh chị ạ." |
| `ROUNDS_EXHAUSTED_TRANSFER` | "Dạ, em giữ nguyên lịch cũ của anh chị và xin phép chuyển máy cho nhân viên để tìm giờ phù hợp ạ." |
| `rescheduled(slot)` (thay `done("RESCHEDULED")`) | "Dạ, em đã đổi lịch sang 10 giờ 30 sáng thứ Năm ngày 15 tháng 10 ạ. Hẹn gặp anh chị ạ." |
| `SLOT_TWO_AT_A_TIME` (đã có) | "Dạ, em đọc lần lượt hai khung một để anh chị dễ nhớ ạ. " + `offer_slots` (khách xin > 2 khung, M-4) |

### 3.8 Hiểu câu nói lệch: rule → LLM fallback → eval

Áp dụng cho 4 câu hỏi chọn khung (`OFFER_SLOTS`, `SLOT_READBACK`, `SLOT_REFUSE_CHOICE`, `ASK_SLOT_PREFERENCE`), dùng chung cho `RESCHEDULE` và `BOOK`.

**Nguyên tắc:**
1. Rule chạy trước. LLM chỉ được gọi khi rule không cho Dialogue đường đi nào, hoặc rule có kết quả nhưng câu có dấu hiệu nghi ngờ.
2. Mỗi lượt gọi LLM tối đa 1 lần. LLM chỉ trả **nhãn trong tập đóng** kèm span, không bao giờ trả lời thoại.
3. Mọi kết luận của LLM phải có **span là một đoạn liền, nguyên văn** trong câu khách nói. Không có span thì bỏ kết luận.
4. **Prompt không chứa khung giờ, lịch hẹn hay hồ sơ.** Chỉ gửi: transcript, mục đích câu hỏi đang chờ, hành động đang chờ (`RESCHEDULE`/`BOOK`), số khung trên trang đang đọc (1 hoặc 2).
5. **LLM không chọn `slot_id` và không tự đổi ra ngày.** "Thời gian mới" chỉ trả span; parser rule đọc span rồi lọc trên `GET /slots`.
6. **LLM không mở khóa lệnh ghi.** Ở câu chốt, LLM thấy "đồng ý" thì bot chỉ hỏi lại câu có/không; ghi lịch vẫn cần rule nhận đồng ý.
7. LLM tắt, lỗi, hết 3 giây, hoặc trả kết quả không qua được bước kiểm span → giữ kết quả rule (hiện tại là "em chưa hiểu").

#### 3.8.1 Rule: bổ sung trước (bước 7)

| Cách nói | Câu hỏi | Nhãn |
| --- | --- | --- |
| "cái gần nhất", "cái sớm nhất", "cái trước", "cái đầu" | `OFFER_SLOTS` | Chọn khung 1 của trang |
| "cái sau", "cái kia", "cái còn lại" (trang 2 khung) | `OFFER_SLOTS` | Chọn khung 2 của trang |
| "còn gì nữa (không)", "còn không", "có khung nào khác không" | mọi câu hỏi chọn khung | MORE |
| "bận (mất) rồi", "kẹt lịch", "có việc", "phải đi làm", "đi công tác", "không rảnh" ("không tiện / không đi được / không kịp" đã là từ chối vì có "không") | `OFFER_SLOTS`, `SLOT_READBACK` | Từ chối khung vừa đọc. **IE vẫn trả UNCLEAR** như mọi câu kể hoàn cảnh (luật chung T-04 §8, test của Hoàn giữ nguyên); Dialogue gọi `mentions_busy` và xử lý như "không". Câu bận có giờ / buổi / khung ("10 giờ rưỡi tôi bận", "chiều tôi bận") chỉ bỏ các khung đó (§3.8.4) |
| "nào cũng được", "khi nào cũng được", "tùy em", "sớm nhất" | `ASK_SLOT_PREFERENCE`, lượt đầu | ANY (bước 5) |
| Câu hỏi lại: "sao lại…", "…à", "…hả", "…nhỉ", "thật à", "phải không" | `SLOT_READBACK` | Không chọn khung; hỏi lại câu có/không cùng khung. Rule vẫn gắn cờ nghi ngờ (§3.8.2) |
| "tuần sau nữa", "đầu tháng sau", "cuối tháng" | mọi câu hỏi chọn khung | Theo R-30, bước 6 (§3.5.2) |

#### 3.8.2 LLM fallback (bước 9)

**Khi nào gọi** (hàm `route_slot_semantic`, hàm thuần, có test riêng):

| Lý do | Điều kiện |
| --- | --- |
| `SLOT_UNRESOLVED` | Đang ở câu hỏi chọn khung, rule không bắt được khung/tiêu chí/MORE, không có đồng ý hoặc từ chối dứt khoát, không phải bỏ đổi lịch, không có intent Policy (xin nhân viên, lâm sàng, hủy…), và câu không nằm trong tập "đã rõ" ("vâng", "dạ", "không", "được", "khung 1"…) |
| `SLOT_UNSURE` | Rule bắt được khung, nhưng câu có dấu hiệu câu hỏi lại (§3.8.1). Ví dụ "sao lại là thứ Sáu" |

**Nhãn LLM được trả, theo từng câu hỏi:**

| Nhãn | Span | `OFFER_SLOTS` | `SLOT_READBACK` | `SLOT_REFUSE_CHOICE` | `ASK_SLOT_PREFERENCE` | Dialogue làm |
| --- | --- | --- | --- | --- | --- | --- |
| `PICK` (1 hoặc 2) | bắt buộc | ✓ | ✓ | – | – | Số > số khung của trang → bỏ. Hợp lệ → đọc câu chốt khung đó, chờ đồng ý |
| `MORE` | bắt buộc | ✓ | ✓ | ✓ | – | Trang tiếp; hết khung → HẾT KHUNG |
| `NEW_TIME` | bắt buộc, là đoạn nói thời gian | ✓ | ✓ | ✓ | ✓ | Parser rule đọc span. Ra tiêu chí → vòng mới. Không ra → hỏi lại ngày cụ thể (R-30, D-6) |
| `ANY` | bắt buộc | – | – | – | ✓ | Đọc 2 khung sớm nhất |
| `REFUSE` | bắt buộc | ✓ | ✓ | – | – | Như "không" trần (§3.2 c) |
| `KEEP_OLD` | bắt buộc | ✓ | ✓ | ✓ | ✓ | Như "thôi không đổi" (§3.2 d) |
| `CONFIRM` | bắt buộc | – | ✓ | – | – | **Không ghi.** Hỏi lại câu có/không cùng khung |
| `QUESTION`, `AMBIGUOUS` | không bắt buộc | ✓ | ✓ | ✓ | ✓ | Như "chưa rõ" hiện tại |

Nhãn không nằm trong cột của câu hỏi đang chờ → bỏ, coi như LLM không trả gì.

**Hợp nhất** (hàm `merge_slot_semantic`): kết quả LLM mang `Provenance.FALLBACK` và ghi vào đúng trường `slot_choice` / `agreement` mà rule dùng, nên Dialogue không cần nhánh riêng cho LLM. Vòng (§3.2) và bộ đếm §1.1.5 tính như kết quả rule.

**File:** prompt và schema riêng `inference/llm/prompt/slot_reply.py` (`slot_reply_v1`) và `extraction/slot_semantic.py`. Dùng lại `LLMGateway`, hàm kiểm span `_grounded` và cấu hình `semantic_fallback_*` của tầng ngữ nghĩa. **Không sửa prompt `semantic_v5`**, để không phải chạy lại eval Confirm/Cancel. Rà với Hoàn trước khi merge.

#### 3.8.3 Bộ eval (bước 8)

- **`eval/reschedule/cases.csv`**, khoảng 100 câu. Chia `prompt` (câu mẫu cho prompt) và `holdout` (dùng để chấm).
  - Cột: `id, split, group, direction, question_id, page_size, transcript, expect, needs_inference, note`.
  - `expect` là hành vi Dialogue: `PICK:1`, `MORE`, `NEW_TIME:<ngày/buổi>`, `ANY`, `REFUSE_CHOICE`, `KEEP_OLD`, `WRITE`, `REREAD_YESNO`, `ASK_DATE`, `TRANSFER:<lý do>`.
  - `needs_inference=yes`: ý khách phải suy ra từ hoàn cảnh, không có từ khóa nói thẳng. Với các câu này, rule được phép không hiểu, nhưng **không được ghi lịch**.
- **Nhóm câu:** chọn khung theo thứ tự hoặc theo giờ; xin nghe tiếp (có và không có số lượng); từ chối; giữ lịch cũ; đồng ý ở câu chốt; "dạ"; câu hỏi lại; ngày tương đối (bảng §3.5.2); câu không dấu; 26 câu ở §2.1.
- **`scripts/reschedule_eval.py`:** chạy mỗi câu qua Orchestrator thật và `FakeClinicAPI` với seed Phụ lục A, ở đúng câu hỏi đang chờ. Ba chế độ:
  - `--baseline`: chỉ rule, không gọi API.
  - `--route-only`: LLM giả trả `None`, để đếm số lượt sẽ gọi model.
  - `--semantic --repeats 3`: gọi model thật.
  
  So hai lần chạy bằng `scripts/eval_compare.py`.
- **Chỉ số:**
  - Độ đúng trên `holdout`, tách câu rule quyết được và câu cần suy nghĩa.
  - Tỷ lệ lượt gọi model.
  - **Lỗi nguy hiểm, phải bằng 0:** ghi lịch khi khách chưa đồng ý; ghi sai khung.
  - Số câu rule hiểu sai tự tin (chọn khung khi khách đang hỏi lại).
- **Mục tiêu:**
  - Trước bước 9: chạy `--baseline` để có số liệu nền.
  - Sau bước 9: độ đúng `holdout` ≥ 90%, lỗi nguy hiểm = 0, lượt gọi model ≤ 30% số lượt ở câu hỏi chọn khung.

**Kết quả 29-09** (`result/29-09-2026/reschedule/`, bộ câu do Hưng dựng, 151 ca, 121 holdout):

| Lần chạy | Holdout | Rule / cần suy nghĩa | Ghi sai / nhầm khung |
| --- | --- | --- | --- |
| `before-slotfix` | 100/121 (82,6%) | 88/100 · 12/21 | 0 / 0 |
| `after-slotfix` | 113/121 (93,4%) | 97/100 · 16/21 | 0 / 0 |

Đã sửa theo eval: khớp nhiều khung chỉ theo giờ / buổi / thứ thì đọc tối đa 2 khung khớp (IE §5.7, không tự chọn; trước đó bị coi là yêu cầu mới và có ca thành "thứ Tư 30/9 đã kín"); thứ trần không khớp khung nào vừa đọc thì theo R-30; "giờ thứ 2", "giờ / khung còn lại"; "không đi được giờ này" ở bước chọn khung là từ chối khung, không sang hủy; "không" ở câu A/B hỏi lại; "đổi sang giờ đó" là đồng ý; "da" không dấu. Eval Confirm / Cancel của Hoàn chạy trước và sau khi sửa: **giống hệt từng câu**.

Còn fail (8): 5 ca cần LLM (R056, R060, R075, R113, R120 — bước 9); 2 ca lâm sàng "tôi có câu hỏi về bệnh", "tôi cần tư vấn bác sĩ" không được nhận ra ở mọi bước (rule `clinical.py`, báo Hoàn); 1 ca P2 "thứ 5 hoặc thứ 6" (bước 10).

#### 3.8.4 Rà soát thứ tự nhánh (30-09)

IE khớp câu nói trên **mọi khung đã tải**, nên MATCH không có nghĩa là khách chọn khung. Ba handler `_slot_choice`, `_slot_refuse_choice`, `_slot_preference` và câu chốt `_slot_readback` xét MATCH trước nên sai 4 kiểu (không ca nào ghi sai, vì vẫn cần đồng ý ở câu chốt):

| Lỗi | Ví dụ | Trước | Sau |
| --- | --- | --- | --- |
| Bận kèm giờ = chọn giờ đó | "10 giờ rưỡi tôi bận" | Chốt 10 giờ 30 | Bỏ khung đó, đọc khung còn lại của trang |
| Ngày mới khớp 1 khung không tính vòng (R-29) | "8 giờ sáng ngày 20" | Chốt thẳng, `slot_round` không tăng, đổi ngày mãi | Yêu cầu mới, tính vòng; vòng 3 chuyển máy |
| Thứ trần không theo R-30 | "9 giờ thứ Sáu" ở câu hỏi ngày khác | Chốt thứ Sáu 16/10 | "Thứ Sáu 2/10 đã kín" + khung gần nhất |
| Đọc lại khung đã từ chối (V-9) | Không nhận 10 giờ 30, rồi "10 giờ rưỡi" | Chốt lại 10 giờ 30 | "Chưa thấy khung giờ đó" + khung khác |
| `SlotTaken` hết khung mất câu báo | Khung vừa bị đặt, không còn khung | "Em đã đọc hết khung…" (khách tưởng xong) | `SLOT_TAKEN_EXHAUSTED`, `SLOT_TAKEN_ROUNDS_TRANSFER`, `SLOT_TAKEN_NO_SLOTS_TRANSFER` |
| `SlotTaken` mất ngày xin | Xin 20/10 (không đúng giờ) hoặc 17/10 (kín) | Tra lại từ hôm nay → đọc 14/10 | Tra từ ngày xin (`ctx.slot_day`) |

Thứ tự mới ở mọi handler: **bận** (bỏ khung được nhắc) → **chọn** (chỉ khung đã đọc cho yêu cầu hiện tại và chưa bị từ chối, `_picked`) → **thời gian mới** (`_new_request`: vòng, R-30) → MORE / ANY / bỏ đổi. Ở câu chốt, nhắc lại chính khung đang chốt ("3 giờ rưỡi") là chưa trả lời, hỏi lại có/không.

**Quyết định (Hưng 30-09): V-9 áp dụng suốt việc đổi / đặt đang chờ**, không chỉ trong một yêu cầu: `reset_slot_request` không xóa `refused_slot_ids`; chỉ đổi / bỏ hành động mới xóa. Eval sau sửa (`result/30-09-2026/reschedule/after-orderfix`): vẫn 113/121, 0 ghi sai; 3 ca (R042, R045, R140) đổi từ PICK_SLOT sang NEW_TIME, vẫn đạt — ngày ngoài trang giờ tính vòng. Eval Confirm / Cancel / No-answer của Hoàn: giống hệt trước khi sửa.

## 4. Các bước và ưu tiên

| Bước | Ưu tiên | Việc | File chính | Ước lượng | Trạng thái |
| --- | --- | --- | --- | --- | --- |
| 1 | P0 | Kịch bản Hình 0: đúng 1 khung → câu có/không; câu báo "đã đổi lịch"; `speak_datetime` có thứ | `manager.py`, `templates.py` | 0,25 ngày | ✅ 29-09 |
| 2 | P0 | R-25: 2 khung/lượt + phân trang + nhãn MORE; sửa vòng lặp V-9 (loại khung đã từ chối, giữ tiêu chí) | `manager.py`, `slot_choice.py`, `context.py` | 0,5 ngày | ✅ 29-09 |
| 3 | P0 | Câu chốt (D-2): "vâng / ừ / đổi giúp tôi" là đồng ý, "dạ" hỏi lại có nhắc "đồng ý", câu chưa rõ khác hỏi lại có/không; ba nhánh từ chối (Q-4) | `agreement.py`, `manager.py` | 0,25 ngày | ✅ 29-09, cộng M-1..M-4 (§2.1) |
| 4 | P1 | R-29: Gateway `date_from` + `clinic_id` lịch hẹn; báo kín + gợi ý gần ngày xin; vòng + `PATIENT_REQUEST`; tiêu chí mới = vòng mới (V-10); `SlotTaken` giữ tiêu chí | `clinic_gateway.py`, `manager.py`, `context.py` | 0,5 ngày | ✅ 29-09 |
| 5 | P1 | D-1: không tiêu chí → 2 khung sớm nhất + mời ngày khác; nhãn ANY; `ASK_SLOT_PREFERENCE` cho hết vòng / ngày không dùng được | `manager.py`, `slot_choice.py`, `templates.py` | 0,25 ngày | ✅ 29-09 (phần "ngày không dùng được" làm ở bước 6) |
| 6 | P1 | R-30: bảng §3.5.2 phần P1 + hỏi lại có lý do | `slot_choice.py`, `templates.py` | 0,5 ngày | ✅ 29-09 |
| 7 | P1 | Rule cho câu nói lệch §3.8.1 | `slot_choice.py`, `agreement.py`, `manager.py` | 0,25 ngày | ✅ 29-09 |
| 8 | P1 | Bộ eval §3.8.3: `eval/reschedule/cases.csv` + `scripts/reschedule_eval.py`; chạy `--baseline` lấy số liệu nền | `eval/`, `scripts/` | 0,5 ngày | ✅ 29-09: 151 ca, baseline 82,6% → 93,4% sau sửa |
| 9 | P1 | LLM fallback §3.8.2: `route_slot_semantic`, prompt `slot_reply_v1`, `merge_slot_semantic`; chạy eval `--route-only` và `--semantic`; rà với Hoàn | `slot_semantic.py`, `prompt/slot_reply.py`, `extractor.py` | 0,75 ngày | ⏳ |
| 10 | P2 | "sau/trước ngày X", "thứ X hoặc Y", intent "càng sớm càng tốt" | `slot_choice.py`, `intent.py` | nếu còn thời gian | ⏳ |
| 11 | — | Test §5; chạy lại test T-11; tài liệu (IE design §5.6/§5.7/§6.1, kiến trúc §3.2, `session-operations.md`) | tests, docs | 0,5 ngày | ⏳ |
| 12 | — | `make check`; bàn giao Hoàn chạy Phụ lục A trên local + deploy; báo Hoàn (câu đọc lịch có thứ) và Dương (BOOK dùng luồng mới); test ổn mới viết `docs/evidence/t10-reschedule-dialogue.md` | — | — | ⏳ |

Thứ tự: 4 → 5 → 6 → 7 → 8 → 9. Bước 7 đứng trước 9 vì câu rule hiểu sai tự tin thì LLM fallback không được gọi. Bước 8 đứng trước 9 để có số liệu nền so sánh. Nếu không kịp gate W3 (02-10), merge 1–7 trước, còn 8–9 làm sau.

## 5. Test

### 5.1 Test hiện có phải đổi kỳ vọng

| Test | Đổi |
| --- | --- |
| `test_orchestrator.py::test_reference_call_reschedule` | Bỏ lượt "khung 1": sau "đổi sang buổi chiều" bot hỏi có/không luôn (seed mặc định chỉ có 1 khung chiều); `writes` không đổi |
| `test_orchestrator.py::test_reschedule_slot_taken_reoffers_and_needs_new_confirmation` | Số lượt không đổi (D-1: "Tôi muốn đổi lịch" vẫn đọc khung ngay, 2 khung); sau `SLOT_TAKEN` gợi ý lại theo tiêu chí đã nói |
| `test_orchestrator.py::test_refusing_slots_drops_pending_action_without_writing` | "không" trần → `SLOT_REFUSE_CHOICE`; đổi câu thành "thôi không đổi nữa" để giữ ý test, thêm ca "không" trần riêng |
| `tests/transports/http/test_calls.py` (e2e "Cho tôi đổi lịch" → "10 giờ sáng" → "Được") | Luồng không đổi (D-1); kiểm câu đọc khung có lời mời nêu ngày khác |
| `test_agreement.py::test_slot_readback_threshold` | Đổi "vâng" / "ừ" thành AGREE, thêm "đổi giúp tôi" = AGREE; "dạ" giữ UNCLEAR (D-2) |
| Test T-04 / T-05 so chuỗi có ngày giờ | Cập nhật vì `speak_datetime` có thứ |
| `test_context_fsm.py` | Tuần tự hóa các khóa mới; đọc phiên cũ thiếu khóa |
| Test T-11 (`test_inbound_booking_flow.py`, `test_scenario7_edge.py`) | Chạy lại; chỉ đổi số khung đọc (R-25) nếu có assert |

### 5.2 Test mới (`tests/engine/test_reschedule_dialogue.py` + IE)

- Mỗi ca ở Phụ lục A thành một test luồng (Orchestrator thật + `FakeClinicAPI` seed như Phụ lục A, `now` cố định qua `received_at`).
- GC-RES-01..06, GC-DATE-01..05 (đúng ví dụ trong PRD, hôm nay thứ Tư 23/09/2026), GC-CONF-01 cho `SLOT_READBACK`.
- IE: MORE / ANY có dấu và không dấu; bảng §3.5.2 với `now` cố định; nhãn "ngày không rõ".
- Bất biến: mọi lượt `OFFERING_SLOTS` / `SLOT_READBACK` có `presented_slot_ids ⊆ ctx.slot_ids` (SF-02); không lượt nào đọc quá 2 khung; không có câu nào trước `VERIFIED` chứa giờ (SF-03).
- HTTP e2e: cuộc gọi đúng Hình 0 qua `/v1/calls` + `/turn` → `ended=true, outcome=RESCHEDULED`.
- Câu nói lệch: bộ eval §3.8.3, chạy tay, không nằm trong `pytest`. `route_slot_semantic` và `merge_slot_semantic` là hàm thuần nên có unit test riêng: mỗi nhãn × mỗi câu hỏi; span giả; `PICK` quá số khung; `CONFIRM` ở câu chốt không ghi.

## 6. Các điểm contract và PRD không quy định — quyết định

Mỗi mục dưới đây đã đối chiếu contract rev 1.1 và PRD v1.6: **cả hai đều không nói, hoặc nói chưa đủ để code**. Hưng (dev) đã chốt D-1..D-6 ngày 29-09-2026. Phần tình huống, phương án và câu hỏi PM giữ lại để giải thích lý do và để báo PM biết quyết định.

| # | Nội dung | Quyết định |
| --- | --- | --- |
| D-1 | Khách nói "đổi lịch" không nêu thời gian | Gợi ý luôn 2 khung sớm nhất + mời nêu ngày khác |
| D-2 | Đồng ý ở câu chốt đổi lịch | "vâng / ừ / ok / được / đồng ý / đổi giúp tôi" → ghi; "dạ" → hỏi lại, nhắc khách nói "đồng ý" |
| D-3 | 7 ngày từ ngày xin đều trống | Tra tiếp khoảng sau, gợi ý 2 khung sớm nhất sau ngày xin; tính 1 vòng |
| D-4 | Hết sạch slot | Nói lý do rồi chuyển máy `OUT_OF_SCOPE` |
| D-5 | Cách đếm "2 vòng" của R-29 | Tổng 2 ngày; "khung khác" cùng ngày không tính; từ chối không nêu ngày → hỏi lại; "thôi không đổi" vòng 1 giữ lịch và hỏi đến khám, vòng 2 chuyển máy; gợi ý ban đầu (D-1) không tính — §3.2 |
| D-6 | Ngày không dùng được có tính "hiểu sai" không | Lần đầu không tính, lần hai liên tiếp mới tính; ngày đã kín không tính |

### D-1. Khách nói "đổi lịch" nhưng không nêu thời gian: hỏi khách trước hay gợi ý khung luôn?

**Quyết định (Hưng, 29-09-2026):** phương án **B** — gợi ý luôn 2 khung sớm nhất và mời nêu ngày khác. Đã sửa V-12, §3.1, §3.4, §3.7, §4, §5.1, ca 1.1.

**Tình huống:**

> Bot: "…Lịch khám của anh chị là 8 giờ sáng thứ Năm ngày 15 tháng 10… Anh chị có đến khám được không ạ?"
> Khách: "**Tôi muốn đổi lịch.**"

**Contract:** không quy định.
- Bảng 1 chỉ nói đổi lịch kích hoạt khi "bệnh nhân yêu cầu một thời điểm khác".
- Ví dụ đổi lịch ở Hình 0 thì khách tự nêu thời gian ("Tôi đổi sang buổi chiều được không?"), nên không có mẫu cho trường hợp không nêu.
- Ví dụ **đặt lịch** (Hình 0 tab Book) thì bot hỏi trước ("Anh muốn khám khoa nào và khoảng thời gian nào ạ?"), nhưng đó là booking.
- §6.1 để nhóm tự thiết kế hội thoại.

**PRD:** không quy định. R-29 chỉ mô tả trường hợp "khi khách xin đổi sang **một ngày**". R-25 giới hạn tối đa 2 khung mỗi lượt.

**Tài liệu nội bộ:** mô tả T-10 trong `task-breakdown.md` ghi "làm rõ thời gian mong muốn"; sơ đồ `ai-callbot-architecture.md` §3.2 có bước `O_NEED` "Hỏi khoảng thời gian mong muốn". Plan v1 lấy Q-1 (hỏi trước) từ hai chỗ này.

**Phương án:**

| | Bot trả lời | Ưu | Nhược |
| --- | --- | --- | --- |
| A. Hỏi trước | "Dạ, anh chị muốn đổi sang ngày nào hoặc buổi nào ạ?" | Đúng sơ đồ kiến trúc; lọc đúng ý khách ngay từ đầu | Thêm một lượt. Nếu bộ test chấm tự động có ca "tôi muốn đổi lịch" → "khung 1", câu "khung 1" rơi vào câu hỏi thời gian → lệch kịch bản, dễ bị tính "không hiểu" |
| B. Gợi ý luôn + mời chọn ngày khác | "Dạ, lịch trống gần nhất có khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10, khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10. Anh chị chọn khung nào, hoặc muốn đổi sang ngày khác ạ?" | Khách chọn được ngay; không lệch nếu test nói "khung 1"; vẫn "làm rõ thời gian" vì mời nêu ngày khác; đúng R-25 | Hai khung sớm nhất có thể không hợp ý khách, thêm một lượt khi khách nêu ngày |
| C. Gợi ý khung gần lịch cũ | Như B, nhưng 2 khung gần ngày/giờ lịch cũ nhất (15/10 10:30, 14/10 15:00) | Hợp lý với người muốn dời nhẹ | Tự đoán ý khách; khó giải thích; không có căn cứ trong contract/PRD |

**Đề xuất của dev:** **B**.

**Câu hỏi gửi PM:**
> "Khi khách chỉ nói 'tôi muốn đổi lịch' mà không nêu ngày giờ, contract và PRD đều không quy định. Bot nên (A) hỏi khách muốn đổi sang ngày/buổi nào trước, hay (B) đọc luôn 2 khung trống sớm nhất và mời khách chọn hoặc nêu ngày khác? Em đề xuất B vì an toàn hơn với bộ test chấm tự động. Anh có biết bộ test tuần 4 có ca khách chỉ nói 'đổi lịch' rồi chọn 'khung 1' không? Nếu anh không rõ, em hỏi thêm trên #residency-batch03."

### D-2. Ở câu chốt đổi lịch, khách chỉ nói "vâng" / "ừ" / "ok": có ghi đổi lịch không?

**Quyết định (Hưng, 29-09-2026):** "vâng", "ừ", "ok", "được", "đồng ý", "đổi giúp tôi" là đồng ý → ghi. **"dạ" không phải đồng ý** (R-23) → không ghi, hỏi lại và nhắc khách nói "đồng ý". Đây là phương án A trong bảng dưới, cộng câu nhắc cho "dạ". Các chặn ngập ngừng, câu hỏi đuôi, "nhưng…" vẫn chạy trước.

**Tình huống:**

> Bot: "Dạ, em xác nhận đổi lịch sang 3 giờ 30 chiều thứ Năm ngày 15 tháng 10. Anh chị đồng ý chứ ạ?"
> Khách: "**Vâng.**" (hoặc "ừ", "ờ", "ok")

**Contract:**
- §1.1.6 **không** đòi xác nhận rõ ràng cho đổi lịch.
- §1.1.10 đòi "xác nhận rõ ràng" cho **đặt lịch**.
- Hình 0: khách đáp "Được, đổi giúp tôi.". Không có ví dụ "vâng".

**PRD:**
- R-23 (chốt 24/09): đồng ý đánh giá theo danh sách từ tường minh, **ngưỡng cao hơn cho hành động phá hủy**; **"dạ" không bao giờ là đồng ý**.
- GC-CONF-01 (câu đọc lại xác nhận đến khám): chỉ "dạ" → không ghi, hỏi lại câu có/không.
- R-29: đọc lại rồi "chờ khách xác nhận" mới ghi.
- GC-RES-04: chọn giờ nhưng chưa xác nhận → không ghi.

**Chưa rõ:**
- "vâng", "ừ", "ờ", "ok" có nằm trong danh sách từ tường minh không.
- Đổi lịch có phải "hành động phá hủy" không. Đổi lịch giải phóng slot cũ và không hoàn tác được trong cuộc gọi.

**Hiện tại code:** "dạ", "vâng", "ừ" → chưa rõ, hỏi lại; "ok", "được", "đồng ý" → ghi.

**Phương án:**

| | Nội dung | Rủi ro |
| --- | --- | --- |
| A | "vâng / ừ / ok" = đồng ý như "được"; chỉ "dạ" bị loại | Ghi nhầm khi "vâng" chỉ là đáp lễ ("vâng, để tôi xem") — luật ngập ngừng vẫn chặn phần lớn |
| B | Chỉ "được / đồng ý / ok / đổi giúp tôi / chốt đi…" là đồng ý; "vâng / ừ / dạ" → hỏi lại, **câu hỏi lại gợi ý luôn cách trả lời**: "Anh chị nói 'đồng ý' giúp em để em đổi lịch ạ" | Khách hoặc test cứ nói "vâng" → hỏi lại mãi → 2 lần chưa rõ → chuyển máy, bản ghi sai. Câu gợi ý cách trả lời giảm rủi ro này |

**Đề xuất của dev:** **B**. Đúng tinh thần "ngưỡng cao" của R-23, có câu hỏi lại gợi ý cách trả lời.

**Câu hỏi gửi PM:**
> "R-23 nói 'dạ' không bao giờ là đồng ý và hành động phá hủy cần ngưỡng cao hơn. Ở câu chốt đổi lịch, khách chỉ nói 'vâng', 'ừ' hoặc 'ok' thì bot có được ghi đổi lịch không? Và đổi lịch có tính là hành động phá hủy (vì giải phóng slot cũ) không? Em đề xuất: 'ok / được / đồng ý / đổi giúp tôi' là đồng ý; 'vâng / ừ / dạ' thì hỏi lại và nhắc khách nói 'đồng ý'."

**Ngoài T-10, cùng hỏi luôn:** câu đọc lại xác nhận đến khám (T-04, `CONFIRM_READBACK`) hiện tính "**dạ**", "vâng", "ừ" là **đồng ý** và ghi `CONFIRMED` (đã chạy thử 29/09). Như vậy trái R-23 và GC-CONF-01. Cần PM xác nhận T-04 phải sửa theo PRD.

### D-3. Khách xin một ngày, nhưng cả 7 ngày tính từ ngày đó đều không còn khung: làm gì?

**Quyết định (Hưng, 29-09-2026):** phương án **B** — tra tiếp khoảng sau, gợi ý 2 khung sớm nhất sau ngày khách xin, tính là 1 vòng.

**Tình huống** (slot deploy bắt đầu từ 14/10):

> Khách: "**Tôi muốn đổi sang thứ bảy.**" (= thứ Bảy 03/10)
> R-29 → `GET /slots` từ 03/10 đến 10/10 → **rỗng**. Khung trống sớm nhất là 14/10.

**Contract:** chỉ quy định slot phải lấy từ `GET /slots` trong chính cuộc gọi (§1.1.6, SF-02). Không nói khi không có slot.

**PRD:** R-29 và GC-RES-02: ngày xin kín → "báo đã kín và gợi ý tối đa 2 giờ **gần ngày khách xin nhất**, chỉ lấy từ kết quả `GET /slots` của chính cuộc gọi". R-29 cũng quy định chỉ tìm "từ ngày đó đến 7 ngày sau". Hai ý này hợp nhau khi trong 7 ngày còn khung; khi 7 ngày trống thì không còn gì để gợi ý và PRD không nói tiếp.

**Phương án:**

| | Bot trả lời | Ghi chú |
| --- | --- | --- |
| A | "Dạ, từ thứ Bảy 3/10 đến 10/10 đã kín lịch. Anh chị muốn đổi sang ngày khác không ạ?" | Đúng từng chữ R-29 (không tra thêm); khách phải đoán ngày tiếp; tính là 1 vòng |
| B | "Dạ, từ thứ Bảy 3/10 đến 10/10 đã kín lịch. Gần nhất em còn 3 giờ chiều thứ Tư 14/10 và 10 giờ 30 sáng thứ Năm 15/10. Anh chị chọn khung nào ạ?" | Bot gọi thêm `GET /slots` cho khoảng sau; khung vẫn từ `GET /slots` trong cuộc gọi nên không vi phạm SF-02; khách chọn được ngay |
| C | Chuyển máy nhân viên | Sớm quá, khách chưa được gợi ý gì |

**Đề xuất của dev:** **B**, tính là 1 vòng.

**Câu hỏi gửi PM:**
> "R-29 bảo tra từ ngày khách xin đến 7 ngày sau, nếu ngày đó kín thì gợi ý 2 giờ gần nhất trong kết quả đó. Nếu cả 7 ngày đều trống (ví dụ khách xin thứ Bảy 3/10 mà lịch trống sớm nhất là 14/10) thì bot nên (A) báo kín và hỏi ngày khác, hay (B) tra tiếp khoảng sau và gợi ý 2 khung sớm nhất sau ngày khách xin? Em đề xuất B."

### D-4. Mock không còn slot trống nào: chuyển máy với lý do gì?

**Quyết định (Hưng, 29-09-2026):** `OUT_OF_SCOPE`, bot nói lý do trước khi chuyển.

**Tình huống:** khách muốn đổi lịch, bot tra `GET /slots` hết các khoảng mà không có slot nào.

**Contract:**
- Bảng 2: `TRANSFERRED` phải kèm `transfer_reason` trong enum Phụ lục A (`IDENTITY_FAILED · PATIENT_NOT_FOUND · OUT_OF_SCOPE · CLINICAL_QUESTION · NOT_UNDERSTOOD · PATIENT_REQUEST · SYSTEM_ERROR`).
- §2.1: với cuộc gọi **đi**, harness chấm bản ghi lịch hẹn, trong đó có `transfer_reason`. Nếu bộ test có ca này thì chọn sai lý do là fail.

**PRD:**
- R-29 dùng `PATIENT_REQUEST` khi khách từ chối hết 2 vòng gợi ý.
- R-24 (bảng ánh xạ tình huống sang lý do) vẫn là "Đề xuất", chưa chốt.
- Không có dòng nào cho trường hợp hết slot.

**Hiện tại code:** `OUT_OF_SCOPE`, câu chuyển máy chung không nói lý do.

**Phương án:**
- **A. `OUT_OF_SCOPE`:** việc này bot không làm được.
- **B. `PATIENT_REQUEST`:** khách vẫn muốn đổi, cần người thật; đồng bộ với R-29.
- **C. `SYSTEM_ERROR`:** không hợp, vì hệ thống không lỗi.

**Đề xuất của dev:** **A**, và bot nói rõ lý do trước khi chuyển ("hiện em không còn khung trống để đổi…").

**Câu hỏi gửi PM:**
> "Khi khách muốn đổi lịch mà Clinic Mock không còn slot trống nào, bot chuyển nhân viên với transfer_reason nào: OUT_OF_SCOPE hay PATIENT_REQUEST? Contract và PRD đều không có dòng cho trường hợp này, mà harness chấm transfer_reason trên bản ghi cuộc gọi đi."

### D-5. "Tối đa 2 vòng" của R-29 tính như thế nào?

**Quyết định (Hưng, 29-09-2026):** a1 (tổng 2 ngày), b không tính, c hỏi lại, d theo đề xuất, e không tính. Luật đầy đủ ở §3.2.

**PRD:**
- R-29: "Khách từ chối và nêu ngày khác thì bot tra lại cho ngày mới, **tối đa 2 vòng**. … Hết 2 vòng mà không chọn được giờ thì giữ nguyên lịch cũ, không ghi gì, và chuyển nhân viên với `PATIENT_REQUEST`."
- GC-RES-05: "Khách từ chối 2 vòng gợi ý → lịch cũ giữ nguyên, chuyển nhân viên với `PATIENT_REQUEST`."

**Contract:** không có khái niệm vòng.

**Chưa rõ**, ví dụ trên dữ liệu deploy:

| # | Câu hỏi con | Ví dụ |
| --- | --- | --- |
| a | "2 vòng" là khách được xin **tổng cộng 2 ngày**, hay ngày đầu **cộng thêm 2 lần** tra lại (tổng 3 ngày)? | Khách xin 14/10 → không chọn → xin 19/10 → không chọn → bot chuyển máy luôn (a1), hay cho xin thêm ngày thứ ba (a2)? |
| b | Xin "khung khác" **trong cùng ngày** có tính thêm vòng không? | Xin 15/10 → nghe 10:30, 15:30 → "khung khác" → hết khung 15/10 |
| c | Khách từ chối nhưng **không nêu ngày mới** ("không được") thì có tính vòng không, bot hỏi ngày khác hay chuyển máy? | Xin 15/10 → "không được" |
| e | Lượt bot gợi ý 2 khung sớm nhất khi khách **chưa nêu thời gian** (D-1) có tính là vòng 1 không? | "Tôi muốn đổi lịch" → bot đọc 14/10, 15/10 → "không, ngày 19 thì sao": đây là vòng 1 hay vòng 2? |
| d | Khách nói "**thôi không đổi nữa**" giữa chừng: giữ lịch cũ rồi hỏi tiếp có đến khám không (cuộc gọi tiếp tục), hay chuyển nhân viên `PATIENT_REQUEST` như hết vòng? | Xin 15/10 → "thôi không đổi nữa" |

**Đề xuất của dev** (đã được chọn, xem §3.2):
- a1: tổng 2 ngày.
- b: không tính vòng mới, cùng một vòng.
- c: hỏi "anh chị muốn ngày khác không"; nếu là vòng 2 thì chuyển máy.
- d: vòng 1 thì giữ lịch cũ và hỏi lại có đến khám không; vòng 2 thì chuyển `PATIENT_REQUEST`.
- e: không tính; vòng 1 bắt đầu khi khách nêu thời gian đầu tiên.

**Câu hỏi gửi PM:**
> "R-29 nói tối đa 2 vòng rồi chuyển PATIENT_REQUEST. Em cần chốt 4 điểm: (a) 2 vòng là khách được xin tổng cộng 2 ngày, hay ngày đầu cộng 2 lần tra lại? (b) Xin 'khung khác' trong cùng ngày có tính vòng mới không? (c) Khách chỉ nói 'không được' mà không nêu ngày mới thì bot hỏi ngày khác hay tính luôn là hết vòng? (d) Khách nói 'thôi không đổi nữa' giữa chừng thì giữ lịch cũ và hỏi lại có đến khám không, hay chuyển nhân viên? Đề xuất của em: (a) tổng 2 ngày, (b) không tính, (c) hỏi ngày khác, (d) vòng 1 thì hỏi lại đến khám, vòng 2 thì chuyển."

### D-6. Hỏi lại vì ngày khách nói không dùng được: có tính vào "2 lần không hiểu" không?

**Quyết định (Hưng, 29-09-2026):** phương án **C** — lần đầu không tính, lần thứ hai liên tiếp mới tính. Khách xin ngày đã kín không tính là hiểu sai (giới hạn bằng 2 vòng của R-29).

**Tình huống** (hôm nay thứ Ba 29/09):

> Khách: "Tôi muốn đổi sang **thứ Hai**." (thứ Hai tuần này 28/09 đã qua)
> Bot (R-30): "Dạ, thứ Hai tuần này đã qua rồi ạ. Anh chị muốn đổi sang ngày nào ạ?"
> Khách: "**Tháng sau** đi." (quá rộng) → bot hỏi lại lần nữa.

Các loại ngày không dùng được: ngày đã qua, ngày không tồn tại ("31 tháng 9"), ngày quá rộng ("tháng sau", "giữa tháng").

**Contract:**
- §1.1.5: chuyển máy sau "**hai lần hiểu sai** liên tiếp"; "không được đoán".
- §1.1.7: một lượt im lặng không tính là hiểu sai.
- §5: chấm cả "tỷ lệ phục hồi sau một lần hiểu sai".

**PRD:**
- R-30: ngày đã qua hoặc không quy đổi chắc chắn → hỏi lại, không đoán. **Không nói có đếm hay không.**
- GC-XFER-05: im lặng, xin nhắc lại, giữ máy không đếm.
- GC-OOS-02: câu lạc đề thì đếm.
- R-31: IE timeout thì đếm.

**Chưa rõ:**
- Bot đã hiểu câu nhưng ngày không dùng được: có phải "hiểu sai" không?
- Cùng loại: khách xin ngày **đã kín** có tính không? Plan v1 Q-3 đang chọn **không tính**, vì "không có hàng" khác với "hiểu sai".

**Phương án:**
- **A. Không bao giờ tính:** thân thiện, nhưng khách cứ nói "tháng sau" thì hỏi mãi.
- **B. Tính ngay từ lần đầu:** hai lần ngày mơ hồ là chuyển máy, hơi khắt khe.
- **C. Lần đầu không tính, lần hai liên tiếp mới tính:** giống cách xử lý hỏi lại ở các bước khác.

**Đề xuất của dev:** **C** cho ngày không dùng được. Ngày đã kín thì không tính (vẫn giới hạn bằng 2 vòng của R-29).

**Câu hỏi gửi PM:**
> "Khi khách nói ngày bot không dùng được (ngày đã qua, ngày không tồn tại, hay quá rộng như 'tháng sau'), R-30 bảo hỏi lại nhưng không nói lượt đó có tính vào 'hai lần hiểu sai' của §1.1.5 không. Em đề xuất lần đầu không tính, lần thứ hai liên tiếp mới tính. Còn khách xin ngày đã kín thì không tính là hiểu sai. Anh thấy được không?"

## 7. Ngoài phạm vi và rủi ro

- **LLM ở bước chọn khung:** hiện tầng ngữ nghĩa không chạy ở 4 câu hỏi chọn khung, nên phần này thuần rule. Thiết kế fallback ở §3.8.2 (bước 9). Rủi ro: thêm độ trễ ở lượt gọi model (timeout 3 giây); khóa OpenAI chỉ dùng được `gpt-6-luna`.
- **Booking inbound (T-11)** dùng chung code slot: R-25, câu chốt, MORE, vòng áp dụng cho cả `BOOK`. Câu báo và lời "đổi lịch" chỉ dùng cho `RESCHEDULE`. Gateway `date_from` tùy chọn nên hành vi tìm slot của booking không đổi.
- **`speak_datetime` thêm thứ** đổi mọi câu đọc lịch (T-04, T-05): đúng GC-DATE-05 nhưng nhiều test so chuỗi phải cập nhật.
- **Bộ lọc đầu ra R-19** (Output Guard, nhánh `feature/r01-output-guard`) không thuộc T-10; T-10 giữ mọi câu có giờ đi qua các hàm trong `templates.py`.
- **Retry lỗi tạm thời** khi ghi đổi lịch: đã có ở T-12.
- **"sớm hơn / muộn hơn"** chỉ là MORE, không lọc theo giờ tương đối.

## Phụ lục A — Bộ ca test thủ công

**Chuẩn bị:**
- Reset Clinic Mock trước **mỗi** ca.
- Cuộc gọi outbound `apt_00418`. Hai lượt xác minh: `Trần Thị Bình`, `21 tháng 6 năm 1990`.
- Lịch cũ: 8 giờ sáng 15/10, Nội tổng quát.
- Slot trống: T4 14/10 15:00 · T5 15/10 10:30, 15:30 · T6 16/10 09:00, 14:00 · T2 19/10 10:00, 15:30 · T3 20/10 08:00, 14:00 · T4 21/10 09:00, 15:00. Không có slot thứ 7, chủ nhật hay trước 14/10.
- Mục 8 tính theo hôm nay là thứ Ba 29/09/2026.

Cột "Hiện tại" là kết quả chạy ngày 29-09 trên nhánh T-10 (LLM tắt). Cột "Đúng (v2)" là tiêu chí nghiệm thu.

### A.1 Không nêu thời gian / Hình 0

| Ca | Khách nói (sau xác minh) | Hiện tại | Đúng (v2) |
| --- | --- | --- | --- |
| 1.1 | `Tôi muốn đổi lịch` | Đọc 3 khung đầu | Đọc 2 khung sớm nhất (15:00 thứ Tư 14/10, 10:30 thứ Năm 15/10) + "hoặc muốn đổi sang ngày khác"; `OFFERING_SLOTS` (D-1) |
| 1.2 | `Tôi đổi sang chiều ngày 14 tháng 10 được không?` → `Được, đổi giúp tôi.` | Hỏi "chọn khung nào" với 1 khung, rồi "em chưa hiểu"; không ghi | Câu có/không với 15:00 thứ Tư 14/10 → `RESCHEDULED`, `slot_91d2`, "em đã đổi lịch sang …" |
| 1.3 | `Tôi đổi sang buổi chiều được không?` | 3 khung chiều | 2 khung chiều + "còn 4 khung khác" |

### A.2 Từ chối và vòng

| Ca | Khách nói | Hiện tại | Đúng (v2) |
| --- | --- | --- | --- |
| 2.1 | `Tôi muốn đổi sang ngày 15 tháng 10` → `không` | Bỏ đổi lịch | Ngày 15/10 chỉ có 2 khung, cả hai đã đọc → hỏi "đổi sang ngày khác hay giữ lịch cũ" (§3.2 c), không ghi |
| 2.2 | `…ngày 15 tháng 10` → `khung 1` → `không, khung khác` | Bỏ đổi lịch | Bỏ 10:30, câu có/không với 15:30 cùng ngày, pending vẫn `RESCHEDULE` |
| 2.3 | `…ngày 15 tháng 10` → `khung 1` → `không, tôi muốn đổi khung khác` → `khung 1` → `không, tôi muốn đổi khung khác` → `khung 1` → `không, tôi muốn đổi khung khác` | Đọc lại cả danh sách, gồm khung vừa từ chối, lặp vô hạn | Không đọc lại khung đã từ chối; hết khung 15/10 → hỏi "đổi sang ngày khác hay giữ lịch cũ" (vẫn vòng 1, D-5b/c); "khung 1" sau đó không phải ngày → hỏi lại / đếm chưa hiểu; không lặp vô hạn; không ghi `RESCHEDULED` |
| 2.4 | `Tôi muốn đổi sang ngày 14 tháng 10` → `không được, ngày 19 tháng 10 thì sao` → `không, thôi` | Vòng 2 mở đầu "có nhiều khung giờ phù hợp"; cuối cùng quay lại hỏi đến khám | Vòng 1: 14/10 → vòng 2: 19/10 (10:00, 15:30) → `TRANSFERRED/PATIENT_REQUEST`, `writes` chỉ có `TRANSFERRED` |
| 2.5 | `…ngày 15 tháng 10` → `khung 1` → `thôi không đổi nữa` | Giữ lịch cũ, không ghi | Vòng 1 → giữ lịch cũ, hỏi lại có đến khám không (D-5d); như hiện tại |
| 2.6 | `Tôi muốn đổi sang ngày 14 tháng 10` → `không được, ngày 19 tháng 10 thì sao` → `không, ngày 21 đi` | Chưa chạy | Ngày thứ ba → **không tra 21/10**, giữ lịch cũ, `TRANSFERRED/PATIENT_REQUEST` (D-5a) |
| 2.7 | `Tôi muốn đổi lịch` → `không, ngày 19 thì sao` → `không, ngày 21 đi` → `khung 1` → `đồng ý` | Chưa chạy | Lượt đầu chưa tính vòng (D-5e) → 19/10 là vòng 1, 21/10 là vòng 2 (09:00, 15:00) → `RESCHEDULED slot_b509` |
| 2.8 | `Tôi muốn đổi sang ngày 14 tháng 10` → `không được` → `ngày 20 tháng 10` | Chưa chạy | "không được" → hỏi "đổi sang ngày khác hay giữ lịch cũ", không ghi (D-5c) → 20/10 là vòng 2 (08:00, 14:00) |
| 2.9 | `Tôi muốn đổi sang ngày 14 tháng 10` → `không được, ngày 19 tháng 10 thì sao` → `thôi không đổi nữa` | Chưa chạy | Vòng 2 → giữ lịch cũ, `TRANSFERRED/PATIENT_REQUEST` (D-5d) |
| 2.10 | `Tôi muốn đổi sang ngày 15 tháng 10` → `khung khác` → `ngày 19 tháng 10` | Chưa chạy | "khung khác" không tính vòng (D-5b): hết khung 15/10 → hỏi ngày khác → 19/10 là vòng 2, đọc 10:00, 15:30 (không chuyển máy) |

### A.3 Ngày kín / ngoài khoảng

| Ca | Khách nói | Hiện tại | Đúng (v2) |
| --- | --- | --- | --- |
| 3.1 | `Tôi muốn đổi sang ngày 17 tháng 10` | Im lặng đọc khung 14–15/10 | "thứ Bảy ngày 17 tháng 10 đã kín" + 10:00 và 15:30 thứ Hai 19/10 |
| 3.2 | `Tôi muốn đổi sang thứ bảy` | Như 3.1 | "thứ Bảy ngày 3 tháng 10 đã kín"; khoảng 03–10/10 trống → D-3 (gợi ý 14/10 15:00, 15/10 10:30) |
| 3.3 | `Tôi muốn đổi sang ngày mai` | Như 3.1 | "ngày mai thứ Tư 30/9 đã kín"; còn lại như 3.2 |
| 4.1 | `Tôi muốn đổi sang ngày 30 tháng 11` | Như 3.1 | Tìm từ 30/11: báo kín / hỏi ngày khác; không đọc khung tháng 10 như thể đúng ý |

### A.4 Đồng ý ở câu chốt

Mở đầu chung: `Tôi muốn đổi sang ngày 15 tháng 10` → `khung 2` → *(câu chốt)*. Mỗi dòng một cuộc gọi.

| Ca | Câu chốt | Hiện tại | Đúng (v2) |
| --- | --- | --- | --- |
| 5.1 | `dạ` | Câu A/B | Không ghi; hỏi lại và nhắc nói "đồng ý" (GC-CONF-01, D-2) |
| 5.2 | `vâng` | Câu A/B | Đồng ý → `RESCHEDULED slot_b502`, câu báo "đã đổi lịch" (D-2) |
| 5.3 | `ừ` | Câu A/B (chạy qua hàm IE) | Như 5.2 (D-2) |
| 5.4 | `đổi giúp tôi` | "em chưa hiểu" (tính 1 lần) | Đồng ý → `RESCHEDULED slot_b502` |
| 5.5 | `ok` | Ghi đúng, câu báo "đã đặt lịch" | Ghi, câu báo "đã đổi lịch sang …" |
| 5.6 | `chắc là được` | Không ghi, câu A/B | Không ghi, câu có/không |
| 5.7 | `được không em?` | Như 5.6 | Như 5.6 |
| 5.8 | `được nhưng để tôi hỏi vợ đã` | Như 5.6 | Như 5.6 |

### A.5 Câu chốt và câu báo

| Ca | Khách nói | Hiện tại | Đúng (v2) |
| --- | --- | --- | --- |
| 6.1 | `…ngày 15 tháng 10` → `khung 1` → `được` | "Em chốt khung 10 giờ 30 sáng ngày 15 tháng 10…"; "em đã đặt lịch…" | "…10 giờ 30 sáng thứ Năm ngày 15 tháng 10…" (không khoa); "Em đã đổi lịch sang 10 giờ 30 sáng thứ Năm ngày 15 tháng 10 ạ"; `slot_b501` |

### A.6 Hai khung mỗi lượt và các khung sau

Khung chiều theo thứ tự: trang 1 = 14/10 15:00, 15/10 15:30 · trang 2 = 16/10 14:00, 19/10 15:30 · trang 3 = 20/10 14:00, 21/10 15:00.

| Ca | Khách nói | Hiện tại | Đúng (v2) |
| --- | --- | --- | --- |
| 7.1 | `Tôi đổi sang buổi chiều được không?` → `khung khác` → `khung khác` → `khung khác` | 3 khung; "chưa hiểu"; lần 2 `TRANSFERRED/NOT_UNDERSTOOD` | Trang 1 + "còn 4" → trang 2 + "còn 2" → trang 3 → `SLOT_EXHAUSTED` hỏi ngày khác hay giữ lịch cũ; không tính "không hiểu" |
| 7.2 | `…buổi chiều…` → `khung 3` | Chọn 16/10 14:00 (vì đang đọc 3) | "em vừa đọc 2 khung" + đọc lại trang 1; NEUTRAL; không tự chọn |
| 7.3 | `…buổi chiều…` → `còn khung nào khác không` | "chưa hiểu" | Trang 2 |
| 7.4 | `…buổi chiều…` → `nghe tiếp` | "chưa hiểu" | Trang 2 |
| 7.5 | `…buổi chiều…` → `giờ khác được không` | "chưa hiểu" | Trang 2 |
| 7.6 | `…buổi chiều…` → `khung khác` → `khung 1` | Hỏng từ "khung khác" | "khung 1" = 16/10 14:00 (thứ tự theo trang hiện tại) |
| 7.7 | `…buổi chiều…` → `khung khác` → `thôi lấy 3 giờ chiều ngày 14` | Chưa chạy tới | Chốt 14/10 15:00 (khung đã đọc ở trang trước, có trong `GET /slots`) |

### A.7 Ngày tương đối (hôm nay thứ Ba 29/09)

Với mọi câu quy đổi được, bot phải nêu **thứ + ngày** đã hiểu. Trước 14/10 không có slot, nên các ca 8.1–8.6 đi tiếp nhánh "kín" (A.3).

| Ca | Khách nói | Đúng (v2) | Hiện tại |
| --- | --- | --- | --- |
| 8.1 | `Tôi muốn đổi sang mốt` | thứ Năm 01/10 | Rỗng → khung 14/10 |
| 8.2 | `…sang thứ 7 này` | thứ Bảy 03/10 | Chỉ "thứ 7" |
| 8.3 | `…sang chủ nhật` | Chủ nhật 04/10 | Khung 14/10 |
| 8.4 | `…sang cuối tuần` | 03–04/10 | Rỗng |
| 8.5 | `…sang sáng mai` | sáng thứ Tư 30/09 | Khung 14/10 |
| 8.6 | `…sang chiều thứ 5 tuần sau` | chiều thứ Năm 08/10 | Khung 14/10 |
| 8.7 | `…sang tuần sau nữa` | 12–18/10 → 14/10 15:00, 15/10 10:30 | Rỗng |
| 8.8 | `…sang ngày 20` | thứ Ba 20/10 (08:00, 14:00) | Đúng khung, không nêu thứ |
| 8.9 | `…sang 20/10` | như 8.8 | như 8.8 |
| 8.10 | `…sang sau ngày 20` | từ 20/10 (P2) | Hiểu thành đúng ngày 20 |
| 8.11 | `…sang thứ 5 hoặc thứ 6` | 15/10 và 16/10 (P2) | Chỉ thứ 5 |
| 8.12 | `…sang ngày sớm nhất có thể` | ANY → 2 khung sớm nhất | 3 khung sớm nhất |
| 8.13 | `Đổi cho tôi càng sớm càng tốt` | Nhận ý định đổi lịch + ANY (P2) | "chưa hiểu" |
| 8.14 | `toi muon doi sang ngay 15 thang 10` | thứ Năm 15/10 | Đúng |
| 8.15 | `…sang thứ 2` | Đã qua (28/09) → hỏi lại | Tự hiểu 19/10 |
| 8.16 | `…sang hôm qua` | Hỏi lại | Khung 14/10 |
| 8.17 | `…sang ngày 31 tháng 9` | Ngày không tồn tại → hỏi lại | Khung 14/10 |
| 8.18 | `…sang tháng sau` | Quá rộng → hỏi lại | Khung 14/10 |
| 8.19 | `…sang đầu tháng sau` | Quá rộng → hỏi lại | Khung 14/10 |
| 8.20 | `…sang giữa tháng 10` | Quá rộng → hỏi lại | Khung 14/10 |

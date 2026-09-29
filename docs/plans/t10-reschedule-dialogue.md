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

## 1. Thay đổi so với v1 — vấn đề → hướng sửa

| # | Mục v1 | Vấn đề | Hướng sửa trong v2 |
| --- | --- | --- | --- |
| V-1 | Q-2: "vâng / dạ / ừ" ở `SLOT_READBACK` là đồng ý | PRD R-23 (chốt 24-09): **"dạ" không bao giờ là đồng ý**, ngưỡng cao hơn cho hành động phá hủy; GC-CONF-01: "dạ" → không ghi, hỏi lại câu có/không | **Bỏ Q-2.** Giữ ngưỡng hiện tại của `SLOT_READBACK` ("dạ", "vâng", "ừ" một mình = UNCLEAR). "vâng" / "ừ" chờ PM (§6 D-2). Thêm cụm hành động tường minh: "đổi giúp tôi", "đổi giúp em", "đổi luôn", "đổi sang giờ đó" (chỉ bản có dấu, vì "doi" = "đợi"). UNCLEAR ở câu chốt → hỏi lại **câu có/không**, không dùng câu A/B `t.slot_choice` |
| V-2 | Q-5: đọc tối đa 3 khung, phân trang | PRD R-25 (chốt): **tối đa 2 khung mỗi lượt** | `MAX_SLOTS_PRESENTED = 2`. Giữ phân trang: nói "còn N khung khác", "khung khác / còn khung nào / nghe tiếp / giờ khác" đọc trang tiếp, không lặp khung đã đọc (§3.4) |
| V-3 | §3.2.2 luật gợi ý 5 bậc, cửa sổ 14 ngày, `OUT_OF_WINDOW` | PRD R-29 (chốt 22-09) định nghĩa khác: tìm từ **ngày khách xin đến +7 ngày**, cùng `clinic_id` với lịch hiện tại; ngày còn giờ → đọc ≤2 giờ của ngày đó; ngày kín → **báo kín** + ≤2 giờ **gần ngày xin nhất**; tối đa **2 vòng**, hết vòng → **giữ lịch cũ, chuyển `PATIENT_REQUEST`** | **Bỏ luật 5 bậc và `OUT_OF_WINDOW`.** Gateway nhận ngày bắt đầu (§3.3), xếp gợi ý theo khoảng cách tới ngày xin. Thêm bộ đếm vòng (§3.2). Vì tìm thẳng theo ngày xin nên không còn khái niệm "ngoài cửa sổ 14 ngày" |
| V-4 | AC-12: không còn slot → `OUT_OF_SCOPE` | Câu thoại hiện là câu chuyển máy chung, không nói lý do | Nói lý do trước khi chuyển (`NO_SLOTS_TRANSFER`). Mã lý do chờ PM (§6 D-4), mặc định giữ `OUT_OF_SCOPE` |
| V-5 | AC-5: chỉ đọc ngày tuyệt đối cho "mai / kia / tuần sau" | PRD R-30 (chốt 22-09): thêm "mốt", "thứ X này", "cuối tuần", "đầu tuần sau"; **ngày đã qua / không quy đổi chắc chắn → hỏi lại**; **mọi câu xác nhận có thứ + ngày/tháng + giờ** (GC-DATE-05) | Bảng quy đổi §3.5.2; nhãn "ngày không rõ" để Dialogue hỏi lại; `speak_datetime` đọc thêm thứ |
| V-6 | `slot_readback`: "đổi lịch sang {giờ} {ngày} tại {cơ sở}" (có ý đọc khoa theo R-29) | Contract không nhắc khoa cho đổi lịch (Hình 0 chỉ đọc ngày + giờ). **Quyết định của dev (Hưng, 29-09): theo contract, không đọc khoa** | Câu chốt: giờ + **thứ** + ngày/tháng (+ cơ sở, R-19 cho phép). Không đọc khoa |
| V-7 | G-9: kiểm tra `status` / `new_slot_id` trước khi báo thành công | T-12 đã làm ở Gateway (`clinic_gateway.reschedule` → `_status_is("RESCHEDULED", new_slot_id=new_slot_id)`) | Chỉ còn: câu báo "em đã **đổi** lịch sang …" (thay "đã **đặt** lịch"), dựng từ slot đã ghi |
| V-8 | Base `7f6c4a1`, `dialogue/manager.py` một file, Gateway một cửa sổ 14 ngày | `main` đã đổi: `questions.ask` thay `_ask`; Gateway quét tối đa 5 cửa sổ × 14 ngày từ `now` (T-11); booking inbound **dùng chung** `_offer_slots` / `_slot_choice` / `_slot_readback` | Code trên `main` mới. Mọi thay đổi luồng slot chạy lại test T-11 (`test_inbound_booking_flow.py`, `test_scenario7_edge.py`, `tests/engine/tools/test_booking_write.py`). Tham số mới của Gateway là tùy chọn, booking giữ hành vi cũ |
| V-9 | *(không có)* | **Lỗi mới — vòng lặp vô hạn** (ca 2.3): ở câu chốt, "không, tôi muốn đổi khung khác" → `_slot_readback` gọi `_present(ctx, ctx.slots)` → đọc lại **toàn bộ** danh sách, **mất tiêu chí**, **có cả khung vừa từ chối**, và tính là "hiểu" → lặp mãi không chuyển máy | Loại khung đã từ chối, giữ tiêu chí, đếm vòng (§3.2, §3.4) |
| V-10 | *(không có)* | **Lỗi mới** (ca 2.4): ở `OFFER_SLOTS`, "không được, ngày 19 tháng 10 thì sao" → IE trả AMBIGUOUS → bot mở đầu bằng "Dạ, có nhiều khung giờ phù hợp", sai ngữ cảnh; không đếm vòng | Tiêu chí thời gian **mới** ở `OFFER_SLOTS` / `SLOT_READBACK` = **vòng mới** → `_offer_slots(tiêu chí mới)` (§3.4) |
| V-11 | *(không có)* | **Lỗi IE mới**: "sau ngày 20" hiểu thành đúng ngày 20; "thứ 5 hoặc thứ 6" chỉ lấy thứ 5; "Đổi cho tôi càng sớm càng tốt" không nhận ra ý định đổi lịch | P2 (§3.5.2) |
| V-12 | Q-1: hỏi khoảng thời gian trước | Contract và PRD đều không yêu cầu hỏi trước (chỉ có trong task-breakdown và sơ đồ kiến trúc). Rủi ro harness ("tôi muốn đổi lịch" → "khung 1") | Chờ PM chốt §6 D-1 (hỏi trước hay gợi ý luôn; dev đề xuất gợi ý luôn). Nếu giữ hỏi trước thì dùng biện pháp v1: ở `ASK_SLOT_PREFERENCE`, câu chỉ có thứ tự ("khung 1", "cái đầu") → coi như "nào cũng được", đọc 2 khung sớm nhất |

**Giữ nguyên từ v1:** Q-1 (hỏi khoảng thời gian khi yêu cầu không có thời gian — tạm giữ, chờ §6 D-1), Q-3 (xin giờ không có ≠ "không hiểu"), Q-4 (ba nhánh từ chối ở câu chốt), Q-6 (`ASK_SLOT_PREFERENCE` báo `AWAITING_INTENT`, chưa `set_pending`), G-7 (giữ tiêu chí sau `SLOT_TAKEN`, khớp GC-RES-06), AC-10 (đổi slot xóa bằng chứng cũ), AC-13 (các lớp lỗi ghi), AC-16 (inbound "đổi lịch" → `OUT_OF_SCOPE`).

## 2. Hiện trạng đã kiểm (29-09-2026)

Chạy Orchestrator thật trên nhánh T-10 (đã merge `main`), `clinic_mock_sim` seed giống Clinic Mock deploy (Phụ lục A), LLM fallback tắt. Chi tiết từng ca ở Phụ lục A; tóm tắt:

| Nhóm | Ca | Hiện tại | Hệ quả chấm điểm |
| --- | --- | --- | --- |
| Hình 0 | 1.2 | Một khung khớp vẫn hỏi "chọn khung nào"; "Được, đổi giúp tôi." → "em chưa hiểu" | Kết thúc `SCHEDULED` → fail |
| Không nêu thời gian | 1.1 | Đọc ngay 3 khung đầu | Trái Q-1, R-25 |
| Số khung | 1.3, 7.1 | Đọc 3 khung; "khung khác" → "chưa hiểu", lần 2 → `TRANSFERRED/NOT_UNDERSTOOD` | Chuyển máy sai lý do |
| Từ chối | 2.1, 2.2 | "không" / "không, khung khác" → bỏ luôn đổi lịch | Đoán ý khách (§1.1.5) |
| Từ chối | 2.3 | Vòng lặp vô hạn (V-9) | Cuộc gọi không kết thúc |
| Vòng | 2.4 | Không đếm vòng; hết 2 vòng → quay lại hỏi đến khám thay vì `PATIENT_REQUEST` | Trái GC-RES-05 |
| Ngày kín / ngoài khoảng | 3.1–3.3, 4.1 | Lọc rỗng → **im lặng** đọc khung 14/10 như thể đúng ý (`filter_slots(...) or slots`) | Trái GC-RES-02 |
| Đồng ý | 5.1–5.8 | "dạ/vâng/ừ" → câu A/B; "đổi giúp tôi" → "chưa hiểu" (tính 1 lần); "ok" → ghi | Câu hỏi lại sai dạng; một cụm đồng ý rõ bị tính "không hiểu" |
| Câu chốt / báo | 6.1 | Thiếu thứ; câu báo "đã **đặt** lịch" | Trái GC-DATE-05, Hình 0 |
| Ngày tương đối | 8.1–8.20 | "mốt", "cuối tuần", "tháng sau"… → rỗng; "thứ 7 này" = mọi thứ 7; "thứ 2" (đã qua) → tự hiểu 19/10 | Trái R-30, GC-DATE-03 |
| Inbound | — | "đổi lịch" → `TRANSFERRED/OUT_OF_SCOPE`, không ghi | Đúng, giữ |

## 3. Thiết kế v2

### 3.1 Luồng

```text
CONFIRM_READBACK / ASK_INTENT (outbound), intent RESCHEDULE
  tiêu chí = parse_slot_criteria(transcript, now)
    ngày không rõ (đã qua / không tồn tại / quá rộng) -> ASK_SLOT_PREFERENCE + lý do (§3.5.2)
    không có tiêu chí                                 -> ASK_SLOT_PREFERENCE, AWAITING_INTENT, CHƯA set_pending   # Q-1, Q-6
    có tiêu chí                                       -> set_pending(RESCHEDULE); vòng = 1; _offer_slots(tiêu chí)

ASK_SLOT_PREFERENCE (_slot_preference)
  tiêu chí mới          -> set_pending nếu chưa; vòng += 1 nếu đã có vòng trước; _offer_slots
  "nào cũng được" / chỉ thứ tự ("khung 1") -> _offer_slots(không lọc)                                          # V-12
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
  MORE ("khung khác", "còn khung nào", "nghe tiếp", "giờ khác") -> trang tiếp; hết -> hết vòng (§3.2)
  tiêu chí thời gian MỚI         -> vòng mới: _offer_slots(tiêu chí mới)                                      # V-10
  thứ tự không có trong trang ("khung 3" khi mới đọc 2) -> nói rõ + đọc lại trang, NEUTRAL
  "không" trần                   -> SLOT_REFUSE_CHOICE (A/B: khung/ngày khác hay giữ lịch cũ), UNCLEAR       # Q-4
  "thôi không đổi" / giữ lịch    -> _abandon
  CANCEL                         -> _start(CANCEL)
  còn lại                        -> đọc lại trang hiện tại + NOT_UNDERSTOOD

SLOT_READBACK (_slot_readback)
  AGREE đúng lượt  -> Gateway.reschedule
       2xx đúng slot -> _finish(RESCHEDULED, rescheduled(slot))       "Em đã đổi lịch sang …"                 # V-7
       SlotTaken     -> select_slot(None); _offer_slots(tiêu chí đã lưu, prefix SLOT_TAKEN)                   # G-7, GC-RES-06
       lỗi khác      -> như T-04 / T-12 (SYSTEM_ERROR / đối soát)
  "không, khung khác" / REFUSE + MORE -> thêm slot vào refused; select_slot(None); trang tiếp                   # V-9
  "không" trần     -> SLOT_REFUSE_CHOICE, UNCLEAR                                                              # Q-4
  "thôi không đổi" -> _abandon
  MATCH khung khác đã đọc ("thôi lấy khung 2") -> select_slot mới; câu chốt mới
  tiêu chí thời gian mới -> vòng mới
  UNCLEAR ("dạ", "vâng", "chắc là được", câu hỏi đuôi, "nhưng…") -> hỏi lại CÂU CÓ/KHÔNG cùng slot           # V-1, GC-CONF-01
```

### 3.2 Vòng (R-29) — định nghĩa đề xuất

- **Một vòng** = một yêu cầu thời gian của khách (một ngày / buổi / "nào cũng được") và các khung bot đọc cho yêu cầu đó, kể cả các trang "khung khác".
- Vòng mới bắt đầu khi khách nêu **tiêu chí thời gian mới** (ở bất kỳ bước nào) hoặc trả lời câu "anh chị muốn ngày khác không" bằng một ngày.
- **Hết vòng** khi khách đã nghe hết khung của yêu cầu đó (hết trang) hoặc từ chối mà không chọn.
- Hết vòng 1 → hỏi ngày khác (`ASK_SLOT_PREFERENCE`, pending giữ).
- **Hết vòng 2 mà chưa chọn được** → giữ lịch cũ, không ghi đổi lịch, `transfer(PATIENT_REQUEST)` (GC-RES-05).
- "Thôi không đổi nữa" / "giữ lịch" **ở vòng 1** → `_abandon` (giữ lịch cũ, quay lại câu đến khám) như hiện tại. Ở vòng 2 → chuyển máy theo GC-RES-05.
- Lượt "chưa hiểu" không tăng vòng; bộ đếm §1.1.5 vẫn chạy riêng.

Định nghĩa này là đề xuất (PRD chưa định nghĩa "vòng") — xem §6 D-5.

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
| `_start` đọc slot ngay kể cả khi không có tiêu chí | Không tiêu chí → `ask(ASK_SLOT_PREFERENCE)`, `AWAITING_INTENT`, chưa `set_pending` (Q-6). Ngày không rõ → hỏi lại kèm lý do |
| `_offer_slots`: `filter_slots(...) or slots` nuốt kết quả rỗng | Ba nhánh theo số khung khớp (§3.1). Lưu `ctx.slot_request` mỗi khi có tiêu chí mới, reset `offered_slot_ids` |
| `_present`: `candidates[:3]`, không báo còn bao nhiêu | Đọc tối đa 2 trong số chưa đọc; nối `slots_remaining(n)`; cộng dồn `offered_slot_ids`; `presented_slot_ids` = trang hiện tại |
| Một khung vẫn hỏi "chọn khung nào" (G-1) | Đúng 1 khung → `select_slot` + `slot_offer_readback` (câu có/không), `SLOT_READBACK` |
| `_slot_choice`: không có nhánh MORE; NO_MATCH tính NOT_UNDERSTOOD; tiêu chí mới thành AMBIGUOUS (V-10) | Thêm MORE; NO_MATCH có tiêu chí mới → vòng mới, NEUTRAL; thứ tự ngoài trang → NEUTRAL + đọc lại |
| `_slot_choice`: "không" → `_abandon` | "không" trần → `SLOT_REFUSE_CHOICE`; "thôi không đổi / giữ lịch" → `_abandon` |
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
- `agreement._SLOT_ACTION` thêm "đổi giúp tôi", "đổi giúp em", "đổi luôn", "đổi sang giờ đó" (chỉ bản có dấu). Không hạ ngưỡng "dạ" / "vâng" / "ừ" (V-1). Chặn ngập ngừng, câu hỏi đuôi, "nhưng…" giữ như T-04.
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

Kết quả "không rõ" đi kèm lý do (`PAST`, `INVALID`, `TOO_BROAD`) để câu hỏi lại nói đúng vấn đề, ví dụ "Dạ, thứ Hai tuần này đã qua rồi ạ. Anh chị muốn đổi sang ngày nào ạ?". Không đoán ngày (R-30, §1.1.5). Lượt hỏi lại lần đầu không tính §1.1.5 (D-6).

### 3.6 Session (`session/context.py`, `session/fsm.py`)

- `CallContext` thêm: `slot_request: Optional[str]` (lời người gọi làm tiêu chí — không phải trạng thái lịch, §4.2.2), `offered_slot_ids: list[str]`, `refused_slot_ids: list[str]`, `slot_round: int`. `SCHEMA_VERSION` 1 → 2; `from_dict` đọc được bản 1 với giá trị mặc định; `clear_pending` xóa cả bốn.
- FSM `check_invariants`: `AWAITING_INTENT` + `pending_action ∈ {RESCHEDULE, BOOK}` hợp lệ khi `question_id is ASK_SLOT_PREFERENCE` (hết vòng → hỏi ngày khác). `presented_slot_ids ⊆ slot_ids` giữ nguyên.

### 3.7 Câu thoại (`dialogue/templates.py`)

Mọi câu có giờ đi qua `guardrails.assert_can_disclose`. Không đọc khoa, số điện thoại, `appointment_id` (V-6, R-19).

| Hàm / hằng | Nội dung (nháp) |
| --- | --- |
| `speak_datetime` (sửa) | "3 giờ chiều **thứ Tư** ngày 14 tháng 10" — thêm thứ; áp dụng cho mọi câu, kể cả câu đọc lịch T-04 (GC-DATE-05) → cập nhật test T-04 có so chuỗi |
| `ASK_SLOT_PREFERENCE` | "Dạ, anh chị muốn đổi sang ngày nào hoặc buổi nào ạ?" |
| `ask_date_again(reason)` | "Dạ, {thứ Hai tuần này đã qua / ngày đó không có trong lịch / em cần ngày cụ thể} ạ. Anh chị muốn đổi sang ngày nào ạ?" |
| `slot_offer_readback(slot)` | "Dạ, chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều. Anh chị đổi sang giờ đó nhé ạ?" (Hình 0) |
| `offer_slots(slots, remaining)` | "Dạ, {thứ + ngày} còn khung 1 là …, khung 2 là …. {Ngoài ra còn N khung khác. }Anh chị chọn khung nào ạ?" |
| `slot_full_for(request)` | "Dạ, {thứ Bảy ngày 17 tháng 10} đã kín lịch. Gần nhất em còn: " + `offer_slots` |
| `slot_readback(slot)` | "Dạ, em xác nhận đổi lịch sang 10 giờ 30 sáng thứ Năm ngày 15 tháng 10 tại {cơ sở}. Anh chị đồng ý chứ ạ?" |
| `SLOT_MORE_NONE` | "Dạ, {tiêu chí} em đã đọc hết khung còn trống. Anh chị muốn đổi sang ngày khác không ạ?" |
| `SLOT_NOT_IN_PAGE` | "Dạ, em vừa đọc {n} khung thôi ạ. " + đọc lại trang |
| `SLOT_REFUSE_CHOICE` | "Dạ, anh chị muốn nghe khung khác hay giữ lịch cũ ạ?" |
| `NO_SLOTS_TRANSFER` | "Dạ, hiện em không còn khung trống để đổi. Em xin phép chuyển máy cho nhân viên hỗ trợ anh chị ạ." |
| `ROUNDS_EXHAUSTED_TRANSFER` | "Dạ, em giữ nguyên lịch cũ của anh chị và xin phép chuyển máy cho nhân viên để tìm giờ phù hợp ạ." |
| `rescheduled(slot)` (thay `done("RESCHEDULED")`) | "Dạ, em đã đổi lịch sang 10 giờ 30 sáng thứ Năm ngày 15 tháng 10 ạ. Hẹn gặp anh chị ạ." |

## 4. Các bước và ưu tiên

| Bước | Ưu tiên | Việc | File chính | Ước lượng |
| --- | --- | --- | --- | --- |
| 1 | P0 | Kịch bản Hình 0: đúng 1 khung → câu có/không; câu báo "đã đổi lịch"; `speak_datetime` có thứ | `manager.py`, `templates.py` | 0,25 ngày |
| 2 | P0 | R-25: 2 khung/lượt + phân trang + nhãn MORE; sửa vòng lặp V-9 (loại khung đã từ chối, giữ tiêu chí) | `manager.py`, `slot_choice.py`, `context.py` (schema v2) | 0,5 ngày |
| 3 | P0 | Câu chốt: UNCLEAR → câu có/không; thêm cụm "đổi giúp tôi"; ba nhánh từ chối (Q-4) | `agreement.py`, `manager.py` | 0,25 ngày |
| 4 | P1 | R-29: Gateway `date_from` + `clinic_id` lịch hẹn; báo kín + gợi ý gần ngày xin; vòng + `PATIENT_REQUEST`; tiêu chí mới = vòng mới (V-10); `SlotTaken` giữ tiêu chí | `clinic_gateway.py`, `manager.py` | 0,5 ngày |
| 5 | P1 | Q-1: `ASK_SLOT_PREFERENCE` + biện pháp thứ tự; FSM invariant | `manager.py`, `schema.py`, `fsm.py` | 0,25 ngày |
| 6 | P1 | R-30: bảng §3.5.2 phần P1 + hỏi lại có lý do | `slot_choice.py`, `templates.py` | 0,5 ngày |
| 7 | P2 | "sau/trước ngày X", "thứ X hoặc Y", intent "càng sớm càng tốt" | `slot_choice.py`, `intent.py` | nếu còn thời gian |
| 8 | — | Test §5; chạy lại test T-11; tài liệu (IE design §5.6/§5.7/§6.1, kiến trúc §3.2, `session-operations.md` schema v2) | tests, docs | 0,5 ngày |
| 9 | — | `make check`; bàn giao Hoàn chạy Phụ lục A trên local + deploy; test ổn mới viết `docs/evidence/t10-reschedule-dialogue.md` | — | — |

Làm bước 1–3 trước và mở PR sớm được: không phụ thuộc quyết định PM, và sửa đúng những ca làm bản ghi sai.

## 5. Test

### 5.1 Test hiện có phải đổi kỳ vọng

| Test | Đổi |
| --- | --- |
| `test_orchestrator.py::test_reference_call_reschedule` | Bỏ lượt "khung 1": sau "đổi sang buổi chiều" bot hỏi có/không luôn (seed mặc định chỉ có 1 khung chiều); `writes` không đổi |
| `test_orchestrator.py::test_reschedule_slot_taken_reoffers_and_needs_new_confirmation` | "Tôi muốn đổi lịch" giờ ra `ASK_SLOT_PREFERENCE` (thêm một lượt); sau `SLOT_TAKEN` gợi ý lại theo tiêu chí đã nói |
| `test_orchestrator.py::test_refusing_slots_drops_pending_action_without_writing` | "không" trần → `SLOT_REFUSE_CHOICE`; đổi câu thành "thôi không đổi nữa" để giữ ý test, thêm ca "không" trần riêng |
| `tests/transports/http/test_calls.py` (e2e "Cho tôi đổi lịch" → "10 giờ sáng" → "Được") | Thêm lượt hỏi khoảng thời gian (Q-1) |
| `test_agreement.py::test_slot_readback_threshold` | Thêm "đổi giúp tôi" = AGREE; "dạ" / "vâng" / "ừ" giữ UNCLEAR |
| Test T-04 / T-05 so chuỗi có ngày giờ | Cập nhật vì `speak_datetime` có thứ |
| `test_context_fsm.py` | Tuần tự hóa schema v2, đọc bản v1 |
| Test T-11 (`test_inbound_booking_flow.py`, `test_scenario7_edge.py`) | Chạy lại; chỉ đổi số khung đọc (R-25) nếu có assert |

### 5.2 Test mới (`tests/engine/test_reschedule_dialogue.py` + IE)

- Mỗi ca ở Phụ lục A thành một test luồng (Orchestrator thật + `FakeClinicAPI` seed như Phụ lục A, `now` cố định qua `received_at`).
- GC-RES-01..06, GC-DATE-01..05 (đúng ví dụ trong PRD, hôm nay thứ Tư 23/09/2026), GC-CONF-01 cho `SLOT_READBACK`.
- IE: MORE / ANY có dấu và không dấu; bảng §3.5.2 với `now` cố định; nhãn "ngày không rõ".
- Bất biến: mọi lượt `OFFERING_SLOTS` / `SLOT_READBACK` có `presented_slot_ids ⊆ ctx.slot_ids` (SF-02); không lượt nào đọc quá 2 khung; không có câu nào trước `VERIFIED` chứa giờ (SF-03).
- HTTP e2e: cuộc gọi đúng Hình 0 qua `/v1/calls` + `/turn` → `ended=true, outcome=RESCHEDULED`.

## 6. Cần PM (Huy) chốt

Mỗi câu hỏi dưới đây đã đối chiếu contract rev 1.1 và PRD v1.6: **cả hai đều không nói, hoặc nói chưa đủ để code**. Mỗi câu có tình huống cụ thể (dữ liệu Clinic Mock deploy, hôm nay 29/09), các phương án, đề xuất của dev và một câu hỏi gửi PM viết sẵn. Chưa có trả lời thì code theo "Đề xuất của dev" để không bị chặn.

### D-1. Khách nói "đổi lịch" nhưng không nêu thời gian: hỏi khách trước hay gợi ý khung luôn?

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

**Đề xuất của dev:** **B**. Plan hiện viết theo A (Q-1, V-12, §3.1, ca 1.1 Phụ lục A); PM chọn B thì sửa các chỗ đó.

**Câu hỏi gửi PM:**
> "Khi khách chỉ nói 'tôi muốn đổi lịch' mà không nêu ngày giờ, contract và PRD đều không quy định. Bot nên (A) hỏi khách muốn đổi sang ngày/buổi nào trước, hay (B) đọc luôn 2 khung trống sớm nhất và mời khách chọn hoặc nêu ngày khác? Em đề xuất B vì an toàn hơn với bộ test chấm tự động. Anh có biết bộ test tuần 4 có ca khách chỉ nói 'đổi lịch' rồi chọn 'khung 1' không? Nếu anh không rõ, em hỏi thêm trên #residency-batch03."

### D-2. Ở câu chốt đổi lịch, khách chỉ nói "vâng" / "ừ" / "ok": có ghi đổi lịch không?

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
| d | Khách nói "**thôi không đổi nữa**" giữa chừng: giữ lịch cũ rồi hỏi tiếp có đến khám không (cuộc gọi tiếp tục), hay chuyển nhân viên `PATIENT_REQUEST` như hết vòng? | Xin 15/10 → "thôi không đổi nữa" |

**Đề xuất của dev** (đang viết ở §3.2):
- a1: tổng 2 ngày.
- b: không tính vòng mới, cùng một vòng.
- c: hỏi "anh chị muốn ngày khác không"; nếu là vòng 2 thì chuyển máy.
- d: vòng 1 thì giữ lịch cũ và hỏi lại có đến khám không; vòng 2 thì chuyển `PATIENT_REQUEST`.

**Câu hỏi gửi PM:**
> "R-29 nói tối đa 2 vòng rồi chuyển PATIENT_REQUEST. Em cần chốt 4 điểm: (a) 2 vòng là khách được xin tổng cộng 2 ngày, hay ngày đầu cộng 2 lần tra lại? (b) Xin 'khung khác' trong cùng ngày có tính vòng mới không? (c) Khách chỉ nói 'không được' mà không nêu ngày mới thì bot hỏi ngày khác hay tính luôn là hết vòng? (d) Khách nói 'thôi không đổi nữa' giữa chừng thì giữ lịch cũ và hỏi lại có đến khám không, hay chuyển nhân viên? Đề xuất của em: (a) tổng 2 ngày, (b) không tính, (c) hỏi ngày khác, (d) vòng 1 thì hỏi lại đến khám, vòng 2 thì chuyển."

### D-6. Hỏi lại vì ngày khách nói không dùng được: có tính vào "2 lần không hiểu" không?

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

- **LLM fallback của IE:** kết quả §2 chạy với LLM tắt. Trên deploy, tầng ngữ nghĩa có thể đổi nhãn một số câu (MORE, đồng ý) nhưng không sửa được các lỗi ở Dialogue. Test trên deploy xác nhận.
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
| 1.1 | `Tôi muốn đổi lịch` | Đọc 3 khung đầu | `ASK_SLOT_PREFERENCE`, chưa đọc khung |
| 1.2 | `Tôi đổi sang chiều ngày 14 tháng 10 được không?` → `Được, đổi giúp tôi.` | Hỏi "chọn khung nào" với 1 khung, rồi "em chưa hiểu"; không ghi | Câu có/không với 15:00 thứ Tư 14/10 → `RESCHEDULED`, `slot_91d2`, "em đã đổi lịch sang …" |
| 1.3 | `Tôi đổi sang buổi chiều được không?` | 3 khung chiều | 2 khung chiều + "còn 4 khung khác" |

### A.2 Từ chối và vòng

| Ca | Khách nói | Hiện tại | Đúng (v2) |
| --- | --- | --- | --- |
| 2.1 | `Tôi muốn đổi sang ngày 15 tháng 10` → `không` | Bỏ đổi lịch | `SLOT_REFUSE_CHOICE` (khung khác hay giữ lịch cũ), không ghi |
| 2.2 | `…ngày 15 tháng 10` → `khung 1` → `không, khung khác` | Bỏ đổi lịch | Bỏ 10:30, câu có/không với 15:30 cùng ngày, pending vẫn `RESCHEDULE` |
| 2.3 | `…ngày 15 tháng 10` → `khung 1` → `không, tôi muốn đổi khung khác` → `khung 1` → `không, tôi muốn đổi khung khác` → `khung 1` → `không, tôi muốn đổi khung khác` | Đọc lại cả danh sách, gồm khung vừa từ chối, lặp vô hạn | Không đọc lại khung đã từ chối; hết khung ngày 15/10 → hỏi ngày khác; không lặp; không ghi `RESCHEDULED` |
| 2.4 | `Tôi muốn đổi sang ngày 14 tháng 10` → `không được, ngày 19 tháng 10 thì sao` → `không, thôi` | Vòng 2 mở đầu "có nhiều khung giờ phù hợp"; cuối cùng quay lại hỏi đến khám | Vòng 1: 14/10 → vòng 2: 19/10 (10:00, 15:30) → `TRANSFERRED/PATIENT_REQUEST`, `writes` chỉ có `TRANSFERRED` |
| 2.5 | `…ngày 15 tháng 10` → `khung 1` → `thôi không đổi nữa` | Giữ lịch cũ, không ghi | Như hiện tại (ca đối chứng) |

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
| 5.1 | `dạ` | Câu A/B | Không ghi, hỏi lại câu có/không (GC-CONF-01) |
| 5.2 | `vâng` | Câu A/B | Theo D-2 (mặc định như 5.1) |
| 5.3 | `ừ` | Câu A/B (chạy qua hàm IE) | Theo D-2 |
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
| 7.1 | `Tôi đổi sang buổi chiều được không?` → `khung khác` → `khung khác` → `khung khác` | 3 khung; "chưa hiểu"; lần 2 `TRANSFERRED/NOT_UNDERSTOOD` | Trang 1 + "còn 4" → trang 2 + "còn 2" → trang 3 → `SLOT_MORE_NONE` hỏi ngày khác; không tính "không hiểu" |
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

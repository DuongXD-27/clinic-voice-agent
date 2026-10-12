# Review luồng Reschedule (12-10-2026) — bug và plan tối ưu

**Base:** `main` @ `6621a8f` (merge PR #119, kéo về 12-10-2026; gồm thay đổi phần danh tính của PR #111, không đụng luồng chọn khung). Nhánh sửa cắt từ `main` — `develop` đang được PM test. Số dòng trong doc này theo `6621a8f`.

**Chuẩn đối chiếu:** contract `tailieu/callbot-contract-vi.md` là chuẩn duy nhất (§1.1.5, §1.1.6, §1.1.10, §1.2.1, Bảng 2, SF-01..05, §5, §6.1). PRD v2.3 (R-23, R-25, R-29, R-30, R-41, R-42, GC-RES-01..12) do PM viết, chỉ là **lựa chọn thiết kế của đội**: điều gì PRD đòi mà contract không đòi thì không được làm yếu an toàn để đạt nó. Tham khảo thêm plan T-10 v2 (`docs/plans/t10-reschedule-dialogue.md` §3.1, §3.2, §3.8.4, D-1..D-6), evidence eval mentor 06-10 (`docs/evidence/reschedule-mentor-eval-2026-10-06.md`); case mentor qc-rs-* cũng là chuẩn.

**Cách kiểm:** chạy Orchestrator thật + `FakeClinicAPI.mentor_mock()` (dữ liệu như mock deploy: apt_00417 15:30 thứ Tư 14/10; 11 khung trống 14–21/10), tầng ngữ nghĩa tắt (chỉ luật — trong transcript của user mọi lượt đều `RULE`, nên model không liên quan). Đồng hồ cố định thứ Hai 12-10-2026 10:00, có chạy thêm với thứ Năm 08-10 và sáng 14-10. Hơn 60 kịch bản; dưới đây chỉ ghi kịch bản có vấn đề hoặc đáng ghi nhận. Các ca mục 1, B4, B6, B13 và các ca mới ở §6.7 đã chạy lại trên `6621a8f`: vẫn tái hiện y hệt.

**Trạng thái `main` @ `6621a8f`:** 478 test pass (`test_reschedule_dialogue.py`, `test_reschedule_review.py`, `test_mentor_eval_reschedule.py`, `extraction/test_slot_choice.py`, `test_inbound_booking_flow.py`, `test_scenario7_edge.py`). Eval luật `scripts/reschedule_eval.py --baseline --label baseline-main-6621a8f`: holdout **109/121 (90,1%)** [luật 93/100, cần suy nghĩa 16/21], 0 ghi sai, 0 nhầm khung, 6 "không hiểu" (kết quả ở `result/12-10-2026/reschedule/baseline-main-6621a8f`, chưa commit). So từng câu với lần đo trên `bbc9f5c` (`.../baseline`): cùng nhãn, cùng khung, cùng lý do chuyển máy ở cả 171 câu; chỉ khác biến thể câu chữ (R-42). Đây là baseline để so sau khi sửa.

## 1. Tái hiện lỗi user báo

```
BOT3  Gần nhất có khung 1: 3 giờ chiều, thứ Tư ngày 14 tháng 10; khung 2: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. ...
USER4 giờ chiều thứ 4                         (STT rớt chữ "3")
BOT4  Có nhiều khung giờ phù hợp. Hiện còn khung 1: 3 giờ chiều, thứ Tư ngày 14 tháng 10; khung 2: 3 giờ chiều, thứ Tư ngày 21 tháng 10. Còn 9 khung khác. Anh chị chọn khung nào ạ?
USER5 3 giờ chiều thứ 4 đi
BOT5  (y hệt BOT4)
USER6 3 giờ chiều thứ 4 đi
BOT6  (y hệt BOT4)   -> lặp vô hạn, failed_understandings vẫn = 0
```

Cùng lỗi với "2 giờ chiều" (trang 16/10 + 20/10), "chiều thứ 4", "3 giờ chiều", "giờ chiều thứ tư ạ". Đường thành công của user ("đổi lịch luôn" → "3 giờ chiều thứ 4") chạy đúng vì lúc đó trang chỉ có **một** khung thứ Tư 15:00.

**Nguyên nhân gốc — hai tầng.**

1. **Trang mơ hồ không nên xuất hiện ở USER4 (B7).** Trang vừa đọc (14/10 15:00 · 15/10 10:30) chỉ có **một** khung chiều thứ Tư. Nhưng `_picked` ([manager.py:1377-1383](../../src/callbot/engine/dialogue/manager.py#L1377)) chỉ ưu tiên khung trên trang khi tiêu chí có **giờ**; "giờ chiều thứ 4" (STT rớt "3") chỉ có thứ + buổi → bỏ qua trang → IE khớp trên **mọi** khung đã tải → AMBIGUOUS {14/10 15:00, 21/10 15:00}. Đã thử bỏ điều kiện "có giờ" trên `6621a8f`: USER4 chọn đúng 14/10 15:00 (`_direct_pick` ghi `slot_91d2`), cuộc gọi xong ở lượt đó. B7 vì thế là sửa **trực tiếp** cho transcript user báo, không phải P2.
2. **Trang mơ hồ không có đường thoát (B1/B2).** Khi trang mơ hồ đã hiện, Dialogue (`_slot_choice`, [manager.py:682-703](../../src/callbot/engine/dialogue/manager.py#L682)) đọc lại hai khung, đặt `presented_slot_ids` = cả hai. "3 giờ chiều thứ 4" lại khớp cả hai; `_picked` chỉ chọn khi **đúng một** khung trên trang khớp → `None` → lại nhánh AMBIGUOUS → đọc lại nguyên trang. Lượt này gắn `NEUTRAL` ([manager.py:695](../../src/callbot/engine/dialogue/manager.py#L695)), Policy không đếm (`register_understanding`, [policy_engine.py:128](../../src/callbot/engine/policy/policy_engine.py#L128)), nên §1.1.5 không bao giờ kích hoạt. Trang mơ hồ vẫn xuất hiện được sau khi sửa B7 (câu chỉ có giờ / buổi không khớp khung nào trên trang, hai khung trên trang cùng khớp), nên vẫn phải sửa B1/B2.

Thiết kế hiện tại (IE §5.7, plan T-10 §3.1 "AMBIGUOUS trong khung đã đọc → đọc lại các khung khớp (≤2), NEUTRAL") chỉ nghĩ tới việc **thu hẹp** danh sách; không có nhánh cho trường hợp câu trả lời không thu hẹp được thêm. Theo contract đây là lỗi bắt buộc sửa: §1.1.5 PHẢI chuyển máy sau hai lần hiểu sai liên tiếp, và hết `max_turns` mà lịch còn `SCHEDULED` là case fail (Bảng 2).

## 2. Danh sách bug

| # | Ưu tiên | Bug | Tái hiện (sau "Đổi lịch cho tôi", trang = 14/10 15:00 · 15/10 10:30) | Hiện tại | Đúng (theo PRD / plan) | Vị trí |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | **P0** | Vòng lặp vô hạn khi câu chọn khớp cả 2 khung của trang mơ hồ | `chiều thứ 4` → `3 giờ chiều thứ 4` (lặp) | Đọc lại nguyên trang mãi | R-23 / R-29: "câu chọn giờ mơ hồ → hỏi lại **đúng một câu có/không**" → đọc câu chốt khung sớm nhất trên trang ("Em xác nhận đổi lịch sang 3 giờ chiều thứ Tư ngày 14 tháng 10… đồng ý chứ ạ?") | `_slot_choice` 682-703, `_picked` 1368-1386 |
| B2 | **P0** | Trang mơ hồ tính `NEUTRAL` → không đếm §1.1.5, không có đường thoát | như B1; cả kiểu luân phiên `sáng` → `chiều` → `sáng` → … (mỗi lượt một trang khác, `failed` = 0 mãi) | `failed_understandings` = 0 sau 4 lượt | Lượt mơ hồ **không đem lại khung mới** phải tính `UNCLEAR` (lần 2 liên tiếp mới đếm, như các câu hỏi lại khác); chỉ lượt đọc ra ít nhất một khung chưa từng đọc mới NEUTRAL (§6.1) | `_slot_choice` 695 |
| B3 | P1 | "Còn N khung khác" sai số ở trang mơ hồ | `chiều thứ 4` → "Còn **9** khung khác" (chỉ có 2 khung chiều thứ Tư); `sáng` → "Còn 9" (còn 3) | Đếm trên toàn danh sách trừ khung đã đọc | Đếm số khung **khớp tiêu chí** chưa đọc | `_present` 1129 → `_unoffered` 1099-1104 |
| B4 | P1 | Sau trang mơ hồ, "khung khác" / "nghe giờ khác" bỏ mất tiêu chí vừa nói và **đọc lại khung đã đọc** | `thứ năm` → trang 15/10 10:30, 15:30 → `khung khác` → "15/10 **15:30**, 16/10 9:00" (15:30 vừa đọc; không còn lọc thứ Năm). `sáng thì sao` → `khung khác` → đọc 15:30 chiều | Nhánh AMBIGUOUS không ghi `slot_request`, không cộng `offered_slot_ids` | Trang mơ hồ là yêu cầu hiện hành: "khung khác" đọc tiếp **trong** tập khớp, không lặp khung đã đọc (R-25, T-10 §3.4), hết thì `SLOT_EXHAUSTED` | `_slot_choice` 688-695, `_present`, `_unoffered` |
| B5 | P1 | Đồng ý trần ở câu mời 2 khung → "Em chưa hiểu" | `đồng ý` / `vâng` / `được` / `ok` / `ừ` / `dạ` ngay sau trang 2 khung | "Em chưa hiểu rõ ý anh chị"; lần 2 → `TRANSFERRED/NOT_UNDERSTOOD` | GC-RES-04: "khách chỉ đáp 'dạ' → không ghi, bot hỏi lại một câu có/không" → đọc câu chốt khung 1 (như nhãn ANY đang làm), `UNCLEAR` | `_slot_choice` 704-708 |
| B6 | P1 | Ở câu chốt **đổi lịch**, nhắc lại đúng khung đang chốt không được tính là đồng ý | `Đổi sang chiều thứ 4 được không` → câu chốt 14/10 15:00 → `3 giờ chiều` ×3 → `TRANSFERRED / NOT_UNDERSTOOD` | Hỏi lại "đồng ý chứ ạ?" hai lần rồi chuyển máy | Lựa chọn của đội (PRD R-23: nói lại đúng ngày giờ là khẳng định rõ). Contract không đòi câu chốt khi đổi lịch nên ghi được. **Chỉ áp cho RESCHEDULE**: đặt lịch giữ nguyên, vì §1.1.10 PHẢI có "xác nhận rõ ràng về khung giờ đã chọn" (code cũng chỉ cho RESCHEDULE chọn-là-ghi, `_direct_pick`) | `_slot_readback` 769, 792-799; `_direct_pick` 802-815 |
| B7 | **P0** | Thứ / buổi trần khớp **đúng một** khung trên trang vẫn mở trang mơ hồ toàn danh sách — **nguyên nhân trực tiếp của transcript mục 1** | `giờ chiều thứ 4` (ca user) → trang 14/10 + 21/10; `thứ tư đi` → "Có nhiều khung… 14/10 15:00; **21/10 9:00**"; `chiều` → 14/10 15:00 + 15/10 15:30 | `_picked` chỉ ưu tiên trang khi tiêu chí có **giờ** | Trang vừa đọc là ngữ cảnh câu trả lời: đúng một khung trên trang khớp → chọn khung đó (thứ / ngày: ghi ngay như giờ; buổi: đọc câu chốt) | `_picked` 1377-1383 |
| B8 | P2 | "cái thứ tư" hiểu thành khung số 4 | `cái thứ tư` → "Em vừa đọc hai khung thôi ạ" | `_ORDINAL` bắt `cái thứ (tư|năm|hai|ba|sáu|bảy)` | Thứ tự vượt số khung của trang mà token là tên thứ → đọc lại như thứ | [slot_choice.py:71-74](../../src/callbot/engine/extraction/slot_choice.py#L71), `_slot_choice` 701-703 |
| B9 | P2 | Câu mời trang mơ hồ không nói rõ hai khung chỉ khác **ngày** | `chiều thứ 4` → "Có nhiều khung giờ phù hợp. Hiện còn khung 1: 3 giờ chiều thứ Tư ngày 14…; khung 2: 3 giờ chiều thứ Tư ngày 21…. Anh chị chọn khung nào ạ?" | Khách nghe hai khung "giống nhau", trả lời lại bằng giờ → B1 | R-42(c): câu hỏi phải bám nội dung khách vừa nói: "Thứ Tư 3 giờ chiều em còn ngày 14 và ngày 21 tháng 10, anh chị chọn ngày nào ạ?" | `templates.offer_slots` 459-507, `SLOT_AMBIGUOUS` 188 |
| B10 | P2 | Từ chối trang + xin giờ không có → đọc lại **nguyên trang vừa từ chối** | `không, 5 giờ chiều` → "Em chưa thấy khung giờ đó. Hiện còn khung 1: 3 giờ chiều 14/10; khung 2: 10 giờ 30 15/10" (y hệt trang trước) | NO_MATCH + tiêu chí → `_new_request`, không đánh dấu trang bị từ chối | Có "không" trước tiêu chí mới → cộng trang vào `refused_slot_ids` (V-9) rồi mới mời gần nhất; tránh lặp nguyên văn (R-42 b) | `_slot_choice` 698-700 |
| B11 | P3 | Nhắc lại giờ lịch **cũ** ở câu chốt bị tính là yêu cầu mới, tốn 1 vòng | câu chốt 14/10 15:00 → `3 giờ rưỡi` → vòng 2: "15/10 15:30; 19/10 15:30" | `_names_current_appointment` chỉ chạy khi có cụm bỏ | Giờ đúng lịch đang đổi, không có lời xin → hỏi lại có/không hoặc "giữ lịch cũ hay đổi?", không tính vòng | `_slot_readback` 770-784 |
| B12 | P3 | Eval luật còn 12 ca fail (đã biết; trừ R112/R118 đã tách thành B14) | R056/R060/R120 (cần suy nghĩa, plan Jev); R075 → B15; R113 "tôi không nhớ là đã đặt lịch này" (→ `REFUSE_CHOICE`, mong `TRANSFER:OUT_OF_SCOPE`; cần suy nghĩa, plan Jev); R105 "thứ 5 hoặc thứ 6" (P2 §3.5.2); R101/R102/R109/R142 ("tháng sau", "thứ ba" hôm nay ở câu mời → `ASK_DAY` thay vì `ASK_DATE` có lý do); R112/R118 → B14 | | Ghi nhận; nhóm `ASK_DATE` nên sửa cùng đợt nếu còn thời gian | `_ask_date_again`, eval |
| B13 | **P0** | Dialogue parse lại nguyên câu, mất phần loại trừ IE đã đọc → đề xuất đúng khung khách vừa loại | `không lấy ngày 14, ngày 15 đi` → câu chốt **14/10 15:00**; `không lấy 3 giờ chiều, thứ 4 đi` → câu chốt **14/10 15:00** (chính khung vừa loại) | `_new_request` gọi `_criteria` trên chuỗi | Contract §1.1.5 (không được đoán): mời khung theo phần khách muốn, **không** mời lại khung khách vừa loại. Chi tiết §6.3 | `_slot_choice` 659-663, 698-700; `_new_request` 1008; [slot_choice.py:518](../../src/callbot/engine/extraction/slot_choice.py#L518) |
| B14 | **P0** | Xin tư vấn bác sĩ / hỏi về bệnh không chuyển máy khi chỉ có luật | R118 `tôi cần tư vấn bác sĩ` → `extract_clinical` = `NONE`; R112 `tôi có câu hỏi về bệnh` → `MENTION` (chỉ chuyển khi model chạy được); `cho tôi hỏi bác sĩ một chút` → `NONE` | "Em chưa hiểu" ×2 → `TRANSFERRED / NOT_UNDERSTOOD` (sai lý do), hoặc không chuyển nếu lượt sau hiểu | Contract §1.2.1: PHẢI chuyển máy **mọi lúc**, `CLINICAL_QUESTION`. Không được phụ thuộc model: Jev timeout, 4 câu chọn khung và inbound trước xác minh đều chỉ có luật | [clinical.py](../../src/callbot/engine/extraction/clinical.py) (mọi câu hỏi, không riêng đổi lịch) |
| B15 | P1 | "Tôi đổi ý" ở câu chọn khung bị hiểu là không hiểu | R075 `tôi đổi ý` ở câu mời khung | "Em chưa hiểu" (eval mong `TRANSFER:PATIENT_REQUEST`) | **Owner 12-10:** "đổi ý" là đổi ý định, bỏ việc đổi lịch — không ghi, không chuyển máy, quay lại câu hỏi lịch cũ (`_abandon`: "Lịch cũ… vẫn giữ nguyên… anh chị đến được không ạ?"). Contract §1.1.5: ý định mới chưa nói thì không đoán (không tự giữ lịch + chuyển, không tự hủy). Câu có vế sau thì vế sau quyết định. Khớp ca contract R164 (`eval/reschedule/cases2.csv`) | 4 handler chọn khung (`_slot_choice`, `_slot_readback`, `_slot_refuse_choice`, `_slot_preference`); cụm "đổi ý" trong `agreement.py` |

**Không phải bug, ghi để khỏi sửa nhầm:**
- "khung 2" / "3 giờ" / "10 rưỡi" ở câu mời → ghi ngay không đọc lại: đúng R-29 v2.1 / GC-RES-03.
- "3 giờ chiều thứ 4" hoặc "giờ chiều thứ 4" nói **ở câu đọc lịch** (không có lời xin) → "em chưa hiểu": đúng R-32 (cần lời xin như "cho tôi", "được không"); tầng Jev trên prod có thể đọc thành ý định đổi lịch.
- Gọi vào thứ Năm 08/10, "Đổi sang 3 giờ chiều thứ 4" → "Thứ Tư ngày 7 tháng 10 đã qua rồi ạ…": đúng R-30 / GC-DATE-03.
- "không, khung khác" ở câu chốt khi yêu cầu là "chiều thứ 4" → "Em đã đọc hết giờ trống phù hợp…": đúng D-5b/c (thứ trần = tuần này).

**Phân loại theo contract** (contract là chuẩn; PRD là lựa chọn của đội):

| Nhóm | Bug | Căn cứ |
| --- | --- | --- |
| Bắt buộc | B1, B2, B7 | §1.1.5 PHẢI chuyển máy sau hai lần hiểu sai liên tiếp; vòng lặp tới hết `max_turns` để lịch `SCHEDULED` = case fail (Bảng 2) |
| Bắt buộc | B13 | §1.1.5 KHÔNG ĐƯỢC đoán: mời đúng khung khách vừa loại là hiểu ngược ý |
| Bắt buộc | B14 | §1.2.1 PHẢI chuyển máy mọi lúc với yêu cầu lâm sàng |
| Lựa chọn của đội | B3–B6, B8–B11 | PRD R-23 / R-25 / R-29 / R-42, plan T-10. Nên làm vì tăng tỷ lệ hoàn thành và "phục hồi sau một lần hiểu sai" (25% ở §5), nhưng không được làm yếu an toàn: B6 không áp cho đặt lịch (§1.1.10). Contract không bắt ghi ngay khi khách chọn khung — ví dụ Reschedule của contract vẫn hỏi "đổi sang giờ đó nhé ạ?" rồi mới ghi; "chọn rõ là ghi ngay" là quyết định PRD v2.1 |

## 3. Edge case đã thiết kế — kiểm lại trên `main`, đều đúng

| Nhóm | Ca | Kết quả |
| --- | --- | --- |
| R-29 | GC-RES-01/02 (ngày kín → "đã kín" + 2 khung gần nhất), 03 (chọn rõ → ghi ngay), 05 (2 vòng → `PATIENT_REQUEST`), 06 (`slot_race` → đọc lại khung, cần đồng ý mới), 09 ("giữ lịch cũ" → `PATIENT_REQUEST`), 10 ("Sáng mai khoảng 9 giờ có được không?" → tra, không ghi), 11 ("3 giờ rưỡi hả em?" → nhắc lịch, không tra), 12 ("Không có 5 giờ thì thôi" → `PATIENT_REQUEST`) | Đúng |
| R-30 | thứ trần đã qua → hỏi lại kèm lý do; "thứ 4 tuần sau", "tuần này", "chiều mai" (ngày kín) | Đúng |
| R-43 / R-44 | qc-rs-06, qc-rs-07 (test mentor) | Đúng |
| D-1 / D-5 | "Đổi lịch cho tôi" → 2 khung sớm nhất + mời ngày khác, không tính vòng; `ngày 19` → `không được, ngày 21` → `không, ngày 20` → chuyển máy; "không" trần → câu A/B; "nghe giờ khác" → trang tiếp | Đúng |
| D-2 | câu chốt: "ừ 3 giờ chiều", "vâng đúng rồi", "đồng ý", "được" → ghi; "dạ" → nhắc nói "đồng ý" | Đúng |
| Chọn khung | "khung 1 đi", "lấy khung 1", "cho tôi khung 1", "khung một nhé", "cái đầu tiên", "cái 3 giờ", "15h", "3h chiều thứ 4", "15 giờ thứ 4", "ngày 14 3 giờ chiều", "ba giờ chiều thứ tư đi em", "3 giờ chiều thứ 4 tuần này" → ghi đúng `slot_91d2` | Đúng |

## 4. Plan sửa (một nhánh cắt từ `main` @ `6621a8f`)

`develop` đang được PM test nên không làm base. Nhánh `fix/t10-reschedule-jev` cắt từ `main` @ `6621a8f`, PR vào `main` (owner chốt 12-10). Cùng nhánh làm cả phần luật (plan này) và tầng Jev ([t10-slot-semantic-jev-2026-10-12.md](t10-slot-semantic-jev-2026-10-12.md)).

**Owner chốt 12-10 (tối):** (1) duyệt PR 1; (2) PR vào `main`; (3) câu chọn khung khớp **một** khung trên trang vừa đọc (vd. trang có một khung thứ Tư, khách nói "thứ 4") → chọn luôn; khớp **hai** khung trên trang (hai khung thứ Tư) → **hỏi lại** khách chọn khung nào, không tự đọc câu chốt khung sớm nhất (§6.1 ca 4); (4) tầng Jev làm luôn, không hoãn.

Nguyên tắc như evidence 06-10 §3.3: sửa theo nguyên nhân gốc, không nới cửa ghi (mọi lệnh ghi vẫn qua `_direct_pick` / AGREE đúng lượt + guardrail `question_offers_slot`), chỉ đổi Dialogue + IE luật, không đụng prompt model.

Bảng dưới giữ số bước cũ để các tham chiếu khác không lệch; **thứ tự làm và cách chia PR ở §6.6**.

| Bước | Bug | Việc | File | Ước lượng |
| --- | --- | --- | --- | --- |
| 1 | B1, B2 | **Nhánh AMBIGUOUS không đem lại khung mới** trong `_slot_choice`: luật chi tiết ở §6.1. Mọi candidate đã nằm trên trang vừa đọc → **không** đọc lại nguyên trang mà **hỏi lại khách chọn khung nào**, nêu đúng chỗ hai khung khác nhau (câu của B9: "…em còn ngày 14 và ngày 21, anh chị chọn ngày nào ạ?"), giữ trang, `UNCLEAR` — owner chốt, không tự đọc câu chốt khung sớm nhất. Trang mới không có khung nào chưa từng đọc cho yêu cầu này → `UNCLEAR`. Chỉ trang có khung mới mới giữ NEUTRAL. Lưu ý: "không, ngày 21" ở câu chốt sau đó **chỉ** chốt được khung 21/10 15:00 khi đã có B7 (ngày 21 có 2 khung: 9:00 và 15:00); trên `main` câu này đi `_new_request` và tốn 1 vòng — đã chạy thử. | `manager.py` `_slot_choice` | 0,25 ngày |
| 2 | B3, B4 | **Trang mơ hồ thành yêu cầu hiện hành:** thêm `CallContext.slot_candidate_ids: list[str]` (tập khung IE khớp, khóa mới đọc bằng `.get` như `slot_request`; xóa trong `reset_slot_request` / `_clear_slot_search`). Nhánh AMBIGUOUS: ghi `slot_candidate_ids = choice.slot_ids`, cộng trang vào `offered_slot_ids`. `_unoffered`: nếu có `slot_candidate_ids` thì lọc trong tập đó (trừ offered / refused). Nhờ vậy "khung khác" đọc tiếp đúng tiêu chí, không lặp khung, "Còn N khung khác" đúng số, hết tập → `_slots_exhausted` như thiết kế (vòng không tăng — D-5b). Không dùng `slot_request` cho việc này vì `_criteria` quy thứ trần về tuần này (R-30), còn câu chọn trong trang thì IE **không** quy (plan §3.5.2). | `context.py`, `manager.py` `_slot_choice`, `_unoffered`, `_present` | 0,25 ngày |
| 3 | B5 | Ở `OFFER_SLOTS`, nếu `ex.agreement.found` và không phải REFUSE (gồm `is_bare_da`) và trang có khung → như nhãn ANY: `_read_back(presented[0])`, `UNCLEAR`. Thêm biến thể câu chốt cho ngữ cảnh này ("Anh chị chọn khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10 phải không ạ?") nếu muốn tự nhiên hơn (R-42), còn không thì dùng `slot_readback`. | `manager.py` `_slot_choice` (trước `_not_understood`), `templates.py` | 0,25 ngày |
| 4 | B6 | Ở `_slot_readback`, **chỉ khi `pending_action == "RESCHEDULE"`**: `restates and self._answers_last_question(ctx) and explicit_slot_pick(ex.transcript) and not asks_back and not busy` → ghi bằng chứng CONFIRMATION (provenance của `slot_choice`) rồi `_write_slot` — **cùng cổng** với `_direct_pick`. BOOK giữ như cũ: nhắc lại khung vẫn hỏi lại "đồng ý" (contract §1.1.10). Giữ nguyên các chặn: "?", `confirmation_veto`, "dạ" trần, câu còn nội dung khác. Transcript ASR thường **không có dấu "?"**, nên chặn câu hỏi trên audio chỉ dựa vào tiểu từ ("à", "hả", "hở") và cụm "sao lại…": test phải có các ca không dấu chấm hỏi ("3 giờ chiều à", "3 giờ chiều hả em"). Test `test_a_slot_named_as_a_question_is_not_written` phải vẫn pass. | `manager.py` `_slot_readback` | 0,25 ngày |
| 5 | B7, B8 | **B7 (P0, làm cùng bước 1):** `_picked`: bỏ điều kiện `criteria.hours is not None` — AMBIGUOUS mà **đúng một** khung trên trang khớp thì là chọn khung đó; với tiêu chí chỉ có **buổi** thì trả về qua `_read_back` (không `_direct_pick`), thứ / ngày / giờ thì như hiện tại (ca user: "giờ chiều thứ 4" → ghi ngay 14/10 15:00 vì là khung chiều thứ Tư duy nhất trên trang vừa đọc; contract cho phép vì khung do `GET /slots` trả về và duy nhất trên trang). **B8 (P2):** `_slot_choice` nhánh `SLOT_NOT_IN_PAGE`: thứ tự > số khung trang và token là tên thứ (`tư`, `năm`, `hai`, `ba`, `sáu`, `bảy`) → gọi lại `extract_slot_choice` trên câu đã thay "cái/khung thứ X" bằng "thứ X". Kiểm lại eval R135, R142 (test hiện có). | `manager.py` `_picked`, `_slot_choice`; `slot_choice.py` | 0,25 ngày |
| 6 | B9 (PR 1, cần cho §6.1 ca 4) | `offer_slots`: khi `prefix == SLOT_AMBIGUOUS` và hai khung cùng giờ + cùng thứ → câu "…em còn **ngày 14** và **ngày 21** tháng 10, anh chị chọn ngày nào ạ?"; cùng ngày khác giờ → "…còn 10 giờ 30 và 3 giờ 30 chiều, anh chị chọn giờ nào ạ?". Vẫn qua renderer / Output Guard (R-19). | `templates.py` | 0,25 ngày |
| 7 | B10, B11 | `_slot_choice` nhánh `_new_time_request`: câu bắt đầu bằng từ chối (`agreement` REFUSE trên phần trước tiêu chí) → `_refuse(ctx, presented)` trước `_new_request`. `_slot_readback`: tiêu chí khớp đúng lịch đang đổi (`_current_matches`) mà không có lời xin → `_reask_readback` (UNCLEAR), không tính vòng. | `manager.py` | 0,25 ngày |
| 8 | — | **Test & eval:** file mới `tests/engine/test_reschedule_ambiguity.py` gồm nguyên transcript user (mục 1) và các ca B1–B14 ở mục 2 + §6.7 (mỗi ca một test, `FakeClinicAPI.mentor_mock()`, `now` cố định 12-10-2026 10:00), cộng test thuộc tính kết thúc (§6.1). Thêm ca vào `eval/reschedule/cases.csv` (nhóm `ambiguous_page`, `exclusion`); eval chỉ dựng ngữ cảnh theo bảng `SETUP` cố định ([reschedule_eval.py:97](../../scripts/reschedule_eval.py#L97), đồng hồ thứ Ba 29/09) nên phải **thêm khóa SETUP mới** (vd. `("outbound", "OFFER_SLOTS", "2-ambiguous")`: `["Tôi muốn đổi lịch", "9 giờ"]` → trang 16/10 9:00 + 21/10 9:00; hoặc `["Tôi muốn đổi lịch", "khung khác", "3 giờ chiều"]` → trang 14/10 15:00 + 21/10 15:00) và chọn câu theo đồng hồ 29/09. Gate: `make check` xanh; `reschedule_eval.py --baseline` ≥ 109/121 (baseline `6621a8f`), **0** unsafe / wrong-slot, so từng câu với `baseline-main-6621a8f` và giải thích mọi câu đổi nhãn; eval Confirm / Cancel / No-answer giống hệt trước. Viết `docs/evidence/t10-reschedule-ambiguity-2026-10-xx.md` theo `TEMPLATE.md`. | tests, eval, docs | 0,75 ngày |
| 9 | — | Bàn giao test local → user test → PR (đích owner chốt; `develop` đang được PM test). | — | — |
| 10 | B13 | Hợp đồng `slot_criteria` + loại trừ (§6.3). | `schema.py`, `extractor.py`, `slot_choice.py`, `context.py`, `manager.py` | 0,5 ngày |
| 11 | B14 | `clinical.py`: "tư vấn bác sĩ", "hỏi bác sĩ", "câu hỏi về bệnh", "hỏi về bệnh / thuốc" → `ADVICE_REQUEST` (luật, không phụ thuộc model). Giữ các ca không lâm sàng: "bệnh viện", "khám bệnh", "bác sĩ nào khám" (hỏi lịch), "đổi bác sĩ". Test ở mọi câu hỏi (danh tính inbound, câu đọc lịch, 4 câu chọn khung, xác nhận hủy) và chạy lại eval Confirm / Cancel / Identity. | `clinical.py`, tests | 0,25 ngày |
| 12 | B15 | Cụm "đổi ý" ("tôi đổi ý", "thôi tôi đổi ý rồi", "đổi ý rồi em") ở 4 câu chọn khung, câu không còn tiêu chí giờ / ý định khác sau cụm → `_abandon` (RESCHEDULE: `CONFIRM_READBACK` lịch cũ; BOOK: hỏi lại nhu cầu như hiện tại), UNDERSTOOD. Có vế sau → bỏ cụm, đọc vế sau như câu thường. Không áp ở câu xác nhận hủy ("đổi ý" ở đó là từ chối hủy, R-41 giữ nguyên). Eval: R075 đổi nhãn sang nhãn mới "quay lại lịch cũ" (thêm vào `_observe`), ghi lý do trong evidence. | `agreement.py`, `manager.py`, `reschedule_eval.py`, `cases.csv` | 0,25 ngày |
| — | câu nói vòng | Tầng fallback **Jev** cho câu chọn khung ("lúc nào thuận tiện cũng được", "tôi đổi ý", "tôi đang lái xe"…): thiết kế riêng ở [t10-slot-semantic-jev-2026-10-12.md](t10-slot-semantic-jev-2026-10-12.md). **Làm luôn trên cùng nhánh** (owner chốt 12-10), sau PR 1 phần luật, bật bằng cờ `SLOT_SEMANTIC_ENABLED` (mặc định tắt). | xem doc | 4–5 ngày |

Tổng phần luật ≈ 2,5–3 ngày công. Chia PR ở §6.6.

**Hành vi sau khi sửa, trên đúng transcript của user** (đã kiểm phần B7 bằng bản vá thử trên `6621a8f`):

```
USER4 giờ chiều thứ 4
BOT4  Em đã đổi lịch khám sang 3 giờ chiều, thứ Tư ngày 14 tháng 10, tại Vinmec Times City cho anh chị ạ.   (B7: khung chiều thứ Tư duy nhất trên trang -> RESCHEDULED slot_91d2)
```

Trang mơ hồ vẫn xuất hiện theo đường khác, kể cả khi đã có B7: câu chỉ có giờ không khớp khung nào trên trang. Đã chạy trên `6621a8f` với bản vá thử B7: `khung khác` (trang 15/10 15:30 · 16/10 9:00) → `3 giờ chiều` → trang 14/10 15:00 + 21/10 15:00 → `3 giờ chiều đi` → đọc lại y hệt (lặp); `9 giờ` ngay sau trang đầu → trang 16/10 9:00 + 21/10 9:00 → `9 giờ sáng đi` → lặp. Sau khi sửa:

```
USER  khung khác                          -> trang 15/10 15:30 · 16/10 9:00
USER  3 giờ chiều
BOT   Ba giờ chiều em còn thứ Tư ngày 14 và thứ Tư ngày 21 tháng 10. Anh chị chọn ngày nào ạ?   (bước 6; thiếu bước 6 thì câu cũ; NEUTRAL vì có khung mới)
USER  3 giờ chiều đi
BOT   Dạ ba giờ chiều thứ Tư em còn hai ngày: ngày 14 và ngày 21 tháng 10. Anh chị chọn ngày nào ạ?   (§6.1 ca 4: hỏi lại, UNCLEAR)
USER  ngày 14                             -> RESCHEDULED slot_91d2 (khớp một khung trên trang)
USER  ngày 21                             -> chốt 21/10 15:00 (cần B7: ngày 21 có 2 khung, chỉ 15:00 trên trang)
USER  3 giờ chiều đi (lần nữa)            -> hỏi lại lần hai, UNCLEAR thứ hai liên tiếp -> đếm §1.1.5; lần nữa -> chuyển máy NOT_UNDERSTOOD
```

## 5. Ngoài phạm vi

- Luồng Book inbound dùng chung `_slot_choice`: các bước trên áp dụng cả `BOOK`; chạy lại `test_inbound_booking_flow.py`, `test_scenario7_edge.py`.
- Tầng model cho câu chọn khung và 4 ca eval cần suy nghĩa (R056, R060, R113, R120; R075 làm bằng luật ở B15): **trong phạm vi**, theo plan Jev, cùng nhánh, sau PR 1 phần luật.
- STT rớt số ("giờ chiều thứ 4"): phía STT có thể thêm bias từ điển số giờ; đợt này chỉ làm Dialogue chịu được câu thiếu số.

## 6. Chốt sau review 12-10 (chiều) — điều kiện bắt đầu code phần luật

Review nêu 6 ý; cả 6 đều đúng và được chốt dưới đây. Review lần hai (12-10 tối, đối chiếu contract, chạy lại trên `6621a8f`) bổ sung: B7 lên P0, điều kiện NEUTRAL tính trên mọi khung đã đọc (§6.1), B13 giữ phần loại trừ (§6.3), B6 chỉ cho đổi lịch (§6.4), thêm B14 lâm sàng. Ước lượng phần luật **2,5–3 ngày** (đụng `context` + persistence, `schema`, `extractor`, `manager`, `clinical`, eval). Thứ tự làm: **test / held-out trước → sửa luật và state → `--baseline` + `make check`, 0 ghi sai / nhầm khung**. Sau đó mới tới tầng Jev (cùng nhánh, owner chốt làm luôn).

### 6.1 B1 — định nghĩa "trang mới trùng trang cũ" và bộ test

Ký hiệu ở nhánh AMBIGUOUS của `_slot_choice`: `cands` = `choice.slot_ids` trừ `refused_slot_ids` (giữ thứ tự `GET /slots`); `on_page` = `cands ∩ presented_slot_ids`; `page_new` = `cands[:2]`.

| # | Điều kiện (xét theo thứ tự) | Hành vi | Hiểu | Test |
| --- | --- | --- | --- | --- |
| 1 | `len(cands) == 0` (mọi khung khớp đã bị từ chối) | như NO_MATCH có tiêu chí: `_new_request` (V-9: "chưa thấy khung giờ đó") | NEUTRAL | `candidate đã bị từ chối` |
| 2 | `len(cands) == 1` | khung còn lại: `_direct_pick` nếu đủ điều kiện, không thì `_read_back` | UNDERSTOOD | — |
| 3 | `len(on_page) == 1` (một khung trên trang, các khung khác ngoài trang) | chọn khung trên trang (`_picked`, mở rộng B7) | UNDERSTOOD | `một trên trang + một ngoài trang` (ca user báo, USER4) |
| 4 | `len(on_page) ≥ 2` **và** `set(page_new) == set(presented_slot_ids)` — trang sẽ đọc lại y hệt trang vừa đọc | **không** đọc lại nguyên trang; **hỏi lại khách chọn khung nào**, nêu chỗ hai khung khác nhau (câu B9: khác ngày → "chọn ngày nào", cùng ngày khác giờ → "chọn giờ nào"); giữ `presented_slot_ids` như cũ. Owner chốt 12-10: hai khung cùng khớp thì hỏi lại, không tự chọn khung sớm nhất | UNCLEAR | `mọi candidate trên trang` (`khung khác` → `3 giờ chiều` → `3 giờ chiều đi`) |
| 5 | `page_new` có **ít nhất một khung chưa từng đọc** cho yêu cầu hiện tại (không thuộc `offered_slot_ids ∪ presented_slot_ids`) | `_present(page_new, SLOT_AMBIGUOUS)` như hiện tại, ghi `slot_candidate_ids = cands` | NEUTRAL | `trang có khung mới` |
| 6 | còn lại (trang khác trang vừa đọc nhưng mọi khung đều đã đọc trước đó — kiểu luân phiên `sáng` / `chiều`) | `_present(page_new, SLOT_AMBIGUOUS)` | UNCLEAR | `luân phiên sáng / chiều` |

"Trùng" ở ca 4 so trên **tập** (không phải thứ tự) với trang vừa đọc. Ca 5 / 6 thì xét mọi khung đã đọc cho yêu cầu hiện tại: chỉ trang đem lại khung mới mới được NEUTRAL. Nếu chỉ so với trang vừa đọc thì luân phiên `sáng` → `chiều` → `sáng`… (đã chạy trên `6621a8f`: mỗi lượt một trang khác, `failed` = 0 mãi) vẫn lặp tới hết `max_turns`. Ca 4 là UNCLEAR nên khách nhắc lại câu không thu hẹp được thì lần hai liên tiếp bắt đầu đếm §1.1.5, rồi chuyển `NOT_UNDERSTOOD` — vòng lặp luôn kết thúc. Khách trả lời bằng ngày / giờ phân biệt được thì chọn khung trên trang: "ngày 14" khớp một khung; "ngày 21" khớp hai khung (9:00, 15:00) nhưng chỉ 15:00 nằm trên trang, nên **cần B7** (trên `main` hiện tại câu này thành yêu cầu mới, tốn 1 vòng).

**Test thuộc tính kết thúc** (cùng file test): sinh ngẫu nhiên (seed cố định) 200 chuỗi 18 lượt từ một kho câu ở pha chọn khung (`sáng`, `chiều`, `3 giờ chiều`, `9 giờ`, `thứ 4`, `khung khác`, `không`, `dạ`, `khung nào cũng được`, `3 giờ chiều đi`…). Mỗi chuỗi phải: không có lệnh ghi nào khi chuỗi không có câu chọn rõ / đồng ý; và không có quá 4 lượt liên tiếp mà không có tiến triển (khung mới, ghi, chuyển máy) trong khi `failed_understandings` không tăng. Mục tiêu: chặn cả **lớp** lỗi vòng lặp, không chỉ ca user báo.

### 6.2 B3/B4 — vòng đời `CallContext.slot_candidate_ids`

| Sự kiện | `slot_candidate_ids` | Ghi chú |
| --- | --- | --- |
| Nhánh AMBIGUOUS đọc trang mới (6.1 ca 5, 6) | `= cands`; trang vào `offered_slot_ids` | "Còn N khung khác" = `len(_unoffered)` tính trong tập này |
| `MORE` / "nghe giờ khác" (`_offer_next`) | giữ; `_unoffered` = `cands` trừ offered / refused | hết → `_slots_exhausted` (không tăng vòng, D-5b) |
| Chọn khung (`_read_back`, `_direct_pick`) | giữ | "không, khung khác" ở câu chốt đọc tiếp trong tập |
| Hết trang (`_slots_exhausted` → `ASK_SLOT_PREFERENCE`) | giữ tới khi có yêu cầu mới | hỏi ngày khác; "ngày nào cũng được" → `reset_slot_request(None)` xóa |
| Yêu cầu mới (`reset_slot_request`) | `= []` | cùng chỗ xóa `offered_slot_ids` |
| Đổi / bỏ hành động (`_clear_slot_search`, `clear_pending`) | `= []` | |
| `SLOT_TAKEN` đề xuất lại (`_offer_slots(prefix=SLOT_TAKEN)`) | giữ; `_unoffered` tự bỏ id không còn trong `ctx.slots` mới | |
| Serialize | `to_dict`: `"slot_candidate_ids": list(...)`; `from_dict`: `data.get("slot_candidate_ids", [])`; `SCHEMA_VERSION` giữ 1 như các khóa T-10 | test `test_context_fsm.py`: round-trip + phiên cũ thiếu khóa |
| Bất biến (FSM `check_invariants`) | `slot_candidate_ids ⊆ slot_ids` | như `presented_slot_ids ⊆ slot_ids` |

### 6.3 B13 — hợp đồng `slot_criteria`, không parse lại chuỗi

- **Kiểu:** `SlotCriteria` (dataclass frozen có sẵn, `extraction/schema.py`). Thêm `SlotCriteria.to_dict()` / `from_dict()`: `hours` → list sorted, `date_*` → ISO, `earlier_than` / `later_than` **không lưu** (mốc gắn lại mỗi lượt bằng `anchor_relative`, vì giờ lịch hẹn không được giữ trong phiên — §4.2.2), các trường còn lại nguyên giá trị.
- **IE:** `ExtractionResult.slot_criteria: Optional[SlotCriteria]` = tiêu chí của `slot_choice` **sau** lời bỏ / loại trừ / tự sửa (chính `choice.criteria` mà `extract_slot_choice` đã tính; ở `_choice_with_exclusion` là `wanted`). Không persist; trace chỉ `slot_choice_kind` như hiện nay.
- **Loại trừ phải đi theo tiêu chí.** Chỉ truyền `wanted` là chưa đủ: `không lấy 3 giờ chiều, thứ 4 đi` → `wanted` = thứ Tư → quy về tuần này (R-30) → 14/10 chỉ có 15:00 → vẫn mời đúng khung vừa loại (đã chạy trên `6621a8f`). Vì vậy `SlotChoice` thêm `excluded_ids: tuple[str, ...]` (chính `out_ids` của `_choice_with_exclusion`, chỉ id do luật dò trên `ctx.slots`). Dialogue cộng `excluded_ids` vào `refused_slot_ids` (V-9) **trước** khi đi bất kỳ nhánh nào (`_picked`, `_new_request`, AMBIGUOUS), nên mọi trang sau, kể cả "khung khác", đều không đọc lại khung bị loại. Khi loại hết mọi khung khớp thì đi như NO_MATCH có tiêu chí ("Em chưa thấy khung giờ đó…" + khung gần nhất).
- **Tiêu chí IE chưa quy đổi.** `choice.criteria` của IE là tiêu chí thô (IE không quy thứ trần, plan §3.5.2). `_new_request` phải tự làm đúng như `_criteria` đang làm: `resolve_request(replace(criteria, ordinal=None), now)`, rồi mới xét `date_issue` / vòng. Thiếu bước này thì "thứ 4" ở yêu cầu mới khớp cả thứ Tư tuần sau.
- **Dialogue:** `_new_request(ctx, now, criteria: SlotCriteria, request_text: str)` nhận tiêu chí từ IE; `_criteria(request, now)` chỉ còn dùng cho lời xin ở câu đọc lịch / danh tính (nơi IE chưa tính `slot_choice`). Lưu `CallContext.slot_criteria: Optional[dict]` (persist `.get`, mặc định `None`) cùng lúc với `slot_request` (giữ chuỗi để trace / đọc log, không parse lại). `_unoffered`, `_offer_slots`, `_request_criteria` đọc `ctx.slot_criteria` (gắn mốc relative nếu cần) — **không gọi `parse_slot_criteria` trên `ctx.slot_request` nữa**. Phiên cũ không có khóa: `slot_criteria None` và `slot_request` có → parse một lần rồi ghi lại (đường tương thích, có test).
- **Test:** "không lấy ngày 14, ngày 15 đi" → 2 khung ngày 15; "không lấy 3 giờ chiều, thứ 4 đi" → không đọc 14/10 15:00, `refused_slot_ids` chứa khung đó, lượt sau "khung khác" cũng không đọc lại; "không phải 14 mà là 15" → ngày 15; "trừ khung 1, lấy cái còn lại" → chốt khung 2; "thứ 4" ở yêu cầu mới vẫn quy về tuần này; round-trip `SlotCriteria`; phiên cũ chỉ có `slot_request`.

### 6.4 B6 — chỉ đổi lịch; test guardrail cho cả hai chiều

Đường ghi ở câu chốt khi nhắc lại đúng khung chỉ mở cho **RESCHEDULE**, đi qua cùng cổng `assert_action_confirmed`: bằng chứng CONFIRMATION cùng lượt, `question.turn == turn - 1`, `question.slot_id == slot_id` (`question_offers_slot`), không veto. BOOK không đổi: contract §1.1.10 PHẢI có xác nhận rõ ràng về khung đã chọn, nên nhắc lại khung ở câu chốt đặt lịch vẫn hỏi lại "đồng ý".

Test outbound RESCHEDULE (mỗi ca một test): "3 giờ chiều" / "khung 1" đúng lượt → ghi; sau câu nhắc im lặng hoặc "em chưa hiểu" (câu hỏi không ở lượt ngay trước) → không ghi, hỏi lại; "3 giờ chiều?" / "3 giờ chiều à" / "3 giờ chiều hả em" (không có "?", như transcript ASR) → không ghi; "3 giờ chiều nhưng thôi" (veto) → không ghi; "dạ" → không ghi, nhắc nói "đồng ý"; nhắc **khung khác** đã đọc → đọc lại khung đó, không ghi.

Test inbound BOOK: "3 giờ chiều" / "khung 1" ở câu chốt đặt lịch → **không** ghi, hỏi lại có/không; "đồng ý" → `BOOKED` (như hiện tại).

### 6.5 B10/B11 — acceptance test

- B10: "không, 5 giờ chiều" (trang 14/10 15:00 · 15/10 10:30) → câu trả lời không chứa hai khung đó; `refused_slot_ids ⊇ trang`; lượt sau "khung 1" chọn khung của trang mới. Đối chứng: "5 giờ chiều" không có "không" → vẫn đọc khung gần nhất như hiện tại.
- B11: câu chốt 14/10 15:00, "3 giờ rưỡi" (= lịch cũ 15:30) → không có `GET /slots` mới, `slot_round` không tăng, bot hỏi lại có/không (hoặc A/B); đối chứng "3 giờ rưỡi ngày 15" (giờ khác) → vẫn là yêu cầu mới.

### 6.6 Held-out, thứ tự và chia PR

Viết `tests/engine/test_reschedule_ambiguity.py` (các ca 6.1–6.5, 6.7 + transcript user + test thuộc tính) và thêm nhóm `ambiguous_page`, `exclusion` vào `eval/reschedule/cases.csv` (split `holdout`, kèm khóa SETUP mới — bước 8) **trước** khi sửa code; chạy để xác nhận đỏ đúng chỗ, rồi mới sửa. So `--baseline` sau sửa với `result/12-10-2026/reschedule/baseline-main-6621a8f` từng câu.

| PR | Nội dung | Vì sao gộp |
| --- | --- | --- |
| PR 1 (bắt buộc, trước 16/10) | B7 + B1/B2 (§6.1) + B9 (câu hỏi lại của §6.1 ca 4) + B3/B4 (`slot_candidate_ids`) + B13 (`slot_criteria`, `excluded_ids`) + B14 (`clinical.py`) + B15 ("tôi đổi ý") + test / eval | B1/B2/B3/B4/B13 cùng đổi trạng thái chọn khung; B7 là sửa trực tiếp ca user báo và là điều kiện để "không, ngày 21" chốt đúng; B14 nhỏ nhưng là MUST của contract |
| PR 2 (nếu còn thời gian) | B5, B6 (chỉ RESCHEDULE), B8, B10, B11 | lựa chọn của đội (PRD), không phụ thuộc lẫn nhau, rút được từng phần |

### 6.7 Ca bổ sung từ review lần hai (đã chạy trên `6621a8f`, chỉ luật, đồng hồ 12-10 10:00)

| Ca | Hiện tại | Sau sửa |
| --- | --- | --- |
| trang đầu → `giờ chiều thứ 4` | trang 14/10 + 21/10, lặp mãi | ghi 14/10 15:00 (B7) |
| trang đầu → `khung khác` → `3 giờ chiều` → `3 giờ chiều đi` | trang 14/10 + 21/10, lặp | hỏi lại "ngày 14 hay ngày 21", UNCLEAR (B1, ca 4) |
| trang đầu → `9 giờ` → `9 giờ sáng đi` | trang 16/10 + 21/10 9:00, lặp | hỏi lại "thứ Sáu 16 hay thứ Tư 21", UNCLEAR (B1, ca 4) |
| trang đầu → `sáng` → `chiều` → `sáng` → `chiều` | mỗi lượt một trang, `failed` = 0 mãi | với B7: `sáng` chọn 15/10 10:30 (khung sáng duy nhất trên trang); không có B7 thì ca 6 tính UNCLEAR từ lần lặp đầu |
| trang mơ hồ → `khung nào cũng được` → câu chốt 14/10 → `không, ngày 21` | yêu cầu mới, tốn 1 vòng | câu chốt 21/10 15:00 (B7) |
| `không lấy 3 giờ chiều, thứ 4 đi` | câu chốt 14/10 15:00 (khung vừa loại) | không đọc khung đó (B13 `excluded_ids`) |
| `tôi cần tư vấn bác sĩ` / `tôi có câu hỏi về bệnh` ở mọi câu hỏi, model tắt | "em chưa hiểu" | `TRANSFERRED / CLINICAL_QUESTION` (B14) |
| `tôi đổi ý` ở câu mời khung | "em chưa hiểu" | bỏ đổi lịch, quay lại câu hỏi lịch cũ, không ghi (B15) |
| `tôi đổi ý, lấy khung 2` | — | chọn khung 2 như câu chọn khung (B15 không chặn vế sau) |

# Fallback Jev cho câu hỏi chọn khung (đổi lịch) — thiết kế 12-10-2026

**Trạng thái:** thiết kế, **owner chốt 12-10 (tối): làm luôn, không hoãn**, trên nhánh `fix/t10-reschedule-jev` (cắt từ `main` @ `6621a8f`, PR vào `main`), sau PR 1 phần luật của [review 12-10](t10-reschedule-review-2026-10-12.md). Rủi ro lịch: Master plan ghi W5 (12–16/10) chỉ hardening, không mở feature mới; tổng luật + Jev ≈ 6,5–8 ngày công nên phần Jev sẽ qua 16/10 — giữ cờ `SLOT_SEMANTIC_ENABLED` mặc định tắt để PR 1 phần luật ra được độc lập. **Chuẩn:** contract là chuẩn duy nhất; PRD (R-xx) dưới đây là lựa chọn của đội. **Cập nhật 12-10 (khuya), owner chốt:** Luna là provider dự phòng của route chọn khung — Jev lỗi dịch vụ (trần đường dự phòng 4 s) hoặc câu không dấu (§4.11); không dấu chỉ áp cho 4 câu chọn khung. **Cập nhật 12-10 (tối) sau review lần hai:** base `main` @ `6621a8f`; §4.4 điểm 4 và 6 chuyển sang Dialogue; §4.7 ghi rõ chỗ lệch PRD R-31; R112/R118 tách thành B14 của plan luật. **Cập nhật 12-10 (chiều) sau review** — thêm §4.7 (chỗ sửa đường lỗi model chung), §4.9 (ma trận ưu tiên), §4.10 (hợp đồng dữ liệu), ba test chứng minh ở §7, thứ tự §8 (held-out đóng băng trước), hai quyết định §9. Điều kiện bắt đầu code phần Jev: owner chốt §9 và bước 1–2 của §8 xong. Viết lại [plan tầng LLM cho câu chọn khung (07/10)](t10-slot-semantic-fallback.md) cho provider **Jev** đang là mặc định trên `main`, và gắn với danh sách bug ở [review luồng Reschedule 12-10](t10-reschedule-review-2026-10-12.md).
**Base:** `main` @ `6621a8f` (đo lại 12-10: baseline luật 109/121, giống từng câu với `bbc9f5c`; số dòng code dưới đây theo `6621a8f`). **Chuẩn:** contract Rev 1.1 (§1.1.5, §1.1.6, SF-02, SF-05), PRD v2.3 (R-19, R-23, R-29, R-30, R-31, R-41, R-44), evidence [Jev 10-10](../evidence/semantic-provider-jev-2026-10-10.md), evidence [eval mentor 06-10](../evidence/reschedule-mentor-eval-2026-10-06.md) (qc-rs-02..08).

## 0. Kết luận nhanh

1. **`main` đã đổi sang Jev.** `config/engine.yaml`: `semantic_provider: jev`, `semantic_backup_provider: openai` (chỉ gọi khi Jev lỗi dịch vụ), `jev-1.13.0`, ngưỡng `semantic_jev_min_confidence: 0.6`, `semantic_jev_min_noul: 0.5` (commit `9a1eeef`, PR #108/#116). Adapter `semantic_jev_v6` ([semantic_jev.py](../../src/callbot/engine/extraction/semantic_jev.py)), failover [semantic_failover.py](../../src/callbot/engine/extraction/semantic_failover.py).
2. **Tầng ngữ nghĩa chưa chạy ở câu chọn khung.** `route_semantic` chỉ nhận `CANCEL_RECONFIRM`, `ASK_INTENT`, `CONFIRM_READBACK` ([semantic_router.py:128](../../src/callbot/engine/extraction/semantic_router.py#L128)); 4 câu hỏi `OFFER_SLOTS`, `SLOT_READBACK`, `SLOT_REFUSE_CHOICE`, `ASK_SLOT_PREFERENCE` là **thuần luật** (chỉ câu có từ lâm sàng mới gọi model qua `CLINICAL_UNRESOLVED`). Eval reschedule 10-10 với Jev vì vậy chỉ có 2 lượt gọi model / lần chạy.
3. **Jev không sinh text** (chỉ Choice có xác suất và Noul có/không), nên plan 07/10 (schema `time_spans` do model viết) phải đổi: model **chọn** nhãn trong tập đóng và **chọn** đoạn thời gian trong các ứng viên do luật cắt; luật vẫn parse đoạn đó và lọc trên `GET /slots`. Mọi nguyên tắc an toàn của plan 07/10 giữ nguyên (model không thấy giờ khung, không trả `slot_id`, không mở khóa ghi, một request một lượt, trần 3 s).
4. **Lợi của Jev ở đây:** p50 355–680 ms (so với 1,3–1,4 s OpenAI) nên có thể gọi ở nhiều lượt hơn mà vẫn giữ NFR p95 ≤ 2 s; gần tất định (eval lặp được); cấu trúc Choice ép model trả đúng tập nhãn. **Hạn chế:** yếu với câu không dấu; nghiêng về option đầu (jaggedness); chưa có số liệu calibration cho nhãn chọn khung → phải đo trước khi bật.
5. **Bám case mentor:** 7 case qc-rs-02..08 đi hoàn toàn bằng luật, router mới **không** được gọi ở bất kỳ lượt nào của 7 case đó (bảng §5), nên kết quả giữ nguyên ở mọi chế độ model (rule / jev / timeout / adversarial). Test hiện có `test_mentor_eval_reschedule.py` thêm chế độ cho tầng mới.
6. **Thứ tự:** sửa luật trước (review 12-10 PR 1: B7, B1/B2, B9, B3/B4, B13, B14 — đường chạy khi model tắt / lỗi), rồi làm tầng Jev ngay trên cùng nhánh, bật bằng cờ riêng `SLOT_SEMANTIC_ENABLED` (mặc định tắt) → staging → đo → owner quyết.

## 1. Câu khó nào cần model — đo trên `main`, chỉ luật

Chạy Orchestrator thật + `FakeClinicAPI.mentor_mock()`, đồng hồ 12-10-2026. "Mời khung" = sau "Đổi lịch cho tôi" (trang 14/10 15:00 · 15/10 10:30); "câu chốt" = sau "Đổi sang chiều thứ 4 được không" (chốt 14/10 15:00).

### 1.1 Luật không có đường đi → "Em chưa hiểu" (đếm §1.1.5, 2 lần là chuyển máy `NOT_UNDERSTOOD`)

| Câu | Câu hỏi | Đúng (eval / PRD) | Model cần nói gì |
| --- | --- | --- | --- |
| lúc nào thuận tiện cũng được (R056) | mời khung / hỏi ngày | ANY → đọc câu chốt khung sớm nhất | `ANY` |
| khung nào gần nhất thì lấy | mời khung | chốt khung 1 | `PICK` + `pick=1` (chỉ trỏ theo thứ tự) |
| không biết nữa (R060) | hỏi ngày | hỏi lại ngày (ASK_DAY), không đếm lần đầu | `AMBIGUOUS` |
| tôi đổi ý (R075) | mời khung | **đổi ý định** (owner 12-10): bỏ việc đổi lịch, không ghi, quay lại câu hỏi lịch cũ (`CONFIRM_READBACK`) | **Luật, không cần model** — review 12-10 **B15** |
| để tôi xem đã · để tôi hỏi vợ rồi gọi lại | mời khung / câu chốt | **ngoài phạm vi** (owner 12-10: không thiết kế riêng, giữ hành vi luật hiện tại) | — |
| tôi đang lái xe (R120) | câu chốt | hỏi lại có/không cùng khung (REREAD_YESNO) | `AMBIGUOUS` (kể hoàn cảnh ≠ ngoài phạm vi) |
| tôi không nhớ là đã đặt lịch này (R113) | câu chốt | `TRANSFERRED / OUT_OF_SCOPE` | `OUT_OF_SCOPE` ("denies booking" đã có trong `_INTENT_CRITERIA` của Jev) |
| tôi có câu hỏi về bệnh (R112) | mọi câu | `CLINICAL_QUESTION` | Đã đi route `CLINICAL_UNRESOLVED` của tầng hiện có khi bật model (Jev đọc ADVICE_REQUEST, evidence 10-10) |
| tôi cần tư vấn bác sĩ (R118) | mọi câu | `CLINICAL_QUESTION` | **Luật** `clinical.py` (contract §1.2.1, không được phụ thuộc model) — đã đưa vào plan luật thành **B14** (PR 1), cùng R112 |

### 1.2 Nhiều vế, mỗi vế một vai — luật đọc được ở IE nhưng Dialogue parse lại cả câu (bug mới **B13**, P1)

| Câu | Câu hỏi | Hiện tại | Đúng |
| --- | --- | --- | --- |
| không lấy ngày 14, ngày 15 đi | mời khung | IE: AMBIGUOUS {15/10 10:30, 15:30} (đúng, có loại trừ) → Dialogue `_new_request` parse lại **nguyên câu** → `day=14` → **câu chốt 14/10 15:00** (sai) | Mời 2 khung ngày 15 |
| (cùng lớp) không phải 14 mà là 15 · trừ khung 1, lấy cái còn lại | mời khung | `_corrected` xử được một phần; mọi câu loại trừ có ngày đều rơi vào parse lại | Theo kết quả IE |

Nguyên nhân: `_slot_choice` → `_new_request(ctx, now, request)` với `request = _slot_request(ex)` chỉ là vế sau lời bỏ (`slot_answer`), **không** mang phần loại trừ mà `extract_slot_choice` đã tính (`_choice_with_exclusion`). Sửa luật: IE trả thêm `ExtractionResult.slot_criteria` (tiêu chí phần khách muốn) **và** `SlotChoice.excluded_ids` (khung bị loại, Dialogue cộng vào `refused_slot_ids`); Dialogue tạo yêu cầu mới từ tiêu chí đó, không parse lại câu. Chỉ có tiêu chí thì chưa đủ: "không lấy 3 giờ chiều, thứ 4 đi" vẫn mời lại 14/10 15:00 (chi tiết review 12-10 §6.3). Đây cũng là chỗ tầng Jev điền kết quả vào (§4.5), nên làm trước.

### 1.3 Luật đã đúng, **không** cần model (giữ chỉ-luật, không route)

Tự sửa R-44 ("3 giờ chiều à không phải 10 giờ 30" → 10:30; "thứ Năm 9 giờ, à không, 10 giờ" → ngày 15, không có 10:00 → "chưa thấy khung giờ đó" + khung ngày 15; "ngày 15 ấy, à không phải 10 giờ đâu, 3 giờ chiều" → ngày 15, 15:00 → như trên); không dấu sau evidence §12.5 ("cho toi 9 gio sang mai duoc khong" → "13/10 đã kín" + khung gần nhất; "lay cai dau" → câu chốt khung 1); bỏ đổi kèm giờ lịch cũ ("thôi để nguyên lịch 3 rưỡi chiều thứ Tư đi", "thôi giữ lịch 3 rưỡi chiều thứ Tư" → giữ lịch, `PATIENT_REQUEST`); "khung sau nha", "trễ quá, có sớm hơn không" (MORE); "tuần sau tôi mới rảnh" (19/10); "hôm đó tôi bận mất rồi" (A/B); "giờ này không tiện", "tôi không đi được giờ này", "đồng ý nhưng giờ đó tôi bận" (từ chối khung → hết khung của yêu cầu → hỏi ngày khác / giữ lịch); "đổi giúp tôi nhưng để tôi hỏi vợ đã", "vâng nhưng để tôi hỏi vợ đã", "sao lại là thứ Sáu" (hỏi lại có/không); "được đấy" (ghi).

Vòng lặp trang mơ hồ (B1, B2 ở review 12-10) cũng **không** đưa cho model: đó là lỗi điều phối của Dialogue, sửa bằng luật thì mọi chế độ model đều đúng.

## 2. Ràng buộc bắt buộc

| # | Ràng buộc | Nguồn |
| --- | --- | --- |
| C1 | 7 case mentor qc-rs-02..08 (và các test `test_mentor_eval_reschedule.py`) cho **cùng kết quả** ở mọi chế độ: chỉ luật, Jev trả đúng, Jev timeout, Jev trả nhãn sai / adversarial | evidence 06-10 §1 ("không phụ thuộc tầng LLM") |
| C2 | Model không mở khóa lệnh ghi RESCHEDULE / BOOK: khung có model tham gia luôn qua câu chốt; `CONFIRM` của model chỉ dẫn tới hỏi lại; guardrail từ chối bằng chứng `FALLBACK` cho RESCHEDULE / BOOK | plan 07/10 §7.3, bảng quyền IE |
| C3 | Model không thấy giờ khung, giờ lịch hẹn, hồ sơ; không trả `slot_id`, không trả ngày giờ chuẩn hóa. Mọi khung đọc ra chỉ từ `GET /slots` của cuộc gọi | SF-02, R-19, T-05 §8.3.2 |
| C4 | Mỗi lượt **một** request model; chỉ khi provider chính lỗi dịch vụ mới có request thứ hai (Luna, §4.11). Trần thời gian ở route chọn khung: Jev 1,5 s; đường dự phòng tổng ≤ 4,0 s tính từ đầu lượt (owner chốt 12-10, vẫn dưới 8 s của contract §4.1.2). Ba câu hỏi đang chạy giữ trần 3 s. Lượt đã gọi model (lâm sàng) thì không gọi nữa | contract §4.1.2, §5; owner 12-10 (PRD R-31 chỉ tham khảo) |
| C5 | Cờ tắt (`SLOT_SEMANTIC_ENABLED=false`, mặc định) → router không chạy, hành vi từng câu bằng chỉ-luật. Cờ bật mà model lỗi / timeout / bị loại → **giữ kết quả luật**, không đi đường "model lỗi" chung (`SLOT_CONFLICT`, xóa intent), không đếm thêm §1.1.5, lượt đó không ghi thẳng | plan 07/10 §8 |
| C6 | Không sửa `semantic_jev_v6` / prompt `semantic_v*` cho 3 câu hỏi đang chạy (eval Confirm / Cancel không phải chạy lại): tầng mới là **module riêng**, chỉ dùng chung `TypeSafeClient`, `ground`/`_grounded`, ngân sách, trace | evidence 10-10 |

## 3. Vì sao thiết kế cho Jev khác plan 07/10

| Điểm | Plan 07/10 (LLM structured output) | Với Jev |
| --- | --- | --- |
| `act` | Model viết 1 trong 11 nhãn | Choice trên tập nhãn **theo từng câu hỏi** (bảng §4.3), option an toàn (`AMBIGUOUS`) đứng đầu; gate bằng xác suất của option được chọn (`_probability`) ≥ `semantic_jev_min_confidence` |
| `time_spans` (1–2 đoạn) | Model viết đoạn, code kiểm `_grounded` | Model **không viết được**. Code cắt ứng viên (`slot_time_candidates`): các cụm thời gian luật nhận ra (tokenizer của `strip_slot_phrases`: run có từ neo giờ / ngày / thứ / buổi), các mệnh đề (`span_candidates` của adapter hiện có) và cả câu; Jev chọn **một** option "đoạn nêu thời gian khách MUỐN". Câu cần 2 đoạn (lời sửa chen giữa, R-44) luật đã đọc đúng (§1.3) nên không route |
| `old_time_span` | Model viết | Noul `drops_a_time`: "khách có bỏ / loại một giờ vừa nhắc không?" + Choice `dropped_time_span` trên cùng ứng viên (chỉ đọc khi Noul ≥ ngưỡng). Dùng để kiểm chéo `KEEP_OLD` và loại trừ, không bao giờ dùng để chọn |
| `pick` | Số trong JSON | Choice `{"1","2"}` chỉ khi `page_size == 2`; `page_size == 1` thì `pick = 1`; chỉ đọc khi `act == PICK` |
| Gợi ý luật trong prompt | Có (`rule_hints`) | **Không** gửi (Jev bị nội dung kéo lệch — ghi chú adapter v6) |
| Không dấu | Route `SLOT_UNACCENTED` | Không có route riêng: câu không dấu mà luật đã đọc đúng (§12.5) vẫn giữ luật; câu không dấu **cần** model (route §4.1) thì gửi **Luna**, không gửi Jev (Jev yếu không dấu — evidence 10-10). §4.11 |
| Dự phòng OpenAI | Cùng tầng | **Có** (owner chốt 12-10): Luna (`gpt-6-luna`, prompt `slot_reply_v1`) đọc câu chọn khung trong hai trường hợp — Jev lỗi dịch vụ, hoặc câu không dấu. Chi tiết §4.11 |

## 4. Thiết kế

### 4.1 Khi nào gọi: `route_slot_semantic` (hàm thuần, có test)

Chạy **sau** `route_semantic` trả `None`, chỉ khi cờ bật, có adapter Jev (có khóa), lượt chưa gọi model, và `question_id` thuộc 4 câu chọn khung.

**Không gọi khi** (luật đã có đường đi chắc — giữ nguyên để C1 đúng):
- im lặng / rỗng; tín hiệu Policy (xin nhân viên, lâm sàng chuyển máy, không phải bệnh nhân, nhắc lại);
- khớp **toàn câu** tập đã rõ: "vâng", "dạ", "không", "được", "đồng ý", "khung 1", "khung 2", "khung khác", "giờ khác", "thôi không đổi nữa", "giữ lịch cũ"…;
- luật ra chọn rõ (`explicit_slot_pick` đúng và `_picked` có khung) — gồm "Vậy 3 giờ chiều ngày 14 cũng được", "Thế ba giờ cũng được", "Đúng rồi, 15 giờ" (qc-rs-03/04/05);
- `SLOT_READBACK` mà luật ra AGREE / REFUSE sau veto R-41 ("Ừ, 3 giờ được", "Vâng, 3 giờ được", "Không có thì 3 giờ cũng được");
- luật ra `MORE` / `ANY` / tiêu chí thời gian hợp lệ (kể cả NO_MATCH có tiêu chí: "Không, tôi chỉ đi được 5 giờ chiều thôi" → yêu cầu mới) / cụm bỏ (`gives_up_if_unavailable`: "Không có 5 giờ thì thôi") / báo bận có khung;
- (câu không dấu **không** còn là lý do bỏ route: route xét như câu có dấu, chỉ đổi provider sang Luna — §4.11.)

| Route | Điều kiện (tính bằng luật) | Ví dụ |
| --- | --- | --- |
| `SLOT_UNRESOLVED` | Không khung, không tiêu chí, không MORE / ANY, không bỏ đổi, không đồng ý / từ chối dứt khoát; câu còn từ nội dung ngoài từ đệm (luật sẽ "em chưa hiểu") | §1.1 |
| `SLOT_HEDGED_ANSWER` | Câu chốt / A/B: có tín hiệu đồng ý hoặc từ chối nhưng luật hạ UNCLEAR vì còn nội dung khác, câu hỏi đuôi, hay điều kiện ("đổi giúp tôi nhưng…", "cũng được, mà có muộn hơn chút không", "vâng nhưng…"). Model chỉ được kéo về `AMBIGUOUS` / `REFUSE` / `MORE` / `TIME`, không về đồng ý | §1.3 câu chốt |
| `SLOT_REFUSAL_WITH_CONTENT` | Từ chối trần kèm vế kể hoàn cảnh không có khung / giờ ("không được, hôm đó tôi về quê") — luật ra A/B; model có thể ra `KEEP_OLD` (đủ điều kiện) hay `OUT_OF_SCOPE` | mới |

Không có route cho câu tự sửa / loại trừ (luật + B13 xử).

### 4.2 State gửi Jev (`build_slot_state`)

```json
{
  "question_id": "SLOT_READBACK",
  "question_asked": "The bot read back one appointment time slot and asked the caller to confirm it (yes / no).",
  "pending_action": "RESCHEDULE",
  "page_size": 1,
  "answers_last_question": true,
  "transcript": "tôi đang lái xe"
}
```

Mô tả 4 câu hỏi bằng tiếng Anh, đặt trong module mới (không thêm vào `_QUESTION_ASKED` của adapter v6 — C6): `OFFER_SLOTS` "offered up to two time slots and asked which one, or another day"; `SLOT_READBACK` như trên; `SLOT_REFUSE_CHOICE` "asked whether the caller wants to hear other slots or keep the current appointment"; `ASK_SLOT_PREFERENCE` "asked which day or part of day the caller prefers". Không có giờ khung, giờ lịch, tên, số điện thoại (C3). Câu không dấu (nếu lọt route) thêm `transcript_note` + `transcript_glossary` như adapter v6, bổ sung từ nghiệp vụ chọn khung ("khung" (slot), "cai sau" (the next one), "gan nhat" (nearest)…).

### 4.3 Bộ câu hỏi, một request (`build_slot_questions`)

| Tên | Kiểu | Option (option đầu = an toàn nhất) | Ghi chú |
| --- | --- | --- | --- |
| `slot_act` | Choice | theo câu hỏi — `OFFER_SLOTS`: `AMBIGUOUS, PICK, TIME, MORE, ANY, REFUSE, KEEP_OLD, CANCEL, OUT_OF_SCOPE, QUESTION`; `SLOT_READBACK`: `AMBIGUOUS, CONFIRM, REFUSE, PICK, TIME, MORE, KEEP_OLD, CANCEL, OUT_OF_SCOPE, QUESTION`; `SLOT_REFUSE_CHOICE`: `AMBIGUOUS, MORE, KEEP_OLD, TIME, PICK, ANY, CANCEL, OUT_OF_SCOPE, QUESTION`; `ASK_SLOT_PREFERENCE`: `AMBIGUOUS, TIME, ANY, KEEP_OLD, CANCEL, OUT_OF_SCOPE, QUESTION` | Criteria dạng `what / not_for / examples`; ví dụ tự đặt, **không trùng** `eval/*/cases*.csv` (quy tắc adapter v6). `CANCEL` chỉ outbound |
| `pick` | Choice `{"1","2"}` | chỉ khi `page_size == 2` | "the first / nearest / earlier one" = 1, "the other / later / remaining one" = 2 |
| `wanted_time_span` | Choice `c0..cN` | ứng viên §3; câu speculative, **không có NONE** | Chỉ đọc khi `slot_act == TIME` |
| `drops_a_time` | Noul | true: khách bỏ / loại / giữ lại giờ cũ ("không lấy…", "thì thôi", "giữ lịch…") | ≥ `semantic_jev_min_noul` |
| `dropped_time_span` | Choice `c0..cN` | như trên | Chỉ đọc khi `drops_a_time` |
| `decides_now` | Noul | true: khách quyết ngay, không điều kiện, không hỏi người khác, không hoãn | Gate chung: `false` → `slot_act` hạ `AMBIGUOUS` (trừ `QUESTION`, `OUT_OF_SCOPE`, `CANCEL`) |
| `intent` | Choice `NONE, OUT_OF_SCOPE, CANCEL` (outbound) / `NONE, OUT_OF_SCOPE` (inbound) | dùng lại `_INTENT_CRITERIA` | `OUT_OF_SCOPE` chỉ nhận cùng `slot_act ∈ {OUT_OF_SCOPE, QUESTION}` (như v6) |
| `clinical` | Choice | dùng lại `_CLINICAL_CRITERIA` | không gate (SF-04) |

Tổng **8 câu hỏi / request** (6 Choice: `slot_act`, `pick`, `wanted_time_span`, `dropped_time_span`, `intent`, `clinical`; 2 Noul: `drops_a_time`, `decides_now`). Để so sánh, adapter v6 đang chạy gửi 11 câu (4 Choice nhãn + 3 Noul + 4 Choice span) với p50 355–680 ms, nên tầng này không chậm hơn tầng đang có; số 8 là cơ sở đo latency / cost ở §7.

### 4.4 Kiểm sau model: `ground_slot_reading` → `None` nếu sai bất kỳ điều nào

1. `slot_act` phải thuộc tập của câu hỏi; xác suất option được chọn ≥ ngưỡng, nếu không → `AMBIGUOUS`.
2. `decides_now < ngưỡng` → `AMBIGUOUS` (trừ các nhãn ở §4.3).
3. `PICK`: `pick ≤ page_size`, khung đó chưa bị từ chối; không thì bỏ cả lượt.
4. `TIME`: `parse_slot_criteria(wanted_time_span)` phải ra tiêu chí không rỗng và không `date_issue` không hợp lệ.
5. `drops_a_time` true thì `dropped_time_span ≠ wanted_time_span`; trùng → bỏ cả lượt.
6. `KEEP_OLD` ở IE chỉ kiểm phần không cần dữ liệu lịch hẹn: cụm giữ / bỏ của luật nằm trong câu; không `pick`, không `TIME`. Thiếu → `KEEP_OLD_UNSURE`.
7. Mọi span qua `_grounded` (luôn đúng vì code cắt, nhưng vẫn kiểm như v6).

**Kiểm cần giờ lịch hẹn đang đổi làm ở Dialogue, không ở IE.** IE không được biết giờ lịch hẹn (`TurnContext`, nguyên tắc 2), còn `_current_matches` nằm ở Dialogue ([manager.py:557](../../src/callbot/engine/dialogue/manager.py#L557), đọc lịch qua cổng một-lần-mỗi-lượt). Vì vậy `_slot_by_model` (§4.6) làm hai kiểm sau trước khi đi bảng hành vi: (a) `TIME` mà tiêu chí trùng lịch đang đổi → `KEEP_OLD_UNSURE` (câu A/B), không phải yêu cầu mới; (b) `KEEP_OLD` mà có `dropped_time_span` thì span đó phải khớp `starts_at` lịch đang đổi (điều kiện thứ ba của plan 07/10 §7.1), không khớp → `KEEP_OLD_UNSURE`. `ground_slot_reading` chỉ chuyển span, không tự so.

### 4.5 Merge thay cả bộ trường (`merge_slot_semantic`)

Như plan 07/10 §7.1: lượt có kết quả model thì `slot_act` có giá trị, các trường chọn khung của luật bị **thay** (không giữ lại để nhánh luật đọc lại), mọi giá trị mang `Provenance.FALLBACK`, **không bao giờ còn AGREE**. `TIME` điền `ExtractionResult.slot_criteria` (trường mới của B13) và `slot_request = wanted_time_span`.

### 4.6 Dialogue: `_slot_by_model` đứng đầu 4 handler

| `slot_act` | Dialogue | Hiểu (§1.1.5) |
| --- | --- | --- |
| `PICK` | `_read_back(khung thứ n của trang)` — không ghi thẳng dù câu trông như chọn rõ (C2) | UNDERSTOOD |
| `TIME` | khớp đúng 1 khung trên trang → `_read_back`; còn lại → `_new_request` từ `slot_criteria` (vòng R-29, quy thứ R-30, bỏ khung đã từ chối V-9) | UNDERSTOOD |
| `MORE` / `ANY` | như nhánh luật cùng tên ở câu hỏi đang chờ | UNDERSTOOD |
| `REFUSE` | `_refuse_slots` (câu A/B hoặc hết khung) | UNCLEAR |
| `KEEP_OLD` | đổi lịch: `_give_up` (giữ lịch cũ, `PATIENT_REQUEST`); đặt lịch: hỏi lại nhu cầu | UNDERSTOOD |
| `KEEP_OLD_UNSURE` | câu A/B `SLOT_REFUSE_CHOICE` | UNCLEAR |
| `CONFIRM` (chỉ câu chốt) | `_reask_readback(..., bare_da=True)` — nhắc nói "đồng ý" | UNCLEAR |
| `CANCEL` (outbound) | `_start(CANCEL)`: lượt yêu cầu, vẫn cần xác nhận lần hai (SF-05) | UNDERSTOOD |
| `OUT_OF_SCOPE` / lâm sàng | Policy chuyển máy trước khi tới Dialogue | — |
| `QUESTION` / `AMBIGUOUS` | hỏi lại **đúng câu đang chờ** bằng câu có/không (câu chốt: `_reask_readback`; mời khung: câu chốt khung 1 như nhãn ANY — khớp GC-RES-04; A/B và hỏi ngày: hỏi lại chính câu đó) | UNCLEAR |

Không gọi lệnh ghi trong `_slot_by_model`. Chốt cuối `_keep_slot_write_threshold` và guardrail từ chối bằng chứng `FALLBACK` cho RESCHEDULE / BOOK như plan 07/10 §7.3 (không áp cho CANCEL).

### 4.7 Model lỗi, timeout, bị loại — chỗ phải sửa trong code hiện tại

**Lệch PRD, không lệch contract.** PRD R-31 ghi "model lỗi → IE trả NONE, hỏi lại câu đóng, lượt đó tính là một lần không hiểu". Contract không quy định cách đếm lượt model lỗi (§1.1.5 chỉ đòi chuyển máy sau hai lần hiểu sai liên tiếp), nên C5 dưới đây là quyết định của đội: lượt route chọn khung mà model lỗi được tính **đúng như kết quả luật** (luật ra "em chưa hiểu" thì vẫn tính; luật ra câu hỏi lại thì UNCLEAR). Hai lượt liên tiếp model lỗi ở câu chọn khung vẫn dẫn tới chuyển máy khi luật cũng không hiểu. Cần báo PM sửa R-31 cho khớp để buổi review tuần 6 không bị hỏi.

Code hiện tại coi mọi lỗi model là lỗi chung: [extractor.py:335-340](../../src/callbot/engine/extraction/extractor.py#L335) xóa `intent` / `agreement` khi `budget.status ∈ {TIMEOUT, ERROR, INVALID}`, rồi [manager.py:200-209](../../src/callbot/engine/dialogue/manager.py#L200) đi `_reask_confirmation(failed=True)` → ở câu chọn khung ra `SLOT_CONFLICT` "anh chị có đồng ý với khung giờ vừa đọc không ạ?" (vô nghĩa sau trang 2 khung) và tính NOT_UNDERSTOOD. Với route chọn khung (C5):

| Chỗ | Sửa |
| --- | --- |
| `extract()` | nếu `result.model_route` là route chọn khung: giữ `intent` / `agreement` của luật, chỉ hạ `AGREE → UNCLEAR` (lượt có route không ghi thẳng); vẫn ghi `model_status` |
| `respond()` | `extraction.model_failed and extraction.model_route là route chọn khung` → không `_reask_confirmation(failed=True)`, không đặt `proposal`; vẫn `ctx.business_write_blocked = True`; đi handler như không có model |
| Policy | hiểu tính theo kết quả luật của handler (không cộng thêm "không hiểu" vì model lỗi) |

Test riêng (timeout, http_error, invalid_response, `ground_slot_reading` trả `None`), mỗi ca ở `OFFER_SLOTS` (trang 2 khung) và `SLOT_READBACK`: câu bot là câu của luật (không phải `SLOT_CONFLICT`), `failed_understandings` không tăng vì lỗi model, không lệnh ghi, không `SYSTEM_ERROR`, `business_write_blocked == True`. Ba câu hỏi đang chạy (`CANCEL_RECONFIRM`, `ASK_INTENT`, `CONFIRM_READBACK`) giữ nguyên đường lỗi chung (test hiện có không đổi).

### 4.9 Ma trận ưu tiên khi đọc kết quả Jev (`to_slot_reading`)

Xét theo thứ tự; dòng trước thắng dòng sau. Mục tiêu: nhãn hành động chỉ đi khi chắc, nhãn kéo về hướng hỏi lại không cần chắc, và `decides_now` không hạ nhầm nhãn trong bảng hành vi §4.6.

| # | Điều kiện | Kết quả | Vì sao |
| --- | --- | --- | --- |
| 1 | `clinical ∈ {EMERGENCY, ADVICE_REQUEST}` (không gate) | giữ `clinical`; Policy chuyển `CLINICAL_QUESTION` | SF-04 |
| 2 | `intent == OUT_OF_SCOPE` ≥ ngưỡng **và** `slot_act ∈ {OUT_OF_SCOPE, QUESTION}` | `OUT_OF_SCOPE` → Policy chuyển máy | như v6: ngoài phạm vi chỉ đi cùng yêu cầu / câu hỏi cụ thể |
| 3 | `intent == CANCEL` ≥ ngưỡng, outbound | `CANCEL` → `_start(CANCEL)` (vẫn cần xác nhận lần hai) | lệnh hủy thắng mọi phán đoán chọn khung |
| 4 | `slot_act == KEEP_OLD` | ≥ ngưỡng **và** `decides_now` **và** đủ 3 điều kiện §4.4 → `KEEP_OLD`; còn lại → `KEEP_OLD_UNSURE` (câu A/B) | `KEEP_OLD` sai = chuyển máy sai; `decides_now` chỉ hạ về A/B, không về "chưa hiểu" |
| 5 | `slot_act == REFUSE` | nhận **không cần** `decides_now`, không cần ngưỡng | từ chối chỉ dẫn tới câu A/B (an toàn, R-23 không đoán) |
| 6 | `slot_act == CONFIRM` (chỉ câu chốt) | luôn → `UNCLEAR` + nhắc nói "đồng ý" | model không mở khóa ghi (C2) |
| 7 | `slot_act ∈ {PICK, TIME, MORE, ANY}` | ≥ ngưỡng **và** `decides_now` → nhãn đó; không thì `AMBIGUOUS` | "chắc khung 2, để tôi xem đã" → hỏi lại chứ không chốt khung 2 |
| 8 | `slot_act ∈ {QUESTION, AMBIGUOUS}` hoặc dưới ngưỡng | `UNCLEAR` → hỏi lại đúng câu đang chờ | — |

`decides_now` vì thế chỉ tác động lên dòng 4 và 7; `REFUSE`, `OUT_OF_SCOPE`, `CANCEL`, `QUESTION` không bị hạ. Test: với mỗi dòng một câu dương tính và một câu bị dòng trước chặn.

### 4.10 Hợp đồng dữ liệu của các trường mới

| Trường | Kiểu | Sống ở đâu | Trace (allow-list `tracing/privacy.py`) | Tương thích |
| --- | --- | --- | --- | --- |
| `ExtractionResult.slot_criteria` | `Optional[SlotCriteria]` (dataclass có sẵn) | một lượt, không persist | không (chỉ `slot_choice_kind` như nay) | review 12-10 §6.3 (B13) |
| `ExtractionResult.slot_act` | `Optional[SlotAct]` (Enum đóng: `PICK, TIME, MORE, ANY, REFUSE, KEEP_OLD, KEEP_OLD_UNSURE, CONFIRM, CANCEL, OUT_OF_SCOPE, UNCLEAR`) | một lượt | thêm khóa `slot_act` (nhãn) | mặc định `None` = không có model |
| `ExtractionResult.model_route` | `Optional[str]` (giá trị `RouteReason` hoặc `SlotRouteReason`) | một lượt | thêm khóa `model_route` | hiện route chỉ là biến cục bộ trong `_extract`; đưa vào kết quả để `extract()` / `respond()` phân biệt (§4.7) |
| `ExtractionResult.slot_request` | `Optional[str]` (có sẵn) | một lượt | không (có nội dung câu) | `TIME` của model điền = `wanted_time_span` |
| `CallContext.slot_candidate_ids`, `CallContext.slot_criteria` | `list[str]`, `Optional[dict]` | persist Redis, `.get` mặc định, `SCHEMA_VERSION` giữ 1 | không | review 12-10 §6.2, §6.3 |
| Span model (`wanted_time_span`, `dropped_time_span`) | `str` | chỉ trong lượt, vào `ExtractionResult` như span luật | không bao giờ vào trace / log kỹ thuật (như v6) | — |

Không trường nào mang `slot_id` do model chọn; `slot_choice` sau merge chỉ chứa id do luật dò trên `ctx.slots`.

### 4.8 File

| File | Việc |
| --- | --- |
| `extraction/slot_semantic_jev.py` (mới) | `SlotSemanticContext`, `build_slot_state`, `build_slot_questions`, `slot_time_candidates`, `JevSlotSemanticExtractor.analyze` → `SlotReading` → `ground_slot_reading`; `PROMPT_VERSION = "slot_jev_v1"` |
| `extraction/slot_semantic_luna.py` (mới), `inference/llm/prompt/slot_reply.py` (mới) | Adapter Luna cho câu chọn khung (§4.11): prompt `slot_reply_v1`, schema `SlotReplyReading` → `SlotReading` |
| `extraction/slot_semantic.py` (mới) | `route_slot_semantic`, `merge_slot_semantic`, `SlotAct`, hàm thuần có test |
| `extraction/schema.py` | `ExtractionResult.slot_criteria` (B13), `slot_act`, `model_route` |
| `extraction/extractor.py` | sau `route_semantic` → `None` và cờ bật: route → adapter (qua `invoke_model`) → merge; lỗi theo §4.7 |
| `dialogue/manager.py` | `_slot_by_model` đầu 4 handler; `_new_request` nhận tiêu chí (B13); chốt `_keep_slot_write_threshold` |
| `policy/guardrails.py` | `assert_action_confirmed`: RESCHEDULE / BOOK không nhận bằng chứng `FALLBACK` |
| `engine/settings.py`, `config/engine.yaml`, `engine/__init__.py` | `slot_semantic_enabled: false`; dựng `JevSlotSemanticExtractor` từ cùng `TypeSafeConfig`; ngưỡng dùng chung `semantic_jev_min_confidence` / `min_noul` (tách riêng nếu số đo khác) |
| `scripts/reschedule_eval.py` | `--semantic` chạy cả tầng mới; `--route-only` đếm theo route; `--fake`, `--adversarial` (mọi `slot_act` × mọi ứng viên span) đếm ghi sai **và** hại không qua lệnh ghi (chuyển máy sai, tốn vòng, đếm "không hiểu") |
| `tests/engine/test_mentor_eval_reschedule.py` | thêm chế độ `slot-jev` (nhãn đúng), `slot-jev-wrong` (mọi lượt trả `KEEP_OLD` / `OUT_OF_SCOPE` / `PICK 2`), `slot-timeout`; 7 case phải pass và `routed == False` ở mọi lượt |

### 4.11 Provider: Jev chính, Luna dự phòng (owner chốt 12-10)

Router (§4.1), bộ nhãn (§4.3), kiểm sau model (§4.4), merge (§4.5), Dialogue (§4.6), ma trận (§4.9) là **một**, dùng chung cho hai provider. Chỉ khác adapter: mỗi adapter trả cùng một `SlotReading`.

| Trường hợp | Provider | Trần thời gian | Ghi chú |
| --- | --- | --- | --- |
| Câu có dấu (kể cả lẫn dấu, vd. "Dạ toi muon doi") | **Jev** (`slot_jev_v1`) | request 1,5 s | lẫn dấu vẫn gửi Jev kèm `transcript_glossary` |
| Câu không dấu hoàn toàn (`is_unaccented(clean(transcript))`) | **Luna** (`slot_reply_v1`), không gọi Jev | trần lượt 3 s | Jev yếu không dấu (evidence 10-10). Câu vốn không có dấu ("khung 2 cho anh") cũng đi Luna — chỉ chậm hơn, không sai |
| Jev lỗi dịch vụ (timeout 1,5 s, lỗi mạng / HTTP, trả hỏng) | **Luna** | tổng ≤ 4,0 s từ đầu lượt; chỉ gọi khi còn ≥ 1,5 s | như `FailoverSemanticExtractor` nhưng trần riêng cho route chọn khung |
| Jev đã trả lời (kể cả `AMBIGUOUS`, dưới ngưỡng, bị `ground_slot_reading` loại) | không gọi Luna | — | gọi thêm lúc đó là hỏi tới khi vừa ý, không phải dự phòng |
| Cả hai lỗi / hết giờ | luật (C5) | — | không ghi thẳng, hỏi lại theo luật |

**Gate cho Luna.** Jev có xác suất để so `semantic_jev_min_confidence`; Luna không có. Schema `slot_reply_v1` bắt Luna điền thêm `decides_now` (bool) và span nguyên văn cho mọi nhãn hành động; nhãn Luna coi như đạt ngưỡng ở ma trận §4.9, nhưng các cổng không dựa xác suất vẫn giữ (`decides_now`, 3 điều kiện `KEEP_OLD`, span phải nguyên văn, `PICK ≤ page_size`, `CONFIRM` không mở khóa ghi). Không đưa giờ khung, giờ lịch hẹn, tên, SĐT vào prompt (C3).

**Trace / eval.** Trace thêm `slot_provider` (`jev` / `luna` / `none`) và lý do (`unaccented` / `failover`), không có nội dung câu. Eval báo theo provider. Khóa OpenAI trong `.env` chỉ chạy `gpt-6-luna` — đúng model dự phòng này.

## 5. Đối chiếu 7 case mentor: lượt nào ở câu chọn khung, luật đi đường nào, có route không

| Case | Lượt ở câu chọn khung | Luật (đã có) | Route mới? | Lý do không route |
| --- | --- | --- | --- | --- |
| qc-rs-02 | "Không có thì 3 giờ cũng được" @ câu chốt 14/10 15:00 | AGREE (vế điều kiện bỏ qua, rs-02 RC-2) → ghi | **Không** | AGREE ở câu chốt |
| qc-rs-03 | "Vậy 3 giờ chiều ngày 14 cũng được" @ mời khung | `explicit_slot_pick` → ghi | **Không** | chọn rõ |
| qc-rs-04 | "Thế ba giờ cũng được" @ câu chốt | AGREE → ghi | **Không** | AGREE |
| qc-rs-05 | "Đúng rồi, 15 giờ" @ câu chốt | AGREE → ghi | **Không** | AGREE |
| qc-rs-06 | "Ừ, 3 giờ được" @ câu chốt | AGREE → ghi | **Không** | AGREE |
| qc-rs-07 | "Vâng, 3 giờ được" @ câu chốt | AGREE → ghi | **Không** | AGREE |
| qc-rs-08 | "Không, tôi chỉ đi được 5 giờ chiều thôi" @ mời khung; "Không có 5 giờ thì thôi" @ mời khung | NO_MATCH + tiêu chí → yêu cầu mới; cụm bỏ → `PATIENT_REQUEST` | **Không** / **Không** | có tiêu chí thời gian; cụm bỏ |

Các lượt trước đó (xin giờ ở câu đọc lịch, xin cùng lượt danh tính) thuộc tầng ngữ nghĩa hiện có, không đổi. Kết luận: tầng mới không thể đổi kết quả 7 case, ở mọi chế độ. Ca user báo 12-10 ("giờ chiều thứ 4" → "3 giờ chiều thứ 4 đi") cũng không route (luật có đường đi: AMBIGUOUS) — sửa bằng B1/B2.

## 6. Kỳ vọng từng câu khó sau khi có tầng Jev

| Câu | Câu hỏi | Chỉ luật (main) | Luật + Jev |
| --- | --- | --- | --- |
| lúc nào thuận tiện cũng được | mời khung | "em chưa hiểu" | `ANY` → câu chốt khung 1 |
| khung nào gần nhất thì lấy | mời khung | "em chưa hiểu" | `PICK 1` → câu chốt khung 1 (không ghi thẳng) |
| không biết nữa | hỏi ngày | "em chưa hiểu" | `AMBIGUOUS` → hỏi lại ngày, lần đầu không đếm |
| tôi đổi ý | mời khung | "em chưa hiểu" | luật B15 (không qua model): bỏ đổi lịch, quay lại câu hỏi lịch cũ |
| để tôi hỏi vợ rồi gọi lại | mời khung | "em chưa hiểu" | ngoài phạm vi (owner 12-10) |
| tôi đang lái xe | câu chốt | "em chưa hiểu" | `AMBIGUOUS` → hỏi lại có/không cùng khung |
| tôi không nhớ là đã đặt lịch này | câu chốt | từ chối khung → hỏi ngày khác | `OUT_OF_SCOPE` → `TRANSFERRED / OUT_OF_SCOPE` |
| không được, hôm đó tôi về quê | mời khung | câu A/B | `REFUSE` → câu A/B (không đổi) hoặc `KEEP_OLD_UNSURE` |
| cũng được, mà có muộn hơn chút không | câu chốt | từ chối + MORE → hết khung | `MORE` / `TIME(muộn hơn)` → khung muộn hơn theo `anchor_relative` |
| không lấy ngày 14, ngày 15 đi | mời khung | câu chốt **14/10** (B13) | luật B13 → 2 khung ngày 15 (không cần model) |

## 7. Eval và tiêu chí bật

| Tiêu chí | Mục tiêu |
| --- | --- |
| `reschedule_eval.py --baseline` (cờ tắt) | từng câu bằng snapshot luật sau khi sửa B1–B13 (≥ 109/121 hiện tại; sau sửa luật kỳ vọng ≥ 113/121) |
| `--route-only` | tỷ lệ lượt gọi ≤ 30 %, báo theo route; 7 case mentor: 0 lượt route |
| `--semantic --repeats 3` với Jev (cần `TYPESAFE_API_KEY` — máy local 12-10 chưa có, chạy trên máy owner / CI) | holdout ≥ 95 %, nhóm cần suy nghĩa ≥ 18/21; 0 ghi sai; p95 lượt có model ≤ 2,0 s (NFR-02) |
| `--fake`, `--adversarial` | 0 ghi sai / nhầm khung; `KEEP_OLD` sai → chuyển máy = 0 (nhờ 3 điều kiện); báo số chuyển máy sai, vòng tốn, đếm "không hiểu" thêm |
| Bộ held-out mới `eval/reschedule/heldout_slot_semantic.csv` (40–60 câu cho 3 lớp §1.1–§1.2 + câu phải giữ nguyên), viết trước khi viết criteria | luật + Jev hơn chỉ-luật ở từng lớp; 0 câu an toàn đổi sang sai |
| Calibration Jev trên nhãn `slot_act` (như evidence 10-10 §"Calibration") | chọn ngưỡng riêng nếu 0,6 không hợp |
| Eval Confirm / Cancel / Identity / No-answer; sha256 `semantic_jev_v6` | không đổi |
| `test_mentor_eval_reschedule.py` 7 case × (rule, llm, timeout, slot-jev, slot-jev-wrong, slot-timeout) | 7/7 **và** adapter chọn khung là mock ghi lại mọi lần gọi: `calls == 0` ở mọi lượt của 7 case (chứng minh `routed == False` bằng số lần gọi, không chỉ bằng kết quả cuối) |
| Dự phòng đúng hai trường hợp (§4.11) | test: Jev timeout / http_error / invalid ở `OFFER_SLOTS` / `SLOT_READBACK` → Luna được gọi đúng 1 lần, kết quả đi cùng `ground_slot_reading`; Jev trả lời (kể cả `AMBIGUOUS`, bị loại khi kiểm) → Luna **không** được gọi; câu không dấu → chỉ Luna, Jev không được gọi; cả hai lỗi → kết quả luật (C5); tổng thời gian model ≤ 4,0 s |
| Tối đa một request mỗi lượt khi không lỗi | `invoke_model` dùng chung `ModelBudget`; test: lượt có route lâm sàng (`CLINICAL_UNRESOLVED`) rồi tới câu chọn khung → adapter chọn khung không được gọi (`budget.used`); lượt chọn khung thường → đúng 1 lần gọi |

## 8. Thứ tự làm và ước lượng

| Bước | Việc | Ước lượng |
| --- | --- | --- |
| 0 | Owner chốt hai quyết định §9 (đổi nhãn eval nếu cần) | — |
| 1 | Plan luật (review 12-10 §6.6): test / held-out → PR 1 (B7, B1/B2, B9, B3/B4, **B13** với `slot_criteria` + `excluded_ids`, B14) → PR 2 nếu còn thời gian (B5, B6 chỉ RESCHEDULE, B8, B10, B11) → `--baseline` + `make check`, 0 ghi sai / nhầm khung | 2,5–3 ngày (W5) |
| 2 | Bộ held-out Jev (`heldout_slot_semantic.csv`, người chưa đọc criteria viết) — **đóng băng trước** khi viết router / criteria, không song song | 0,5 ngày |
| 3 | `slot_semantic.py`: `SlotAct`, router, merge, kiểm sau model, ma trận §4.9, test thuần (kể cả adversarial không mạng) | 1 ngày |
| 4 | `slot_semantic_jev.py`: state, questions, candidates, adapter; cờ; nối `extractor` / `manager` (`_slot_by_model`, §4.7); guardrail; test lỗi model riêng, "một request mỗi lượt", mentor `calls == 0` | 1,5 ngày |
| 4b | `slot_semantic_luna.py` + prompt `slot_reply_v1` (schema `SlotReplyReading`, theo plan 07/10 §6–7, cùng bộ nhãn §4.3); bộ chọn provider §4.11 (không dấu → Luna; Jev lỗi → Luna trong trần 4 s); test dự phòng §7 | 1–1,5 ngày |
| 5 | Eval: `--route-only`, `--fake`, `--adversarial`; `--semantic` 3 lần với Jev chính + Luna dự phòng (khóa Jev đã có trong `.env` local từ 12-10); eval riêng nhóm không dấu (chỉ Luna) và chế độ ép Jev lỗi (chỉ Luna); calibration Jev; evidence theo `TEMPLATE.md` | 1 ngày |
| 6 | PR vào `main` (cờ tắt) → bật cờ trên staging → user test → owner quyết bật prod | — |

Tổng ≈ 7,5–9,5 ngày công (luật 2,5–3 + Jev / Luna 5–6,5); bước 1 là PR riêng, ra trước, không phụ thuộc model. Bước 3–4b chỉ bắt đầu sau bước 2.

## 9. Rủi ro và điểm cần owner chốt

- **Calibration chưa biết.** Confirm 10-10 cho thấy Jev calibrate kém ở bin 0,7–0,8; nhãn chọn khung chưa đo. Vì vậy mọi nhãn mở hành động (`KEEP_OLD`, `TIME`, `PICK`, `CANCEL`) đều có cổng kiểm bằng luật / dữ liệu (§4.4), và nhãn sai chỉ dẫn tới hỏi lại, không ghi.
- **Không dấu**: câu cần model thì sang Luna (§4.11). Ba câu hỏi đang chạy (đọc lịch, hỏi nhu cầu, xác nhận hủy) **giữ nguyên** Jev + glossary: đổi sẽ làm đổi hành vi đang chạy trên `main` và phải chạy lại eval Confirm / Cancel. Khóa Jev đã có trong `.env` local (12-10): đo riêng nhóm không dấu của hai eval đó (Jev vs Luna) rồi mới quyết có mở rộng hay không. Chưa có số tỷ lệ ASR không dấu trên prod; ở audio mode STT thường trả có dấu nên nhóm này chủ yếu đến từ text mode / eval.
- **Hai quyết định nghiệp vụ — owner đã chốt 12-10 (tối), không còn chặn bước 3–4:**
  1. **"Để tôi hỏi vợ rồi gọi lại"** (khách tự hoãn quyết định): **ngoài phạm vi** — không thiết kế nhãn / route riêng, không bắt buộc có trong held-out; ưu tiên các ca quan trọng.
  2. **R075 "tôi đổi ý"** ở câu chọn khung: là **đổi ý định**, không phải yêu cầu đổi lịch, cũng không phải "giữ lịch cũ + chuyển máy". Xử lý bằng **luật** (review 12-10 B15): câu chỉ có cụm đổi ý → bỏ hành động đổi lịch (không ghi), quay lại câu hỏi lịch cũ như `_abandon` ("Lịch cũ của anh chị vẫn giữ nguyên… anh chị đến được không ạ?"); câu có vế sau thì vế sau quyết định ("tôi đổi ý, lấy khung 2" → chọn khung; "tôi đổi ý, hủy luôn" → hủy, vẫn cần xác nhận lần hai). Khớp ca contract R164 trong `eval/reschedule/cases2.csv` ("Tôi đổi ý, giữ lịch… xác nhận tôi sẽ đến" → `CONFIRMED` sau khi đọc lại lịch cũ). Nhãn eval R075 đổi từ `TRANSFER:PATIENT_REQUEST` sang nhãn mới "quay lại lịch cũ" (thêm vào `_observe`). Model không cần đọc câu này.
- **Bật ở đâu trước**: đề xuất staging với cờ bật 1 tuần, đọc trace `slot_act` / route / latency, rồi mới prod.
- **Chi phí**: Jev tính theo request; tỷ lệ route ≤ 30 % lượt ở câu chọn khung ≈ thêm ~0,3 request / cuộc gọi đổi lịch.

## 10. Triển khai 12-10 — chỗ lệch so với thiết kế (đo trên held-out trước khi chốt)

Code: `extraction/slot_semantic.py` (router, kiểm, ma trận, chọn provider, merge), `slot_semantic_jev.py`, `slot_semantic_luna.py` + `inference/llm/prompt/slot_reply.py`, `dialogue/manager.py` (`_slot_by_model`), `policy/guardrails.py`, cờ `slot_semantic_enabled` (mặc định tắt). Test `tests/engine/test_slot_semantic.py`. Evidence chung với PR 1: `docs/evidence/t10-reschedule-ambiguity-2026-10-12.md`.

| Thiết kế | Triển khai | Vì sao |
| --- | --- | --- |
| §4.3 Noul `decides_now` gate PICK / TIME / MORE / ANY | **Bỏ khỏi request Jev**; Luna vẫn trả `decides_now` | Held-out 12-10: Noul ra 0,03–0,18 ở mọi câu, kể cả câu chọn dứt khoát (ANY 0,95, PICK 0,91) — chỉ chặn nhầm. Do dự đã là nhãn AMBIGUOUS (1,0 ở mọi câu do dự) |
| §4.3 `drops_a_time` + `dropped_time_span`; `KEEP_OLD` nhận thẳng khi đủ 3 điều kiện | **Không hỏi**; `KEEP_OLD` của model luôn thành câu A/B | Câu có cụm giữ / bỏ của luật đã do luật xử lý và không route tới model, nên điều kiện 1 gần như không bao giờ đạt. A/B là lựa chọn không đoán (§1.1.5) |
| §4.9 dòng 2: `OUT_OF_SCOPE` cần intent + act | Thêm: act `OUT_OF_SCOPE` của Jev ≥ 0,9 mà câu intent không chọn thì vẫn là ngoài phạm vi | Held-out S023 "lịch này ai đặt cho tôi vậy tôi có đặt đâu": act 1,0, intent NONE 0,64 |
| §4.7 đường lỗi chỉ cho route chọn khung | **Mọi** lượt model lỗi ở 4 câu chọn khung (cả route lâm sàng cũ) đi nhánh luật, không ghi thẳng | Eval `--route-only` R122 "lay cai dau" ("dau" đọc thành "đau" → route lâm sàng → model lỗi → "đồng ý với khung vừa đọc không" sau trang 2 khung). Sau sửa `--route-only` = `--baseline` từng câu |
| §4.11 timeout Luna 2,5 s | **3,0 s** (trần cả route vẫn 4 s) | Lượt Luna đầu tiên (cold) 2,7 s; các lượt sau 1,5–1,9 s |
| §4.1 route `SLOT_REFUSAL_WITH_CONTENT` | Giữ | "không được, cái đó không hợp với tôi đâu em" → model đọc REFUSE / CANCEL / OUT_OF_SCOPE |

Luật sửa thêm khi chạy held-out (không phụ thuộc model): "cái sớm hơn / cái muộn hơn" là chỉ khung 1 / 2 ("sớm hơn" trần vẫn là xin khung khác, R033 / R034); ở câu chốt và câu mời, lệnh hủy rõ của luật ("…xóa lịch giúp tôi") thắng lời từ chối khung (vẫn hỏi xác nhận hủy lần hai), trừ câu báo bận.

Còn lại có chủ đích: "thôi bỏ luôn lịch khám đó cho tôi" (held-out S021) — luật đọc là bỏ đổi lịch → `PATIENT_REQUEST`; "bỏ lịch" chưa là cụm hủy của luật, sửa ở luật ý định (ngoài phạm vi đợt này).

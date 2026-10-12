# Evidence: T-10 đổi lịch 12-10 — PR 1 (luật) và tầng model chọn khung (Jev + Luna)

## Mục tiêu

Sửa các lỗi bắt buộc theo contract trong luồng đổi lịch, theo [review 12-10](../plans/t10-reschedule-review-2026-10-12.md) (PR 1, owner duyệt 12-10). Chuẩn đối chiếu là contract (§1.1.5, §1.1.6, §1.1.10, §1.2.1, Bảng 2); PRD chỉ tham khảo.

- **Lỗi user báo:** STT rớt "3" → "giờ chiều thứ 4" → bot đọc trang mơ hồ 14/10 + 21/10 → "3 giờ chiều thứ 4 đi" đọc lại nguyên trang mãi, `failed_understandings` = 0, không bao giờ chuyển máy (vi phạm §1.1.5; hết `max_turns` thì lịch còn `SCHEDULED` = case fail).
- Phạm vi: B7, B1/B2, B9, B3/B4, B13, B14, B15. Chỉ luật (Dialogue + IE), không đụng prompt / tầng model. PR 2 (B5, B6, B8, B10, B11) và tầng Jev / Luna cho câu chọn khung làm sau trên cùng nhánh.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| **B7** — câu chọn khớp đúng một khung trên trang vừa đọc thì chọn khung đó (owner 12-10), kể cả khi chỉ có thứ / buổi; chỉ có buổi thì đọc câu chốt; đặt lịch luôn đọc câu chốt (§1.1.10) | `_picked` bỏ điều kiện "phải có giờ"; `_part_of_day_only` trong `_slot_choice` (`dialogue/manager.py`). Test `test_user_report_picks_the_only_wednesday_afternoon_on_the_page`, `test_a_weekday_matching_one_slot_on_the_page_is_picked`, `test_a_part_of_day_matching_one_slot_on_the_page_is_read_back`, `test_booking_reads_back_the_only_matching_slot_on_the_page` |
| **B1/B2** — trang mơ hồ luôn có đường thoát: lượt đem lại khung mới không tính (NEUTRAL); trang sẽ đọc lại y hệt thì **hỏi lại chọn khung nào** (owner 12-10, không tự chốt khung sớm nhất); không còn khung mới thì tính UNCLEAR → lặp thì chuyển `NOT_UNDERSTOOD` | `DialogueManager._ambiguous_page`. Test `test_repeating_the_ambiguous_answer_asks_which_one_then_transfers`, `test_alternating_between_pages_already_read_counts_as_not_understood`, `test_non_narrowing_answers_always_end_the_call` (12 chuỗi ngẫu nhiên, seed cố định) |
| **B9** — câu trang mơ hồ nêu đúng chỗ hai khung khác nhau ("3 giờ chiều thứ Tư em còn ngày 14 và ngày 21 tháng 10. Anh chị chọn ngày nào ạ?"); câu hỏi lại "Dạ, anh chị chọn ngày 14 hay ngày 21 tháng 10 ạ?" | `templates.offer_slots` + `_contrast`, `_day_pair`; prefix mới `SLOT_AMBIGUOUS_AGAIN` trong `SLOT_PREFIXES` (Output Guard vẫn render lại từ dữ liệu nguồn). Test `test_an_ambiguous_page_names_what_differs`, `test_an_hour_matching_two_slots_off_the_page_names_both_days` |
| **B3/B4** — trang mơ hồ là yêu cầu hiện hành: "Còn N khung khác" đếm trong tập khớp; "khung khác" đọc tiếp trong tập, không lặp khung đã đọc | `CallContext.slot_candidate_ids` (persist bằng `.get`, xóa ở `reset_slot_request`); `_unoffered` lọc trong tập. Test `test_more_after_an_ambiguous_page_stays_within_the_matching_slots`, `test_candidate_slots_survive_the_session_round_trip` (gồm phiên cũ thiếu khóa) |
| **B13** — phần khách loại trừ không bị mời / chốt lại; yêu cầu mới tạo từ phần khách muốn, không parse lại nguyên câu | IE: `SlotChoice.excluded_ids`, `SlotChoice.request` (`extraction/schema.py`, `_choice_with_exclusion`); `extractor.py` dùng `request` làm `slot_request`. Dialogue: `_drop_excluded` → `refused_slot_ids` (V-9) ở 4 câu chọn khung. Test `test_excluding_a_day_reads_back_the_other_day`, `test_excluding_a_day_off_the_page_offers_the_other_day`, `test_excluding_an_hour_never_offers_that_slot_again` |
| **B14** — xin tư vấn bác sĩ / hỏi về bệnh chuyển máy `CLINICAL_QUESTION` bằng luật (§1.2.1), không phụ thuộc model; câu hỏi về lịch có chữ "bác sĩ" thì không | `_CONSULT_PHRASES` trong `extraction/clinical.py` (câu còn từ lịch hẹn mà không có từ bệnh / thuốc → MENTION). Test `test_asking_for_clinical_advice_is_an_advice_request`, `test_asking_about_the_booking_is_not_an_advice_request`, `test_clinical_advice_at_the_slot_offer_transfers`, `test_clinical_advice_before_inbound_verification_transfers` |
| **B15** — "tôi đổi ý" ở 4 câu chọn khung là đổi ý định: bỏ đổi / đặt lịch, không ghi, không chuyển máy, quay lại câu hỏi lịch cũ (owner 12-10); có vế sau thì đi theo vế sau | `agreement.changes_mind`, `manager._only_changes_mind` → `_abandon`. Test `test_changing_ones_mind_at_the_offer_goes_back_to_the_appointment`, `..._at_the_slot_read_back_...`, `test_changing_ones_mind_then_picking_a_slot_reads_that_slot_back`, `test_changing_ones_mind_then_cancelling_asks_the_cancel_question`, `test_changing_ones_mind_while_booking_drops_the_booking` |
| Không nới cửa ghi: mọi lệnh ghi vẫn qua `_direct_pick` / AGREE đúng lượt + guardrail | Eval: 0 ghi sai, 0 nhầm khung (bảng dưới); 7 case mentor `test_mentor_eval_reschedule.py` pass ở mọi chế độ model |
| Eval reschedule: thêm nhóm `ambiguous_page`, `pick_on_page`, `exclusion` (14 ca holdout R173–R186); nhãn mới `ASK_WHICH`, `BACK_TO_APPOINTMENT`; khóa SETUP `2-mo-ho`; R075 đổi nhãn theo owner | `scripts/reschedule_eval.py`, `eval/reschedule/cases.csv` |

## File liên quan

- `src/callbot/engine/dialogue/manager.py`
- `src/callbot/engine/dialogue/templates.py`
- `src/callbot/engine/session/context.py`
- `src/callbot/engine/extraction/schema.py`
- `src/callbot/engine/extraction/slot_choice.py`
- `src/callbot/engine/extraction/extractor.py`
- `src/callbot/engine/extraction/clinical.py`
- `src/callbot/engine/extraction/agreement.py`
- `tests/engine/test_reschedule_ambiguity.py`
- `scripts/reschedule_eval.py`, `eval/reschedule/cases.csv`

## Luồng hiện tại

```text
Trang đầu: 14/10 15:00 · 15/10 10:30
"giờ chiều thứ 4"            -> một khung chiều thứ Tư trên trang -> ghi 14/10 15:00 (B7)

Trang 15/10 15:30 · 16/10 9:00
"3 giờ chiều"                -> khớp 14/10 + 21/10, có khung mới -> "3 giờ chiều thứ Tư em còn ngày 14 và
                                ngày 21 tháng 10. Anh chị chọn ngày nào ạ?"            (NEUTRAL)
"3 giờ chiều đi"             -> trang sẽ y hệt -> "Dạ, anh chị chọn ngày 14 hay ngày 21 tháng 10 ạ?" (UNCLEAR)
"ngày 21"                    -> ngày 21 có 9:00 + 15:00, chỉ 15:00 trên trang -> ghi 21/10 15:00 (B7)
(nói lại "3 giờ chiều đi" mãi) -> UNCLEAR liên tiếp -> TRANSFERRED / NOT_UNDERSTOOD (§1.1.5)
```

## Quy trình xác minh

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
python scripts/reschedule_eval.py --baseline --label pr1-rules
python scripts/eval_compare.py result/12-10-2026/reschedule/baseline-branch-184e8e2 result/12-10-2026/reschedule/pr1-rules
```

Windows: đặt `PYTHONUTF8=1` (một test đọc file bằng bảng mã mặc định); máy không cài `livekit` thì thêm `--continue-on-collection-errors`.

## Kết quả xác minh cục bộ (2026-10-12)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest tests/engine/test_reschedule_ambiguity.py -q` | Pass (65 passed; trước khi sửa: 57 failed) |
| `python -m pytest -q --continue-on-collection-errors` (`PYTHONUTF8=1`) | Pass (5362 passed, 26 skipped — gồm cả phần 2 bên dưới); 1 lỗi collect `tests/transports/livekit/test_worker_speech_settings.py` vì máy local không cài `livekit` |
| `python scripts/export_openapi.py --check` | Báo lệch — **có sẵn trước PR này** (chạy trên `184e8e2` cũng lệch); PR không đổi schema HTTP |
| `confirm_eval.py --baseline`, `cancel_eval.py --baseline`, `identity_eval.py` trước / sau | Giống hệt từng ca (confirm 125/171, cancel 91 ca holdout, identity 215 ca) |
| `no_answer_eval.py --baseline` trước / sau | 83/83 cả hai lần; chỉ khác biến thể câu chào kết thúc |
| `reschedule_eval.py --baseline` trước sửa (`184e8e2`) | holdout 109/121 (90,1%), 0 ghi sai, 0 nhầm khung, 6 "không hiểu" |
| `reschedule_eval.py --baseline` sau sửa (`pr1-rules`) | holdout **126/135 (93,3%)** [luật 110/115, cần suy nghĩa 16/20], **0 ghi sai, 0 nhầm khung**, 3 "không hiểu"; 14 ca mới đều đạt |

So từng câu (121 ca cũ): đổi kết quả đúng 5 ca — R075 (`NOT_UNDERSTOOD` → `BACK_TO_APPOINTMENT`, đạt theo nhãn mới), R112 / R118 (`NOT_UNDERSTOOD` → `TRANSFER:CLINICAL_QUESTION`, đạt), R136 "buổi sáng" (`AMBIGUOUS` → `PICK:2`, cả hai đều được chấp nhận), R105 "thứ 5 hoặc thứ 6" (`AMBIGUOUS` → câu chốt 15/10 10:30, vẫn fail như trước, không ghi). Không ca nào từ đạt sang trượt.

## Ghi chú

- **3 test cũ đổi kỳ vọng theo quyết định owner 12-10** (một khung khớp trên trang → chọn khung đó; trang mơ hồ nêu chỗ khác nhau): `test_ambiguous_slot_choice_does_not_pick_first_slot` ("buổi chiều" → câu chốt khung chiều duy nhất trên trang, vẫn không chọn khung đầu trang), `test_time_only_choice_matching_several_slots_off_the_page_reads_at_most_two` (câu mới "2 giờ chiều em còn thứ Sáu ngày 16 và thứ Ba ngày 20 tháng 10…"), `test_corrected_day_when_choosing_among_offered_slots` ("ngày 14 à không 15" sau trang buổi chiều → câu chốt 15/10 15:30 thay vì mời lại khung sáng 15/10).
- **Catalog câu thoại TTS** (`docs/evidence/tts-static-cache/tts-utterance-catalog-2026-10-08.json`) xuất lại bằng `python scripts/tts_utterance_catalog.py --date 2026-10-08` (không gọi provider) vì catalog khóa hash `templates.py`. Không thêm câu tĩnh nào, nên audio cache không cần thu lại; catalog có thêm thành phần `SLOT_AMBIGUOUS_AGAIN`.
- **Đổi nhãn eval R075** (owner 12-10): `TRANSFER:PATIENT_REQUEST` → `BACK_TO_APPOINTMENT`, `needs_inference` → `no`. Vì vậy tách luật / cần suy nghĩa đổi từ 100/21 thành 115/20 (gồm 14 ca mới).
- Ca fail còn lại (9): R056, R060, R113, R120 cần suy nghĩa (tầng Jev / Luna, làm sau); R101, R102, R109, R142 nhóm `ASK_DATE`; R105 câu hai thứ. Không thuộc PR 1.
- "tôi đổi ý, lấy khung 2" đọc câu chốt khung 2 chứ không ghi ngay: "đổi ý" là dấu hiệu đổi ý (R-41) nên `explicit_slot_pick` không nhận — an toàn hơn và vẫn đúng ý khách.
- Đã bỏ bất biến FSM `slot_candidate_ids ⊆ slot_ids` dự kiến trong plan: sau `SLOT_TAKEN` danh sách khung đọc lại có thể thiếu id cũ; `_unoffered` lọc theo `ctx.slots` nên id không còn tự rơi ra.
- B13 làm gọn hơn plan §6.3: không thêm `ExtractionResult.slot_criteria` / `CallContext.slot_criteria`; IE trả đoạn câu phần khách muốn (`SlotChoice.request`) làm `slot_request`, Dialogue đọc tiêu chí từ đoạn đó như cũ (vẫn quy thứ trần theo R-30), và bỏ khung bị loại qua `refused_slot_ids`. Kết quả như plan, ít trạng thái mới hơn.

---

# Phần 2 — Tầng model cho câu chọn khung (Jev chính, Luna dự phòng)

## Mục tiêu

Theo [plan Jev](../plans/t10-slot-semantic-jev-2026-10-12.md) (owner 12-10: làm luôn; Luna dự phòng khi Jev lỗi dịch vụ hoặc câu không dấu). Ở 4 câu hỏi chọn khung (`OFFER_SLOTS`, `SLOT_READBACK`, `SLOT_REFUSE_CHOICE`, `ASK_SLOT_PREFERENCE`), câu luật không có đường đi ("lúc nào thuận tiện cũng được", "để tôi tính đã", "tôi đang lái xe", "lịch này ai đặt cho tôi") được model đọc, thay vì "em chưa hiểu" → chuyển máy. Cờ `slot_semantic_enabled` **mặc định tắt**: tắt thì hành vi y hệt phần 1.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Chỉ route câu luật không có đường đi; 7 case mentor qc-rs-02..08 **không gọi model lần nào** (đếm số lần gọi, model giả đọc sai mọi câu) | `route_slot_semantic` (`extraction/slot_semantic.py`). Test `test_mentor_cases_never_call_the_slot_model`, `test_rule_decided_answers_at_the_offer_do_not_call_the_model`, `test_answers_without_a_rule_path_call_the_model_once` |
| Model không thấy giờ khung / lịch hẹn / hồ sơ (C3); không trả `slot_id` | `SlotSemanticContext` chỉ có transcript, mã câu hỏi, hướng gọi, hành động chờ, **số** khung. Test kiểm đúng tập trường, state Jev và prompt Luna không có `slot_`, `starts_at`, `apt_` |
| Model không bao giờ mở khóa ghi (C2): chọn khung → câu chốt; thời gian → tra `GET /slots`; còn lại → hỏi lại đúng câu đang chờ | `DialogueManager._slot_by_model`; guardrail `assert_action_confirmed` từ chối bằng chứng `FALLBACK` cho RESCHEDULE / BOOK; `_direct_pick` không ghi khi lượt có model lỗi. Test `test_model_pick_or_any_reads_the_slot_back_without_writing`, `test_model_confirm_at_the_read_back_only_asks_to_say_agree`, … |
| Ma trận ưu tiên §4.9 (nhãn hành động chỉ đi khi chắc; KEEP_OLD → câu A/B; lâm sàng / ngoài phạm vi / hủy) | `resolve_slot_act`. Test `test_priority_matrix` (14 ca), `test_ground_rejects_readings_outside_the_contract` |
| Model lỗi / timeout / bị loại → **đúng kết quả luật**, không `SLOT_CONFLICT`, không đếm thêm §1.1.5, không ghi (C5) | `extract()` và `respond()` (mọi lượt model lỗi ở 4 câu chọn khung). Test `test_model_failure_keeps_the_rule_answer` (error / none / rejected), `test_model_failure_at_the_read_back_reasks_the_same_slot`. Eval `--route-only` = `--baseline` từng câu |
| Chọn provider §4.11: không dấu → chỉ Luna; Jev lỗi dịch vụ → Luna một lần nếu còn ≥ 1,5 s trong trần 4 s; Jev đã trả lời (kể cả bị loại) → không gọi Luna | `SlotSemanticReader`; `invoke_model(..., timeout_s=)` (`model_budget.py`). Test `test_unaccented_answers_go_to_luna_only`, `test_jev_service_failure_falls_back_to_luna_once` (4 trạng thái lỗi), `test_jev_answer_is_final_even_when_ambiguous_or_rejected`, `test_no_fallback_when_the_turn_has_too_little_time_left`, `test_route_budget_is_longer_than_the_default_three_seconds` |
| Adapter Jev (`slot_jev_v1`) và Luna (`slot_reply_v1`) cùng bộ nhãn, cùng kiểm sau model | `slot_semantic_jev.py`, `slot_semantic_luna.py`, `inference/llm/prompt/slot_reply.py`. Test adapter với client / gateway giả; JSON sai, nhãn ngoài câu hỏi, span bịa, khóa lạ đều bị loại |
| Ví dụ criteria / prompt không trùng câu eval hay held-out | Test `test_examples_do_not_leak_eval_sentences` |
| Bộ held-out viết **trước** router / criteria và giữ nguyên | `eval/reschedule/heldout_slot_semantic.csv` (44 câu: 33 cần model, 11 phải giữ nguyên) |

## Kết quả eval (2026-10-12; `reschedule_eval.py`, Orchestrator thật + `mentor_mock()`)

| Bộ | Chỉ luật | Luật + Jev + Luna (`--semantic --repeats 3`) |
| --- | --- | --- |
| `eval/reschedule/cases.csv` (135 holdout) | 126/135 (93,3%), cần suy nghĩa 16/20 | **130/135 (96,3%) cả 3 lần**, cần suy nghĩa **20/20** (R056, R060, R113, R120 giờ đạt) |
| `heldout_slot_semantic.csv` (44) | 26/44 (59,1%) | **42/44 (95,5%) cả 3 lần**; 11/11 câu phải giữ nguyên vẫn đúng |
| Ghi sai / ghi nhầm khung | 0 | **0** (cả 6 lần chạy) |
| Lượt gọi model ở câu chọn khung | — | cases: 11 / 185 lượt (6%, đều Jev); held-out: 18 / 44 (17 Jev, 1 Luna vì không dấu) |
| Độ trễ model ở câu chọn khung | — | p50 542–586 ms, p95 575–857 ms, lâu nhất 2,07 s (Luna); p95 cả lượt ≤ 669 ms |

Ca còn fail đều không qua model (luật đã có đường đi): `ASK_DATE` (R101, R102, R109, R142), R105 "thứ 5 hoặc thứ 6", S021 "thôi bỏ luôn lịch khám đó cho tôi" (luật đọc là bỏ đổi lịch), S034 "lay cai muon hon" (không dấu, luật đọc "muon" là "muốn" → xin khung khác).

## Ghi chú

- Lệch so với thiết kế (đo trên held-out rồi mới chốt, chi tiết ở plan Jev §10): bỏ Noul `decides_now` khỏi request Jev (ra 0,03–0,18 ở mọi câu, chỉ chặn nhầm); `KEEP_OLD` của model luôn thành câu A/B; act `OUT_OF_SCOPE` của Jev ≥ 0,9 tính là ngoài phạm vi; timeout Luna 3 s (lượt đầu cold 2,7 s).
- Luật sửa thêm khi chạy held-out: "cái sớm hơn / cái muộn hơn" chỉ khung 1 / 2 ("sớm hơn" trần vẫn là xin khung khác — R033 / R034); lệnh hủy rõ ở câu mời / câu chốt thắng lời từ chối khung (trừ câu báo bận), vẫn hỏi xác nhận lần hai.
- Hành vi mới không phụ thuộc cờ: lượt model lỗi ở 4 câu chọn khung (kể cả route lâm sàng cũ) đi nhánh luật thay vì câu "đồng ý với khung giờ vừa đọc không" — R122 "lay cai dau" ở `--route-only` hết sai.
- **Bật cờ**: theo plan, bật trên staging trước, đọc trace `slot_act` / `model_route` / độ trễ, rồi owner quyết bật prod. Cần `TYPESAFE_API_KEY` (Jev) và `OPENAI_API_KEY` (Luna) trên server.
- Chi phí: khoảng 1 request Jev mỗi lượt được route (6% lượt ở câu chọn khung trên bộ eval chính); Luna chỉ khi câu không dấu hoặc Jev lỗi.

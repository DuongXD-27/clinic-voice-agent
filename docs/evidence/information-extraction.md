# Evidence: Information Extraction (thiết kế v1.1, contract rev 1.1)

## Mục tiêu

Xây module Information Extraction (IE) theo [docs/information-extraction-design.md](../information-extraction-design.md) v1.1: từ transcript của một lượt và câu bot vừa hỏi (`question_id`), trích và chuẩn hoá các trường `full_name`, `dob`, `intent`, `clinical`, `agreement`, `slot_choice`, `cancel_reason`, `line_signal`, `silent`, mỗi trường có `provenance` và `span` để truy vết.

Phạm vi:

- IE **mù với hồ sơ bệnh nhân**, không ra quyết định nghiệp vụ, không chọn `transfer_reason` (Policy làm).
- Tầng luật viết tay là chính; tuyến sau (NER / LLM tập nhãn đóng) chỉ là interface, bị chặn bởi guard chống bịa đặt.
- Hỗ trợ transcript không dấu (ASR audio mode).

Kết quả mong đợi: `InformationExtractor.extract(ctx, transcript, silence_ms=...)` trả `ExtractionResult` đúng hướng an toàn cho SF-02 → SF-05, có unit test cho từng trường.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Interface dữ liệu §4: mỗi trường có `value`, `provenance`, `span`; phân biệt "không áp dụng" / "không trích được" / `INVALID` | `src/callbot/engine/extraction/schema.py` định nghĩa `Field[T]` (`skipped()`, `nothing()`, `found`), `Provenance` (`EXACT`/`NORMALIZED`/`FALLBACK`/`NONE`), `ExtractionResult` với `to_trace()` cho trace JSONL. Test: `test_trace_is_json_ready` trong `tests/engine/extraction/test_extractor.py` |
| Nguyên tắc 2: IE không thấy hồ sơ bệnh nhân | `TurnContext` (`schema.py`) chỉ có `turn`, `question_id`, `direction`, `now`, `slots`, `presented_slot_ids` — không có trường `verify.*` hay chi tiết lịch hẹn |
| Điều phối theo `question_id`, đúng thứ tự line_signal → clinical → intent → name/dob → agreement → slot → cancel_reason | `InformationExtractor.extract` trong `src/callbot/engine/extraction/extractor.py`. Test: `test_dob_only_when_asked`, `test_cancel_reconfirm_flow_fields`, `test_slot_choice_uses_all_slots_from_context` |
| Bước danh tính không chạy intent nghiệp vụ ("Lê Văn Thôi", "Trần Văn Được" vẫn là tên), chỉ giữ nhãn an toàn | `IDENTITY_SAFE_INTENTS = {REQUEST_HUMAN, NOT_PATIENT, REPEAT_REQUEST}` trong `extractor.py`; `OUT_OF_SCOPE` chỉ xét khi không trích được tên/ngày sinh. Test: `test_identity_step_does_not_run_business_intents`, `test_identity_step_keeps_safety_labels_and_does_not_read_them_as_names`, `test_out_of_scope_at_identity_step_only_when_answer_is_not_an_identifier` |
| §1.1.7: lượt im lặng (`silence_ms > 0`) không tính là failed understanding | `extract` trả `ExtractionResult.only(..., silent=True)`. Test: `test_silent_turn_is_not_a_failed_understanding` |
| §5.9 / §4.2.5: phát hiện voicemail / tổng đài trên outbound, dừng sớm, không đọc lời chào thành tên; người thật nói "tôi đang bận" không phải tín hiệu đường dây | `extract_line_signal` trong `line_signal.py` (cần dấu hiệu tổng đài cho `LINE_BUSY`/`NO_ANSWER`). Test: `test_voicemail_short_circuits_outbound_identity_steps`, `test_line_signal_uses_unreachable_reason_names`, `test_line_signal`, `test_human_speech_is_not_a_line_signal` |
| §5.1 `full_name`: bỏ tiền tố lễ phép, chuẩn hoá Unicode, loại câu không phải tên; NER tắt mặc định | `extract_full_name` trong `full_name.py`; `name_fallback=False` trong `InformationExtractor.__init__`. Test: `test_extracts_normalized_name`, `test_rejects_non_names`, `test_name_fallback_is_off_by_default_and_guarded` |
| §5.2 `dob`: số viết và số đọc tiếng Việt, tự sửa trong câu; mọi chỗ mơ hồ (31/02, thiếu năm, năm 2 chữ số khớp 2 thế kỷ) → `INVALID` | `extract_dob` trong `dob.py`, `parse_number` / `spoken_digits` trong `spoken_numbers.py`. Test: `test_valid_dates`, `test_invalid_is_not_a_date`, `test_no_date_content_is_none`, `test_self_correction_takes_last_value`, `test_provenance_distinguishes_digits_from_spoken_numbers` (`test_dob.py`), `test_parse_number*` (`test_spoken_numbers.py`) |
| §5.4 `intent`: 9 nhãn, thứ tự ưu tiên, chặn phủ định ("không hủy"), nhãn theo chiều gọi (CONFIRM chỉ outbound, BOOK chỉ inbound) | `PRIORITY`, `extract_intent`, `allowed_in_direction` trong `intent.py`. Test: `test_outbound_labels`, `test_priority`, `test_negation_blocks_action_labels`, `test_direction_only_labels`, `test_allowed_restricts_labels`, `test_span_and_provenance` |
| §5.5 `clinical` 3 lớp: EMERGENCY ưu tiên recall, ADVICE_REQUEST cần hành vi hỏi, MENTION ưu tiên precision (không chuyển máy nhầm cuộc đặt lịch) | `extract_clinical` trong `clinical.py`. Test: `test_emergency`, `test_advice_request_needs_asking`, `test_mention_is_not_transferred`, `test_mention_and_none` |
| §5.6 `agreement`: ngưỡng theo hành động được mở khóa; SF-05 — "dạ/vâng" một mình không bao giờ hủy lịch | `extract_agreement` trong `agreement.py`; `_agreement` trong `extractor.py` hạ AGREE → UNCLEAR khi intent/clinical mâu thuẫn. Test: `test_cancel_reconfirm_never_agrees_without_explicit_cancel`, `test_cancel_reconfirm_agrees_on_explicit_cancel_verb`, `test_slot_readback_threshold`, `test_confirm_readback_accepts_any_affirmative`, `test_confirm_readback_traps`, `test_agreement_is_downgraded_when_caller_talks_about_something_else` |
| §5.7 `slot_choice`: chỉ lọc trên `GET /slots` của cuộc gọi, không dựng mốc giờ mới (SF-02); `MATCH` / `AMBIGUOUS` / `NO_MATCH` | `extract_slot_choice`, `parse_slot_criteria`, `filter_slots` trong `slot_choice.py`; `SlotCriteria` trong `schema.py`. Test: `test_match`, `test_ambiguous_returns_all_candidates`, `test_half_past_two_without_period_matches_the_only_listed_time`, `test_no_match`, `test_no_criteria_is_none`, `test_criteria_parsing_does_not_double_read_tokens` |
| §5.8 `cancel_reason`: chỉ ánh xạ cụm tường minh, nhiều lý do → `UNSPECIFIED` | `extract_cancel_reason` trong `cancel_reason.py`. Test: `test_explicit_reasons`, `test_unspecified` |
| Tuyến sau chống bịa đặt: chỉ gọi khi luật không khớp, `span` phải nằm trong transcript, không được mở khóa hủy lịch | `FallbackExtractor` (Protocol) và `guard_fallback` trong `fallback.py`. Test: `test_fallback_is_only_called_when_rules_find_nothing`, `test_fallback_span_must_be_in_transcript`, `test_fallback_cannot_unlock_cancellation` |
| §5.10 transcript không dấu: khớp bản bỏ dấu của từ khoá, loại cụm trùng nghĩa ("dạ"/"đã", "đúng"/"đừng", "từ từ"/"tự tử") | `normalize`, `is_unaccented`, `compile_phrases(..., unaccented_exclude)`, `find_phrase` trong `text.py`. Test: toàn bộ `tests/engine/extraction/test_unaccented.py` (intent, clinical, agreement, tên, ngày sinh, cancel_reason, line_signal, slot_choice), `test_text.py` |

## File liên quan

- `src/callbot/engine/extraction/__init__.py`
- `src/callbot/engine/extraction/schema.py`
- `src/callbot/engine/extraction/extractor.py`
- `src/callbot/engine/extraction/text.py`
- `src/callbot/engine/extraction/spoken_numbers.py`
- `src/callbot/engine/extraction/full_name.py`
- `src/callbot/engine/extraction/dob.py`
- `src/callbot/engine/extraction/intent.py`
- `src/callbot/engine/extraction/clinical.py`
- `src/callbot/engine/extraction/agreement.py`
- `src/callbot/engine/extraction/slot_choice.py`
- `src/callbot/engine/extraction/cancel_reason.py`
- `src/callbot/engine/extraction/line_signal.py`
- `src/callbot/engine/extraction/fallback.py`
- `tests/engine/extraction/test_*.py` (12 file)
- `docs/information-extraction-design.md`

## Luồng hiện tại

`InformationExtractor.extract(ctx: TurnContext, transcript, silence_ms)` cho một lượt:

```text
transcript + TurnContext(question_id, direction, now, slots, presented_slot_ids) + silence_ms
  -> silence_ms > 0:            mọi trường skipped, silent=True                 -> trả về
  -> line_signal (outbound, trước/trong bước danh tính):
                                VOICEMAIL | LINE_BUSY | NO_ANSWER               -> trả về (chỉ line_signal)
  -> clinical (mọi lượt):       EMERGENCY | ADVICE_REQUEST | MENTION | NONE
  -> intent:                    bước danh tính chỉ REQUEST_HUMAN / NOT_PATIENT / REPEAT_REQUEST;
                                bước khác: luật -> (nếu NONE và có fallback) tuyến sau + guard_fallback
  -> full_name (ASK_NAME, intent NONE, không phải clinical chuyển máy): chuỗi | NONE
  -> dob (ASK_DOB):             date | INVALID | NONE
  -> OUT_OF_SCOPE (bước danh tính, không trích được tên/ngày sinh)
  -> agreement (ASK_ATTENDANCE / CONFIRM_READBACK / SLOT_READBACK / CANCEL_RECONFIRM):
                                AGREE | REFUSE | UNCLEAR, hạ AGREE -> UNCLEAR nếu intent/clinical mâu thuẫn
  -> slot_choice (OFFER_SLOTS): MATCH(slot_id) | AMBIGUOUS(slot_ids) | NO_MATCH, lọc trên ctx.slots
  -> cancel_reason (CANCEL_RECONFIRM / ASK_CANCEL_REASON / intent CANCEL): mã Phụ lục A | UNSPECIFIED
  -> ExtractionResult (to_trace() -> JSONL)
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`).

```powershell
make check
```

`make check` chạy lần lượt (giống bước test trên CI):

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
```

Chỉ chạy test của phần liên quan: `python -m pytest tests\engine\extraction -q`

## Kết quả xác minh cục bộ (2026-09-16)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass (`All checks passed!`) |
| `python -m ruff format --check src tests` | Pass (`92 files already formatted`) |
| `python -m pytest -q` | Pass (352 passed, 2 warnings — DeprecationWarning từ `starlette.testclient`) |
| `python -m pytest tests\engine\extraction -q` | Pass (334 passed) |
| `make check` | Pass |

## Ghi chú

- **Chưa nối vào pipeline:** `src/callbot/engine/orchestrator.py` vẫn dùng `callbot.engine.nlu.extractor.InformationExtractor` (bản heuristic cũ). Module `callbot.engine.extraction` mới chỉ được dùng trong unit test; việc thay thế trong orchestrator, Dialogue Manager và Policy là task tiếp theo (xem Phụ lục "Đối chiếu code hiện tại" của thiết kế).
- **Tuyến sau chưa có cài đặt:** `FallbackExtractor` mới là Protocol; test dùng fake. NER cho tên tắt mặc định (`name_fallback=False`), bật theo kế hoạch tuần 3; LLM cho intent/agreement theo kế hoạch tuần 4 (§8).
- **Ngoài phạm vi IE:** so khớp tên/ngày sinh với hồ sơ (Verifier), bộ đếm §1.1.5, giới hạn lần thử danh tính, chọn `transfer_reason` (Policy), output guard lời thoại (§7). Số điện thoại (§5.3) đang hoãn.
- **Phụ thuộc câu hỏi mở (§10):** nhóm đang hiểu MENTION không bắt buộc chuyển máy (câu 6); REPEAT_REQUEST và agreement mơ hồ lần đầu không tính là failed understanding (câu 7); lượt nào nhận clip voicemail (câu 9). Nếu PO trả lời khác, chủ yếu đổi ở Policy — IE giữ nguyên nhãn.
- **Reviewer lưu ý:** các hướng hiệu chỉnh ngược nhau là có chủ đích (EMERGENCY ưu tiên recall, không xét phủ định; MENTION ưu tiên precision; `dob` thà `INVALID`; `CANCEL_RECONFIRM` lệch về UNCLEAR). Đừng "làm cho nhất quán" giữa các bộ này.

# Evidence: F-04 — Nối Information Extraction vào đường HTTP, xoá NLU cũ

## Mục tiêu

`engine.extraction.InformationExtractor` chạy trên đường HTTP thật thay `engine/nlu`. IE chỉ nhận ngữ cảnh hội thoại được phép; Policy và Dialogue dùng thẳng `ExtractionResult`.

Ngoài phạm vi: LLM fallback, audio HTTP. Lưu phiên, thứ tự lượt và nhật ký lệnh nằm ở [F-03](f03-session-store.md); module IE nằm ở [information-extraction.md](information-extraction.md).

## Bằng chứng trong repo

| Tiêu chí | Vị trí code | Test |
| --- | --- | --- |
| Factory / orchestrator dùng `extraction.InformationExtractor`; Policy/Dialogue nhận `ExtractionResult`, không adapter về `NLUResult`; xoá `engine/nlu` | `engine/__init__.py::create_orchestrator`, `orchestrator.py`, `policy/policy_engine.py`, `dialogue/manager.py` | Toàn bộ test engine / HTTP; không còn import `engine.nlu` |
| `TurnContext` từ session: lượt, `question_id`, hướng gọi, thời điểm tiếp nhận (+07:00, lưu để xử lý lại), slot hiện hành, thứ tự đã đọc | `orchestrator.build_turn_context`; `call_turns.received_at` | `test_crash_before_clinic_write_recovers_safely` (xử lý lại dùng `received_at` cũ) |
| Không truyền hồ sơ / tên, ngày sinh chuẩn / `verify.*` vào IE; không "sửa" lời người gọi theo hồ sơ | `build_turn_context` | `test_extractor_never_sees_patient_identity` |
| Dialogue đặt mã câu hỏi; xin nhắc lại đọc lại câu đang chờ; im lặng / câu nhắc chung không đổi câu hỏi | `DialogueManager._ask`, `respond`, `silence` | `test_repeat_request_rereads_pending_question_without_counting`, `test_opening_discloses_ai_assistant` |
| Câu hỏi ý định inbound là câu hỏi mở; "vâng" không thành đặt lịch | `templates.ASK_INTENT_INBOUND` | `test_inbound_booking_with_open_intent_question` |
| `AGREE` mới ghi; `REFUSE` bỏ hành động; `UNCLEAR` hỏi lại A/B; Gateway kiểm bằng chứng đúng câu hỏi / hành động / slot | `DialogueManager._attendance`, `_slot_readback`, `_cancel_reconfirm`; `guardrails.assert_action_confirmed` | `test_cancel_requires_explicit_second_confirmation`, `test_cancel_refused_keeps_appointment`, `test_confirm_attendance_in_one_readback_turn` |
| Bộ đếm: xin nhắc lại và slot mơ hồ không tính; `UNCLEAR` từ lần thứ hai liên tiếp mới tính; im lặng đếm riêng | `PolicyEngine.register_understanding`, `check_silence` | `test_unclear_confirmation_counts_from_second_time`, `test_ambiguous_slot_choice_does_not_pick_first_slot`, `test_two_failed_understandings_transfer` |
| Chọn slot `MATCH / AMBIGUOUS / NO_MATCH` trên toàn bộ slot Clinic; từ chối ở bước chọn slot bỏ hành động, không ghi | `_slot_choice`; `extractor.py` chạy agreement (không bao giờ AGREE) ở `OFFER_SLOTS` | `test_reference_call_reschedule`, `test_ambiguous_slot_choice_does_not_pick_first_slot`, `test_refusing_slots_drops_pending_action_without_writing` |
| Tín hiệu lâm sàng, xin người thật, không phải bệnh nhân, đường dây vào Policy; outbound `UNREACHABLE` theo lý do; inbound im lặng quá ngưỡng chuyển máy, không tạo lịch | `PolicyEngine.check_signals`, `check_silence` | `test_clinical_question_transfers`, `test_request_human_transfers_before_verification`, `test_voicemail_ends_unreachable_without_disclosing`, `test_outbound_three_silent_turns_marks_unreachable`, `test_inbound_silence_transfers_without_booking` |
| Clinic: `/unreachable`, `confirmed=true` khi hủy đủ bằng chứng, `SLOT_TAKEN` → đọc lại slot, xác nhận mới | `clinic_mock_client.py`, `ports.py`, `ClinicGateway` | `test_reschedule_slot_taken_reoffers_and_needs_new_confirmation`, `test_contract_clinic_client_never_requests_harness_paths` |
| Kết quả extraction (provenance/span) lưu trong bản ghi lượt, xuất qua trace; lỗi trace không làm lượt chạy lại | `call_turns.extraction`; `CallOrchestrator._trace` sau commit | `test_extraction_with_provenance_is_stored_on_turn_record`, `test_information_extraction_over_http`, `test_trace_failure_does_not_rerun_committed_turn` |
| IE qua HTTP: xác minh, xác nhận, hủy, đổi lịch, đặt lịch, voicemail | Orchestrator thật trên `FakeClinicAPI` | `test_information_extraction_over_http[*]` |
| Chuẩn hoá tên chuyển sang verification, giữ quy tắc đối chiếu | `verification/names.py` | `test_name_normalizer_moved_to_verification`, `tests/engine/test_identity.py` |
| Tài liệu liên quan cập nhật | [information-extraction.md](information-extraction.md), phụ lục [information-extraction-design.md](../reference/information-extraction-design.md), [ai-callbot-architecture.md](../reference/ai-callbot-architecture.md) | — |

## File liên quan

- `src/callbot/engine/__init__.py`, `orchestrator.py`
- `src/callbot/engine/dialogue/manager.py`, `templates.py`, `prompts.py`
- `src/callbot/engine/policy/policy_engine.py`, `guardrails.py`
- `src/callbot/engine/extraction/extractor.py`
- `src/callbot/engine/tools/clinic_gateway.py`, `clinic_mock_client.py`, `ports.py`
- `src/callbot/engine/verification/names.py`, `identity.py`
- Xoá: `src/callbot/engine/nlu/`
- `tests/engine/test_orchestrator.py`, `tests/engine/fake_clinic.py`, `tests/engine/test_identity.py`
- `tests/transports/http/test_calls.py`

## Luồng một lượt (phần hội thoại)

```text
CallOrchestrator._process(ctx, caller, received_at)
  Policy.check_preconditions
  IE.extract(TurnContext(turn, question_id, direction, received_at, slots, presented), transcript, silence_ms)
  Policy.check_silence       -> REPROMPT | outbound UNREACHABLE(SILENCE) | inbound TRANSFER(NOT_UNDERSTOOD)
  Policy.check_signals       -> line_signal -> UNREACHABLE; clinical / REQUEST_HUMAN / NOT_PATIENT / OUT_OF_SCOPE -> TRANSFER
  Dialogue.respond theo question_id -> Reply(action, understanding)
    ASK_NAME / ASK_DOB       -> Verifier
    CONFIRM_READBACK         -> AGREE: ghi CONFIRMED | REFUSE: hỏi đổi/hủy | UNCLEAR: câu A/B
    ASK_INTENT               -> CONFIRM | CANCEL | RESCHEDULE (outbound); BOOK (inbound)
    OFFER_SLOTS              -> MATCH: đọc lại | AMBIGUOUS: đọc ≤3 slot | REFUSE: bỏ hành động
    SLOT_READBACK            -> AGREE: reschedule/book (SLOT_TAKEN -> đề xuất lại) | REFUSE | UNCLEAR
    CANCEL_RECONFIRM         -> AGREE (động từ hủy tường minh): ghi CANCELLED | REFUSE | UNCLEAR
  Policy.register_understanding -> TRANSFER(NOT_UNDERSTOOD) sau 2 lần
```

## Quy trình xác minh

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q tests/engine tests/transports
```

## Kết quả xác minh cục bộ (2026-09-17)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` (kết quả lịch sử trước khi chuyển session sang Redis) | 493 passed, 1 skipped, 1 failed |
| `python -m pytest -q tests/engine/test_orchestrator.py` | 22 passed |
| `python -m pytest -q tests/engine/test_identity.py` | 13 passed |
| `python -m pytest -q tests/engine/extraction` | 334 passed |
| `python -m pytest -q tests/transports` | 39 passed |

- Mốc trước F-03/F-04: 404 passed, 1 skipped, 1 failed.
- Test lỗi: `tests/speech/test_narrowband.py::test_settings_default_to_narrowband` — lỗi có sẵn về cấu hình Speech sample rate, không phải regression.

## Ghi chú

- **`CONFIRM_READBACK` gộp một lượt** (Figure 0 rev 1.1): outbound sau xác minh đọc tóm tắt + ngày, giờ, cơ sở + hỏi đến được không; "Có, tôi đến được" ghi `CONFIRMED` ngay. "Tôi sẽ đến" không có từ đồng ý → hỏi lại bằng câu lựa chọn.
- **Inbound** chỉ đặt lịch mới; yêu cầu hủy / đổi lịch chuyển máy `OUT_OF_SCOPE`.
- **`NOT_PATIENT`** chuyển máy `IDENTITY_FAILED` (câu hỏi mở §10.8 của thiết kế).
- **Cửa sổ slot** là 14 ngày từ thời điểm tiếp nhận lượt (giới hạn của mock). Mock chung chỉ có slot quanh 14-10-2026, nên đổi lịch trên mock thật trước thời điểm đó không có slot → chuyển máy `OUT_OF_SCOPE`.
- **Chưa làm:** so khớp tên theo từ căn cuối (§5.1) — Verifier vẫn so bằng nhau sau khi bỏ dấu; giới hạn lần thử danh tính riêng từng trường (§6.2); LLM tuyến sau; output guard SF-02.

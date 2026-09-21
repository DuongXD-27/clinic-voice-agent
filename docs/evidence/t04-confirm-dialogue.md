# Evidence: T-04 — Hội thoại Confirm

**Owner:** A (Hoàn) · **Plan:** `docs/plans/t04-confirm-dialogue.md` · **Branch:** `feature/t04-confirm-dialogue` (từ `main` `db669f7`) · **Ngày:** 18-09-2026

## Mục tiêu

Hội thoại xác nhận đến khám (outbound): nhận ý định tham dự, đọc lại ngày–giờ–cơ sở, nhận đồng ý đúng nội dung, xử lý từ chối / chưa rõ, gọi Gateway khi đủ điều kiện.

Điều kiện hoàn thành (task-breakdown §3): **chỉ trả `CONFIRMED` sau khi API xác nhận ghi thành công.**

Luồng Confirm đã có từ F-04. T-04 sửa các lỗi hiểu sai câu trả lời đo được khi chạy thử (plan §2, G-1..G-9), cho câu đọc lại có tên cơ sở, kiểm tra kết quả ghi, và khóa bằng test ở IE, Dialogue, HTTP.

Quyết định (plan §6):

| # | Quyết định | Căn cứ |
| --- | --- | --- |
| Q-1 | "Tôi sẽ đến", "xác nhận", "giữ nguyên lịch" ở câu đọc lại là đồng ý | Contract Bảng 1: "Patient states or agrees they will attend" |
| Q-2 | "Vâng" / "dạ" / "ừ" là xác nhận, kể cả kèm lời khác | Chốt với owner 18-09-2026; §1.1.3 "agrees to that read-back" |
| Q-2b | Câu ngập ngừng ("để xem", "chắc là", "có lẽ", "chưa chắc") → chưa rõ, ở mọi câu hỏi xác nhận | Theo đề xuất |
| Q-3 | Chưa rõ → đọc lại ngày, giờ, cơ sở bằng câu có / không (bỏ câu A/B `ATTENDANCE_CHOICE`) | Kiến trúc §3.2 "Chưa rõ → O_READ"; hệ quả của Q-2 |
| Q-4 | Tên cơ sở từ bảng `clinic_id → tên` (seed Mock), id lạ → "Vinmec" | §1.1.3 "read back date, time **and clinic**"; Mock chỉ trả `clinic_id` |
| Q-5 | Không hỏi xác nhận lại khi lịch đổi giữa lượt đọc và lượt ghi | §4.2.5 / Listing 5 chỉ yêu cầu đọc lại + cùng key (Gateway T-03 đã làm); không có điều khoản xác nhận lại |
| Q-6 | Inbound "xác nhận lịch" → chuyển máy ngay, `OUT_OF_SCOPE` | §1 (inbound chỉ có đặt lịch mới), §1.1.5 "MUST transfer on anything outside these scenarios"; §2.1 không chấm `transfer_reason` inbound |

## Bằng chứng trong repo

| Tiêu chí | Vị trí code | Test chứng minh |
| --- | --- | --- |
| AC-1 Nhận ý định tham dự: khẳng định sẽ đến ở câu đọc lại là đồng ý; `ASK_INTENT` outbound `CONFIRM` → đọc lại | `agreement.extract_agreement(attendance=...)`; `extractor._agreement` truyền span intent `CONFIRM`; `_KEEP` ("giữ lịch", "giữ nguyên lịch"); `_NOT_CANCEL` bị bỏ qua ở câu hỏi đến khám | `test_confirm_dialogue.py::test_agreement_confirms_in_one_turn[*]` (9 câu); `::test_refusal_drops_pending_and_changed_mind_needs_new_readback`; `test_extractor.py::test_stated_attendance_is_agreement_at_readback[*]`; `test_agreement.py::test_attendance_agrees_on_polite_words_and_keeping[*]`, `::test_stated_attendance_agrees_only_at_attendance_questions[*]` |
| AC-2 Đọc lại ngày–giờ–cơ sở trong mọi câu mở khóa `CONFIRMED` | `templates.attendance_facts`, `clinic_name`, `CLINIC_NAMES`; `appointment_summary`, `attendance_readback`, `attendance_reread`, `keep_appointment` dùng chung | `::test_summary_reads_back_date_time_and_clinic_name`, `::test_unknown_clinic_id_is_not_given_a_guessed_name`, `::test_unclear_answer_rereads_without_writing[*]`; HTTP `test_calls.py::test_confirm_over_http_reports_confirmed_only_after_write` |
| AC-3 Đồng ý đúng nội dung: "vâng/dạ/ừ" ghi; ngập ngừng không ghi; đồng ý chỉ tính cho câu đọc lại ở lượt trước | `agreement._HEDGE` (xét sau `_CONTRAST`, trước tín hiệu đồng ý); `guardrails.assert_action_confirmed` (có sẵn) | `test_agreement.py::test_hedging_never_agrees[*]` (7 câu × `CONFIRM_READBACK`, `SLOT_READBACK`); `::test_attendance_traps[*]`; `test_confirm_dialogue.py::test_yes_after_reread_confirms_with_evidence_of_that_turn` (bằng chứng lượt 4, câu hỏi lượt 3) |
| AC-4 Chưa rõ: đọc lại, câu có/không; lần 1 không tính; UNCLEAR ×3 → `NOT_UNDERSTOOD` + `/transfer` | `DialogueManager._attendance` → `t.attendance_reread`, `Understanding "UNCLEAR"` | `::test_unclear_answer_rereads_without_writing[*]` (6 câu, gồm "được không em?", "mấy giờ nhỉ?"), `::test_unclear_three_times_transfers_not_understood` |
| AC-5 Từ chối: bỏ hành động chờ, không ghi; đổi ý phải đọc lại + đồng ý mới | `_attendance` REFUSE → `clear_pending`, `ASK_CHANGE_OR_CANCEL` (có sẵn) | `::test_refusal_drops_pending_and_changed_mind_needs_new_readback`, `::test_yes_to_change_or_cancel_question_does_not_confirm`, `::test_cancel_or_reschedule_at_readback_does_not_confirm[*]` |
| AC-6 Gọi Gateway khi đủ điều kiện; `VERSION_CONFLICT` đọc lại + cùng key (§4.2.5) | Gateway T-03 (không đổi) | `::test_version_conflict_retries_with_same_key_then_confirms` (2 request `c_t04_conflict:3:confirm`); `test_clinic_gateway.py` confirm (T-03) |
| AC-7 Chỉ `CONFIRMED` sau khi API ghi thành công | `_attendance`: `status == "CONFIRMED"` mới `_finish`; câu báo dựng từ bản ghi Mock trả về (`t.confirmed(ctx, written)`); status khác → `WriteOutcomeUnknown`; bỏ nhánh `CONFIRMED` trong `t.done` | `::test_success_message_uses_the_written_record`, `::test_rejected_write_is_system_error_not_confirmed`, `::test_unknown_write_outcome_blocks_the_turn_instead_of_reporting`, `::test_write_without_confirmed_status_is_not_reported_as_confirmed`, `::test_resent_confirm_turn_does_not_write_twice`; HTTP `::test_rejected_confirm_over_http_is_transferred`, `::test_unknown_confirm_outcome_over_http_needs_reconciliation` (409 `CALL_RECONCILIATION_REQUIRED`) |
| AC-8 Ngoại lệ vẫn kiểm tra ở bước xác nhận | Policy `check_silence`/`check_signals` (có sẵn) chạy trước Dialogue | `::test_exceptions_at_readback_transfer_without_confirming[*]` (lâm sàng, xin nhân viên), `::test_silence_and_repeat_request_keep_the_readback_question` |
| AC-9 Inbound "xác nhận lịch" → chuyển máy ngay, không ghi | `intent._CROSS_DIRECTION_KEYWORDS` (inbound `CONFIRM` chỉ cho cụm "xác nhận lịch …"); `DialogueManager._intent` inbound `CONFIRM` → `OUT_OF_SCOPE` | `::test_inbound_confirm_request_transfers_at_once_without_write`, `::test_inbound_attendance_wording_is_not_mistaken_for_confirm`; `test_intent.py::test_inbound_confirm_only_on_existing_appointment_wording[*]` |
| Không đổi ngưỡng hủy / chọn slot (SF-05) | `_REFUSE` vẫn chứa "giữ lịch", "không hủy"; `attendance` chỉ xét ở `CONFIRM_READBACK`/`ASK_ATTENDANCE` | `test_agreement.py::test_keeping_is_still_refusal_outside_attendance[*]`; `test_extractor.py::test_stated_attendance_does_not_unlock_other_writes`; toàn bộ test SF-05 hiện có không đổi, xanh |

### Trước / sau (chạy thử Orchestrator + fake, outbound đã xác minh, câu ở `CONFIRM_READBACK`)

| Câu người gọi | Trước T-04 | Sau T-04 |
| --- | --- | --- |
| "ờ để xem" | **ghi `CONFIRMED`** | đọc lại, không ghi |
| "chắc là được", "có lẽ vậy", "vâng để tôi xem lại" | **ghi `CONFIRMED`** | đọc lại, không ghi |
| "tôi sẽ đến" ×2 | câu A/B lặp → `NOT_UNDERSTOOD` | `CONFIRMED` lượt 1 |
| "xác nhận" | câu A/B | `CONFIRMED` |
| "vâng, giữ lịch", "giữ nguyên lịch", "không hủy đâu, tôi vẫn đến" | hỏi "đổi hay hủy?" | `CONFIRMED` |
| Câu đọc lại / câu báo | "… tại Vinmec", "Dạ, em đã xác nhận lịch khám." | "… tại Vinmec Times City", câu báo có ngày giờ + cơ sở từ bản ghi Mock |
| Inbound "tôi muốn xác nhận lịch khám" | hỏi lại, lượt 2 `NOT_UNDERSTOOD` | `TRANSFERRED/OUT_OF_SCOPE` ngay, không ghi |
| "vâng", "Có, tôi đến được.", "không", "không đến được", "vâng nhưng tôi muốn đổi giờ", "vâng, à mà tôi đau ngực" | — | không đổi |

## File liên quan

Sửa (code):
- `src/callbot/engine/extraction/agreement.py` — `_HEDGE`; tách `_REFUSE_COMMON` / `_KEEP_WORDS` / `_NOT_CANCEL_WORDS`; `_ATTENDANCE_REFUSE`; tham số `attendance`
- `src/callbot/engine/extraction/extractor.py` — truyền span intent `CONFIRM` vào `extract_agreement`
- `src/callbot/engine/extraction/intent.py` — `_CROSS_DIRECTION_KEYWORDS` (inbound "xác nhận lịch …")
- `src/callbot/engine/dialogue/manager.py` — `_attendance` (kiểm tra kết quả ghi, đọc lại khi chưa rõ); `_intent` inbound `CONFIRM`
- `src/callbot/engine/dialogue/templates.py` — `CLINIC_NAMES`, `clinic_name`, `attendance_facts`, `attendance_reread`, `confirmed`; bỏ `ATTENDANCE_CHOICE` và nhánh `CONFIRMED` của `done`

Test:
- Mới: `tests/engine/test_confirm_dialogue.py` (34 test)
- Thêm case: `tests/engine/extraction/test_agreement.py`, `test_extractor.py`, `test_intent.py`, `test_unaccented.py`; `tests/transports/http/test_calls.py` (3 test HTTP)
- Sửa (B, cần B review): `tests/engine/tools/test_clinic_gateway.py` — xem Ghi chú

Tài liệu: `docs/reference/information-extraction-design.md` §5.6; `docs/reference/ai-callbot-architecture.md` §4.2 (dòng `VERSION_CONFLICT`), §5 (Dialogue Manager); `docs/plans/t04-confirm-dialogue.md`.

## Luồng hiện tại

```text
Sau VERIFIED (outbound): appointment_summary = khoa + attendance_facts (giờ, ngày, tên cơ sở) + "có đến được không"
                          CONFIRM_READBACK, AWAITING_INTENT

Lượt n: Policy (im lặng, voicemail, lâm sàng, xin nhân viên, ngoài phạm vi) -> IE -> Dialogue._attendance
  IE agreement (câu hỏi đến khám):
    câu hỏi đuôi / từ hỏi / "nhưng" / ngập ngừng        -> UNCLEAR
    bỏ "không hủy"; từ chối ("không", "thôi", ...)       -> REFUSE  (kèm tín hiệu đồng ý -> UNCLEAR)
    "có/được/đúng", "vâng/dạ/ừ", "giữ lịch", câu khẳng định sẽ đến (intent CONFIRM) -> AGREE
  Dialogue:
    intent CANCEL | RESCHEDULE -> nhánh hủy / đổi lịch (không đổi)
    AGREE   -> bằng chứng -> Gateway.confirm (FSM + guardrail + If-Match + key; VERSION_CONFLICT: đọc lại, cùng key)
               status CONFIRMED  -> "đã xác nhận lịch khám {facts từ bản ghi Mock}"   ENDED/CONFIRMED
               status khác       -> WriteOutcomeUnknown -> 409 CALL_RECONCILIATION_REQUIRED
               ClinicWriteRejected -> TRANSFERRED/SYSTEM_ERROR ;  chưa rõ kết quả -> 409 đối soát
    REFUSE  -> bỏ hành động chờ, "đổi lịch hay hủy lịch?"                           ASK_INTENT
    UNCLEAR -> attendance_reread (đọc lại + câu có/không)   lần 1 không tính, ×3 -> NOT_UNDERSTOOD
Inbound ASK_INTENT: "xác nhận lịch …" -> TRANSFERRED/OUT_OF_SCOPE, không ghi Mock
```

## Quy trình xác minh

```powershell
make check
```

Chỉ phần T-04: `python -m pytest tests\engine\test_confirm_dialogue.py tests\engine\extraction tests\transports\http\test_calls.py -q`

## Kết quả xác minh cục bộ (18-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass (138 file) |
| `python -m pytest -q` | Pass — 979 passed, 21 skipped |
| `make check` | Pass |
| `python -m pytest -q tests/engine/test_confirm_dialogue.py` | 34 passed |
| `python -m pytest -q tests/engine/extraction/test_agreement.py` | 93 passed |
| `python -m pytest -q tests/transports/http/test_calls.py` | 42 passed |
| `python -m pytest -q tests/engine/tools/test_clinic_gateway.py` | 24 passed |

Mốc trước T-04 trên `main` `db669f7`: 886 passed, **6 failed**, 21 skipped (xem Ghi chú); sau khi sửa helper test của T-03: 892 passed.

Contract test `live` (`CLINIC_MOCK_LIVE=1`): chưa chạy — T-04 không đổi Gateway / client.

## Ghi chú

- **`main` đang đỏ trước T-04 (cần B review).** 6 test confirm/cancel của T-03 (`test_clinic_gateway.py`) fail vì helper đặt `identity_step = "VERIFIED"` mà không có `identity_lookup = "LOADED"` và `patient_id`. Invariant FSM của T-02 bắt buộc hai trường này (`fsm.check_invariants`). T-02 và T-03 merge độc lập nên CI của từng PR không thấy nhau. T-04 thêm helper `_verify(ctx)` đặt đủ ba trường và dùng ở 3 chỗ; mọi assert giữ nguyên, logic Gateway không đổi. Cách làm giống T-02 Q-4 (A sửa test của B, B review).
- **Mock trả 2xx mà status không phải `CONFIRMED`:** plan ban đầu định chuyển `SYSTEM_ERROR`. Không làm được vì lệnh đã `SUCCEEDED` trong nhật ký, nên F-03 xóa nội dung phiên và chặn mọi lệnh ghi tiếp theo (`/transfer` → `ReconciliationRequired`). Bot chặn lượt để đối soát (`WriteOutcomeUnknown` → 409): không báo thành công, không ghi thêm. Mock thật luôn trả `CONFIRMED` khi 2xx, nên đây chỉ là lưới an toàn.
- **Gửi lại lượt đã `CONFIRMED`** nhận `CallEnded` (F-03 xóa nội dung sau khi ghi Clinic), không phải phản hồi cũ; không có lần ghi thứ hai.
- **Tên cơ sở (Q-4):** bảng `CLINIC_NAMES` lấy từ seed của Mock (`clinic-mock/src/clinic_mock/store.py::CLINICS`), vì API không có `/clinics` và appointment không có `clinic_name`. Nếu harness chấm dùng `clinic_id` khác, bot đọc "Vinmec" (không đoán). Nên hỏi `#residency-batch03` xem harness có kiểm tên cơ sở trong `utterance` không; nếu có dữ liệu khác, chuyển bảng sang `EngineSettings`.
- **Q-2b ảnh hưởng `SLOT_READBACK`:** "chắc là được" trước đây mở khóa đổi lịch / đặt lịch; nay là UNCLEAR. Ngưỡng khác của `SLOT_READBACK` và `CANCEL_RECONFIRM` không đổi.
- **Chưa làm, thuộc task khác:**
  - Lịch đổi nội dung giữa lượt đọc lại và lượt ghi (Q-5): ghi theo §4.2.5, không hỏi lại. Nếu đội muốn giữ chính sách "xác nhận lại" ở kiến trúc §4.2 → T-12 (B).
  - `/confirm` bị từ chối vì lịch đã ở trạng thái cuối → `/transfer` cũng bị từ chối, nhưng `DialogueManager.transfer` vẫn trả `outcome=TRANSFERRED` (có sẵn từ trước, trái kiến trúc §4.2 "không tuyên bố Mock đã có `TRANSFERRED`") → T-06 / T-12.
  - Retry 429/503 khi confirm → T-12.
- `SCHEMA_VERSION` giữ 1: T-04 không thêm trường vào `CallContext`, không lưu trạng thái lịch hẹn (§4.2.2).

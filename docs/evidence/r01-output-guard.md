# Evidence: R-01 — Output Guard

**Owner:** A (Hoàn) · **Ngày:** 28-09-2026 · **Baseline:** `main` `1062041` · **Plan:** `docs/plans/r01-output-guard.md` (Rev 6)

## Mục tiêu

Mọi câu bot sắp nói, dù trả text qua HTTP hay đưa vào TTS qua LiveKit, phải qua **một** chốt kiểm tra đầu ra trong core. Chốt này chặn bốn loại vi phạm:

1. Lộ chi tiết lịch hẹn khi chưa xác minh danh tính, kể cả trên voicemail (SF-03).
2. Đọc slot hoặc thông tin lịch không khớp dữ liệu gốc Gateway trả về (SF-01, SF-02).
3. Nội dung tư vấn lâm sàng (SF-04).
4. Báo thành công khi chưa có bằng chứng API ghi thành công, với đúng status và đúng đối tượng, trong chính lượt đó.

Guard không tin nội dung tự khai. Một câu chỉ được nói khi biết chắc câu đó do một template đã đăng ký tạo ra, và render lại template đó từ dữ liệu gốc của Gateway cho ra đúng nguyên văn.

Hai điểm plan để ngỏ (§6), triển khai theo đề xuất trong plan:
- Guard chạy ở chế độ `enforce`, không có chế độ `shadow`.
- Lời mở đầu bị chặn trả mã mới `503 CALL_START_BLOCKED`.

## Bằng chứng trong repo

| Acceptance criterion | Vị trí code | Test chứng minh |
| --- | --- | --- |
| HTTP và Phone dùng **cùng một** cơ chế; transport không có kiểm tra riêng, không có đường vòng | Guard chỉ được gọi từ `CallOrchestrator`: `_opening` (trước `sessions.open` lưu phiên) và `_process` → `_settle` → `_guard` (trước `_apply`/commit, mọi nhánh kể cả exception) | `tests/transports/test_no_business_rules.py` (transport không import `callbot.engine.policy`, không dựng `BotAction`). Parity: `test_in_turn_violation_returns_the_guarded_utterance` (HTTP) và `test_in_turn_violation_speaks_the_guarded_utterance` (LiveKit, orchestrator thật) cùng ra `DONE_SAFE["CONFIRMED"]` |
| OG-0: chỉ nói câu đã đăng ký (hằng tĩnh, renderer có trong ledger của lượt, hoặc đọc lại câu hỏi của lượt trước); tham số chuỗi phải trong miền khai báo | `policy/utterances.py` (`static`, `@renderer`, `str_args`, ledger ContextVar); mọi câu trong `dialogue/templates.py` đã đăng ký; `prefix` chỉ nhận `SLOT_PREFIXES`; `output_guard._origin` | `test_handwritten_utterance_is_blocked` (có và không có ngày giờ), `test_registered_forms_pass`, `test_success_constant_as_slot_prefix_is_rejected`, `test_silence_reprompt_only_wraps_the_prior_question`, `test_dialogue_never_builds_bot_action_from_a_literal` |
| OG-1 (SF-03): câu lộ lịch khi chưa xác minh, hoặc khi outcome `UNREACHABLE`. Câu hỏi động của lượt trước đọc lại được coi là lộ lịch (fail-closed) | `output_guard._disclosure`, `_reread` | `test_disclosing_render_before_verification_is_blocked`, `test_disclosing_render_on_voicemail_is_blocked`, `test_rereading_a_dynamic_question_on_voicemail_is_blocked[False/True]`, `test_rereading_a_static_question_on_voicemail_passes`, `test_every_question_renderer_is_declared_as_disclosing` |
| OG-2/OG-3 (SF-01/SF-02): ref phải có nguồn và đúng phạm vi; render lại từ snapshot `deepcopy` phải ra đúng nguyên văn | `policy/sources.py` (`SourceRegistry`, `SourceRecorder` bọc `get_actionable_appointment` / `list_open_slots` trong `DialogueManager`); `output_guard._sources` | `test_unknown_appointment_is_blocked`, `test_slot_outside_snapshot_is_blocked`, `test_real_slot_id_with_edited_time_is_blocked`, `test_in_place_edit_of_ctx_slot_is_blocked`, `test_in_place_edit_of_list_open_slots_result_is_blocked`, `test_appointment_edited_after_read_is_blocked`, `test_rereading_offer_whose_slots_are_gone_is_blocked`, `test_offer_of_unpresented_slot_is_blocked` |
| OG-4 (SF-04): `assert_no_clinical_advice` được gọi trên mọi câu | `output_guard._clinical` | `test_clinical_advice_is_blocked`; `test_no_registered_utterance_trips_the_clinical_markers` (mọi hằng và renderer, kể cả `TRANSFER`) |
| OG-5: báo thành công cần receipt đúng outcome **và** đúng đối tượng vừa ghi; outcome thành công phải đi với template thành công | Metadata `success_outcome` trên template; `done()` tách thành `CONFIRMED_DONE`, `CANCELLED_DONE`, `RESCHEDULED_DONE` ("đã đổi lịch"), `BOOKED_DONE`; `output_guard._success`, `_bound_to_receipt` | `test_confirmed_without_receipt_is_blocked`, `test_confirmed_with_receipt_passes`, `test_success_outcome_needs_a_success_template`, `test_confirmed_render_of_another_appointment_is_blocked`, `test_rescheduled_says_changed_and_is_bound_to_the_written_slot` (ghi A, nói B), `test_booked_render_of_another_slot_is_blocked`, `test_success_phrases_match_declared_success_outcome` |
| OG-6: `ctx.slots` và `ctx.question` sắp commit khớp đúng câu đã kiểm; fallback khôi phục slot gốc và bỏ câu hỏi trước khi kiểm lại | `output_guard.normalize_question`, `_state`; `SourceRegistry.restore_slots`; `_guard` khôi phục rồi mới kiểm action thay thế | Unit: `test_in_place_slot_edit_without_render_is_blocked`, `test_question_text_changed_after_ask_is_blocked`, `test_old_question_edited_without_new_ask_is_blocked`, `test_question_state_cases_that_must_pass`. Core thật (spy ngay trước `_apply`): `test_in_place_slot_edit_is_blocked_and_restored_before_commit`, `test_question_text_changed_after_ask_is_blocked`, `test_old_question_edited_without_new_ask_is_blocked`. Không chặn nhầm: `test_legitimate_rereads_are_not_blocked` (im lặng, HOLD, xin nhắc lại), `test_unsent_question_before_policy_transfer_is_dropped` |
| Receipt gate (§3.5) chạy trước mọi fallback: chưa rõ → đối soát; đúng một thành công → cấm chuyển máy, chỉ báo đúng kết quả đó và phải đóng phiên; nhiều thành công → đối soát; chỉ lệnh bị từ chối → fallback như cũ | `output_guard.receipt_gate`, `matches_receipt`, `safe_action`; `CallOrchestrator._settle`, `_receipt` | Unit: `test_gate_*`, `test_action_must_close_with_the_receipt_outcome_and_reason`. Luồng: (a) `test_render_error_after_confirm_keeps_confirmed` (G-5: `CONFIRMED`, không `/transfer`, không `GET` đọc lại version); (a') `..._retried_once_keeps_confirmed`; (b) `test_reschedule_with_wrong_status_requires_reconciliation`; (c) `test_blocked_success_message_is_replaced_not_transferred`; (d) `test_receipt_with_wrong_status_requires_reconciliation`; (e) `test_failed_unreachable_then_successful_transfer_passes_guard` (`write_attempted=2`, `write_succeeded=1`); (f) `test_failed_unreachable_and_rejected_transfer_still_transfers`; (g) `test_pending_write_with_ordinary_error_is_not_transferred`; (h) `test_success_that_does_not_close_the_session_is_replaced[...]`, `test_transfer_reason_that_differs_from_receipt_is_replaced` |
| Lỗi thường trong fallback SAU khi `/transfer` đã ghi thành công (sau lỗi Dialogue hoặc sau guard BLOCK) không làm mất kết quả: đọc lại receipt, trả câu an toàn đúng receipt, không ghi thêm. `TURN_ABORTING_ERRORS` giữ nguyên; chưa có receipt thì lỗi đi tiếp như trước | `CallOrchestrator._fallback_transfer` (dùng ở `_settle` và nhánh BLOCK của `_guard`) | `test_error_in_fallback_after_dialogue_error_keeps_transferred`, `test_error_in_fallback_after_guard_block_keeps_transferred`, `test_error_in_fallback_before_any_write_still_raises`; HTTP: `test_error_in_fallback_after_transfer_write_returns_200_not_500` (200, không 500, phiên không kẹt `CLINIC_COMMITTED`) |
| Receipt lấy từ nhật ký trong RAM, không từ store (Redis ghi `result=None` và purge ngay khi `SUCCEEDED`); receipt chỉ có sau khi store ghi `SUCCEEDED` thành công | `StoreCommandJournal` giữ `JournalEntry` (`session/manager.py`); `journal.JournalEntry`, `CommandJournal.entries`, `turn_entries` | `test_receipt_survives_redis_purge`, `test_store_failure_on_success_leaves_no_receipt`. Mọi test luồng chạy trên `RedisSessionStore` (fakeredis) |
| Lời mở đầu bị chặn: không tạo phiên, không nói, không ghi Mock; gửi lại sau khi sửa thì mở bình thường | `CallOrchestrator._opening` ném `CallStartBlocked`; HTTP ánh xạ `503 CALL_START_BLOCKED` (`transports/http/calls.py`) | `test_opening_blocked_by_output_guard_never_starts_and_can_retry[outbound/inbound]` (HTTP), `test_blocked_opening_is_never_spoken` (LiveKit: `_speak` không được gọi), `test_opening_blocked_creates_no_session`, `test_opening_must_be_a_non_disclosing_constant` |
| Replay của phiên còn hoạt động trả action đã guard, guard không chạy lại | Guard nằm trong `_process`, chỉ chạy trước commit | `test_replayed_turn_returns_guarded_action_without_rerunning_guard` (`test_turn_lifecycle.py`) |
| Dọn 4 chỗ kiểm status thừa ở Dialogue (bàn giao từ T-12) | `DialogueManager.transfer`, `unreachable`, `_attendance`, `_cancel_reconfirm` không còn `written.get("status") != …` | Test T-12 ở Gateway giữ vai trò chứng minh; hồi quy xanh |
| Tracing: span `GUARD` / `core.output_guard`, event `output_guard.blocked` và `output_guard.replaced`, mã lỗi mới; không chứa câu thoại hay ID | `tracing/privacy.py`, `tracing/errors.py`, `engine/diagnostics.py` | `tests/tracing/test_output_guard_tracing.py` (allowlist, thuộc tính ngoài hợp đồng bị từ chối, trace lượt bị chặn không có ID / giờ / nội dung) |

## File liên quan

Code:
- `src/callbot/engine/policy/utterances.py`: registry hằng / renderer, `RenderRecord`, ledger
- `src/callbot/engine/policy/sources.py`: `SourceRegistry`, `SourceRecorder`
- `src/callbot/engine/policy/output_guard.py`: OG-0..OG-6, receipt gate, câu thay thế
- `src/callbot/engine/dialogue/templates.py`: mọi câu đăng ký qua `static` / `@renderer`; `DONE_SAFE`; tách `done()`
- `src/callbot/engine/dialogue/manager.py`: đọc qua `SourceRecorder`, `silence_reprompt`, renderer thành công mới, bỏ kiểm status trùng
- `src/callbot/engine/journal.py`, `src/callbot/engine/session/manager.py`: `JournalEntry`, `entries()`
- `src/callbot/engine/orchestrator.py`: `_opening`, `_settle`, `_guard`, `_fallback_transfer`, `_replace`
- `src/callbot/engine/errors.py`: `CallStartBlocked`
- `src/callbot/transports/http/calls.py`: `503 CALL_START_BLOCKED`
- `src/callbot/tracing/privacy.py`, `src/callbot/tracing/errors.py`, `src/callbot/engine/diagnostics.py`
- `scripts/tts_bench_set.py`: câu mẫu `done_resched` theo câu mới

Test:
- `tests/engine/policy/test_output_guard.py` (mới)
- `tests/engine/test_output_guard_flow.py` (mới)
- `tests/tracing/test_output_guard_tracing.py` (mới)
- `tests/transports/test_no_business_rules.py` (mới)
- `tests/transports/http/test_calls.py`, `tests/transports/livekit/test_call_bridge_mapping.py`, `tests/engine/session/test_turn_lifecycle.py` (thêm ca)
- `tests/engine/test_cancel_dialogue.py` (đổi `t.done("CANCELLED")` thành `t.cancelled_done()`)

Tài liệu: `docs/reference/http-api.md` (mã `CALL_START_BLOCKED`, hành vi khi đã ghi thành công).

## Luồng hiện tại

```text
Transport (HTTP | LiveKit)
  -> CallOrchestrator
       start_call: DialogueManager.opening -> check_opening -> PASS: SessionManager lưu phiên
                                                          -> BLOCK: CallStartBlocked (503, không phiên, không TTS)
       _process:
         chụp đầu lượt (deepcopy): prior_question, ctx.slots -> SourceRegistry; bind ledger + registry
         -> Policy -> Extraction -> Dialogue
              đọc Gateway qua SourceRecorder -> registry (appointment, slots)
              Gateway ghi -> StoreCommandJournal: JournalEntry (receipt chỉ sau finish_command SUCCEEDED)
              template render -> ledger (template_id, refs, args, text)
         -> _settle
              1. receipt_gate: PENDING/UNKNOWN hoặc >1 SUCCEEDED -> WriteOutcomeUnknown (409 đối soát)
              2. lỗi + receipt -> DONE_SAFE[outcome] (REPLACE); lỗi không receipt -> chuyển máy SYSTEM_ERROR
              3. normalize_question (kết thúc -> question = None)
              4. OutputGuard.check (OG-0..OG-6)
                   receipt: PASS + khớp receipt -> giữ; ngược lại -> REPLACE bằng DONE_SAFE
                   không receipt: PASS -> giữ; BLOCK -> khôi phục slot, chuyển máy SYSTEM_ERROR, kiểm lại
       -> _apply -> commit -> transport trả text / phát TTS
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
python scripts/export_openapi.py --check
```

Chỉ chạy test của R-01:

```powershell
python -m pytest tests\engine\policy tests\engine\test_output_guard_flow.py tests\tracing\test_output_guard_tracing.py tests\transports\test_no_business_rules.py -q
```

## Kết quả xác minh cục bộ (2026-09-28)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | Pass (2720 passed, 16 skipped; baseline `1062041`: 2638 passed) |
| `python scripts/export_openapi.py --check` | Pass (không đổi schema) |
| `make check` | Pass |
| Test riêng R-01 (lệnh trên) | Pass (74 passed) |

Kiểm tra ngược: tạm cho `output_guard.check` luôn trả `PASS` thì 29 test R-01 đỏ; khôi phục thì xanh.

## Ghi chú

- Guard là CPU thuần, không thêm I/O: không đọc lại lịch để đối chiếu (ngân sách ghi 4 s của T-12 giữ nguyên).
- Ledger, source registry và receipt chỉ sống trong lượt; không đổi schema session. Metadata câu hỏi đọc lại được xác định lại fail-closed (câu động coi như lộ lịch).
- Renderer phải là hàm thuần của (dữ liệu nguồn, tham số), ghi trong docstring `templates.py`. T-10/T-11 thêm câu thoại mới phải đăng ký qua `static` / `@renderer`, nếu không OG-0 sẽ chuyển máy.
- Câu báo đổi lịch đổi từ "đã đặt lịch …" sang "đã đổi lịch khám sang …".
- Lượt kết thúc vẫn bị purge khi commit; gửi lại lượt đó nhận `CallEnded` / `ReconciliationRequired` như trước (không đổi).
- `docs/evidence/matrix.md` hiện là ma trận TTS (ADR-002), không có dòng cho task nên chưa cập nhật.

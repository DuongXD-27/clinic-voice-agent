# Evidence: F-03 — Session/FSM bền vững, thứ tự lượt và chống ghi trùng

## Mục tiêu

Session nhất quán qua restart và nhiều worker; gửi lại lượt không gây ghi trùng; lệnh ghi Clinic có nhật ký, kết quả không xác định thì chặn đối soát.

Ngoài phạm vi: tự động đối soát / mở khóa phiên, chính sách xoá dữ liệu phiên. Phần nối Information Extraction nằm ở [F-04](f04-information-extraction-http.md).

## Bằng chứng trong repo

### Context và FSM

| Tiêu chí | Vị trí code | Test |
| --- | --- | --- |
| Context có phiên bản schema, thời điểm mở phiên, câu hỏi gần nhất (`question_id`, nội dung, lượt), bước xác minh, hành động chờ, slot đang chọn, toàn bộ slot Clinic, thứ tự slot đã đọc | `session/context.py`: `CallContext`, `Question`, `SCHEMA_VERSION`, `to_dict` / `from_dict` | `test_context_roundtrip_keeps_every_field`, `test_unknown_schema_version_is_rejected` |
| Bằng chứng xác nhận (lượt, câu hỏi, transcript, agreement, provenance/span, hành động, slot); mất hiệu lực khi từ chối / đổi hành động / đổi slot | `ActionEvidence`, `set_pending`, `select_slot`, `clear_pending`, `add_evidence` | `test_evidence_is_cleared_on_refusal_action_change_and_slot_change`, `test_evidence_must_match_pending_action_and_slot`, `test_old_evidence_does_not_unlock_new_slot`, `test_confirmation_must_be_from_current_turn_and_right_question` |
| Hủy cần yêu cầu hủy + xác nhận tường minh ở hai lượt khác nhau; bỏ `cancel_confirmations` | `policy/guardrails.py`: `assert_action_confirmed` | `test_cancel_needs_request_and_confirmation_in_different_turns` |
| Mọi đổi state, kể cả kết thúc, qua FSM; kiểm tra đồng nhất state / xác minh / hành động / slot / outcome trước khi ghi | `session/fsm.py`: `check_invariants`, `check_write`, `check_closing_write`; `SessionManager.transition` / `close`; gọi trong `ClinicGateway` | `test_illegal_transitions_are_blocked`, `test_close_goes_through_fsm_and_is_terminal`, `test_awaiting_confirmation_requires_consistent_pending_action`, `test_check_write_rejects_inconsistent_state` |
| `ENDED` là trạng thái cuối, không mở lại bằng `call_id` | `TRANSITIONS["ENDED"] = set()`; `SessionManager.open` trả phản hồi đã lưu | `test_new_turn_after_end_is_rejected_but_old_turns_replay`, `test_reopening_same_call_does_not_reset_context` |
| Trạng thái kỹ thuật của lượt tách khỏi state hội thoại | `call_turns.status` (`PROCESSING` / `COMPLETED` / `RECONCILIATION_REQUIRED`); enum HTTP không đổi | `test_contract_*_openapi_shape_*` trong `tests/test_schema.py` |

### PostgreSQL, thứ tự lượt, chống ghi trùng

| Tiêu chí | Vị trí code | Test |
| --- | --- | --- |
| Hai repository cùng hợp đồng; HTTP dùng PostgreSQL, không fallback bộ nhớ | `session/store.py` (`SessionStore`, `InMemorySessionStore`), `session/postgres/store.py`; `transports/http/main.py::_default_session_store` | `tests/engine/session/test_store_contract.py` (mỗi test chạy `[memory]` và `[postgres]`) |
| Ba nhóm dữ liệu: session, lượt `(call_id, turn)`, lệnh Clinic | `session/postgres/migrations/001_session_store.sql` | `test_session_and_turn_roundtrip`, `test_command_journal_lifecycle` |
| Bảng quy tắc API (mở lại cùng/khác cấu hình, lượt mới, replay, khác đầu vào, nhảy số, sau kết thúc, không có phiên) | `SessionManager.open`, `SessionManager._admit`; ánh xạ HTTP trong `transports/http/calls.py::_run_engine` | `test_replaying_any_turn_returns_stored_result_without_side_effects`, `test_order_errors_leave_session_unchanged`, `test_silence_input_is_compared_exactly`, `test_turn_order_errors_over_http`, `test_start_call_is_idempotent_over_http`, `test_new_turn_after_end_returns_call_ended`, `test_engine_errors_map_to_http_status` |
| Khóa theo `call_id` bằng advisory lock cấp session trên connection riêng, luôn nhả trước khi trả pool; chờ 5 giây → `CALL_BUSY` | `PostgresSessionStore.call_lock`; `LOCK_TIMEOUT_S` | `test_lock_times_out_with_call_busy_and_other_calls_are_independent`, `test_lock_released_when_body_raises`, `test_busy_call_returns_call_busy_without_changes`, `test_different_calls_do_not_block_each_other` |
| Context + history + kết quả lượt commit trong một transaction; replay không chạy lại gì | `complete_turn` | `test_complete_turn_is_atomic_and_ordered`, `test_replaying_any_turn_returns_stored_result_without_side_effects` |
| Nhật ký lệnh commit trước khi gửi, khóa cố định; không lưu được nhật ký → không gửi, 503 | `engine/journal.py`, `ClinicGateway._write`, `StoreCommandJournal` | `test_store_unavailable_before_journal_sends_nothing`, `test_version_conflict_retries_once_with_same_key` |
| Kết quả ghi không xác định → chặn đối soát, không gửi lại, không chuyển máy thay thế | `WriteOutcomeUnknown`, `TURN_ABORTING_ERRORS`; `SessionManager.run_turn` | `test_write_timeout_requires_reconciliation_without_transfer` |
| Hai worker cùng lượt chỉ xử lý một lần; restart tiếp tục đúng bước | Khóa + đặt chỗ lượt | `test_two_workers_same_turn_process_once`, `test_restart_continues_at_same_step_and_replays`, `test_http_app_on_postgres_replays_across_app_restart` |
| Gián đoạn: trước gửi Clinic / sau Clinic thành công trước commit / sau commit trước trả HTTP | `SessionManager._admit` (lượt `PROCESSING`) | `test_crash_before_clinic_write_recovers_safely`, `test_crash_after_clinic_success_before_commit_blocks_for_reconciliation`, `test_crash_after_commit_before_response_replays` |
| Tra cứu chỉ đọc + hướng dẫn đối soát | `session/postgres/inspect.py`; [session-operations.md](../reference/session-operations.md) | Chạy tay trên stack Compose (mục kết quả) |

### Interface và triển khai

| Tiêu chí | Vị trí |
| --- | --- |
| Response thành công và enum HTTP giữ nguyên; mã lỗi mới có tài liệu | `transports/http/schemas.py` không đổi; [http-api.md](../reference/http-api.md) |
| Đầu vào engine giữ text, `silence_ms`, metadata ASR | `types.CallerInput` (`text`, `silence_ms`, `audio_url`, `asr_confidence`, `fingerprint`) |
| Repository injection cho factory / app | `create_orchestrator(..., store=)`, `create_app(..., session_store_factory=)` |
| Migration có phiên bản, chạy một lần trước worker; readiness | `session/postgres/migrate.py`, `schema.py`; `GET /ready` (`test_ready_reports_session_store`) |
| Compose: PostgreSQL + volume bền, service `migrate`; CI có PostgreSQL service, không skip test DB | `docker-compose.yml`, `docker-compose.prod.yml`, `.github/workflows/ci-cd.yml` (`REQUIRE_POSTGRES_TESTS=1`) |
| Smoke test không tái sử dụng `call_id` | `ci-cd.yml`: `ci_smoke_${GITHUB_RUN_ID}_${GITHUB_RUN_ATTEMPT}` |

## File liên quan

- `src/callbot/engine/errors.py`, `src/callbot/engine/journal.py`, `src/callbot/engine/types.py`
- `src/callbot/engine/session/context.py`, `fsm.py`, `manager.py`, `store.py`
- `src/callbot/engine/session/postgres/` (`store.py`, `migrate.py`, `schema.py`, `inspect.py`, `settings.py`, `migrations/001_session_store.sql`)
- `src/callbot/engine/policy/guardrails.py`, `src/callbot/engine/tools/clinic_gateway.py`
- `src/callbot/transports/http/calls.py`, `main.py`
- `tests/engine/session/test_context_fsm.py`, `test_store_contract.py`, `test_turn_lifecycle.py`
- `tests/transports/http/test_calls.py`, `tests/conftest.py`
- `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `.github/workflows/ci-cd.yml`

## Luồng một lượt (phần session)

```text
POST /v1/calls/{id}/turn
  -> CallerInput(turn, text, silence_ms, audio_url)
  -> SessionManager.run_turn
       khóa call_id (advisory lock, ≤5s)             -> 409 CALL_BUSY
       lượt COMPLETED + cùng đầu vào                   -> trả kết quả cũ
       lượt PROCESSING có lệnh chưa chắc thất bại      -> 409 CALL_RECONCILIATION_REQUIRED
       lượt mới: đúng last_completed_turn+1, đặt chỗ   -> 409 TURN_OUT_OF_ORDER / CALL_ENDED
  -> CallOrchestrator._process (xem F-04)
       Gateway: FSM.check_write + guardrails + bằng chứng
                -> nhật ký PENDING (commit) -> Clinic -> SUCCEEDED | FAILED | UNKNOWN
       SessionManager.transition / close (FSM)
  -> complete_turn: context + history + result + extraction (1 transaction)
  -> trace (lỗi chỉ log)
```

## Quy trình xác minh

```powershell
docker run -d --name callbot-pg-test -e POSTGRES_USER=callbot -e POSTGRES_PASSWORD=callbot -e POSTGRES_DB=callbot -p 55432:5432 postgres:16-alpine
$env:TEST_SESSION_DATABASE_URL = "postgresql://callbot:callbot@localhost:55432/callbot"
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
```

Không đặt `TEST_SESSION_DATABASE_URL` thì các test `[postgres]` bị skip (CI đặt `REQUIRE_POSTGRES_TESTS=1` để thiếu DB là lỗi).

## Kết quả xác minh cục bộ (2026-09-17)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` (có PostgreSQL 16 thật, gồm cả F-04) | 493 passed, 1 skipped, 1 failed |
| `python -m pytest -q tests/engine/session` | 59 passed (24 test store/lượt × memory + postgres, 11 test context/FSM) |
| `python -m pytest -q tests/transports` | 39 passed |

- Mốc trước F-03/F-04: 404 passed, 1 skipped, 1 failed.
- Test lỗi: `tests/speech/test_narrowband.py::test_settings_default_to_narrowband` — lỗi có sẵn về cấu hình Speech sample rate (`SpeechSettings()` đọc `.env` cục bộ), không phải regression.
- Test skip: `test_external_blocked_clinic_mock_image_matches_official_digest` (chưa có digest chính thức).

**Stack Compose thật** (`docker compose up --build`): `migrate` áp `001_session_store.sql` rồi thoát 0; bot chạy 2 worker process; `/ready` → `ready`. Smoke: mở cùng `call_id` hai lần trả cùng câu chào; gửi lượt 1 bốn lần trả cùng phản hồi; lượt 3 → `409 TURN_OUT_OF_ORDER` (`expected_turn=2`); lượt 1 khác nội dung → `409 TURN_CONFLICT`; `inspect call` in đúng lượt và context tóm tắt. Smoke không gọi lệnh ghi Clinic (Clinic chung).

## Ghi chú

- **Chặn đối soát bảo thủ:** lượt `PROCESSING` có lệnh `SUCCEEDED` nhưng chưa commit cũng bị chặn (không tự dựng lại context từ kết quả lệnh).
- **Xác nhận phải trong cùng lượt ghi:** bằng chứng `AGREE` từ lượt trước không mở khóa lệnh ghi ở lượt sau.
- **`VERSION_CONFLICT`** gửi lại một lần với cùng `Idempotency-Key` sau khi đọc lại version; lỗi 4xx khác → chuyển máy `SYSTEM_ERROR`. Lỗi 5xx và lỗi không phải "chưa kết nối được" coi là kết quả không xác định.
- **Chuyển từ bộ nhớ sang PostgreSQL:** kết thúc các cuộc gọi đang chạy trước khi triển khai; không có dữ liệu phiên cũ để migrate.
- Chưa có chính sách xoá session / lượt / nhật ký lệnh; không tái sử dụng `call_id`.

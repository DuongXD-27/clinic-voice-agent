# Evidence: T-12 — Phục hồi lỗi ghi

**Owner:** B (Hưng) · **Ngày:** 28-09-2026 · **Nhánh:** `feature/t12-write-recovery` (từ `main` `bce7072`) · **Plan:** `docs/plans/t12-write-recovery.md`

## Mục tiêu

Trước T-12, `ClinicGateway._write` chỉ gửi lại khi gặp `409 VERSION_CONFLICT`. Mọi lỗi tạm thời khác làm hỏng cuộc gọi:
- Timeout hoặc 5xx khi ghi: phiên bị khóa `409 CALL_RECONCILIATION_REQUIRED`, kể cả khi Mock đã ghi thành công.
- `429` hoặc không kết nối được: chuyển máy `SYSTEM_ERROR` ngay, không thử lại lần nào.

T-12 thêm phần gửi lại có giới hạn trong Gateway. Gửi lại luôn giữ cùng Idempotency-Key và cùng payload, nên không ghi trùng. Gateway chỉ báo thành công khi body phản hồi ở đúng trạng thái đích. Dialogue và port không đổi.

Quyết định đã chốt với owner (plan §6):
- **D-1:** `VERSION_CONFLICT` làm theo contract, không hỏi lại người gọi.
- **D-2:** kiểm tra kết quả ghi đặt ở Gateway.
- **D-3:** gửi lại giữ `If-Match` cũ.
- **Q-1:** timeout client Clinic 2 s, connect 1 s.
- **Q-2:** tối đa 3 lần gửi, ngân sách 4 s, chờ 0,2 s rồi 0,5 s giữa các lần.

## Bằng chứng trong repo

| Acceptance criterion | Vị trí code | Test chứng minh |
| --- | --- | --- |
| AC-1 Chưa rõ kết quả (timeout, 5xx): gửi lại y hệt — cùng key, cùng `If-Match`, cùng body; không đọc lại version; không ghi `unknown` vào nhật ký trước khi hết lượt (ghi `UNKNOWN` xóa nội dung phiên) | `ClinicGateway._write`, nhánh `not exc.outcome_known` (`clinic_gateway.py:390-469`). Đã có một lần gửi chưa rõ thì mọi lỗi xác định phía sau (429, không kết nối được, `VERSION_CONFLICT`, 404...) cũng là chưa rõ, không bao giờ `journal.failed` hay `ClinicWriteRejected` | `test_timeout_resends_the_identical_request_and_writes_once[applied]` và `[not_applied]`: `CONFIRMED`, `writes` 1 dòng, 2 request cùng key, 1 lần đọc version, nhật ký `begin, succeeded`. Fake tính `If-Match` vào dấu vân tay idempotency giống mock thật, nên nếu Gateway đọc lại version thì test này nhận `422` và đỏ. `test_a_definite_error_after_an_uncertain_send_is_still_unknown` (5 loại lỗi, nhật ký `begin, unknown`); `test_uncertain_then_rate_limited_then_replayed_is_success` |
| AC-2 `429` / `CONNECT_ERROR` (chắc chắn chưa ghi): chờ ngắn rồi gửi lại cùng key | `_write`, nhánh `exc.retryable` | `test_rate_limited_once_is_resent_with_the_same_key`: nhật ký `begin, failed, begin, succeeded`, chờ 0,2 s |
| AC-3 Lỗi tạm thời khi đọc version trước khi ghi: đọc lại | `ClinicGateway._read_version` (`clinic_gateway.py:471-483`) | `test_transient_version_read_failure_is_read_again_before_any_write` |
| AC-4 Có giới hạn số lần và thời gian; hết lượt thì trả đúng lớp lỗi như trước | `WRITE_MAX_SENDS`, `WRITE_BUDGET_S`, `WRITE_MIN_ATTEMPT_S`, `WRITE_BACKOFF_S` (`clinic_gateway.py:58-65`); `_may_resend` (`:485-493`) | `test_unknown_outcome_on_every_send_is_journaled_as_unknown` (3 lần gửi, chờ `[0.2, 0.5]`, `WriteOutcomeUnknown`); `test_timeout_after_the_write_budget_is_spent_is_not_resent` (đồng hồ giả, 1 lần gửi); `test_definite_rejections_carry_retryable_flag` (429/`CONNECT_ERROR` gửi 3 lần rồi `ClinicWriteRejected(retryable=True)`); `test_read_failure_before_send_is_rejection_without_journal_entry` |
| AC-5 `VERSION_CONFLICT` giữ nguyên theo contract: **luôn** đọc lại, gửi lại một lần cùng key (D-1); lần gửi này không tính vào giới hạn lỗi tạm thời | `_write`, nhánh `VERSION_CONFLICT` | Test T-03 có sẵn vẫn pass (`test_version_conflict_rereads_and_retries_once_with_same_key`, `test_second_version_conflict_is_a_definite_rejection`, `test_lifecycle_is_checked_again_after_version_conflict`); mới: `test_version_conflict_then_timeout_after_apply_still_writes_once` (3 request cùng key, 2 lần đọc version, 1 lần ghi); `test_version_conflict_is_always_reread_even_after_transient_retries` (429 → 429 → `VERSION_CONFLICT` → thành công) |
| AC-6 Kiểm tra kết quả sau khi ghi ở Gateway cho confirm, cancel, transfer, unreachable, reschedule (D-2); reschedule còn phải khớp `new_slot_id` (Listing 4) | `_status_is` (`clinic_gateway.py:96-100`) truyền vào `_write` qua `written_ok`; kiểm tra **trước** `journal.succeeded`, sai thì ghi `unknown`. Book dùng cùng cơ chế | `test_a_2xx_with_the_wrong_status_is_not_success` (5 thao tác, 1 request, không gửi lại, nhật ký `begin, unknown`); `test_reschedule_reports_success_only_for_the_chosen_slot` |
| AC-7 Không gửi lại lỗi xác định (`SLOT_TAKEN`, `INVALID_STATE_TRANSITION`, `IDEMPOTENCY_CONFLICT`, 4xx khác) | `_write`: chỉ `outcome_known=False`, `retryable` và `VERSION_CONFLICT` lần đầu được gửi lại | `test_slot_taken_is_not_resent`; có sẵn: `test_invalid_state_transition_is_not_actionable_and_not_retried`, `test_definite_rejections_carry_retryable_flag[error1/error2]` |
| AC-8 Trace: mỗi lần gửi là một bản ghi API riêng | Không đổi `traced_clinic`: `attempt_count` và sự kiện `clinic.attempt` đếm từ `collect_api_calls` | `test_each_send_is_a_traced_clinic_attempt` (`unknown` rồi `ok`) |
| Không tăng `attempt_count` hai lần khi gửi lại `/unreachable` (§4.2.5) | Cùng key `{call_id}:{turn}:unreachable` | `test_unreachable_resent_after_timeout_increments_attempt_count_once` |
| 2xx nhưng body không phải JSON là chưa rõ kết quả, không phải từ chối | `_json_body` (`clinic_mock_client.py:261-270`): `outcome_known=False` | `test_2xx_without_a_json_body_is_an_unknown_outcome` (`test_clinic_mock_client.py`); `test_a_non_json_2xx_on_write_is_unknown_not_rejected` |
| Q-1 Timeout client 2 s / connect 1 s | `ClinicMockClient.__init__` (`clinic_mock_client.py:38-39`) | Dùng chung cho HTTP (`clinic_backend.py`) và LiveKit worker (không truyền giá trị riêng) |

## File liên quan

Code:
- `src/callbot/engine/tools/clinic_gateway.py`: vòng gửi lại, `_read_version`, `_may_resend`, `_status_is`, tham số `sleep`/`clock` để test không chờ thật
- `src/callbot/engine/tools/clinic_mock_client.py`: timeout mặc định (Q-1); 2xx không phải JSON là `outcome_known=False`
- `src/callbot/engine/errors.py`: chỉ sửa docstring
- `src/clinic_mock_sim/faults.py`, `src/clinic_mock_sim/README.md`: thêm `fail_unknown(operation, times, apply_first=...)` để giả lập "mọi lần gửi đều timeout"

Test:
- `tests/engine/tools/test_clinic_gateway.py`: 3 test đổi kỳ vọng, thêm 26 test T-12 (gồm 11 test sau review)
- Chỉ đổi cách giả lập lỗi để lỗi lặp đủ `WRITE_MAX_SENDS` lần, giữ nguyên assertion nghiệp vụ:
  - `tests/engine/test_call_termination.py`
  - `tests/engine/test_cancel_dialogue.py`
  - `tests/engine/test_confirm_dialogue.py`
  - `tests/engine/test_silence_line_signal.py`
  - `tests/transports/http/test_calls.py`
- `scripts/no_answer_eval.py`: fault `outcome_unknown` (case NA086) lặp đủ số lần gửi

Tài liệu:
- `docs/plans/t12-write-recovery.md`
- `docs/reference/ai-callbot-architecture.md` §4.2: dòng `VERSION_CONFLICT`, `429/503`, timeout

## Luồng hiện tại

```text
Dialogue gọi gateway.confirm / cancel / reschedule / book / transfer / mark_unreachable
  -> kiểm tra FSM + SF-01/02/05 + bằng chứng xác nhận (như cũ)
  -> _write: deadline = now + 4 s
       _read_version: lỗi tạm thời -> đọc lại (≤ 3 lần, trong ngân sách); hết -> ClinicWriteRejected
       journal.begin(key = call_id:turn:operation, If-Match = version)
       gửi:
         2xx, body đúng trạng thái đích -> journal.succeeded -> trả body
         2xx, body sai / không phải JSON -> journal.unknown -> WriteOutcomeUnknown (không gửi lại)
         timeout / 5xx (chưa rõ)      -> còn lượt: chờ 0,2 / 0,5 s, gửi lại Y HỆT (lệnh vẫn PENDING)
                                         hết lượt: journal.unknown -> WriteOutcomeUnknown -> 409 đối soát
         đã có lần gửi chưa rõ, rồi lỗi xác định -> lỗi tạm thời: gửi lại tiếp; còn lại / hết lượt:
                                         journal.unknown -> WriteOutcomeUnknown (không bao giờ "từ chối")
         VERSION_CONFLICT lần đầu     -> journal.failed, luôn đọc lại version, begin lại, gửi lại cùng key
         429 / CONNECT_ERROR          -> journal.failed; còn lượt: chờ, begin lại, gửi lại cùng key
                                         hết lượt: ClinicWriteRejected(retryable=True) -> SYSTEM_ERROR
         SLOT_TAKEN                   -> SlotTaken (Dialogue đề xuất slot khác)
         INVALID_STATE_TRANSITION     -> AppointmentNotActionable
         lỗi xác định khác            -> ClinicWriteRejected
```

## Quy trình xác minh

```powershell
make check
```

Chỉ các test liên quan T-12:

```powershell
python -m pytest tests\engine\tools tests\engine\test_call_termination.py tests\engine\test_cancel_dialogue.py tests\engine\test_confirm_dialogue.py tests\engine\test_silence_line_signal.py tests\eval\test_no_answer_evaluator.py tests\transports\http\test_calls.py tests\clinic_mock_sim -q
```

## Kết quả xác minh cục bộ (28-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests` | Pass (275 file) |
| Test liên quan T-12 (lệnh ở trên) | 545 passed, 1 failed: `test_demo_audio_upload_returns_public_narrowband_wav`, thiếu module `soxr` trên máy, không liên quan |
| `python -m pytest -q` (toàn repo) | 2568 passed, 16 skipped, 10 failed. **10 test fail giống hệt trên `main` trước T-12** (2540 passed, 10 failed, chạy cùng máy bằng `git stash`): thiếu `soxr` / model speech (`tests/speech/*`, `test_audio_adapter.py`, `test_demo_audio_upload...`) |
| Contract test trên mock thật (`CLINIC_MOCK_LIVE=1`) | Chưa chạy. Hành vi idempotency của mock đã đối chiếu bằng đọc code `clinic-mock/src/clinic_mock/routes.py:289-616` |

## Ghi chú

- **Việc cho A (Hoàn):** bốn chỗ kiểm tra `status` sau khi ghi ở `dialogue/manager.py` (`:125, :147, :295, :469`) giờ không bao giờ kích hoạt, vì Gateway đã chặn trước. T-12 không xóa để tránh conflict với T-10/T-11; A xóa khi tiện.
- **Rủi ro đã chấp nhận (D-1):** nếu nhân viên sửa giờ lịch giữa lúc bot đọc lại và lúc ghi, bot vẫn ghi theo version mới mà không hỏi lại người gọi. Lịch chuyển sang trạng thái không thao tác được thì Gateway vẫn chặn.
- **Chỉ gửi lại trong cùng lượt:** key chứa số lượt. Nếu harness gửi lại cùng lượt khi lệnh đang `PENDING`/`UNKNOWN`, lượt đó vẫn bị chặn đối soát như trước (`SessionManager._admit`).
- **Mock nguyên bản không tự phát `429`/`503`.** Trên EC2, các mã này đến từ proxy khi mock restart. Timeout là ca thực tế chính.
- **Ngân sách 4 s dùng chung cho mọi lệnh ghi trong một lượt** (vd. confirm lỗi rồi `/transfer`), gắn với nhật ký lệnh của lượt. Gateway không biết lượt đã tiêu bao nhiêu cho ASR/IE. Lần đọc version và lần gửi đầu của mỗi lệnh luôn chạy, và một lần gửi có thể kéo dài tới timeout 2 s, nên có thể vượt 4 s. Đo bằng đồng hồ giả, riêng phần gọi Clinic: Clinic không kết nối được (confirm lỗi rồi `/transfer`) 4,7 s; timeout mọi lần 6,2 s (trước T-12 cùng kịch bản: 4 s và 10 s). Cần đo lại ở S-03.
- **Thời gian chạy test tăng nhẹ:** các test Orchestrator/HTTP giả lập lỗi lặp dùng `time.sleep` thật (0,7 s mỗi test). Test tầng Gateway dùng đồng hồ giả.
- **Lần gửi lại do `VERSION_CONFLICT` không tính vào ngân sách 4 s** (AC-5 ưu tiên §4.2.5). Trường hợp hiếm 429 → 429 → `VERSION_CONFLICT` có thể thêm một lần đọc version và một lần gửi (tối đa 2 × 2 s) ngoài ngân sách.

## Sửa sau review (28-09-2026)

Reviewer báo 4 lỗi, cả 4 tái hiện được bằng `FakeClinicAPI` / `httpx.MockTransport` trước khi sửa:

| # | Lỗi | Trước khi sửa | Sau khi sửa |
| --- | --- | --- | --- |
| 1 | Lần gửi trước chưa rõ, lần gửi sau gặp lỗi xác định vẫn báo "từ chối" | timeout (mock đã ghi TRANSFERRED) → 429 → 429: `ClinicWriteRejected`, nhật ký `begin, failed, begin, failed` | `WriteOutcomeUnknown`, nhật ký `begin, unknown` |
| 2 | Nhật ký ghi SUCCEEDED rồi mới kiểm tra status | nhật ký `begin, succeeded` rồi raise | Kiểm tra trong `_write` trước khi ghi nhật ký: `begin, unknown` |
| 3 | 2xx không phải JSON bị coi là lỗi xác định | `outcome_known=True` → `ClinicWriteRejected` → chuyển máy dù mock đã nhận lệnh | `outcome_known=False` → gửi lại y hệt → hết lượt thì chưa rõ |
| 4 | Không còn đảm bảo gửi lại sau `VERSION_CONFLICT` | 429 → 429 → `VERSION_CONFLICT`: dừng ở 3 lần gửi, không đọc lại version | Luôn đọc lại và gửi lại một lần, không tính vào giới hạn: thành công sau 4 request cùng key |

Lỗi 1 và 4 do T-12 gây ra. Lỗi 2 (với `book`) và 3 có từ F-05, sửa luôn trong T-12.
### Rà soát lần 2 (28-09-2026)

Rà lại toàn bộ đường ghi (Gateway, nhật ký lệnh, Dialogue/SessionManager bắt exception, client HTTP, response thật của mock). Tìm thêm:

| # | Vấn đề | Mức | Sửa |
| --- | --- | --- | --- |
| 5 | Ngân sách 4 s tính riêng cho từng lệnh ghi: confirm lỗi rồi `/transfer` cùng lượt được thêm 4 s mới. Clinic không kết nối được: 7,4 s chỉ riêng phần gọi Clinic (trước T-12: 4 s) | Cao (vượt 8 s/lượt) | Hạn chót chung theo lượt, gắn với nhật ký lệnh (`_turn_deadline`). Còn 4,7 s. Test `test_the_write_budget_is_shared_by_every_write_in_the_turn`, `test_a_new_turn_gets_a_fresh_write_budget` |
| 6 | Trace ghi 2xx không phải JSON là `ok` trong khi Gateway coi là chưa rõ | Thấp | Client ghi `outcome=unknown`. Test `test_2xx_without_a_json_body_is_traced_as_unknown` |
| 7 | Đứt kết nối giữa chừng (`TRANSPORT_ERROR`) khi đọc version không được đọc lại (không nằm trong mã `retryable`) | Thấp | Đọc version là thao tác đọc nên đọc lại cả khi `outcome_known=False`. Test `test_a_dropped_connection_on_the_version_read_is_read_again` |

Đã kiểm tra, không có lỗi:
- **Response thật của mock** (`clinic-mock/.../routes.py`): confirm, cancel, transfer, unreachable, reschedule, create đều trả `status` đích và replay trả đúng body cũ, khớp `_status_is`.
- **`time.sleep` trong lúc chờ gửi lại:** route HTTP là `def` đồng bộ (chạy trong threadpool), LiveKit gọi orchestrator qua `asyncio.to_thread`, nên không chặn event loop.
- **Khóa phiên:** lease 60 s, dư nhiều so với một lượt dài nhất.
- **Không còn chỗ gọi `_write` / `_require_written` theo chữ ký cũ.**

Còn để ngỏ (không sửa trong T-12):
- Trace gắn nhãn `CLINIC_REJECTED` cho cả lần gọi có `outcome=unknown` (`_clinic_error_code`), có từ trước. Nên tách nhãn `CLINIC_UNKNOWN` ở R-02.
- Các lệnh đọc khác (`list_open_slots`, tra bệnh nhân) chưa thử lại khi lỗi tạm thời. Ngoài phạm vi "phục hồi lỗi ghi".

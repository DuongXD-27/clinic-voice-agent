# Evidence: T-03 — Gateway Confirm/Cancel/Transfer

**Owner:** B (Hưng) · **Ngày:** 18-09-2026

## Mục tiêu

Phần ghi `confirm`/`cancel`/`transfer` của `ClinicGateway` đã được dựng sẵn từ F-05 (cần có sớm để A
phát triển song song T-04/T-05) nhưng chưa có test riêng cho từng thao tác — bộ test của F-05 chỉ
dùng `transfer()` làm đại diện cho phần hạ tầng ghi dùng chung (`_write`), vì `transfer` chỉ cần
`fsm.check_closing_write` (ít điều kiện setup hơn `confirm`/`cancel`). T-03 lấp khoảng trống đó: xác
nhận `confirm()` và `cancel()` — bằng chứng xác nhận (kể cả xác nhận hủy lần hai — SF-05), kiểm tra
appointment đích (SF-01), reason code, idempotency key/version, retry một lần khi VERSION_CONFLICT —
đều đúng như `transfer()` đã được kiểm chứng.

Phạm vi: chỉ thêm test trong `tests/engine/tools/test_clinic_gateway.py`, dùng API công khai của
`session/context.py` và `extraction/schema.py` (sở hữu bởi A) mà không sửa hai file đó. Không tìm
thấy gap về logic — `src/callbot/engine/tools/clinic_gateway.py` không đổi.

## Bằng chứng trong repo

| Acceptance criterion | Vị trí code | Test chứng minh |
| --- | --- | --- |
| Confirm chỉ ghi sau khi có bằng chứng AGREE đúng câu hỏi CONFIRM_READBACK ở chính lượt hiện tại (§1.1.3) | `ClinicGateway.confirm` (`clinic_gateway.py:98-108`) gọi `guardrails.assert_action_confirmed` trước khi gửi | `test_confirm_writes_after_valid_readback_agreement`, `test_confirm_without_agreement_evidence_is_blocked` (`SevereFailureBlocked` code `CONFIRMATION`) |
| Cancel cần xác nhận rõ ràng **lần thứ hai** — yêu cầu hủy phải ở một lượt **trước** lượt xác nhận (SF-05, §1.1.4) | `ClinicGateway.cancel` (`clinic_gateway.py:110-122`) dùng chung `assert_action_confirmed`, nhánh CANCEL kiểm tra thêm bằng chứng REQUEST ở lượt < lượt CONFIRMATION | `test_cancel_writes_reason_and_confirmed_flag_after_second_agreement`, `test_cancel_without_prior_request_evidence_is_blocked_by_sf05` (chỉ có AGREE ở lượt hiện tại, không có REQUEST trước đó → `SevereFailureBlocked` code `SF-05`) |
| Kiểm tra appointment đích trước khi ghi (SF-01) — áp dụng cho `confirm`/`cancel`, không chỉ `get_appointment`/`transfer` | `ClinicGateway._target` (`clinic_gateway.py:250-255`) dùng chung cho mọi lệnh ghi | `test_confirm_blocks_write_when_call_has_no_target_appointment`: mọi bằng chứng hợp lệ nhưng `call.appointment_id=None` → `SevereFailureBlocked` code `SF-01`, không gửi request |
| Gửi đúng reason code cho Cancel (`cancel_reason` từ Phụ lục A) kèm `confirmed: true` mock yêu cầu | `ClinicGateway.cancel` payload `{"cancel_reason": reason, "confirmed": True}` | `test_cancel_writes_reason_and_confirmed_flag_after_second_agreement`: `fake.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "PATIENT_UNAVAILABLE"})]` |
| Idempotency key cố định theo `call_id:turn:operation`, version đọc lại làm `If-Match`, retry đúng 1 lần khi `VERSION_CONFLICT` — đúng cho `confirm`/`cancel`, không chỉ `transfer` | `ClinicGateway._write` (`clinic_gateway.py:199-236`) | `test_confirm_writes_after_valid_readback_agreement` (`fake.requests == [("c_cf1:3:confirm", ...)]`); `test_cancel_version_conflict_rereads_and_retries_once_with_same_key` (hai request cùng key `c_ca3:3:cancel`) — mở rộng case đã có `test_version_conflict_rereads_and_retries_once_with_same_key` (F-05, chạy trên `transfer`) sang `cancel` |
| Inbound transfer trước khi đặt lịch **không ghi Mock** (§2.1 rev 1.1) | `ClinicGateway.transfer` (`clinic_gateway.py:161-172`): inbound + `created_appointment_id is None` → trả `None`, không gọi API | Đã có từ F-05: `test_transfer_inbound_without_booking_sends_nothing` (giữ nguyên, không sửa) |
| Ba lớp kết quả ghi (thành công / từ chối xác định / chưa rõ) áp dụng chung cho mọi thao tác ghi, bao gồm confirm/cancel | `ClinicGateway._write` phân loại `ClinicAPIError` → `ClinicWriteRejected`/`WriteOutcomeUnknown` | Đã có từ F-05, kiểm bằng `transfer` (`test_version_conflict_rereads_and_retries_once_with_same_key`, `test_second_version_conflict_is_a_definite_rejection`, `test_definite_rejections_carry_retryable_flag`, `test_unknown_outcome_is_journaled_and_not_retried`) — cùng cơ chế, không lặp lại toàn bộ ma trận lỗi cho `confirm`/`cancel` vì logic dùng chung một hàm `_write`; chỉ mở rộng case VERSION_CONFLICT (dòng trên) để khóa hành vi cho `cancel` do payload phức tạp hơn (`cancel_reason`) |

## File liên quan

Sửa:
- `tests/engine/tools/test_clinic_gateway.py` — thêm helper `_ready_to_confirm`, `_agree_confirm`, `_ready_to_cancel`, `_agree_cancel` và 6 test mới cho `confirm`/`cancel`

Không đổi (đã đúng từ F-05, chỉ xác nhận lại bằng test):
- `src/callbot/engine/tools/clinic_gateway.py`
- `src/callbot/engine/tools/fake_clinic.py`
- `src/callbot/engine/errors.py`

## Luồng hiện tại

Không đổi so với F-05 (`docs/evidence/f05-clinic-gateway.md`). Tham chiếu cụ thể cho `confirm`/`cancel`:

```text
Dialogue (A) đặt xong pending_action + question + evidence AGREE (và REQUEST cho Cancel, lượt trước)
  -> ClinicGateway.confirm(ctx) / cancel(ctx, reason)
       -> fsm.check_write (A, session/fsm.py)         : state/question/slot khớp hành động chờ
       -> guardrails.assert_action_confirmed (A)       : có AGREE đúng lượt/câu hỏi; Cancel thêm SF-05
       -> _target(ctx)                                 : SF-01, appointment đích của cuộc gọi
       -> _write(...)                                  : idempotency key call_id:turn:op, đọc version,
                                                          journal.begin -> API -> succeeded/failed/unknown
  Thiếu bất kỳ điều kiện nào ở trên -> SevereFailureBlocked (CONFIRMATION/SF-05/SF-01), không gửi request,
  không ghi journal — giống hành vi transfer đã kiểm ở F-05
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`).

```powershell
make check
```

Chỉ test T-03: `python -m pytest tests\engine\tools\test_clinic_gateway.py -q`

## Kết quả xác minh cục bộ (18-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check tests\engine\tools\test_clinic_gateway.py` | Pass (repo còn drift CRLF có sẵn ở 23 file khác, không thuộc T-03 — như đã ghi ở evidence F-05) |
| `python -m pytest tests\engine\tools\test_clinic_gateway.py -q` | Pass (24 passed, gồm 6 test mới) |
| `python -m pytest -q` | 685 passed, 45 skipped, 1 failed có sẵn: `tests/speech/test_narrowband.py::test_settings_default_to_narrowband` (đọc `SAMPLE_RATE`/`TTS_PROVIDER` từ `.env` local, không liên quan T-03, có từ trước — cùng lỗi đã ghi ở evidence F-05) |
| Contract test `live` (`CLINIC_MOCK_LIVE=1`) | Chưa chạy — `confirm`/`cancel` không đổi code nên không cần chạy lại riêng cho T-03; lần chạy live gần nhất thuộc F-05 |

## Ghi chú

- Không phát hiện gap logic ở `clinic_gateway.py` — toàn bộ khoảng trống là **thiếu test riêng** cho `confirm`/`cancel` (F-05 chỉ kiểm qua `transfer` vì setup đơn giản hơn). Sau khi viết test, mọi case đều xanh ngay lần đầu.
- Không tìm cách viết test SF-01 "ghi nhầm sang appointment khác" theo đúng nghĩa đen cho `confirm`/`cancel`/`transfer`: `_target(ctx)` luôn lấy `appointment_id` từ chính `ctx.target_appointment_id` rồi so nó với chính nó, nên guard này chỉ có thể bắt trường hợp **không có** target (`None`) — đó là case đã test (`test_confirm_blocks_write_when_call_has_no_target_appointment`, và case tương đương có sẵn cho `get_appointment`: `test_get_appointment_blocks_other_appointment_ids`). Bảo đảm thật sự rằng Gateway "không ghi nhầm appointment" nằm ở chỗ `target_appointment_id` được suy ra bất biến từ `CallStart.appointment_id`/`created_appointment_id` (A, `session/context.py`), không có đường nào trong `tools/` truyền một `appointment_id` khác vào.
- Không tự mở rộng test sang runtime-validate `cancel_reason`/`transfer_reason` so với enum Phụ lục A: hai kiểu này là `Literal` ở `engine/types.py` (kiểm tra tĩnh bằng mypy/type-checker), việc sinh ra reason hợp lệ thuộc Dialogue/Policy (A, T-06). Nếu một giá trị sai lọt tới Gateway, mock sẽ trả `400 INVALID_REQUEST` và rơi vào nhánh `ClinicWriteRejected` đã test (`test_definite_rejections_carry_retryable_flag`) — không cần thêm rào chắn thứ hai ở Gateway.
- Việc tiếp theo không thuộc T-03: retry có giới hạn cho lỗi tạm thời ngoài VERSION_CONFLICT (T-12), cửa sổ slot/idempotency cho Reschedule/Book (T-09), `/unreachable` timeout chưa rõ kết quả (T-07).

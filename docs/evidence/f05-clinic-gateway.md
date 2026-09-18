# Evidence: F-05 — Hoàn thiện Clinic Client/Gateway

**Owner:** B (Hưng) · **Plan:** `docs/plans/f05-clinic-gateway.md` · **Ngày:** 17-09-2026

## Mục tiêu

Làm cạnh "API nghiệp vụ" giữa Clinic Gateway và Clinic Mock (kiến trúc `tailieu/AI-callbot-architecture.svg`) chạy đúng với mock thật của mentor, và cung cấp `FakeClinicAPI` hành xử như mock để A phát triển song song không cần docker.

Phạm vi: `src/callbot/engine/tools/` (ports, client, gateway, normalize, telemetry, fake) + `engine/errors.py`. Không đổi luồng hội thoại, không đổi FSM/journal (F-03), không chuẩn hóa số điện thoại (chuyển sang T-01 theo quyết định 17-09).

Quyết định đã chốt với owner: fake đặt ở `src/` (Q-1); Protocol trả từng trang, Gateway đi hết trang (Q-2); Gateway tự quyết "inbound chưa tạo lịch → không ghi transfer" (Q-3).

## Bằng chứng trong repo

| Acceptance criterion | Vị trí code | Test chứng minh |
| --- | --- | --- |
| AC-1 Mọi endpoint nghiệp vụ đúng path/method/header/body và **đọc hết mọi trang** | `ClinicMockClient` (`clinic_mock_client.py`): `_request`, `_page_params`, `_write_headers`; `ClinicGateway._all_pages` (`clinic_gateway.py`) | `test_clinic_mock_client.py::test_read_sends_bearer_and_pagination_params`, `::test_write_headers_and_unreachable_body_per_4_2_5`; `test_clinic_gateway.py::test_list_open_slots_walks_every_page_and_normalizes` (230 slot = 3 trang), `::test_find_patients_by_phone_returns_canonical_candidates_from_all_pages` (121 ứng viên); `test_clinic_api_contract.py::test_slots_pagination_with_limit_1_walks_all_records` (fake + live) |
| AC-2 Thời gian, slot/patient/appointment chuẩn hóa về một dạng | `tools/normalize.py`: `iso_local`, `normalize_slot`, `normalize_patient_candidate`, `normalize_appointment` | `test_normalize.py` (8 test); `test_clinic_gateway.py::test_list_open_slots_sends_rfc3339_window_of_14_days` |
| AC-3 Lỗi phân loại thành tập cố định; Gateway không rò `httpx` | `ClinicAPIError` (`engine/errors.py`), `ClinicWriteRejected.retryable`; `ClinicMockClient._request/_parse_error`; `ClinicGateway._write` dịch về 3 lớp; `dialogue/manager.py` bỏ `import httpx` | `test_clinic_mock_client.py::test_error_envelope_maps_to_clinic_api_error` (11 mã), `::test_error_without_envelope_falls_back_to_status_code`, `::test_connect_error_is_known_rejection_but_timeout_is_unknown`; `test_clinic_gateway.py::test_definite_rejections_carry_retryable_flag`, `::test_read_failure_before_send_is_rejection_without_journal_entry`, `::test_unknown_outcome_is_journaled_and_not_retried`, `::test_version_conflict_rereads_and_retries_once_with_same_key`, `::test_second_version_conflict_is_a_definite_rejection`; `grep httpx src/callbot/engine` chỉ còn `tools/clinic_mock_client.py` |
| AC-4 `/unreachable` đúng §4.2.5 | `ClinicMockClient.mark_unreachable` (body chỉ reason, If-Match); `FakeClinicAPI.mark_unreachable` (idempotency chỉ băm body, kiểm tra key trước If-Match) | `test_clinic_api_contract.py::test_unreachable_increments_once_and_replays_with_stale_if_match` (fake + live); `test_clinic_mock_client.py::test_write_headers_and_unreachable_body_per_4_2_5` |
| AC-5 `FakeClinicAPI` hành xử như mock, A dùng được không cần docker | `src/callbot/engine/tools/fake_clinic.py` (phân trang, regex phone, cửa sổ slot, If-Match, IDEMPOTENCY_CONFLICT, lifecycle, CONFIRMATION_REQUIRED, SLOT_TAKEN, 201 create, unreachable); `tests/engine/fake_clinic.py` re-export giữ import cũ | Toàn bộ `test_clinic_api_contract.py` pass trên fake (11 case); test hiện có của A (`test_identity.py`, `test_orchestrator.py`, `test_turn_lifecycle.py`, `test_calls.py`) pass không đổi nội dung |
| AC-6 Không gọi `/_harness/*` | Client không có phương thức nào tới `/_harness`; contract test reset từ fixture pytest, không từ client | `test_clinic_mock_client.py::test_client_never_calls_harness_endpoints` (9 endpoint); `tests/test_schema.py::test_contract_clinic_client_never_requests_harness_paths` (của A, giữ nguyên) |
| Transfer theo hướng gọi (luồng PDF "Chuyển nhân viên — không ghi Mock") | `ClinicGateway.transfer` trả `None` cho inbound chưa tạo lịch; `DialogueManager.transfer` gọi vô điều kiện | `test_clinic_gateway.py::test_transfer_inbound_without_booking_sends_nothing`, `::test_transfer_outbound_writes_with_fresh_if_match_and_fixed_key` |
| Trace "API, độ trễ, chi phí" | `tools/telemetry.py`: `ApiCallRecord`, `collect_api_calls`, `record_api_call`; client và fake đều ghi | `test_clinic_mock_client.py::test_every_request_emits_api_call_record_without_body`; `test_clinic_gateway.py::test_gateway_api_calls_are_collectable_for_trace` |

## File liên quan

Mới:
- `src/callbot/engine/tools/fake_clinic.py`
- `src/callbot/engine/tools/normalize.py`
- `src/callbot/engine/tools/telemetry.py`
- `tests/engine/tools/test_clinic_api_contract.py`, `test_clinic_gateway.py`, `test_clinic_mock_client.py`, `test_normalize.py`

Sửa:
- `src/callbot/engine/tools/ports.py` — `Page`, `as_page`, Protocol thêm `cursor`/`limit`
- `src/callbot/engine/tools/clinic_mock_client.py` — viết lại quanh `_request`
- `src/callbot/engine/tools/clinic_gateway.py` — `_all_pages`, normalize, dịch `ClinicAPIError`, `transfer` theo hướng gọi
- `src/callbot/engine/tools/__init__.py` — export
- `src/callbot/engine/errors.py` — `ClinicAPIError`, `RETRYABLE_CLINIC_CODES`, `ClinicWriteRejected.retryable`
- `src/callbot/engine/dialogue/manager.py` (A, đã báo) — bỏ `httpx`; `transfer` không tự kiểm `target_appointment_id`
- `src/callbot/engine/verification/identity.py` (B) — đọc ứng viên canonical `{full_name, dob, verifiable}`; T-01 sẽ viết lại
- `tests/engine/fake_clinic.py` — re-export
- `README.md`, `docs/reference/clinic-mock.md` §5.2 và §7, `docs/reference/ai-callbot-architecture.md` §5

## Luồng hiện tại

```text
Dialogue / Verifier
  -> ClinicGateway.get_appointment / find_patients_by_phone / list_open_slots
       -> ClinicAPI (1 trang/lần) x N trang  -> normalize_*  -> dict canonical (Session lưu được)
  -> ClinicGateway.confirm/cancel/reschedule/book/transfer/mark_unreachable
       -> FSM + guardrail + bằng chứng  -> đọc version  -> journal.begin
       -> ClinicAPI  ok            -> journal.succeeded -> kết quả (chỉ lúc này mới nói "đã ghi")
                    ClinicAPIError outcome_known   -> journal.failed
                         VERSION_CONFLICT lần 1    -> đọc lại version, gửi lại cùng key
                         SLOT_TAKEN                -> SlotTaken (Dialogue đọc lại slot, hỏi lại)
                         khác                      -> ClinicWriteRejected(retryable)
                    ClinicAPIError outcome_known=False / ngoại lệ lạ -> journal.unknown -> WriteOutcomeUnknown
  Mỗi request (thật hoặc fake) -> ApiCallRecord vào collector của lượt (R-02 nối vào trace)
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`).

```powershell
make check
```

Chỉ test F-05: `python -m pytest tests\engine\tools -q`

Contract test trên mock thật (reset instance chung — **báo kênh team trước**):

```powershell
$env:CLINIC_MOCK_LIVE = "1"; python -m pytest tests\engine\tools\test_clinic_api_contract.py -q
```

## Kết quả xác minh cục bộ (17-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check` (16 file F-05 chạm) | Pass — repo còn 28 file drift CRLF có sẵn, không thuộc F-05 |
| `python -m pytest tests/engine/tools -q` | Pass (64 passed, 18 skipped = biến thể `live`) |
| `python -m pytest tests/engine tests/transports tests/test_schema.py -q` | Pass (527 passed, 44 skipped) |
| `python -m pytest -q` | 532 passed, 1 failed có sẵn: `tests/speech/test_narrowband.py::test_settings_default_to_narrowband` (đọc `SAMPLE_RATE` từ `.env` local, không liên quan F-05, có từ trước khi sửa) |
| Contract test `live` | **Chưa chạy** — cần reset instance chung, chờ owner báo team rồi chạy lệnh ở trên |

## Ghi chú

- **Test của A không sửa nội dung.** `tests/test_schema.py` từng bị sửa trong lúc làm rồi đã hoàn nguyên; để test đó pass nguyên bản, `as_page` coi body `{}` là trang rỗng (mock thật luôn trả đủ ba khóa; `{"patients": [...]}` vẫn bị từ chối `BAD_RESPONSE`).
- `FakeClinicAPI()` mặc định seed theo Listing 3 (09:00, hai slot) để test engine hiện có của A không đổi; `FakeClinicAPI.with_mock_fixtures()` seed đúng dữ liệu mock mentor (15:30, một slot, bộ per-tenant) cho contract test. `strict_slot_window=False` mặc định vì test engine dùng đồng hồ thật và slot 14-10-2026 nằm ngoài `now+14d` — cửa sổ slot là việc của T-09.
- Số điện thoại: Gateway nhận số đã chuẩn; `+84…` hiện vẫn tới mock và bị 400 (test `test_find_patients_propagates_mock_validation_error` khóa hành vi này). T-01 chuẩn hóa trong `Verifier.prepare()`.
- Việc của A tiếp theo: (1) `orchestrator.py` mở `collect_api_calls()` quanh `_process` và đưa `[r.to_dict() for r in calls]` vào event `turn` (R-02); (2) review 3 dòng sửa ở `dialogue/manager.py`.
- T-12 dùng `ClinicWriteRejected.retryable` / `ClinicAPIError.retryable` và `FakeClinicAPI.fail_next(..., outcome_unknown=True, apply_first=True)` để cài retry có giới hạn.

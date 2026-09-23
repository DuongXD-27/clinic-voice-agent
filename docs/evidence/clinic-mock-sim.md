# Evidence: clinic_mock_sim — clinic giả dùng chung cho test

## Mục tiêu

Chuyển `FakeClinicAPI` (trước ở `src/callbot/engine/tools/fake_clinic.py`, re-export qua
`tests/engine/fake_clinic.py`) thành package riêng `src/clinic_mock_sim/`, **chỉ dùng cho test**, để:

- mọi feature (engine, transports, speech, script) dùng chung một clinic giả qua fixture `clinic`,
  không phải tự viết subclass hay sửa thẳng state;
- sim bám sát mock của mentor (`clinic-mock/src/clinic_mock/`, CHANGELOG 2.0.0) — mỗi file sim trỏ về
  một file mock, và sửa các chỗ lệch đã tìm thấy khi đối chiếu;
- edge case mock thật không có (trùng số, timeout đã ghi, backend sập...) dựng một lần, cả team dùng lại;
- code production không import được sim và test không vô tình ghi vào mock chung của team.

Tên `clinic_mock_sim` (không phải `clinic_mock`) để không trùng package của mentor.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Package dưới `src/`, cấu trúc đối chiếu mock | `src/clinic_mock_sim/{routes,store,schemas,lifecycle,errors}.py` ↔ file cùng tên của mock; `faults.py`, `recorder.py`, `scenarios.py`, `pytest_plugin.py` chỉ có ở sim |
| Chỉ dùng cho test | `pyproject.toml`: không có trong `[tool.hatch.build.targets.wheel] packages` → không vào image (Dockerfile `pip install .`); import được khi cài `-e` nhờ `dev-mode-dirs = ["src"]`. `test_production_code_never_imports_the_sim`, `test_sim_is_not_shipped_in_the_wheel` trong `tests/clinic_mock_sim/test_plugin.py` |
| Test mới chỉ cần xin fixture | `pytest_plugin.py` định nghĩa `clinic`, `clinic_scenario`; `tests/conftest.py` đăng ký `pytest_plugins = ["clinic_mock_sim.pytest_plugin"]`. `test_clinic_fixture_is_a_fresh_default_sim`, `test_clinic_scenario_fixture_builds_by_name` |
| Chặn ghi nhầm vào mock chung | Fixture autouse `block_live_clinic` chặn request tới host `CLINIC_MOCK_BASE_URL` trừ khi `CLINIC_MOCK_LIVE=1`. `test_live_clinic_host_is_blocked_unless_opted_in` (pytester) |
| Sửa lệch với mock: enum reason | Mock trả 400 khi `cancel_reason`/`transfer_reason`/`unreachable_reason` ngoài Appendix A, kiểm trước idempotency; sim cũ nhận mọi chuỗi. `test_reason_outside_appendix_a_is_400_and_writes_nothing` (contract, chạy cả `live`), `test_invalid_reason_is_checked_before_idempotency` |
| Sửa lệch: patient không có `verify` | Mock lỗi 500 khi đặt lịch (PatientRef.verify bắt buộc). `test_create_for_patient_without_verify_is_500_and_books_nothing` |
| Sửa lệch: slot giải phóng khi reschedule | Mock trả slot cũ với `provider_id` của lịch cũ và ghi đè theo `slot_id`. `test_reschedule_releases_old_slot_with_the_old_provider`, `test_seed_slot_replaces_same_id_and_normalizes_shape` |
| Sửa lệch: `confirmed_at`, 5xx | `confirmed_at` UTC dạng `...sssZ` như `store.now_iso()` (assert trong contract test); `clinic_error` 5xx mặc định `outcome_known=False` như `ClinicMockClient`. `test_clinic_error_marks_5xx_outcome_unknown_like_the_real_client` |
| Gây lỗi dùng chung | `faults.py`: `fail_next` (mọi exception, `"*"`), `fail_times`, `fail_always`, `delay`, `after_next`, `clear_faults`; tên thao tác sai → `ValueError`. 13 test trong `tests/clinic_mock_sim/test_faults.py` |
| Edge case có tên | `scenarios.py`: 11 scenario kèm cờ "mock thật có không". `tests/clinic_mock_sim/test_scenarios.py` |
| Thay subclass tự viết | `tests/engine/session/test_turn_lifecycle.py`: `SlowClinic` → `delay`, `CrashingClinic`/`TimeoutClinic`/`ConflictOnce` → `fail_next`; `test_orchestrator.py`: `clinic.slots.append` → `seed_slot` |
| Không vỡ test hiện có | Bề mặt quan sát giữ nguyên (`writes`, `requests`, `calls`, `appointments`, `taken_slots`, `apt_new_<n>`); `with_mock_fixtures()` giữ làm alias của `mentor_mock()`. Toàn bộ suite pass |

## File liên quan

- `src/clinic_mock_sim/` (mới: 10 module + `README.md`)
- `tests/clinic_mock_sim/` (mới: `test_faults.py`, `test_routes.py`, `test_scenarios.py`, `test_plugin.py`; `test_contract.py` chuyển từ `tests/engine/tools/test_clinic_api_contract.py`)
- Xóa: `src/callbot/engine/tools/fake_clinic.py`, `tests/engine/fake_clinic.py`
- `src/callbot/engine/tools/__init__.py` (bỏ export `FakeClinicAPI`), `src/callbot/engine/tools/ports.py` (docstring)
- `tests/conftest.py` + 17 file test đổi import sang `clinic_mock_sim`, `scripts/cancel_eval.py` (bỏ hack `sys.path` tới gốc repo)
- `tests/engine/test_call_termination.py` (transfer gặp 503 → đối soát như client thật, xem Ghi chú; `_set_status` dùng `clinic.set_status`)
- `pyproject.toml` (ruff `known-first-party`), `README.md`, `docs/reference/clinic-mock.md`

## Luồng hiện tại

```text
test xin fixture `clinic` / `clinic_scenario(name)`
  -> pytest_plugin: FakeClinicAPI() mới (store.seed_listing3) [+ scenarios.apply]
  -> create_orchestrator(clinic) / client (create_app(clinic_factory=lambda: clinic))
  -> ClinicGateway gọi FakeClinicAPI.<thao tác>
       -> CallRecorder: delay → fault (fail_next / fail_always) → schemas → idempotency
          → version → lifecycle → ghi state + writes → after_next
       -> ApiCallRecord vào clinic.calls + record_api_call (trace)
  -> test assert clinic.writes / requests / calls
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

Chỉ chạy test của phần liên quan: `python -m pytest tests\clinic_mock_sim -q`

Đối chiếu với mock thật (xóa dữ liệu của cả team trên instance chung — báo trước):
`CLINIC_MOCK_LIVE=1 python -m pytest tests\clinic_mock_sim\test_contract.py -q`

## Kết quả xác minh cục bộ (2026-09-23)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Fail — 6 file có sẵn từ trước, không thuộc task này (`src/callbot/__init__.py`, `engine/dialogue/__init__.py`, `engine/extraction/fallback.py`, `tracing/__init__.py`, `transports/__init__.py`, `transports/http/__init__.py`); mọi file task này tạo/sửa đều đã format |
| `python -m pytest -q` | Pass (1700 passed, 28 skipped; trước task: 1643 passed, 25 skipped) |
| `python -m pytest tests/clinic_mock_sim -q` | Pass (75 passed, 21 skipped — phần `live` của contract test) |
| `make check` | Không chạy — máy không có `make`; đã chạy ba lệnh tương đương ở trên |
| Contract test trên mock thật (`CLINIC_MOCK_LIVE=1`) | Chưa chạy — cần báo team trước khi reset instance chung |

## Ghi chú

- **Transfer gặp 503 (đã chốt: theo hành vi mock/client thật):** sim cũ trả 503 dạng "đã biết" nên `test_rejected_transfer_still_hands_the_call_to_staff[upstream]` kỳ vọng bot vẫn chuyển máy. `ClinicMockClient` luôn coi 5xx là `outcome_known=False`, nên thực tế bot chặn lượt để đối soát (`ReconciliationRequired`) — đúng quy tắc "lệnh ghi chưa rõ kết quả mới chặn lượt để đối soát" của file test. Ca 503 chuyển sang `test_transfer_timeout_needs_reconciliation[upstream_5xx]`; không đổi code bot.
- **Lịch đã ở trạng thái cuối khi mở cuộc gọi (đúng thiết kế, không phải lỗi):** lượt 0 bot chào và báo "xin phép chuyển máy" nhưng chưa `ended`; lượt 1 mới kết thúc `TRANSFERRED` và không gửi `/transfer` vì mock không cho transfer từ trạng thái cuối — `test_non_actionable_appointment_is_transferred_at_turn_one`. Hành vi của bot, như nhau trên mock deploy và sim.
- Contract test phần `live` chưa chạy lại trên mock thật sau khi thêm ca enum reason 400 và assert `confirmed_at` hậu tố `Z`; hai hành vi này đọc từ source mock (`schemas.py`, `store.now_iso`).
- Sim chưa mô phỏng auth/tenant, `/_harness/*`, `GET /v1/appointments?date=` (bot không gọi); `bad_key` có dưới dạng scenario lỗi.
- Tài liệu lịch sử (`docs/plans/f05-clinic-gateway.md`, evidence cũ) vẫn nhắc đường dẫn cũ `tools/fake_clinic.py` — giữ nguyên vì là bản ghi tại thời điểm đó.

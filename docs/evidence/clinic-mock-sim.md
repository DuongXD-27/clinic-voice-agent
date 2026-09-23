# Evidence: clinic_mock_sim — clinic giả dùng chung cho test và demo Docker local

## Mục tiêu

Chuyển `FakeClinicAPI` (trước ở `src/callbot/engine/tools/fake_clinic.py`, re-export qua
`tests/engine/fake_clinic.py`) thành package riêng `src/clinic_mock_sim/` dùng cho test, để:

- mọi feature (engine, transports, speech, script) dùng chung một clinic giả qua fixture `clinic`,
  không phải tự viết subclass hay sửa thẳng state;
- sim bám sát mock của mentor (`clinic-mock/src/clinic_mock/`, CHANGELOG 2.0.0) — mỗi file sim trỏ về
  một file mock, và sửa các chỗ lệch đã tìm thấy khi đối chiếu;
- edge case mock thật không có (trùng số, timeout đã ghi, backend sập...) dựng một lần, cả team dùng lại;
- code production không import được sim và test không vô tình ghi vào mock chung của team.

Phần 2 — demo Docker local: `CLINIC_BACKEND=mock|sim` chọn clinic cho app. `docker compose` local
mặc định chạy trên sim (không cần mạng/key, luôn có slot để demo đổi lịch — mock deploy lọc slot theo
14 ngày từ hôm nay nên hiện không trả slot 14/10/2026); deploy cố định `mock`.

Tên `clinic_mock_sim` (không phải `clinic_mock`) để không trùng package của mentor.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Package dưới `src/`, cấu trúc đối chiếu mock | `src/clinic_mock_sim/{routes,store,schemas,lifecycle,errors}.py` ↔ file cùng tên của mock; `faults.py`, `recorder.py`, `scenarios.py`, `pytest_plugin.py` chỉ có ở sim |
| Ranh giới với code production | Trong `src/callbot`, `src/speech`, `src/inference` chỉ `callbot/transports/http/clinic_backend.py` import sim, và chỉ trong hàm. `test_production_code_imports_the_sim_only_through_the_backend_switch`, `test_backend_switch_imports_the_sim_lazily` trong `tests/clinic_mock_sim/test_plugin.py` |
| Test mới chỉ cần xin fixture | `pytest_plugin.py` định nghĩa `clinic`, `clinic_scenario`; `tests/conftest.py` đăng ký `pytest_plugins = ["clinic_mock_sim.pytest_plugin"]`. `test_clinic_fixture_is_a_fresh_default_sim`, `test_clinic_scenario_fixture_builds_by_name` |
| Chặn ghi nhầm vào mock chung | Fixture autouse `block_live_clinic` chặn request tới host `CLINIC_MOCK_BASE_URL` trừ khi `CLINIC_MOCK_LIVE=1`. `test_live_clinic_host_is_blocked_unless_opted_in` (pytester) |
| Sửa lệch với mock: enum reason | Mock trả 400 khi `cancel_reason`/`transfer_reason`/`unreachable_reason` ngoài Appendix A, kiểm trước idempotency; sim cũ nhận mọi chuỗi. `test_reason_outside_appendix_a_is_400_and_writes_nothing` (contract, chạy cả `live`), `test_invalid_reason_is_checked_before_idempotency` |
| Sửa lệch: patient không có `verify` | Mock lỗi 500 khi đặt lịch (PatientRef.verify bắt buộc). `test_create_for_patient_without_verify_is_500_and_books_nothing` |
| Sửa lệch: slot giải phóng khi reschedule | Mock trả slot cũ với `provider_id` của lịch cũ và ghi đè theo `slot_id`. `test_reschedule_releases_old_slot_with_the_old_provider`, `test_seed_slot_replaces_same_id_and_normalizes_shape` |
| Sửa lệch: `confirmed_at`, 5xx | `confirmed_at` UTC dạng `...sssZ` như `store.now_iso()` (assert trong contract test); `clinic_error` 5xx mặc định `outcome_known=False` như `ClinicMockClient`. `test_clinic_error_marks_5xx_outcome_unknown_like_the_real_client` |
| Gây lỗi dùng chung | `faults.py`: `fail_next` (mọi exception, `"*"`), `fail_times`, `fail_always`, `delay`, `after_next`, `clear_faults`; tên thao tác sai → `ValueError`. 13 test trong `tests/clinic_mock_sim/test_faults.py` |
| Edge case có tên | `scenarios.py`: 11 scenario kèm cờ "mock thật có không". `tests/clinic_mock_sim/test_scenarios.py` |
| Thay subclass tự viết | `tests/engine/session/test_turn_lifecycle.py`: `SlowClinic` → `delay`, `CrashingClinic`/`TimeoutClinic`/`ConflictOnce` → `fail_next`; `test_orchestrator.py`: `clinic.slots.append` → `seed_slot` |
| Docker local mặc định sim, 1 worker | `docker-compose.yml`: `CLINIC_BACKEND: ${CLINIC_BACKEND:-sim}`, `WEB_CONCURRENCY: ${WEB_CONCURRENCY:-1}`, `CLINIC_SIM_DATASET`, `CLINIC_SIM_SCENARIO`. `test_local_compose_defaults_to_sim_with_one_worker`; `docker compose config` ra `CLINIC_BACKEND: sim`, `WEB_CONCURRENCY: "1"` |
| Deploy luôn là mock | `docker-compose.prod.yml`: `CLINIC_BACKEND: mock` trong `environment:` (ghi đè `.env` server). `test_deploy_compose_pins_the_real_mock`; `docker compose -f docker-compose.prod.yml config` với `CLINIC_BACKEND=sim` trong môi trường vẫn ra `mock` |
| Chọn backend | `clinic_backend.build_clinic(settings)`: `mock` (mặc định) → `ClinicMockClient`; `sim` → `FakeClinicAPI` theo `CLINIC_SIM_DATASET` (`listing3` \| `mentor_mock`) + `CLINIC_SIM_SCENARIO` (tên cách nhau dấu phẩy), log cảnh báo. `config.Settings` thêm 3 trường kiểu `Literal`. `tests/transports/http/test_clinic_backend.py` (dataset, scenario, backend sai → `ValidationError`) |
| Sim luôn chạy 1 worker, không ai phải sửa `.env` | Sim nằm trong bộ nhớ từng process → nhiều worker là nhiều bản lệch nhau. `Dockerfile` CMD: `CLINIC_BACKEND=sim` thì `export WEB_CONCURRENCY=1` trước `uvicorn --workers` (thành viên còn `WEB_CONCURRENCY=2` trong `.env` vẫn chạy được); mock giữ nguyên số worker. Lưới an toàn khi chạy `uvicorn --workers N` trực tiếp: `build_clinic` raise `RuntimeError` nếu `WEB_CONCURRENCY != 1`. `test_image_forces_one_worker_when_the_sim_is_selected`, `test_sim_refuses_more_than_one_worker`; scenario sai tên raise lúc khởi động — `test_unknown_scenario_fails_at_startup` |
| App chạy offline trên sim | `test_app_runs_a_call_on_the_sim_without_a_clinic_factory`: `create_app()` mặc định + `CLINIC_BACKEND=sim` → `POST /v1/calls` 200, clinic là `FakeClinicAPI`, đóng khi shutdown |
| Sim có trong image | `pyproject.toml` wheel `packages` thêm `src/clinic_mock_sim`; `Dockerfile` stub bước cài dependency thêm `src/clinic_mock_sim/__init__.py`. `test_sim_ships_in_the_wheel_and_the_docker_dependency_stub`; `pip wheel .` ra wheel có 11 file `clinic_mock_sim/` |
| Không vỡ test hiện có | Bề mặt quan sát giữ nguyên (`writes`, `requests`, `calls`, `appointments`, `taken_slots`, `apt_new_<n>`); `with_mock_fixtures()` giữ làm alias của `mentor_mock()`. Toàn bộ suite pass |

## File liên quan

- `src/clinic_mock_sim/` (mới: 10 module + `README.md`)
- `tests/clinic_mock_sim/` (mới: `test_faults.py`, `test_routes.py`, `test_scenarios.py`, `test_plugin.py`; `test_contract.py` chuyển từ `tests/engine/tools/test_clinic_api_contract.py`)
- Xóa: `src/callbot/engine/tools/fake_clinic.py`, `tests/engine/fake_clinic.py`
- `src/callbot/engine/tools/__init__.py` (bỏ export `FakeClinicAPI`), `src/callbot/engine/tools/ports.py` (docstring)
- `tests/conftest.py` + 17 file test đổi import sang `clinic_mock_sim`, `scripts/cancel_eval.py` (bỏ hack `sys.path` tới gốc repo)
- `tests/engine/test_call_termination.py` (transfer gặp 503 → đối soát như client thật, xem Ghi chú; `_set_status` dùng `clinic.set_status`)
- `pyproject.toml` (ruff `known-first-party`; wheel `packages`), `README.md`, `docs/reference/clinic-mock.md`
- Phần 2: `src/callbot/transports/http/clinic_backend.py` (mới), `config.py`, `main.py` (`_default_clinic` → `build_clinic`), `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example` (mô tả `CLINIC_*`; `WEB_CONCURRENCY` thành comment — CD tự ghi 2 vào `.env` server, không lấy từ file này), `tests/transports/http/test_clinic_backend.py` (mới)

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

```text
container khởi động (Dockerfile CMD): CLINIC_BACKEND=sim ? export WEB_CONCURRENCY=1 : giữ nguyên
  -> uvicorn --workers "$WEB_CONCURRENCY"
app khởi động (lifespan) -> _default_clinic() -> build_clinic(Settings)
  CLINIC_BACKEND=mock (mặc định; deploy cố định) -> ClinicMockClient(CLINIC_MOCK_BASE_URL, KEY)
  CLINIC_BACKEND=sim (docker compose local mặc định)
     -> WEB_CONCURRENCY != 1 ? RuntimeError : tiếp
     -> FakeClinicAPI.listing3() | mentor_mock()  (CLINIC_SIM_DATASET)
     -> scenarios.apply(...) cho từng tên trong CLINIC_SIM_SCENARIO
     -> log cảnh báo "CLINIC_BACKEND=sim ..."
  -> create_orchestrator(clinic)
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
| `python -m pytest -q` | Pass (1712 passed, 28 skipped; phần 1: 1700; trước task: 1643 passed, 25 skipped) |
| `python -m pytest tests/transports/http/test_clinic_backend.py tests/clinic_mock_sim -q` | Pass (86 passed, 21 skipped — phần `live` của contract test) |
| `docker compose config` (local / prod) | Pass — local `CLINIC_BACKEND: sim`, `WEB_CONCURRENCY: "1"`; prod `CLINIC_BACKEND: mock` kể cả khi môi trường đặt `sim` |
| `python -m pip wheel . --no-deps` | Pass — wheel có 11 file `clinic_mock_sim/` |
| `docker compose build bot` | Pass — `import clinic_mock_sim` được trong image |
| `build_clinic` trong image (`docker run ... python -c`) | Pass — `CLINIC_BACKEND=sim`, `WEB_CONCURRENCY=1`, `CLINIC_SIM_SCENARIO=terminal_status,duplicate_phone` → `FakeClinicAPI`, lịch `CANCELLED`, 2 bệnh nhân, có log cảnh báo; gọi `build_clinic` thẳng với `WEB_CONCURRENCY=2` → `RuntimeError` kèm hướng dẫn |
| CMD thật của image (`docker inspect` → chạy với `exec uvicorn` thay bằng `echo`) | Pass — sim + `WEB_CONCURRENCY=2` → `--workers 1`; sim → 1; mock + 2 → 2; mock → 2; không đặt gì (như deploy) → 2 |
| `docker compose up` đầy đủ | Không chạy — tránh chiếm cổng 8000/6379 trên máy dev và gọi TTS trả phí lúc warm-up; đường `create_app()` + sim đã phủ bằng `test_app_runs_a_call_on_the_sim_without_a_clinic_factory` |
| `make check` | Không chạy — máy không có `make`; đã chạy ba lệnh tương đương ở trên |
| Contract test trên mock thật (`CLINIC_MOCK_LIVE=1`) | Chưa chạy — cần báo team trước khi reset instance chung |

## Ghi chú

- **Transfer gặp 503 (đã chốt: theo hành vi mock/client thật):** sim cũ trả 503 dạng "đã biết" nên `test_rejected_transfer_still_hands_the_call_to_staff[upstream]` kỳ vọng bot vẫn chuyển máy. `ClinicMockClient` luôn coi 5xx là `outcome_known=False`, nên thực tế bot chặn lượt để đối soát (`ReconciliationRequired`) — đúng quy tắc "lệnh ghi chưa rõ kết quả mới chặn lượt để đối soát" của file test. Ca 503 chuyển sang `test_transfer_timeout_needs_reconciliation[upstream_5xx]`; không đổi code bot.
- **Lịch đã ở trạng thái cuối khi mở cuộc gọi (đúng thiết kế, không phải lỗi):** lượt 0 bot chào và báo "xin phép chuyển máy" nhưng chưa `ended`; lượt 1 mới kết thúc `TRANSFERRED` và không gửi `/transfer` vì mock không cho transfer từ trạng thái cuối — `test_non_actionable_appointment_is_transferred_at_turn_one`. Hành vi của bot, như nhau trên mock deploy và sim.
- Contract test phần `live` chưa chạy lại trên mock thật sau khi thêm ca enum reason 400 và assert `confirmed_at` hậu tố `Z`; hai hành vi này đọc từ source mock (`schemas.py`, `store.now_iso`).
- **Demo trên sim:** dữ liệu trong bộ nhớ, mất khi restart và dồn lại giữa các lần demo — `docker compose restart bot` để về ban đầu. Không thêm endpoint reset để phần demo không mở thêm đường ghi. Dataset `mentor_mock` lọc slot như mock deploy nên có thể không có slot nào (cửa sổ 14 ngày từ hôm nay).
- Chạy `uvicorn` trực tiếp vẫn mặc định `mock` như trước; `docker run --env-file .env` image cũng mặc định `mock` (image đặt `WEB_CONCURRENCY=2`).
- Sim chưa mô phỏng auth/tenant, `/_harness/*`, `GET /v1/appointments?date=` (bot không gọi); `bad_key` có dưới dạng scenario lỗi.
- Tài liệu lịch sử (`docs/plans/f05-clinic-gateway.md`, evidence cũ) vẫn nhắc đường dẫn cũ `tools/fake_clinic.py` — giữ nguyên vì là bản ghi tại thời điểm đó.

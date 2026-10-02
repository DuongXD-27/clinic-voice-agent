# clinic_mock_sim

Clinic mock chạy trong bộ nhớ, dùng cho **test** và **demo Docker local**. Cài đúng
`ports.ClinicAPI` như `ClinicMockClient` (HTTP thật) nên bot không phân biệt được hai bên — nhưng
không cần mạng, không cần key, và dựng được những tình huống mock thật không có (trùng số điện
thoại, backend timeout, slot bị lấy mất giữa chừng...). Bản deploy luôn dùng mock thật.

- Viết test mới: **xin fixture `clinic` là xong**, không cần tự viết clinic giả hay subclass.
- Demo local: `docker compose up` là chạy trên sim — xem [Demo bằng Docker local](#demo-bằng-docker-local).

---

## Bắt đầu trong 1 phút

Không cần cài thêm gì: đã `pip install -e ".[dev]"` là import được.

```python
from callbot.engine import CallerInput, CallStart, create_orchestrator


def test_confirm_goes_through(clinic) -> None:
    # clinic: FakeClinicAPI mới cho riêng test này — apt_00417, 09:00 14/10/2026
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id="c_demo", direction="outbound", appointment_id="apt_00417"))

    for turn, text in enumerate(["Nguyễn Văn A", "14/03/1978", "đúng rồi"], start=1):
        bot.handle_turn("c_demo", CallerInput(turn=turn, text=text))

    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
```

```bash
python -m pytest tests/engine/test_confirm_dialogue.py -q
```

| Muốn | Viết |
|---|---|
| Clinic mặc định | fixture `clinic`, hoặc `FakeClinicAPI()` |
| Edge case dựng sẵn | fixture `clinic_scenario("slot_race")` |
| Gây lỗi một lần | `clinic.fail_next("confirm_appointment")` |
| Xem bot đã ghi gì | `clinic.writes`, `clinic.requests`, `clinic.calls` |

---

## Fixture pytest

Đăng ký sẵn trong `tests/conftest.py` (`pytest_plugins = ["clinic_mock_sim.pytest_plugin"]`), mọi
test trong `tests/` dùng được, không cần import.

| Fixture | Trả về |
|---|---|
| `clinic` | `FakeClinicAPI()` mới cho mỗi test, dữ liệu mặc định |
| `clinic_scenario` | Factory: `clinic_scenario("terminal_status", status="TRANSFERRED")` |
| `client` | `TestClient` của app HTTP, chạy trên fixture `clinic` (định nghĩa ở `tests/conftest.py`) |
| `block_live_clinic` | Autouse — chặn request tới host của `CLINIC_MOCK_BASE_URL`, xem [dưới](#chặn-gọi-mock-thật) |

Muốn clinic khác cho cả file test (kể cả test HTTP qua `client`): override `clinic` trong file đó.

```python
import pytest

from clinic_mock_sim import FakeClinicAPI


@pytest.fixture
def clinic() -> FakeClinicAPI:
    clinic = FakeClinicAPI()
    clinic.fail_next("get_appointment")
    return clinic


def test_start_call_when_clinic_is_down(client, clinic) -> None:
    # payload đầy đủ: xem _start() trong tests/transports/http/test_calls.py
    client.post("/v1/calls", json={...})
    assert [c.code for c in clinic.calls] == ["UPSTREAM"]
```

Script chạy tay (ngoài pytest) import thẳng: `from clinic_mock_sim import FakeClinicAPI`.

---

## Dữ liệu có sẵn

**`FakeClinicAPI()`** (= `FakeClinicAPI.listing3()`) — mặc định, khớp Listing 3 của contract. Test
engine hiện có ghi cứng các giá trị này.

| Bản ghi | Giá trị |
|---|---|
| Patient `pt_3391` | phone `0912345600`, verify `Nguyễn Văn A` / `1978-03-14` |
| Appointment `apt_00417` | `SCHEDULED`, version `3`, `2026-10-14T09:00+07:00`, `cl_vinmec`, Nội tổng quát, chiếm `slot_77aa` |
| Slot trống | `slot_aa01` 10:00, `slot_91d2` 14:30 (cùng ngày, `cl_vinmec`) |

`/slots` **không** lọc theo cửa sổ `from`/`to` ở chế độ này (test dùng đồng hồ thật, slot
14/10/2026 nằm ngoài `now + 14 ngày`).

**`FakeClinicAPI.mentor_mock()`** — y như mock của mentor sau `/_harness/reset`. Dùng khi test
Gateway hoặc cần hành vi sát mock thật. (`with_mock_fixtures()` là tên cũ, vẫn dùng được.)

| Khác mặc định | Giá trị |
|---|---|
| `apt_00417` | 15:30–16:00 |
| Slot trống `cl_vinmec` | `slot_91d2` 15:00 14/10, cộng 10 slot demo `slot_b501`–`slot_b510` (15–21/10) |
| Bệnh nhân demo | `pt_3401`–`pt_3410` (SĐT `0901234501`–`0901234510`), mỗi người một lịch `apt_00418`–`apt_00427` SCHEDULED 15–20/10 — giống mock deploy từ 24/09 (clinic-mock `aa8b94e`) |
| Bộ per-tenant | patient `p_12345` (`0912345678`), `p_67890` (`0987654321`); slot `s_987`, `s_988` (`c_001`), `s_1024` (`c_002`) ngày 15/09/2026 |
| `/slots` | **có** lọc cửa sổ `from ≤ start < to` |

**Clinic rỗng:** `FakeClinicAPI(seed=False)` rồi tự seed.

---

## Edge case dựng sẵn — `scenarios`

```python
def test_bot_offers_again_when_slot_is_taken(clinic_scenario) -> None:
    clinic = clinic_scenario("slot_race")
    ...
```

Ngoài pytest: `scenarios.build("slot_race")`; chồng lên sim có sẵn:
`scenarios.apply(FakeClinicAPI.mentor_mock(), "version_drift")`.

| Tên | Tình huống | Tham số | Mock thật có |
|---|---|---|---|
| `duplicate_phone` | `pt_3392` dùng chung số `0912345600` với `pt_3391` | | Không |
| `verify_null` | `pt_4000` số `0912345611`, `verify: null`; đặt lịch → 500 | | Không |
| `many_slots` | Slot `slot_m000…` ngày 15/10/2026, mỗi 5 phút từ 07:00 | `count=150` | Không |
| `slot_race` | Slot đầu tiên của lần `get_slots` kế tiếp bị lấy ngay sau khi đọc → reschedule `SLOT_TAKEN`, create `NOT_FOUND` | | Có |
| `version_drift` | Ngay sau lần `get_appointment` kế tiếp, version tăng → lệnh ghi đầu `VERSION_CONFLICT` | `appointment_id` | Có |
| `terminal_status` | Lịch đã ở trạng thái cuối → mọi lệnh ghi `INVALID_STATE_TRANSITION` | `status="CANCELLED"` | Có |
| `write_timeout_applied` | Clinic đã ghi nhưng bot nhận timeout | `operation="confirm_appointment"` | Không |
| `upstream_down` | Mọi lần gọi 503, tới khi `clear_faults()` | `operation="*"` | Không |
| `rate_limited` | `times` lần gọi kế tiếp 429, sau đó bình thường | `operation="*"`, `times=1` | Không |
| `bad_key` | Mọi lần gọi 401 `BAD_KEY` | | Không |
| `slow_backend` | Mọi lần gọi chậm (chờ thật) | `seconds=7.5`, `operation="*"` | Không |

Hằng số dùng trong assert (`VERIFY_NULL_PHONE`, `DUPLICATE_PATIENT`...) import từ
`clinic_mock_sim.scenarios`.

---

## Tự dựng tình huống

### Dữ liệu

```python
# trùng số, không có verify
clinic.seed_patient({"patient_id": "pt_x", "phone": "0912345600", "verify": None})
# field thiếu tự điền (cl_vinmec, +30 phút, pr_vinmec_1); trùng slot_id thì thay
clinic.seed_slot({"slot_id": "slot_x", "start_time": "2026-10-14T16:00:00+07:00"})
# slot_id / provider_id: để reschedule trả slot cũ về như mock
clinic.seed_appointment({...}, slot_id="slot_y", provider_id="pr_vinmec_1")

clinic.set_status("apt_00417", "CANCELLED")  # trạng thái trước cuộc gọi, không tăng version
clinic.bump_version("apt_00417")  # người khác vừa sửa → lệnh ghi sau VERSION_CONFLICT
clinic.take_slot("slot_91d2")  # người khác vừa đặt → biến khỏi /slots
```

### Lỗi và độ trễ

```python
from clinic_mock_sim import clinic_error

# Lần gọi KẾ TIẾP lỗi; gọi nhiều lần để xếp hàng nhiều lỗi
clinic.fail_next("get_slots")  # 503 UPSTREAM
clinic.fail_next("cancel_appointment", clinic_error(409, "VERSION_CONFLICT"))
clinic.fail_next("confirm_appointment", outcome_unknown=True)  # timeout, chưa ghi
clinic.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)  # timeout, ĐÃ ghi
clinic.fail_next("get_appointment", RuntimeError("boom"))  # nhận mọi exception

clinic.fail_times("get_slots", 2, clinic_error(429, "RATE_LIMITED"))  # 2 lần rồi bình thường
# Lần đầu ĐÃ ghi, mọi lần gửi lại (Gateway T-12) vẫn timeout: bot hết lượt mà chưa rõ kết quả
clinic.fail_unknown("confirm_appointment", WRITE_MAX_SENDS, apply_first=True)
clinic.fail_always("*", clinic_error(401, "BAD_KEY"))  # mọi thao tác, tới khi clear_faults()
clinic.delay("get_appointment", 7.5)  # chờ thật; times=1 để chỉ chậm một lần
clinic.after_next("get_slots", lambda page: clinic.take_slot("slot_aa01"))  # chạy sau lần gọi kế
clinic.clear_faults()
```

- Tên thao tác: `find_patient_by_phone`, `get_slots`, `get_appointment`, `create_appointment`,
  `confirm_appointment`, `cancel_appointment`, `transfer_appointment`, `reschedule_appointment`,
  `mark_unreachable`, hoặc `"*"` cho mọi thao tác. Gõ sai tên → `ValueError` ngay.
- Thứ tự trong một lần gọi: `delay` → lỗi đã xếp (`fail_next`/`fail_times`) → `fail_always` → xử
  lý như mock → `after_next`.
- `apply_first=True` là case quan trọng nhất để test chống ghi trùng: clinic đã đổi state nhưng bot
  nhận `ClinicAPIError(outcome_known=False)`. Gửi lại cùng key sẽ được replay, không ghi hai lần.
- Gateway tự gửi lại lỗi tạm thời tới `WRITE_MAX_SENDS` lần (T-12, `callbot.engine.tools.clinic_gateway`):
  một lỗi đơn lẻ sẽ được phục hồi. Muốn test nhánh "vẫn lỗi" thì cho lỗi lặp đủ số lần đó.
- `delay` chờ thật bằng `clinic.sleep`. Không muốn chờ: `clinic.sleep = lambda seconds: None` —
  `calls[i].latency_ms` vẫn ghi độ trễ giả.

---

## Kiểm tra bot đã làm gì

| Thuộc tính | Nội dung |
|---|---|
| `writes` | `[(appointment_id, STATUS, extra)]` — lệnh ghi **đã áp dụng**. Replay idempotent không thêm dòng |
| `requests` | `[(idempotency_key, op)]` — **mọi** lệnh ghi đã gửi, kể cả replay và lần bị lỗi |
| `calls` | `ApiCallRecord` mỗi lần gọi (operation, status, code, outcome, latency_ms) — giống trace client thật |
| `patient_lookups` | Các số điện thoại đã tra |
| `slot_reads` | Số lần `get_slots` thành công |
| `appointments[id]` | State hiện tại — **chỉ đọc để assert**; dựng state thì dùng helper ở trên |
| `closed` | App đã gọi `close()` khi shutdown |

`STATUS` trong `writes`: `BOOKED`, `CONFIRMED`, `CANCELLED`, `TRANSFERRED`, `RESCHEDULED`,
`UNREACHABLE`. `op` trong `requests`: `book`, `CONFIRMED`, `CANCELLED`, `TRANSFERRED`,
`reschedule`, `unreachable`.

```python
assert clinic.writes == []  # bot không được ghi
cancel_keys = {key for key, op in clinic.requests if op == "CANCELLED"}
assert len(cancel_keys) == 1  # gửi lại dùng cùng một key
```

---

## Sim trả lỗi gì

Tất cả là `ClinicAPIError(status, code, message, request_id, outcome_known)`, giống client thật.
`outcome_known` theo client thật: **5xx → `False`** (không biết mock đã ghi chưa), còn lại `True`.
Cần 5xx "đã biết" thì ghi rõ: `clinic_error(503, "UPSTREAM", outcome_known=True)`.

| Status | Code | Khi nào |
|---|---|---|
| 400 | `INVALID_REQUEST` | Phone sai `^(02\|03\|05\|07\|08\|09)\d{8}$`; `from`/`to` không phải RFC 3339 đủ giây + offset, `to ≤ from`, hoặc cửa sổ > 14 ngày; `cancel_reason` / `transfer_reason` / `unreachable_reason` ngoài Appendix A |
| 404 | `NOT_FOUND` | Appointment / patient / slot (khi create) không tồn tại hoặc đã bị chiếm |
| 409 | `VERSION_CONFLICT` | `version` (If-Match) lệch |
| 409 | `INVALID_STATE_TRANSITION` | Sai lifecycle (bảng dưới) |
| 409 | `CONFIRMATION_REQUIRED` | `cancel_appointment(..., confirmed=False)` |
| 409 | `SLOT_TAKEN` | Reschedule sang slot không còn trống |
| 422 | `IDEMPOTENCY_CONFLICT` | Cùng `idempotency_key`, khác payload |
| 500 | `HTTP_ERROR` | Đặt lịch cho patient không có `verify` (mock lỗi pydantic, chưa ghi gì) |
| 503 | `UPSTREAM` | `fail_next` mặc định |
| — | `TIMEOUT` | `fail_next(..., outcome_unknown=True)`: `status=None`, `outcome_known=False` |

Thứ tự kiểm tra như mock: body (enum) → idempotency → tồn tại → version → `confirmed` → lifecycle
→ slot.

| Thao tác | Được phép từ trạng thái |
|---|---|
| confirm, cancel, transfer, reschedule | `SCHEDULED`, `BOOKED`, `CONFIRMED` |
| unreachable | `SCHEDULED`, `BOOKED`, `UNREACHABLE` (mỗi lần tăng `attempt_count`) |

**Khác mock có chủ đích:** id lịch mới là `apt_new_<n>` (mock: `apt_<uuid>`; test ghi cứng),
`request_id` là `"fake"`. Không mô phỏng (bot không gọi): auth/tenant, `/_harness/*`,
`GET /v1/appointments?date=`.

---

## Demo bằng Docker local

`docker-compose.yml` mặc định chạy bot trên sim — không cần mạng hay `CLINIC_MOCK_API_KEY`.

| Muốn | Đặt trong `.env` | Chạy |
|---|---|---|
| Demo trên sim (mặc định) | không cần gì | `docker compose up -d` |
| Demo edge case | `CLINIC_SIM_SCENARIO=slot_race` (nhiều tên: cách nhau dấu phẩy) | `docker compose up -d` |
| Dữ liệu giống mock deploy | `CLINIC_SIM_DATASET=mentor_mock` | `docker compose up -d` |
| Gọi mock đã deploy | `CLINIC_BACKEND=mock` + `CLINIC_MOCK_API_KEY` | `docker compose up -d` |
| Làm lại từ đầu (sim) | — | `docker compose restart bot` |

Lần đầu sau khi pull cần `docker compose up -d --build` để image có package này; sau đó đổi qua
lại chỉ cần `up -d`.

- **Dataset:** `listing3` (mặc định) — `apt_00417` 09:00 14/10/2026, 2 slot trống, `/slots` không
  lọc ngày nên luôn có slot để demo đổi lịch. `mentor_mock` giống mock deploy — `/slots` lọc theo
  cửa sổ 14 ngày từ hôm nay nên có thể không có slot nào.
- **1 worker, tự động:** sim giữ dữ liệu trong bộ nhớ của từng process, nhiều worker là nhiều bản
  lệch nhau. Image tự chạy 1 worker khi `CLINIC_BACKEND=sim`, kể cả khi `.env` còn
  `WEB_CONCURRENCY=2` — không cần sửa `.env`. Chạy `uvicorn --workers 2` trực tiếp với sim thì app
  từ chối khởi động kèm hướng dẫn.
- **Dữ liệu mất khi restart** và dồn lại giữa các lần demo (huỷ `apt_00417` xong thì các lần sau
  đều chuyển máy) — `docker compose restart bot` để về dữ liệu ban đầu.
- Log khởi động có dòng cảnh báo `CLINIC_BACKEND=sim: dùng clinic giả trong bộ nhớ...`.
- Chạy `uvicorn` trực tiếp (không Docker): mặc định `mock`; muốn sim thì đặt `CLINIC_BACKEND=sim`.
- **Deploy** (`docker-compose.prod.yml`) cố định `CLINIC_BACKEND: mock`, ghi đè `.env` trên server.

Code chọn backend: [clinic_backend.py](../callbot/transports/http/clinic_backend.py).

---

## Chặn gọi mock thật

Fixture autouse `block_live_clinic` chặn mọi request tới host của `CLINIC_MOCK_BASE_URL` (đọc từ
`.env`). Test quên truyền clinic — ví dụ `create_app()` không có `clinic_factory` — sẽ đỏ với
`RuntimeError: Test đang gọi clinic mock thật...` thay vì âm thầm ghi vào instance chung của team.
Mock chạy ở `localhost` không bị chặn.

---

## Kiểm tra sim vẫn khớp mock thật

```bash
python -m pytest tests/clinic_mock_sim -q   # chỉ sim, offline
```

Không có test tự động chạy trên mock thật: instance dùng chung, reset/ghi sẽ xóa và đổi dữ liệu của
cả team. Muốn đối chiếu với mock thật thì đọc `routes.py` / `store.py` của repo clinic-mock.

---

## Quy tắc

- **Import từ `tests/` và `scripts/`.** Trong `src/callbot`, `src/speech`, `src/inference` chỉ
  `callbot/transports/http/clinic_backend.py` được import package này, và chỉ trong hàm khi
  `CLINIC_BACKEND=sim` (`test_plugin.py` kiểm tra). Package có trong image để demo local; deploy
  vẫn luôn là mock nhờ compose prod.
- **Sửa hành vi sim** (mã lỗi, lifecycle, shape) → đối chiếu `routes.py` của mock, cập nhật
  `test_contract.py`.
- **Thêm edge case** → hàm `(sim, **params)` trong `scenarios.py` có docstring, đăng ký vào
  `SCENARIOS` kèm cờ "mock thật có không", test trong `tests/clinic_mock_sim/test_scenarios.py`,
  thêm dòng vào bảng scenario ở trên. Mock thật có tình huống đó thì thêm case vào contract test.
- **Mentor cập nhật mock** → đọc `clinic-mock/docs/CHANGELOG.md`, sửa file tương ứng (bảng dưới).

## File

Mỗi file trỏ về một file của `clinic-mock/src/clinic_mock/` (đang bám CHANGELOG `2.0.0`).

| File | Tương ứng mock | Nội dung |
|---|---|---|
| `routes.py` | `routes.py` | `FakeClinicAPI` — 9 thao tác, idempotency, phân trang, helper dựng state |
| `store.py` | `store.py` | Fixture Listing 3 / mentor, chuẩn hóa slot, `now_iso` |
| `schemas.py` | `schemas.py` | Regex phone/ISO, enum reason và status |
| `lifecycle.py` | `lifecycle.py` | Bảng chuyển trạng thái |
| `errors.py` | `errors.py` | `clinic_error` và các lỗi chuẩn |
| `faults.py` | — | `fail_next`, `fail_times`, `fail_always`, `delay`, `after_next` |
| `recorder.py` | — | Ghi `ApiCallRecord` cho mỗi lần gọi |
| `scenarios.py` | — | Edge case có tên |
| `pytest_plugin.py` | — | Fixture `clinic`, `clinic_scenario`, `block_live_clinic` |

Test của package: `tests/clinic_mock_sim/`. Tài liệu liên quan:
[clinic-mock.md](../../docs/reference/clinic-mock.md) (hành vi mock thật),
[ports.py](../callbot/engine/tools/ports.py) (interface `ClinicAPI`).

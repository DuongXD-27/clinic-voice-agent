# Plan F-05 — Hoàn thiện Clinic Client/Gateway

**Owner:** B (Hưng) · **Trạng thái:** Chờ duyệt · **Ngày:** 17-09-2026
**Nguồn:** `docs/task-breakdown.md` §2 (F-05), contract AIHR-PC-001 rev 1.1 §4.2, repo clinic-mock (mentor, commit `5f16851`)

## 1. Mục tiêu và điều kiện hoàn thành

Theo task-breakdown:

> Đối chiếu endpoint, authentication, wrapper và phân trang; chuẩn hóa patient/appointment/slot; bổ sung `unreachable`; thống nhất kết quả lỗi; cung cấp fake theo interface.
> **Điều kiện hoàn thành:** Các thao tác Gateway tương thích Mock thực tế; A có fake để phát triển song song.

Diễn giải thành tiêu chí kiểm được:

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | Mọi endpoint nghiệp vụ (9 endpoint Bảng 3, trừ `/_harness/*`) gọi đúng path, method, header, body và **đọc hết mọi trang** kết quả | Contract test chạy trên fake **và** trên mock thật (`CLINIC_MOCK_LIVE=1`) cùng pass |
| AC-2 | Số điện thoại, thời gian, slot/patient/appointment được chuẩn hóa về một dạng duy nhất trước khi vào engine | Unit test normalizer + Gateway trả đúng khóa canonical |
| AC-3 | Lỗi từ mock (400/401/404/409/422/429/5xx, timeout, mất kết nối) được phân loại thành một tập lỗi cố định; Gateway không rò `httpx` ra ngoài | Unit test từng mã lỗi → đúng exception; `grep httpx` ngoài `tools/` không còn |
| AC-4 | `POST /appointments/{id}/unreachable` đúng §4.2.5 (body chỉ có reason, If-Match, replay cùng key không tăng attempt) | Test trên fake + live |
| AC-5 | `FakeClinicAPI` mô phỏng đúng mock (envelope, mã lỗi, version, idempotency, lifecycle) và A dùng được mà không cần docker | Cùng bộ contract test AC-1 pass trên fake; `tests/engine/test_identity.py`, `test_orchestrator.py` hiện có vẫn pass |
| AC-6 | Bot không bao giờ gọi `/_harness/*` (§4.2.4) | Test `test_contract_clinic_client_never_requests_harness_paths` hiện có giữ nguyên và mở rộng cho endpoint mới |

## 2. Ràng buộc contract liên quan

| Điều khoản | Nội dung áp dụng cho Gateway |
| --- | --- |
| §4.2.2 | Mock là nguồn duy nhất về trạng thái lịch hẹn. Gateway chỉ giữ bản sao chỉ đọc trong `CallContext` (`slots`, `version` đọc gần nhất). |
| §4.2.3 | Mọi write mang `Idempotency-Key` (MUST) và `If-Match` (SHOULD). |
| §4.2.4 | Không gọi `/_harness/*`. |
| §4.2.5 | `/unreachable`: body chỉ `unreachable_reason`; gửi `attempt_count` → 400; mock kiểm tra key trước If-Match; sau 409 VERSION_CONFLICT đọc lại và retry **cùng key**. |
| §1.1.6, SF-02 | Slot đề xuất phải đến từ `GET /slots` trong chính cuộc gọi. |
| §1.1.9 | `GET /patients?phone=` chỉ là tra cứu, không phải bằng chứng danh tính; không tạo patient. |
| Phụ lục A | Mã lỗi HTTP: 400 INVALID_REQUEST · 401 BAD_KEY · 404 NOT_FOUND · 409 SLOT_TAKEN/VERSION_CONFLICT · 429 RATE_LIMITED · 503 UPSTREAM. |

## 3. Hiện trạng (đối chiếu code ngày 17-09)

### 3.1 Bot — `src/callbot/engine/tools/`

| File | Có gì | Ghi chú |
| --- | --- | --- |
| `ports.py` | `Protocol ClinicAPI` 9 phương thức, trả `dict[str, Any]` thô | Chưa có tham số `cursor`/`limit`; docstring chưa định nghĩa shape trả về |
| `clinic_mock_client.py` | `ClinicMockClient(httpx)`: đủ 9 endpoint, Bearer, `Idempotency-Key`/`If-Match` qua `_write_headers`, `mark_unreachable` đúng body §4.2.5 | `raise_for_status()` → rò `httpx.HTTPStatusError` ra ngoài; một `timeout=5.0` chung; không phân trang; không chuẩn hóa phone; không log request_id |
| `clinic_gateway.py` | `ClinicGateway`: đọc (`get_appointment`, `find_patients_by_phone`, `list_open_slots`) + ghi qua `_write` (journal, key `call_id:turn:op`, retry 1 lần khi VERSION_CONFLICT, phân loại 5xx/timeout → `WriteOutcomeUnknown`, connect error → `ClinicWriteRejected`) | Phần **ghi** đã khá hoàn chỉnh (F-03 làm). Phần **đọc** chỉ lấy trang đầu và parse "bao dung" (`data`/`patients`/`items`/`slots`) — dấu hiệu chưa chốt shape |
| `engine/errors.py` | `ClinicWriteRejected(status, code)`, `SlotTaken`, `WriteOutcomeUnknown` | Chỉ cho write; read chưa có lỗi typed |
| `tests/engine/fake_clinic.py` | `FakeClinicAPI` in-memory, có idempotency replay, `writes` log | Xem lệch ở §4.3 |

### 3.2 Mock thật — `clinic-mock/src/clinic_mock/`

Đọc trực tiếp `routes.py`, `schemas.py`, `errors.py`, `lifecycle.py`, `auth.py`, `store.py`:

- Prefix `/v1`; auth Bearer `sk_*` → 401 `BAD_KEY`; cross-tenant → 404 (ẩn tồn tại).
- **Danh sách** (`/patients`, `/slots`, `/appointments?date=`): `{"data": [...], "next_cursor": str|null, "has_more": bool}`; `limit` mặc định 25, kẹp `[1, 100]`; cursor base64 offset.
- `/patients?phone=`: regex `^(02|03|05|07|08|09)\d{8}$` — sai dạng → **400 `INVALID_REQUEST`** (mock có handler `RequestValidationError` → envelope `error` kèm `details[]`). `Patient`: `patient_id, display_name, phone, dob, verify{full_name, dob} | null`.
- `/slots`: `from`/`to` phải RFC3339 đủ giây + offset; `to - from ≤ 14 ngày`; `Slot`: `slot_id, clinic_id, start_time, end_time, provider_id` (**không có** `starts_at`).
- `GET /appointments/{id}`: Listing 3 + `ends_at`, `cancel_reason`, `transfer_reason`, `unreachable_reason`, `confirmed_at`, `confirmed_via`, `new_slot_id`, `attempt_count`, `version`.
- Write: idempotency cache key = `endpoint:Idempotency-Key`; payload hash của confirm/cancel/transfer/reschedule **gồm cả `if_match`**, của unreachable/create **chỉ body**. Cùng key khác payload → **422 `IDEMPOTENCY_CONFLICT`**. Chỉ lưu cache sau khi thành công (409 không được cache → retry với If-Match mới OK).
- Lifecycle (`lifecycle.py`): confirm/cancel/transfer/reschedule từ `{SCHEDULED, BOOKED, CONFIRMED}`; unreachable từ `{SCHEDULED, BOOKED, UNREACHABLE}`; sai → **409 `INVALID_STATE_TRANSITION`**.
- Cancel thiếu `confirmed: true` → **409 `CONFIRMATION_REQUIRED`**.
- Reschedule: slot không còn → 409 `SLOT_TAKEN`; response **tối giản** (`status, new_slot_id, released_slot_id, version`), không phải appointment đầy đủ.
- Create: **201**, replay có header `Idempotent-Replayed: true`; slot bị tiêu thụ khỏi `db.slots`.
- Envelope lỗi: `{"error": {"code", "message", "request_id", "details"?}}`.

## 4. Khoảng cách cần xử lý

### 4.1 Client / Gateway

| # | Vấn đề | Bằng chứng | Ảnh hưởng |
| --- | --- | --- | --- |
| G-1 | Không phân trang: `list_open_slots` và `find_patients_by_phone` chỉ đọc trang đầu (25 bản ghi) | `clinic_gateway.py:57-76`; mock `paginate()` limit 25 | Slot hợp lệ trang 2 không vào `ctx.slots` → bot nói "hết slot" sai; SF-02 chặn slot thật |
| G-2 | Không chuẩn hóa số điện thoại | mock regex chỉ nhận `0xxxxxxxxx`; harness/telephony có thể đưa `+84…`, `84…`, có khoảng trắng | Inbound lookup bị 400 INVALID_REQUEST → ngoại lệ → chuyển máy SYSTEM_ERROR thay vì PATIENT_NOT_FOUND |
| G-3 | Read rò `httpx.HTTPStatusError` lên Dialogue | `clinic_mock_client.py` dùng `raise_for_status()`; `dialogue/manager.py:86` phải `except httpx.HTTPError` | Dialogue (của A) phụ thuộc httpx; lỗi 404/401 khi đọc không phân biệt được |
| G-4 | Parse "bao dung" nhiều khóa (`data`/`patients`/`items`/`slots`) | `clinic_gateway.py:53,70` | Che lỗi shape; fake và mock lệch nhau mà test vẫn xanh |
| G-5 | Slot chỉ chuẩn hóa `starts_at`, không `ends_at`; patient/appointment không chuẩn hóa | `_normalize_slot` | Chưa có định nghĩa shape canonical để A tin cậy |
| G-6 | Timeout đơn 5s, không tách connect/read; không cấu hình được | `ClinicMockClient.__init__` | Ngân sách 8s/lượt (S-03): một read chậm ăn hết lượt |
| G-7 | Không log `request_id`/latency mỗi request | — | R-02 khó truy nguyên khi đối chiếu với writelog của mock |
| G-8 | Mã lỗi ngoài Phụ lục A (`CONFIRMATION_REQUIRED`, `INVALID_STATE_TRANSITION`, `IDEMPOTENCY_CONFLICT`) chưa được nhận diện tường minh | `_write` chỉ xét `VERSION_CONFLICT`, `SLOT_TAKEN` | Rơi vào `ClinicWriteRejected` chung — chấp nhận được, nhưng cần test để chắc không bị coi là "unknown" |
| G-9 | 429 RATE_LIMITED bị coi như từ chối vĩnh viễn | `_write`: `status < 500` → `ClinicWriteRejected` | Lệnh chưa được áp dụng nhưng có thể thử lại — F-05 chỉ phân loại, T-12 quyết định retry |
| G-10 | API key không kiểm tra prefix `sk_` lúc khởi tạo | — | Lỗi cấu hình chỉ lộ khi cuộc gọi đầu tiên 401 |

### 4.2 `/unreachable` (yêu cầu "bổ sung unreachable")

Đã có ở cả Client và Gateway (F-03 làm trước). F-05 chỉ cần **xác nhận bằng test** với mock thật: body chỉ reason, If-Match gửi kèm, replay cùng key + If-Match cũ vẫn 200 và `attempt_count` không tăng, gửi `attempt_count` → 400. Hành vi retry/timeout sâu hơn thuộc T-07.

### 4.3 Fake lệch mock

| # | Fake hiện tại | Mock thật | Hậu quả với A |
| --- | --- | --- | --- |
| K-1 | `{"patients": [...]}`, `{"slots": [...]}` | `{"data": [...], "next_cursor", "has_more"}` | Code A test xanh trên fake, đỏ trên mock |
| K-2 | Slot có `starts_at` | Slot có `start_time`, `end_time`, `provider_id`, `clinic_id` | Normalizer không được test thật |
| K-3 | **Bỏ qua `version`** | 409 VERSION_CONFLICT khi If-Match lệch | Nhánh retry của `_write` chưa từng được chạy trên fake |
| K-4 | Không kiểm tra lifecycle | 409 INVALID_STATE_TRANSITION | A không thấy lỗi khi confirm một lịch đã CANCELLED |
| K-5 | Không có 404 appointment/patient, không có 422 IDEMPOTENCY_CONFLICT, không kiểm tra regex phone | Có | Thiếu nhánh lỗi để A viết policy |
| K-6 | `mark_unreachable` không kiểm tra status trước | Chỉ từ SCHEDULED/BOOKED/UNREACHABLE | — |
| K-7 | Tạo lỗi bằng `httpx.HTTPStatusError` thủ công | — | Fake phụ thuộc httpx; nếu Client đổi sang lỗi typed thì fake phải đổi theo |
| K-8 | Nằm trong `tests/` | — | Chỉ dùng được trong pytest; không chạy được HTTP app local không cần mock |

## 5. Thiết kế đề xuất

### 5.1 Nguyên tắc phân lớp

```text
DialogueManager / IdentityVerifier (A, B)
        │  dict canonical (starts_at, ends_at, slot_id, patient.verify, version ...)
        ▼
ClinicGateway  (B) — guardrail SF-01/02/05, FSM, journal, phân trang, chuẩn hóa, map lỗi → engine.errors
        │  ClinicAPI Protocol: shape THÔ của mock, một trang mỗi lần gọi, lỗi = ClinicAPIError
        ▼
ClinicMockClient (httpx)  |  FakeClinicAPI (in-memory)   (B)
```

- **Protocol mô phỏng mock 1:1** (một trang, shape thô, cùng mã lỗi) → cùng một bộ contract test chạy được trên cả fake và mock thật. Đây là cách duy nhất chứng minh "fake theo interface".
- **Gateway là nơi duy nhất chuẩn hóa** và đi hết các trang; A chỉ thấy dict canonical.
- Không đưa `httpx` ra khỏi `tools/`.

### 5.2 Thay đổi interface `ports.py` (cần A đồng ý — chạm F-01)

```python
class ClinicAPIError(Exception):
    """Mock trả lỗi xác định (envelope {"error": {...}}) hoặc lỗi transport."""
    status: Optional[int]      # None khi lỗi transport
    code: Optional[str]        # INVALID_REQUEST | BAD_KEY | NOT_FOUND | SLOT_TAKEN | VERSION_CONFLICT
                               # | CONFIRMATION_REQUIRED | INVALID_STATE_TRANSITION | IDEMPOTENCY_CONFLICT
                               # | RATE_LIMITED | UPSTREAM | CONNECT_ERROR | TIMEOUT | ...
    message: str
    request_id: Optional[str]
    outcome_known: bool        # False = không biết mock đã áp dụng chưa (read timeout, 5xx, mất kết nối giữa chừng)

class ClinicAPI(Protocol):
    def find_patient_by_phone(self, phone: str, cursor: Optional[str] = None, limit: int = 100) -> Page: ...
    def get_slots(self, clinic_id: str, from_: str, to: str, cursor: Optional[str] = None, limit: int = 100) -> Page: ...
    # 7 phương thức còn lại giữ nguyên chữ ký
```

`Page = dict` với đúng 3 khóa `data`, `next_cursor`, `has_more` (TypedDict để mypy/ruff bắt). `phone` truyền vào Protocol **đã chuẩn hóa** (Gateway lo).

Lý do giữ phân trang ở Gateway thay vì Client tự gộp: (1) fake buộc phải cài phân trang → A thấy hành vi thật; (2) Gateway là nơi quyết định "nguồn slot" (SF-02) nên phải biết mình đã đọc hết chưa; (3) Protocol vẫn 1:1 với mock.

### 5.3 `ClinicMockClient`

- `httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=2.0)`; đọc từ `Settings.clinic_mock_timeout_s` (mặc định 5.0 cho read). Số cụ thể chốt ở F-01 với A theo ngân sách 8s.
- Kiểm tra `api_key.startswith("sk_")` lúc khởi tạo → `ValueError` sớm (fail-fast); base URL bỏ `/` cuối và cảnh báo nếu không kết thúc bằng `/v1`.
- `_request()` chung: đo latency, đọc envelope `error`, đính `request_id`, raise `ClinicAPIError`. Phân loại:
  - `httpx.ConnectError`/`ConnectTimeout` → `code=CONNECT_ERROR`, `outcome_known=True` (chưa tới mock);
  - `httpx.ReadTimeout`/`RemoteProtocolError`/5xx → `outcome_known=False`;
  - 4xx → `outcome_known=True`, `code` từ envelope `error.code` (mock luôn trả envelope, kể cả lỗi validation → 400 INVALID_REQUEST); fallback theo status nếu body không parse được: 400→INVALID_REQUEST, 401→BAD_KEY, 404→NOT_FOUND, 429→RATE_LIMITED.
- `log.debug` một dòng/request: `method path status request_id latency_ms` (không log body — có PII).
- Giữ `close()`; thêm `__enter__/__exit__`.

### 5.4 `ClinicGateway`

- `_all_pages(fetch) -> list[dict]`: lặp `cursor` đến `has_more == False`, trần 20 trang (chống vòng lặp vô hạn nếu mock lỗi cursor) → vượt trần raise `ClinicAPIError(code="PAGINATION_OVERFLOW")`.
- `find_patients_by_phone(raw_phone)`: `normalize_phone()` → `None` thì trả `[]` **không gọi mock** (log lý do); có thì đi hết trang, chuẩn hóa từng patient.
- `list_open_slots(ctx, now)`: đi hết trang, `_normalize_slot` bổ sung `ends_at`; giữ `start_time`/`end_time` gốc để trace. Vẫn thay toàn bộ `ctx.slots`.
- `get_appointment(ctx)`: `_normalize_appointment` — đảm bảo có `patient.verify` (nếu mock trả `null` thì để `None`, Verifier tự xử lý), ép `version: int`, `attempt_count: int`.
- `_write`: chuyển sang bắt `ClinicAPIError` thay cho `httpx.*`:
  - `outcome_known=False` → `WriteOutcomeUnknown` (như hiện tại);
  - `code == VERSION_CONFLICT` và attempt 1 → đọc lại, retry cùng key (giữ);
  - `SLOT_TAKEN` → `SlotTaken`; `RATE_LIMITED` → `ClinicWriteRejected(retryable=True)` (trường mới, T-12 dùng);
  - còn lại → `ClinicWriteRejected(status, code)`.
- Xóa parse bao dung (G-4): đọc đúng `page["data"]`, sai shape → `ClinicAPIError(code="BAD_RESPONSE")`.

### 5.5 Chuẩn hóa (`tools/normalize.py`, mới)

| Hàm | Vào | Ra | Quy tắc |
| --- | --- | --- | --- |
| `normalize_phone(raw)` | `"+84 912 345 600"`, `"84912345600"`, `"0912345600"`, `"tel:+84-912…"` | `"0912345600"` hoặc `None` | Bỏ mọi ký tự không phải số; `84` đầu (11 số) → `0`; kết quả phải khớp regex của mock, không thì `None` |
| `normalize_slot(raw)` | slot mock | `{slot_id, clinic_id, provider_id, starts_at, ends_at, start_time, end_time}` | `starts_at = start_time`, `ends_at = end_time` |
| `normalize_patient(raw)` | patient mock | `{patient_id, display_name, phone, dob, verify: {full_name, dob} \| None}` | Không bịa `verify` từ `display_name` |
| `normalize_appointment(raw)` | appointment mock | Listing 3 + các trường tuỳ chọn, `version`/`attempt_count` là `int` | Không suy ra trạng thái |
| `iso_local(dt)` | `datetime` | `"2026-10-14T00:00:00+07:00"` | Đủ giây + offset, đúng regex `from`/`to` |

Giữ dict (không đổi sang dataclass) để không đụng code của A (`templates.appointment_summary`, `slot_choice.py` đang đọc `appointment["starts_at"]`, `slot["slot_id"]`). Shape canonical được ghi thành docstring trong `ports.py` và bảng ở `docs/reference/clinic-mock.md`.

### 5.6 `FakeClinicAPI` (chuyển sang `src/callbot/engine/tools/fake_clinic.py`)

Viết lại để **hành xử như `routes.py` của mock**, không có httpx:

- Store: `patients`, `slots`, `appointments` với đúng shape mock; seed mặc định = fixture canonical của mock (`pt_3391`/`0912345600`, `apt_00417` v3 lúc 15:30, `slot_91d2`, `slot_77aa` bị chiếm) + helper `seed_patient()`, `seed_slot()`, `seed_appointment()` để test thêm dữ liệu.
- Đọc: phân trang `data/next_cursor/has_more` với `limit` như mock; `find_patient_by_phone` kiểm tra regex → `ClinicAPIError(400, INVALID_REQUEST)`; `get_slots` kiểm tra RFC3339, `to > from`, ≤ 14 ngày → 400; `get_appointment` 404.
- Ghi: idempotency cache theo `endpoint:key` với payload hash **giống mock** (confirm/cancel/transfer/reschedule gồm `if_match`; unreachable/create chỉ body) → 422 `IDEMPOTENCY_CONFLICT`; `If-Match` lệch → 409 `VERSION_CONFLICT` (kiểm tra **sau** idempotency); lifecycle → 409 `INVALID_STATE_TRANSITION`; cancel thiếu `confirmed` → 409 `CONFIRMATION_REQUIRED`; reschedule giải phóng slot cũ, `SLOT_TAKEN`; create 201 trả appointment BOOKED v1 và tiêu thụ slot; unreachable tăng `attempt_count`, replay không tăng.
- Núm thử nghiệm cho A và cho T-12: `fail_next(operation, ClinicAPIError)`, `fail_next(operation, outcome_unknown=True)` (mô phỏng timeout sau khi đã áp dụng hoặc chưa), `latency_ms`.
- Quan sát: `requests: list[(method, path, headers, body)]` (mọi request kể cả replay), `writes` (giống `/_harness/writelog`).
- `tests/engine/fake_clinic.py` giữ lại như re-export mỏng để test hiện có của A không đổi import.

### 5.7 Contract test dùng chung fake ↔ mock thật

`tests/engine/tools/test_clinic_api_contract.py`, fixture `api` parametrize hai giá trị:

- `fake` — luôn chạy;
- `live` — `ClinicMockClient(CLINIC_MOCK_BASE_URL, CLINIC_MOCK_API_KEY)`, `pytest.skip` nếu thiếu `CLINIC_MOCK_LIVE=1`. Trước mỗi test gọi `POST /_harness/reset` **từ fixture test** (không phải từ Client — Client không có phương thức này) và báo trên kênh team theo quy ước `docs/reference/clinic-mock.md` §6.

Các case: phân trang (seed > 25 slot ở fake; live dùng bộ per-tenant), phone regex, slot window, 404, VERSION_CONFLICT → retry, IDEMPOTENCY_CONFLICT, CONFIRMATION_REQUIRED, INVALID_STATE_TRANSITION, SLOT_TAKEN, create 201 + replay, unreachable §4.2.5 (replay không tăng attempt; `attempt_count` trong body → 400), không có request nào tới `/_harness/*` từ Client.

## 6. Các bước thực hiện

| Bước | Việc | File | Phụ thuộc |
| --- | --- | --- | --- |
| 1 | Chốt với A: `ClinicAPIError`, `Page`, tham số `cursor/limit`, timeout mặc định, vị trí fake | `ports.py`, ghi chú vào evidence F-01 | Trước khi code |
| 2 | Viết `tools/normalize.py` + unit test | `src/callbot/engine/tools/normalize.py`, `tests/engine/tools/test_normalize.py` | — |
| 3 | `ClinicAPIError` + `Page` trong `ports.py`; cập nhật Protocol | `ports.py` | 1 |
| 4 | Viết lại `ClinicMockClient` (`_request`, timeout, auth check, log) | `clinic_mock_client.py`, `transports/http/config.py` (thêm `clinic_mock_timeout_s`) | 3 |
| 5 | Viết lại `FakeClinicAPI` theo §5.6; re-export ở `tests/engine/fake_clinic.py` | `src/callbot/engine/tools/fake_clinic.py`, `tests/engine/fake_clinic.py` | 3 |
| 6 | Contract test §5.7, chạy trên fake trước | `tests/engine/tools/test_clinic_api_contract.py` | 4, 5 |
| 7 | Sửa `ClinicGateway`: `_all_pages`, normalize, map `ClinicAPIError`; bỏ parse bao dung | `clinic_gateway.py`, `engine/errors.py` (thêm `retryable`) | 2–5 |
| 8 | Gỡ `httpx` khỏi `dialogue/manager.py` (`except httpx.HTTPError` → `ClinicAPIError`) — **sửa 2 dòng trong file của A, báo A review** | `dialogue/manager.py:86,98` | 7 |
| 9 | Chạy contract test trên mock thật (`CLINIC_MOCK_LIVE=1`), sau khi báo team | — | 6 |
| 10 | Cập nhật `docs/reference/clinic-mock.md` §5.2/§5.4 (shape canonical, mã lỗi typed), viết `docs/evidence/f05-clinic-gateway.md` | docs | 9 |
| 11 | `make check` xanh | — | tất cả |

Thứ tự 2→5 có thể làm song song với A đang F-03/F-04 vì chưa đụng Gateway; bước 7–8 là điểm hợp nhất, làm trong một PR ngắn.

## 7. Phối hợp với A

| A cần từ B | Khi nào |
| --- | --- |
| `FakeClinicAPI` mới (import path `callbot.engine.tools.fake_clinic`) với seed helper và `fail_next` | Sau bước 5 |
| Bảng shape canonical (slot/patient/appointment) để viết template và IE | Sau bước 2 (docstring `ports.py`) |
| Danh sách `ClinicAPIError.code` để viết policy T-06/T-12 | Sau bước 3 |

| B cần từ A | Khi nào |
| --- | --- |
| Duyệt thay đổi Protocol (§5.2) và timeout | Bước 1 |
| Review 2 dòng sửa ở `dialogue/manager.py` | Bước 8 |
| Xác nhận cách IE/templates đọc slot: chỉ `slot_id`, `starts_at` (đã kiểm tra `slot_choice.py:316`, `manager.py:253-266`) — nếu A cần thêm trường thì báo để normalizer bổ sung | Bước 2 |

## 8. Rủi ro và điểm cần duyệt

| # | Điểm cần quyết | Đề xuất của B | Phương án khác |
| --- | --- | --- | --- |
| Q-1 | Vị trí fake: `src/` hay `tests/`? | `src/callbot/engine/tools/fake_clinic.py` — để chạy HTTP app local không cần mock (`CLINIC_MOCK_BASE_URL=fake://`) và A import không cần `tests` trong path | Giữ ở `tests/`, chấp nhận không chạy app local bằng fake |
| Q-2 | Protocol trả từng trang (fake phải cài phân trang) hay Client tự gộp? | Từng trang (§5.2) | Client gộp, Protocol trả `list` — đơn giản hơn cho A nhưng fake không mô phỏng phân trang |
| Q-3 | Đổi shape dict sang dataclass? | Không, trong F-05 | Làm sau khi A ổn định templates |
| Q-4 | Regex phone: mock chỉ nhận đầu số `02/03/05/07/08/09`; số `01x`, `04x`, `06x` cũ → `None` → PATIENT_NOT_FOUND | Chấp nhận, theo mock | Hỏi mentor nếu dữ liệu chấm điểm có số khác |
| Q-5 | `/patients` với phone sai định dạng: mock trả 400 INVALID_REQUEST | Gateway chặn trước bằng `normalize_phone` nên thực tế không gọi mock; contract test vẫn có case này để khóa hành vi fake = mock | — |
| Q-6 | `list_open_slots` cửa sổ `now → now+14d`: dữ liệu mock là 14-10-2026 nên test live tuần này sẽ trống | Không sửa trong F-05 — ghi nhận cho T-09 (cửa sổ quanh ngày lịch hẹn / theo yêu cầu khách) | — |
| R-1 | Test live trên instance chung có thể phá phiên test của người khác | Luôn báo kênh team trước; mặc định skip | — |
| R-2 | Image chính thức có thể khác bản mentor (§4 `clinic-mock.md`: cờ `confirmed`, mã lỗi ngoài danh sách) | Client bám contract; các mã lỗi ngoài danh sách chỉ dùng để phân loại, không rẽ nhánh nghiệp vụ | — |

## 9. Ngoài phạm vi F-05 (ghi để không lẫn)

- Retry có giới hạn/backoff cho 429 và outcome-unknown → **T-12**.
- Hành vi `/unreachable` khi timeout chưa rõ kết quả, retry cùng key nhiều lần → **T-07**.
- Cửa sổ slot theo yêu cầu khách, đổi lịch nguyên tử, tạo đúng một appointment → **T-09**.
- Thay đổi luồng Verifier → **T-01** (plan riêng `docs/plans/t01-identity-verifier.md`).

## 10. Định nghĩa hoàn thành → evidence

`docs/evidence/f05-clinic-gateway.md` theo `TEMPLATE.md`, mỗi AC ở §1 có một dòng: vị trí code + tên test. Kết quả `make check` và lệnh chạy live (`CLINIC_MOCK_LIVE=1 python -m pytest tests/engine/tools -q`) kèm ngày giờ và ai đã được báo trên kênh team.

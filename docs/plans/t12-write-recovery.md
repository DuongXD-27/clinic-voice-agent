# Plan T-12 — Phục hồi lỗi ghi

**Owner:** B (Hưng) theo `docs/task-breakdown.md` · **Trạng thái:** Đã triển khai — D-1..D-3 chốt 27-09-2026, Q-1, Q-2 chốt theo đề xuất 28-09-2026; evidence `docs/evidence/t12-write-recovery.md` · **Ngày:** 27-09-2026, cập nhật 28-09-2026
**Nguồn:** `docs/task-breakdown.md` §3 (T-12), §7 bất biến 3, 5; contract rev 1.1 §4.2.3, §4.2.5, Listing 4, Listing 5, bảng lỗi Phụ lục A (`429 RATE_LIMITED`, `503 UPSTREAM`); `clinic-mock/src/clinic_mock/routes.py` (idempotency cache); evidence `f05-clinic-gateway.md`, `t03-gateway-confirm-cancel-transfer.md`, `t07-gateway-unreachable.md`, `t09-gateway-slot-reschedule-booking.md`; ghi chú chuyển sang T-12 trong plan/evidence T-04, T-05, T-10
**Phụ thuộc:** F-05 (cờ `retryable`, `outcome_known`, `FakeClinicAPI.fail_next/fail_times`), T-03, T-07, T-09 — đều đã có trên `main` `bce7072`. **Không** phụ thuộc T-10 (T-10 mới có plan, chưa có code).

## 1. Mục tiêu và điều kiện hoàn thành

> Xử lý timeout, version conflict và lỗi dịch vụ tạm thời; retry có giới hạn; giữ cùng key/payload cho cùng thao tác; đánh giá lại điều kiện khi dữ liệu thay đổi.
> **Điều kiện hoàn thành:** Không ghi trùng hoặc báo thành công khi chưa biết kết quả; lỗi được trả cho core để xử lý nhất quán.

Phạm vi nằm trong `ClinicGateway` (`engine/tools/clinic_gateway.py`). Dialogue và các port không đổi.

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | **Chưa rõ kết quả** (timeout, 5xx, đứt kết nối giữa chừng): gửi lại **y hệt** — cùng `Idempotency-Key`, cùng `If-Match`, cùng body; **không** đọc lại version trước khi gửi lại | `fail_next(op, outcome_unknown=True, apply_first=True)` → thành công, `fake.writes` 1 dòng, 2 request cùng key; `apply_first=False` → thành công, 1 dòng |
| AC-2 | **Lỗi tạm thời chắc chắn chưa ghi** (`429 RATE_LIMITED`, `CONNECT_ERROR`): chờ ngắn rồi gửi lại cùng key | `fail_next(op, clinic_error(429, ...))` → thành công, 2 request cùng key |
| AC-3 | **Đọc version trước khi ghi** lỗi tạm thời: đọc lại, chưa gửi lệnh ghi nào | `fail_next("get_appointment", clinic_error(503, ...))` → thành công, không có dòng nhật ký thừa |
| AC-4 | **Retry có giới hạn:** tối đa `WRITE_MAX_SENDS` lần gửi; ngân sách `WRITE_BUDGET_S` dùng chung cho mọi lệnh ghi trong một lượt (sửa ở rà soát lần 2); hết lượt thì trả đúng lớp lỗi như hiện nay — chưa rõ → `WriteOutcomeUnknown` (409 đối soát), chắc chắn chưa ghi → `ClinicWriteRejected(retryable=True)` | `fail_times` vượt giới hạn → đúng exception, số request = giới hạn; đồng hồ giả vượt ngân sách → dừng sớm |
| AC-5 | **`VERSION_CONFLICT` giữ nguyên theo contract** (D-1): **luôn** đọc lại, gửi lại một lần với version mới và cùng key, không tính vào giới hạn của AC-4 (sửa sau review 28-09-2026); không hỏi lại người gọi | Test T-03 hiện có vẫn pass; 429 → 429 → `VERSION_CONFLICT` vẫn được đọc lại |
| AC-1b | **Đã có một lần gửi chưa rõ thì không bao giờ là "từ chối"** (sửa sau review): lỗi xác định ở lần gửi lại vẫn là chưa rõ; 2xx không phải JSON là chưa rõ; kiểm tra status trước khi ghi nhật ký SUCCEEDED | Evidence §"Sửa sau review" |
| AC-6 | **Kiểm tra kết quả sau khi ghi ở Gateway** (D-2) cho confirm, cancel, transfer, unreachable, reschedule (book đã có): 2xx mà `status` sai, hoặc reschedule có `new_slot_id` khác slot đã chọn → `WriteOutcomeUnknown` | Fake trả body lạ (`after_next`) → exception, không báo thành công |
| AC-7 | **Không retry lỗi xác định:** `SLOT_TAKEN`, `INVALID_STATE_TRANSITION`, `IDEMPOTENCY_CONFLICT`, 4xx khác — hành vi như cũ | Test hiện có + 1 request duy nhất |
| AC-8 | **Trace:** mỗi lần gửi là một sự kiện `clinic.attempt`; `attempt_count` bằng số request ghi thật | `collect_api_calls` + span test |

## 2. Hiện trạng (main `bce7072`, 27-09-2026)

`ClinicGateway._write` (`clinic_gateway.py:355-400`) chạy tối đa 2 vòng: mỗi vòng **đọc lại version** rồi gửi; chỉ `VERSION_CONFLICT` ở vòng 1 mới được gửi lại.

| Lỗi khi ghi | Hiện tại | Hậu quả |
| --- | --- | --- |
| `409 VERSION_CONFLICT` | Đọc lại version, gửi lại 1 lần cùng key | ✅ Đúng §4.2.5 |
| Timeout / 5xx / đứt kết nối (`outcome_known=False`) | `journal.unknown` → `WriteOutcomeUnknown` | ❌ Phiên bị khóa, mọi lượt sau nhận `409 CALL_RECONCILIATION_REQUIRED`, kể cả khi Mock đã ghi thành công |
| `429`, `CONNECT_ERROR` (`outcome_known=True`, `retryable=True`) | `ClinicWriteRejected(retryable=True)` | ❌ Dialogue chuyển máy `SYSTEM_ERROR`, không thử lại |
| Lỗi tạm thời khi đọc version trước khi ghi | `ClinicWriteRejected(retryable=True)` | ❌ Như trên |
| 2xx nhưng `status` sai | Book: Gateway chặn. Confirm/cancel/transfer/unreachable: Dialogue chặn (`manager.py:125, 147, 295, 469`). **Reschedule: không ai chặn** | ❌ Có thể báo `RESCHEDULED` sai |

**Sự thật cần biết khi thiết kế:**
- **Mock tính `If-Match` vào dấu vân tay idempotency** của confirm, cancel, transfer, reschedule (`clinic-mock/.../routes.py:290-413`); unreachable và create chỉ tính body. Cùng key + `If-Match` khác → `422 IDEMPOTENCY_CONFLICT`. Nếu lần gửi đầu đã được áp dụng thì version đã tăng; đọc lại version rồi gửi lại cùng key sẽ nhận 422 thay vì replay. `clinic_mock_sim` mô phỏng đúng điều này (`routes.py:8-9`).
- **Mock chỉ cache phản hồi 2xx.** Lỗi 409/422 không được cache, nên sau `VERSION_CONFLICT` gửi cùng key với version mới là hợp lệ (đường T-03 hiện tại).
- **Nhật ký lệnh:** `begin_command` chỉ cho mở lại cùng key khi bản ghi đang `FAILED` và cùng lệnh (`redis_store.py:251-276`, `same_command` không so `if_match`). `finish_command(UNKNOWN)` **xóa nội dung phiên** (`purged_reason=RECONCILIATION_REQUIRED`). ⇒ Gửi lại sau "chưa rõ" phải diễn ra **trước** khi ghi `unknown`, khi lệnh vẫn `PENDING`.
- **Mock nguyên bản không tự phát 429/503** (không có trong `clinic-mock/src`). Trên thực tế các lỗi này đến từ proxy (Caddy 502/503 khi mock restart) hoặc mạng; timeout có thể xảy ra trên EC2. 429 vẫn xử lý vì có trong bảng lỗi Phụ lục A.
- **Client timeout mặc định 5 s** (`clinic_mock_client.py:38`; `clinic_backend.py:21` và `livekit/worker.py:76` không truyền giá trị khác). Một lần timeout đã ăn 5 s trong ngân sách 8 s/lượt → xem Q-1.

### 2.1 Đối chiếu contract

| Điều khoản | Nội dung | Hệ quả cho T-12 |
| --- | --- | --- |
| §4.2.3 | Mọi thao tác ghi PHẢI có `Idempotency-Key`, NÊN có `If-Match` | Key cố định `{call_id}:{turn}:{operation}` (đã có); gửi lại giữ key |
| §4.2.5 | Key được kiểm trước `If-Match`; chỉ 200 được replay; sau `409 VERSION_CONFLICT` đọc lại rồi thử lại với version mới và cùng key | AC-5 giữ nguyên; AC-1 dựa vào replay |
| Listing 4 | `409 SLOT_TAKEN`: "đọc lại /slots, đừng retry mù quáng" | AC-7: không retry, Dialogue đề xuất lại |
| Phụ lục A | `429 RATE_LIMITED`, `503 UPSTREAM` | AC-1, AC-2 |
| Contract | **Không** yêu cầu hỏi lại người gọi khi nội dung lịch đổi | D-1: không làm |
| §4 (8 s) | Mỗi lượt phản hồi trong 8 giây | AC-4: ngân sách cho một thao tác ghi |

## 3. Thiết kế

### 3.1 Luồng `_write` mới

```text
deadline = clock() + WRITE_BUDGET_S
version  = đọc version (retry lỗi đọc tạm thời trong ngân sách; hết → ClinicWriteRejected như cũ)
conflict_retried = False
loop:
    command = ClinicCommand(kind, endpoint, payload, version, key)
    journal.begin(command)                         # lần đầu, hoặc mở lại khi bản ghi đang FAILED
    sends = 0
    loop gửi (cùng version, cùng key):
        sends += 1
        try: result = send(version, key)
        except ClinicAPIError:
            outcome_known=False (timeout, 5xx):
                còn lượt + còn ngân sách → chờ backoff, gửi lại (lệnh vẫn PENDING, KHÔNG journal)
                hết → journal.unknown → WriteOutcomeUnknown
            VERSION_CONFLICT và chưa conflict_retried:
                journal.failed; conflict_retried = True
                version = đọc lại; quay lại loop ngoài (begin lại, cùng key)
            retryable (429, CONNECT_ERROR):
                journal.failed
                còn lượt + còn ngân sách → chờ backoff; journal.begin lại; gửi lại cùng version
                hết → ClinicWriteRejected(retryable=True)
            SLOT_TAKEN → SlotTaken · INVALID_STATE_TRANSITION → AppointmentNotActionable
            khác → ClinicWriteRejected
        except Exception (lỗi ngoài hợp đồng) → journal.unknown → WriteOutcomeUnknown   # như cũ
        journal.succeeded(result); return result
```

- `sends` đếm chung mọi lần gửi của một thao tác (kể cả sau `VERSION_CONFLICT`) và không vượt `WRITE_MAX_SENDS`.
- Trước mỗi lần gửi lại: nếu `deadline - clock() < WRITE_MIN_ATTEMPT_S` thì dừng và trả lỗi của lần cuối.
- Không đổi Idempotency-Key giữa các lần gửi trong cùng thao tác.

### 3.2 Kiểm tra kết quả sau khi ghi (D-2)

Bảng kỳ vọng trong Gateway, kiểm tra ngay sau `_write` trả về (giống `book()` hiện nay):

| Thao tác | Kỳ vọng |
| --- | --- |
| confirm | `status == "CONFIRMED"` |
| cancel | `status == "CANCELLED"` |
| transfer | `status == "TRANSFERRED"` (inbound chưa đặt lịch trả `None` như cũ, bỏ qua) |
| unreachable | `status == "UNREACHABLE"` |
| reschedule | `status == "RESCHEDULED"` và `new_slot_id` == slot đã chọn (Listing 4) |
| book | Đã có: `status == "BOOKED"` và có `appointment_id` |

Sai → `WriteOutcomeUnknown` (lệnh đã được Mock nhận nên không ghi `/transfer` thay thế; phiên bị khóa đối soát — cùng hành vi Dialogue đang làm). Bốn chỗ kiểm tra ở `dialogue/manager.py` **giữ nguyên** (code của A, tránh conflict với T-10/T-11); sau T-12 chúng không bao giờ kích hoạt. Evidence ghi rõ để A xóa khi tiện.

### 3.3 Tham số

Hằng số trong `clinic_gateway.py`, cạnh `PAGE_LIMIT`/`MAX_PAGES`:

| Tên | Đề xuất | Lý do |
| --- | --- | --- |
| `WRITE_MAX_SENDS` | 3 (1 lần đầu + 2 lần gửi lại) | Đủ cho một lần `VERSION_CONFLICT` cộng một lỗi tạm thời |
| `WRITE_BACKOFF_S` | `(0.2, 0.5)` | Ngắn, để còn thời gian cho TTS trong 8 s |
| `WRITE_BUDGET_S` | 4.0 | Phần còn lại của 8 s cho ASR/IE/TTS |
| `WRITE_MIN_ATTEMPT_S` | 1.0 | Không bắt đầu lần gửi khi gần hết ngân sách |

`ClinicGateway.__init__` nhận thêm `sleep` và `clock` (mặc định `time.sleep`, `time.monotonic`) để test không phải chờ thật.

### 3.4 Không đổi

`DialogueManager`, `ports.py`, `ClinicMockClient` (trừ khi Q-1 chọn giảm timeout), `SessionManager`, nhật ký lệnh, khóa idempotency, `SlotTaken`.

## 4. Các bước thực hiện

| # | Việc | File | Phụ thuộc |
| --- | --- | --- | --- |
| 1 | Test đỏ cho AC-1..AC-4, AC-6 ở tầng Gateway | `tests/engine/tools/test_clinic_gateway.py` | 0 |
| 2 | Tách `_read_version` (retry đọc) và vòng gửi trong `_write` theo §3.1; thêm `sleep`/`clock`, hằng số §3.3 | `engine/tools/clinic_gateway.py` | 1 |
| 3 | Bảng kỳ vọng §3.2, áp cho 5 thao tác | `engine/tools/clinic_gateway.py` | 2 |
| 4 | Cập nhật test hiện có đổi kỳ vọng (§5.1) | các file ở §5.1 | 2 |
| 5 | Test luồng qua Orchestrator/HTTP: timeout đã ghi → `CONFIRMED`/`CANCELLED`/`UNREACHABLE` thay vì 409 | `tests/engine/`, `tests/transports/http/test_calls.py` | 3 |
| 6 | Cập nhật docstring `_write` + `errors.py` (bỏ ghi chú "T-12 quyết định"), kiến trúc §4.2 dòng timeout/429 | `clinic_gateway.py`, `errors.py`, `docs/reference/ai-callbot-architecture.md` | 5 |
| 7 | `ruff check`, `ruff format --check`, `pytest -q`; evidence `docs/evidence/t12-write-recovery.md` | — | 6 |

## 5. Test

### 5.1 Test hiện có sẽ đổi kỳ vọng

Các test dưới đây giả lập **một** lỗi rồi mong đợi bị khóa / chuyển máy. Sau T-12, một lỗi sẽ được gửi lại và thành công. Giữ ý định của test bằng cách cho lỗi lặp vượt giới hạn (`fail_times(op, WRITE_MAX_SENDS, ...)`), và thêm test mới cho ca một lỗi → thành công.

| Test | Hiện mong đợi | Sửa |
| --- | --- | --- |
| `test_clinic_gateway.py::test_unknown_outcome_is_journaled_and_not_retried` | 1 request, `unknown` | Đổi tên + lặp lỗi vượt giới hạn; ca 1 lỗi → test mới |
| `test_clinic_gateway.py::test_definite_rejections_carry_retryable_flag` (429, `CONNECT_ERROR`) | `ClinicWriteRejected` ngay | Hai ca `retryable=True` lặp lỗi vượt giới hạn |
| `test_clinic_gateway.py::test_read_failure_before_send_is_rejection_without_journal_entry` | 503 đọc → từ chối | Lặp lỗi đọc vượt ngân sách |
| `test_confirm_dialogue.py:293` | timeout đã ghi → 409 | Lặp lỗi |
| `test_cancel_dialogue.py:500, 509` | timeout → 409 | Lặp lỗi |
| `test_silence_line_signal.py:312` | unreachable timeout → 409 | Lặp lỗi |
| `test_call_termination.py:190, 202, 220` | 429 / 503 khi transfer | Lặp lỗi |
| `transports/http/test_calls.py:713, 780, 941` | HTTP 409 đối soát | Lặp lỗi |

Các file `test_confirm_dialogue.py`, `test_cancel_dialogue.py`, `test_silence_line_signal.py`, `test_call_termination.py` thuộc A: chỉ đổi cách giả lập lỗi, không đổi assertion nghiệp vụ.

### 5.2 Test mới (tầng Gateway, `FakeClinicAPI`)

| Ca | Giả lập | Kỳ vọng |
| --- | --- | --- |
| Timeout, Mock đã ghi | `fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)` | `CONFIRMED`; 2 request cùng key **và cùng `If-Match`**; `writes` 1 dòng; nhật ký `begin, succeeded` |
| Timeout, Mock chưa ghi | `outcome_unknown=True` | `CONFIRMED`; `writes` 1 dòng |
| Timeout mọi lần | `fail_times(..., WRITE_MAX_SENDS, outcome_unknown=True)` | `WriteOutcomeUnknown`; số request = giới hạn; nhật ký `begin, unknown` |
| Hết ngân sách | đồng hồ giả nhảy quá `WRITE_BUDGET_S` sau lần 1 | Dừng, `WriteOutcomeUnknown`, 1 request |
| 429 một lần | `fail_next(..., clinic_error(429, "RATE_LIMITED"))` | Thành công; nhật ký `begin, failed, begin, succeeded`; `sleep` được gọi với 0.2 |
| 429 mọi lần | `fail_times(..., WRITE_MAX_SENDS, 429)` | `ClinicWriteRejected(retryable=True)` |
| `VERSION_CONFLICT` rồi timeout đã ghi | 409 → `outcome_unknown, apply_first` | Thành công; lần 2 và 3 cùng version mới |
| Đọc version 503 một lần | `fail_next("get_appointment", 503)` | Thành công |
| Không retry | `SLOT_TAKEN`, `INVALID_STATE_TRANSITION`, `422 IDEMPOTENCY_CONFLICT`, `404` | 1 request, exception như cũ |
| Unreachable timeout đã ghi | `mark_unreachable` `apply_first=True` | `attempt_count` trên Mock tăng đúng 1 |
| Reschedule `new_slot_id` sai | `after_next` sửa body | `WriteOutcomeUnknown` |
| Kiểm tra status 5 thao tác | body `status` sai cho từng thao tác | `WriteOutcomeUnknown` |
| Trace | timeout rồi thành công | `attempt_count == 2`, 2 sự kiện `clinic.attempt` |

## 6. Quyết định

| # | Câu hỏi | Chốt | Căn cứ |
| --- | --- | --- | --- |
| D-1 | Nội dung lịch đổi giữa lượt đọc lại và lượt ghi (`VERSION_CONFLICT`) có hỏi lại người gọi? | **Không** — theo contract: đọc lại, gửi lại cùng key (owner 27-09-2026) | §4.2.5 chỉ yêu cầu đọc lại + cùng key; "xác nhận lại" ở kiến trúc §4.2 là chính sách đội, không bắt buộc. Rủi ro ghi ở §7 |
| D-2 | Kiểm tra kết quả ghi đặt ở đâu? | **Gateway**, cho mọi thao tác; không xóa chỗ kiểm tra ở Dialogue trong T-12 (owner 27-09-2026) | Gateway là lớp duy nhất hiểu response Mock và đã hứa trả "thành công có bằng chứng"; một chỗ áp cho mọi luồng; tránh conflict file của A |
| D-3 | Gửi lại sau "chưa rõ" có đọc lại version không? | **Không** — gửi y hệt, giữ `If-Match` cũ (owner 27-09-2026) | Mock tính `If-Match` vào dấu vân tay idempotency; đọc lại → 422 thay vì replay |
| Q-1 | Timeout client Clinic 5 s: một lần timeout đã ăn gần hết ngân sách nên lần gửi lại sau timeout gần như không bao giờ chạy | **Giảm mặc định `ClinicMockClient` còn `timeout=2.0`, `connect=1.0`** (owner 28-09-2026) | Mock trả trong vài chục ms; ảnh hưởng cả lệnh đọc |
| Q-2 | Tham số §3.3 (`3` lần, `4.0 s`, backoff `0.2/0.5`) | **Như §3.3** (owner 28-09-2026); chỉnh sau khi có số đo S-03 | — |

## 7. Ngoài phạm vi và rủi ro

- **Hỏi lại người gọi khi nội dung lịch đổi** (D-1): không làm. Rủi ro: nhân viên sửa giờ lịch giữa lúc bot đọc lại và lúc ghi → bot xác nhận lịch có giờ mới. Hiếm trên đường chấm điểm; lịch chuyển sang trạng thái không thao tác được thì Gateway vẫn chặn (`get_actionable_appointment`).
- **Gửi lại sang lượt sau:** key chứa số lượt, nên T-12 chỉ gửi lại trong cùng lượt. Harness gửi lại cùng lượt khi lệnh đang `PENDING`/`UNKNOWN` vẫn bị chặn đối soát như hiện nay (`SessionManager._admit`).
- **Xóa 4 chỗ kiểm tra status ở Dialogue** (`manager.py:125, 147, 295, 469`): việc của A sau khi T-12 merge.
- **Header `Retry-After`:** Mock không gửi; T-12 dùng backoff cố định.
- **Ngân sách toàn lượt:** Gateway chỉ giới hạn thời gian của riêng thao tác ghi, không biết lượt đã tiêu bao nhiêu cho ASR/IE. Đo thật và cân lại ở S-03.
- **Mock restart giữa hai lần gửi:** cache idempotency và dữ liệu đều nằm trong bộ nhớ nên mất cùng lúc; lần gửi lại sẽ gặp `404`/`VERSION_CONFLICT` và đi đường lỗi xác định.

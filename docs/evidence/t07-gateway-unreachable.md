# Evidence: T-07 — Gateway Unreachable

**Owner:** B (Hưng) · **Ngày:** 21-09-2026

## Mục tiêu

`POST /appointments/{id}/unreachable` (§4.2.5) đã được cài trong lúc làm F-05 (nhánh
`feature/f05-clinic-gateway`, commit `00205e7 f05-clinic-gateway: Done`) vì Gateway cần đủ 9 endpoint
ghi ngay từ đầu để A phát triển song song (silence/voicemail → `UNREACHABLE`, T-08). T-07 chưa có
task riêng nào commit hay evidence xác nhận từng tiêu chí hoàn thành trong `docs/task-breakdown.md`
§3. Evidence này rà lại toàn bộ điều kiện hoàn thành của T-07 đối chiếu với code hiện có, không sửa
logic — chỉ xác nhận lại bằng test đã có sẵn.

Phạm vi: không đổi `src/callbot/engine/tools/clinic_gateway.py`,
`src/callbot/engine/tools/clinic_mock_client.py`, `src/callbot/engine/tools/fake_clinic.py`.

## Bằng chứng trong repo

| Acceptance criterion | Vị trí code | Test chứng minh |
| --- | --- | --- |
| Cài `/unreachable` đúng path/method | `ClinicMockClient.mark_unreachable` (`clinic_mock_client.py:174-188`) POST `/appointments/{id}/unreachable`; `ClinicGateway.mark_unreachable` (`clinic_gateway.py:184-195`) gọi qua `_write` chung | `test_client_never_calls_harness_endpoints` (`test_clinic_mock_client.py:165-187`) xác nhận path `/v1/appointments/.../unreachable` |
| Body **chỉ** gửi `unreachable_reason`, **không gửi `attempt_count`** (§4.2.5) | `clinic_mock_client.py:186` payload `{"unreachable_reason": unreachable_reason}` — không có tham số `attempt_count` nào trong signature | `test_write_headers_and_unreachable_body_per_4_2_5` (`test_clinic_mock_client.py:60-77`): `json.loads(unreachable.content) == {"unreachable_reason": "SILENCE"}` |
| Chỉ áp dụng cho **outbound** | `ClinicGateway.mark_unreachable` (`clinic_gateway.py:186-187`): `if ctx.call.direction != "outbound": raise SevereFailureBlocked("SF-01", ...)` | `test_outbound_three_silent_turns_marks_unreachable` (`test_orchestrator.py:313-320`) ghi UNREACHABLE cho outbound; `test_inbound_silence_transfers_without_booking` (`test_orchestrator.py:344-350`) xác nhận inbound 3 silence → `TRANSFERRED`/`NOT_UNDERSTOOD`, `clinic.writes == []` (không gọi `/unreachable`) |
| Retry giữ **cùng Idempotency-Key**, xử lý `VERSION_CONFLICT` bằng đọc lại version rồi gửi lại đúng 1 lần | `ClinicGateway._write` (`clinic_gateway.py:199-236`): key cố định `{call_id}:{turn}:unreachable`; `attempt in (1, 2)`, đọc lại `_current_version` khi `VERSION_CONFLICT` ở attempt 1 | Contract test `test_unreachable_increments_once_and_replays_with_stale_if_match` (`test_clinic_api_contract.py:200-221`) |
| **Không tăng `attempt_count` hai lần khi retry cùng key** (điều kiện hoàn thành chính của T-07) | Mock kiểm `Idempotency-Key` trước `If-Match` — hành vi này thuộc `clinic-mock` (mentor), Fake mô phỏng lại ở `fake_clinic.py:475-507` (`_write` nội bộ trả cache theo key) | `test_unreachable_increments_once_and_replays_with_stale_if_match` (`test_clinic_api_contract.py:200-221`): gọi lại đúng key với `If-Match` cũ → vẫn 200, `attempt_count` giữ nguyên `attempts + 1`; key mới + version cũ → `409 VERSION_CONFLICT`; key mới + version mới → `attempt_count` mới tăng tiếp lên `attempts + 2` |
| `VERSION_CONFLICT` sau khi đã retry 1 lần → từ chối xác định, không lặp vô hạn | `clinic_gateway.py:226-227`: `if exc.code == "VERSION_CONFLICT" and attempt == 1: continue` — hết vòng lặp thì rơi xuống `raise ClinicWriteRejected` | `test_rejected_unreachable_write_does_not_report_success` (`test_orchestrator.py:323-341`): `fail_next("mark_unreachable", ...)` 2 lần liên tiếp `409 VERSION_CONFLICT` → `appointment["attempt_count"] == 0`, `clinic.writes == []`, `action.outcome != "UNREACHABLE"` (không báo thành công khi bị từ chối) |
| Timeout / kết quả chưa rõ → không báo thành công, chặn phiên để đối soát (không phải retry mù) | `ClinicMockClient._request` (`clinic_mock_client.py:223-225`): `httpx.TimeoutException` → `ClinicAPIError(..., outcome_known=False)`; `clinic_gateway.py:222-224`: `if not exc.outcome_known: raise WriteOutcomeUnknown` (không thử lại); `errors.py:116-120`: `WriteOutcomeUnknown` nằm trong `TURN_ABORTING_ERRORS`, được `session/manager.py:132-135` chuyển thành `ReconciliationRequired` để khóa phiên | Cơ chế dùng chung cho mọi thao tác ghi (đã kiểm bằng `transfer`/`confirm` ở F-05/T-03); cho riêng `mark_unreachable` chưa có test trực tiếp mô phỏng timeout — xem Ghi chú |
| Không lộ chi tiết lịch hẹn trên voicemail khi kết thúc UNREACHABLE (§1.1.7) | `DialogueManager.unreachable` trả `t.GOODBYE_UNREACHABLE`, không đọc lại ngày/giờ | `test_voicemail_ends_unreachable_without_disclosing` (`test_orchestrator.py:353-360`): `"14 tháng 10" not in action.utterance` |

## File liên quan

Không đổi (đã đúng từ F-05, evidence này chỉ xác nhận lại bằng test có sẵn):
- `src/callbot/engine/tools/clinic_gateway.py`
- `src/callbot/engine/tools/clinic_mock_client.py`
- `src/callbot/engine/tools/fake_clinic.py`
- `src/callbot/engine/errors.py`
- `src/callbot/engine/dialogue/manager.py` (hàm `unreachable`)

Test đối chiếu (không sửa):
- `tests/engine/tools/test_clinic_api_contract.py`
- `tests/engine/tools/test_clinic_mock_client.py`
- `tests/engine/test_orchestrator.py`

## Luồng hiện tại

```text
Policy phát hiện outbound 3-silence / voicemail (T-08, A)
  -> DialogueManager.unreachable(ctx, reason)
       -> ClinicGateway.mark_unreachable(ctx, reason)
            -> fsm.check_closing_write                 : lượt hợp lệ để kết thúc
            -> direction != "outbound" -> SevereFailureBlocked("SF-01")
            -> _write("unreachable", ..., {"unreachable_reason": reason})
                 key = f"{call_id}:{turn}:unreachable"
                 đọc version hiện tại -> journal.begin -> gọi mock
                 VERSION_CONFLICT lần 1 -> đọc lại version, gửi lại CÙNG key (lần 2)
                 VERSION_CONFLICT lần 2 / lỗi xác định khác -> ClinicWriteRejected
                 outcome_known=False (timeout, 5xx) -> WriteOutcomeUnknown -> ReconciliationRequired
       -> ghi thành công -> outcome="UNREACHABLE", không đọc lại lịch trên voicemail
       -> ghi bị từ chối -> outcome="TRANSFERRED", transfer_reason="SYSTEM_ERROR" (không báo UNREACHABLE giả)
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`; môi trường xác
minh này còn thiếu `fakeredis` so với `pyproject.toml`, đã `pip install fakeredis` riêng để chạy được
`tests/conftest.py`).

```powershell
make check
```

Chỉ test liên quan T-07:

```powershell
python -m pytest tests\engine\tools\test_clinic_gateway.py tests\engine\tools\test_clinic_api_contract.py tests\engine\tools\test_clinic_mock_client.py tests\engine\test_orchestrator.py -q
```

Contract test trên mock thật (reset instance chung — **báo kênh team trước khi chạy**):

```powershell
$env:CLINIC_MOCK_LIVE = "1"; python -m pytest tests\engine\tools\test_clinic_api_contract.py -q
```

## Kết quả xác minh cục bộ (21-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | 12 file cần format lại, không file nào thuộc phạm vi T-07 (drift CRLF có sẵn, cùng loại đã ghi nhận ở evidence F-05/T-03: `src/callbot/__init__.py`, `speech/`, `tracing/`, `transports/__init__.py`...) |
| `python -m pytest tests\engine\tools\test_clinic_gateway.py tests\engine\tools\test_clinic_api_contract.py tests\engine\tools\test_clinic_mock_client.py tests\engine\test_orchestrator.py -q` | Pass (86 passed, 18 skipped = biến thể `live`) |
| `python -m pytest -q` (toàn repo) | Pass (1126 passed, 24 skipped), không có lỗi nào |
| Contract test `live` (`CLINIC_MOCK_LIVE=1`) | Chưa chạy — code không đổi so với F-05, không cần chạy lại riêng; lần chạy live gần nhất thuộc F-05 (`docs/evidence/f05-clinic-gateway.md`: "Chưa chạy — cần reset instance chung") |

## Ghi chú

- Không phát hiện gap logic. Toàn bộ khoảng trống là **thiếu evidence doc riêng** cho T-07 — chức năng
  được cài đủ trong F-05 vì Gateway cần đủ 9 endpoint để A phát triển song song `T-08` (silence/voicemail).
- **Timeout thực tế khi gọi `/unreachable` chưa có test riêng mô phỏng** (`httpx.TimeoutException` →
  `outcome_known=False`). Cơ chế `WriteOutcomeUnknown`/`ReconciliationRequired` dùng chung cho mọi thao
  tác ghi và đã được test cho `transfer`/`confirm` (F-05: `test_unknown_outcome_is_journaled_and_not_retried`),
  nhưng chưa có case gọi thẳng `mark_unreachable` với `fail_next("mark_unreachable", outcome_unknown=True)`.
  Nên bổ sung nếu cần khóa hành vi này riêng cho `/unreachable`.
- Việc tiếp theo không thuộc T-07: retry có giới hạn/backoff cho lỗi tạm thời khác (429/503) — thuộc T-12,
  hiện **chưa triển khai** (xem ghi chú T-12 ở `docs/evidence/f05-clinic-gateway.md` và
  `docs/plans/f05-clinic-gateway.md:78,276`).

# Evidence: Inbound nhận `caller_number: null` (eval mentor qc-ib-*, PR 0)

## Mục tiêu

Lần chạy eval mentor ngày 13-10-2026, cả 10 case inbound qc-ib-01..10 lỗi ngay ở `POST /v1/calls`. Tất cả trả HTTP 422 `"inbound yêu cầu caller_number"`, chưa chạy lượt nào và chưa case nào được chấm. Nguyên nhân: harness gửi `{"direction": "inbound", "appointment_id": null, "caller_number": null, ...}`. Đây là giá trị Listing 1 của contract cho phép, nhưng validator HTTP lại bắt buộc có `caller_number`.

Phạm vi PR 0: chỉ bỏ điều kiện đó để harness mở được cuộc gọi, rồi chạy lại bộ case để thấy kịch bản thật. Không đổi hành vi engine. Khi không có số dùng được, câu mở đầu báo chuyển máy, lượt 1 kết thúc `TRANSFERRED`, không tra Clinic và không ghi gì. Đây là nhánh `NO_PHONE` có sẵn, LiveKit đã dùng. Bước hỏi số điện thoại đã đăng ký và các sửa luồng đặt lịch nằm trong [plan Booking](../plans/t11-booking-inbound-2026-10-13.md) (PR 1–3).

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Payload inbound của harness (`caller_number: null`) mở được cuộc gọi | `StartCallRequest._check_direction_fields` trong `src/callbot/transports/http/schemas.py` không còn bắt buộc `caller_number`; giữ nguyên: outbound bắt buộc `appointment_id`, inbound có `appointment_id` → 422 |
| Thiếu số / số không chuẩn hóa được: mở phiên `AWAITING_IDENTITY`, lượt 1 `TRANSFERRED`, không tra mock, không ghi (§1.1.9, §2.1) | `test_inbound_without_usable_caller_number_starts_and_transfers_without_write` (`null`, `""`, `"+840000000001"`) trong `tests/transports/http/test_calls.py`, dùng đúng `call_id` và payload của qc-ib-01 |
| Dữ liệu không hợp lệ vẫn bị từ chối | `test_start_call_rejects_invalid_input` (bỏ đúng một dòng là payload inbound thiếu số) |
| Tài liệu khớp hành vi | `docs/reference/http-api.md`; ghi chú trong `docs/evidence/f02-http-engine.md` |

## File liên quan

- `src/callbot/transports/http/schemas.py`
- `tests/transports/http/test_calls.py`
- `docs/reference/http-api.md`, `docs/evidence/f02-http-engine.md`

## Luồng hiện tại

```text
POST /v1/calls inbound, caller_number = null | "" | số không chuẩn hóa được
  -> IdentityVerifier.prepare: NO_PHONE (không gọi GET /patients)
  -> inbound.opening: GREETING_HANDOFF_INBOUND, state=AWAITING_IDENTITY, turn=0
POST /v1/calls/{id}/turn (turn 1, bất kỳ lời nào)
  -> Policy.check_preconditions: lookup_failure -> ended=true, outcome=TRANSFERRED, 0 lệnh ghi
```

Dự kiến khi mentor chạy lại (dự đoán từ tái hiện local, **chưa phải kết quả chấm**): 6 case kỳ vọng `TRANSFERRED` (03, 04, 05, 06, 08, 09) đạt vì chuyển máy ở lượt 1; 4 case kỳ vọng `BOOKED` (01, 02, 07, 10) chưa đạt. Báo cáo chỉ cho thấy câu lượt 1 của mỗi kịch bản, vì bot dừng ở lượt 1.

## Quy trình xác minh

```powershell
$env:PYTHONUTF8 = "1"
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests\transports\http\test_calls.py tests\test_schema.py tests\engine\test_identity_dialogue.py tests\engine\test_inbound_booking_flow.py tests\engine\test_scenario7_edge.py -q
python -m pytest tests\transports tests\tracing tests\engine\test_sf03_appointment_disclosure.py -q --continue-on-collection-errors
```

## Kết quả xác minh cục bộ (2026-10-13)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| pytest HTTP + schema + định danh + đặt lịch | Pass (255 passed, 1 skipped) |
| pytest `tests/transports` + `tests/tracing` + SF-03 | Pass (369 passed, 22 skipped); 1 lỗi collect `tests/transports/livekit/test_worker_speech_settings.py` do máy local thiếu `livekit` (có từ trước) |
| `python scripts/export_openapi.py --check` | Lệch, **có sẵn trên `main`** (đã kiểm khi bỏ thay đổi này); validator không nằm trong OpenAPI schema |

## Ghi chú

- Trang thử UI (`ui/src/features/call/model/config.ts`) vẫn bắt nhập số khi chọn inbound; đây chỉ là kiểm tra phía trình duyệt, không ảnh hưởng harness.
- Sau khi merge và deploy prod: nhờ mentor chạy lại qc-ib-*, rồi chép câu lượt 1 và "Mock state before" của từng case vào plan Booking §6.
- Muốn thấy trọn kịch bản (định danh, chọn khung) thì bot phải tiếp tục hội thoại khi thiếu số. Đó là bước hỏi số điện thoại (G1, PR 1).

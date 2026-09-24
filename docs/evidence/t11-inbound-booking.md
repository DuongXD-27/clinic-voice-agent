# Evidence: T-11 — Hội thoại Booking inbound

## Mục tiêu

Task T-11 phụ trách luồng inbound booking: bệnh nhân gọi vào và chủ động đặt lịch khám.
Quá trình booking bắt buộc phải thông qua bước xác minh danh tính trước; sau khi xác định intent đặt lịch, bot sẽ tra cứu và đề xuất các slot khả dụng từ Gateway/Clinic. Bệnh nhân phải có sự xác nhận rõ ràng (explicit confirmation) mới tiến hành ghi nhận vào hệ thống. Việc đặt lịch chỉ thông báo thành công (trạng thái `BOOKED`) sau khi được API Clinic phản hồi hợp lệ với đúng một `appointment_id`. Các trường hợp hủy hoặc chuyển máy giữa chừng, chưa booking sẽ không tạo ra lịch khám mới nào.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Inbound booking chỉ tiếp tục sau identity verification | `src/callbot/engine/dialogue/manager.py` — `DialogueManager._verify` đặt `ctx.identity_step = "VERIFIED"` và `ctx.patient_id`, sau đó gọi `ASK_INTENT` để hỏi nhu cầu; `tests/engine/test_inbound_booking_flow.py::test_inbound_booking_happy_path` chứng minh flow bắt đầu bằng thông tin xác minh danh tính. |
| BOOK intent đi vào booking flow | `src/callbot/engine/dialogue/manager.py` — `_intent` chuyển intent `BOOK` gọi `_start` và đặt `ctx.set_pending("BOOK")`; `tests/engine/test_scenario7_edge.py::test_case_j_booking_phrases_keep_book_intent` xác nhận phân loại intent. |
| Slot phải được lấy từ Gateway / Clinic | `src/callbot/engine/dialogue/manager.py` — `_offer_slots` gọi `self._gateway.list_open_slots(ctx, now)`. |
| Không được booking slot chưa từng được offer | `tests/engine/tools/test_booking_write.py::test_sf02_blocks_unoffered_slot` kiểm tra policy SF-02 chặn `slot_unoffered`. |
| Explicit confirmation bắt buộc trước POST /appointments | `src/callbot/engine/dialogue/manager.py` — `_slot_readback` chỉ gọi `gateway.book` khi `agreement is Agreement.AGREE` và `_answers_last_question(ctx)` đúng. |
| Booking success chỉ hợp lệ nếu response có appointment_id | `tests/engine/test_inbound_booking_flow.py::test_inbound_booking_missing_id_aborts_turn` và `tests/engine/tools/test_booking_write.py::test_book_missing_appointment_id_raises_unknown`. |
| Booking success chỉ hợp lệ nếu status == BOOKED | `tests/engine/test_inbound_booking_flow.py::test_inbound_booking_wrong_status_aborts_turn` và `tests/engine/tools/test_booking_write.py::test_book_wrong_status_raises_unknown`. |
| Invalid / incomplete Clinic write result không được announce success | `src/callbot/engine/tools/clinic_gateway.py` — `ClinicGateway.book(...)` raise `WriteOutcomeUnknown` khi response thiếu `appointment_id` hoặc `status != "BOOKED"`; `src/callbot/engine/dialogue/manager.py` xử lý lỗi ghi và không kết thúc turn với booking success. Các test `tests/engine/test_inbound_booking_flow.py::test_inbound_booking_missing_id_aborts_turn`, `tests/engine/test_inbound_booking_flow.py::test_inbound_booking_wrong_status_aborts_turn`, `tests/engine/tools/test_booking_write.py::test_book_missing_appointment_id_raises_unknown` và `test_book_wrong_status_raises_unknown` xác nhận các nhánh này. |
| Exactly-one appointment / duplicate protection | `tests/engine/tools/test_booking_write.py::test_book_duplicate_prevented_by_sf01` chặn gọi Gateway lần 2 qua policy SF-01. |
| Inbound transfer trước booking không tạo appointment | `tests/engine/tools/test_clinic_gateway.py::test_transfer_inbound_without_booking_sends_nothing` trả về `None` không gọi API ghi; `DialogueManager.transfer` không gọi lệnh ghi. |
| Multi-window slot search tiếp tục sang window sau khi chưa có slot | `tests/engine/test_scenario7_edge.py::test_case_d_no_slots_scans_bounded_policy_then_transfers_out_of_scope` (tìm kiếm tối đa 5 window) và `test_case_a_slot_plus_7_days_uses_one_window_and_is_offered`. |
| Flow happy path kết thúc ENDED / BOOKED | `tests/engine/test_inbound_booking_flow.py::test_inbound_booking_happy_path` assert `action.outcome == "BOOKED"` và `action.ended is True`. |

## File liên quan

- `src/callbot/engine/dialogue/manager.py`
- `src/callbot/engine/extraction/agreement.py`
- `src/callbot/engine/tools/clinic_gateway.py`
- `tests/engine/test_inbound_booking_flow.py`
- `tests/engine/test_scenario7_edge.py`
- `tests/engine/tools/test_booking_write.py`
- `tests/engine/tools/test_clinic_gateway.py`

## Luồng hiện tại

Khái quát luồng cho Inbound Booking:

```text
POST /v1/calls (inbound)
  -> lookup patient candidate
  -> identity verification
  -> detect BOOK intent
  -> retrieve slots from Gateway
  -> select offered slot
  -> explicit booking confirmation
  -> POST /appointments
  -> validate appointment_id
  -> validate status == BOOKED
  -> set successful booking state
  -> ENDED / BOOKED
```

Các luồng an toàn (Safety / Failure flow) đã được tích hợp:
- **Unverified identity**: Bắt buộc xác minh trước, nếu không tìm thấy/xác minh sai → transfer, không booking.
- **Unoffered slot**: Chọn slot chưa từng offer (qua SF-02) → booking blocked.
- **No explicit confirmation**: Thiếu câu trả lời đồng ý rõ ràng → không gọi `POST /appointments`.
- **Invalid Clinic response**: Thiếu `appointment_id` hoặc trạng thái không phải `BOOKED` → raise `WriteOutcomeUnknown` (reconciliation path).
- **Inbound transfer**: Chuyển máy nhân viên trước khi xác nhận tạo lịch → no appointment creation (không gọi Gateway Mock).

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

Chỉ chạy test của phần liên quan:

```powershell
python -m pytest tests/engine/test_inbound_booking_flow.py -q
python -m pytest tests/engine/test_scenario7_edge.py -q
python -m pytest tests/engine/tools/test_booking_write.py -q
python -m pytest tests/engine/tools/test_clinic_gateway.py -q
```

## Kết quả xác minh cục bộ (2026-09-23)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass (175 files already formatted) |
| `python -m pytest -q` | Pass (1307 passed, 25 skipped) |
| `make check` | Not run — `make` không có trong môi trường Windows hiện tại; ba bước tương đương gồm Ruff lint, Ruff format check và full pytest đã được chạy riêng. |
| `python -m pytest tests/engine/test_inbound_booking_flow.py -q` | Pass (4 passed) |
| `python -m pytest tests/engine/test_scenario7_edge.py -q` | Pass (10 passed) |
| `python -m pytest tests/engine/tools/test_booking_write.py -q` | Pass (4 passed) |

## Ghi chú

- `make check` không chạy được trên môi trường Windows hiện tại do không có lệnh `make`; đây là giới hạn của môi trường local, không phải lỗi của T-11. Các bước tương đương của `make check` đã được chạy riêng. Full suite `python -m pytest -q` ban đầu gặp `UnicodeEncodeError` ở console renderer trên Windows, sau đó đã pass với cấu hình UTF-8: **1307 passed, 25 skipped**.
- Mọi test chỉ định riêng cho T-11 (`test_inbound_booking_flow.py`, `test_scenario7_edge.py`, `test_booking_write.py`) đều pass bình thường và không bị ảnh hưởng.
- T-11 quản lý hành vi đặt lịch gọi inbound (hội thoại xác minh, xác nhận và quyết định ghi lịch). Tuy nhiên một phần Gateway logic về quản lý phân trang và lỗi được thiết kế chia sẻ cùng T-09 / T-12.
- Multi-window slot search: Quét qua tuần tự các slot window, tối đa là 5 lần lặp, test `test_case_d_no_slots_scans_bounded_policy_then_transfers_out_of_scope` chứng minh có 5 reads khi tìm không thấy (mỗi window 14 ngày).
- Quá trình booking flow hoàn toàn tôn trọng các rule SF-01 (duplicate protection) và SF-02 (offered-slot protection).
- Không có patient thật nào được tạo hay sử dụng trong test, mọi tham chiếu đều dùng data tổng hợp (synthetic).

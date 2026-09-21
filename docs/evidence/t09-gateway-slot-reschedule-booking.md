# Evidence: T-09 — Gateway Slot/Reschedule/Booking

**Owner:** B (Hưng) · **Ngày:** 21-09-2026

## Mục tiêu

Đọc slot (`GET /slots`), đổi lịch (`POST /appointments/{id}/reschedule`) và tạo lịch hẹn inbound
(`POST /appointments`) đã được cài trong F-05 (nhánh `feature/f05-clinic-gateway`, commit
`00205e7 f05-clinic-gateway: Done`) — cần có sớm để A phát triển song song T-10 (Reschedule) và T-11
(Booking inbound). T-09 chưa có evidence riêng đối chiếu từng điều kiện hoàn thành ở
`docs/task-breakdown.md` §3. Evidence này rà lại toàn bộ, không sửa logic.

Phạm vi: không đổi `src/callbot/engine/tools/clinic_gateway.py`,
`src/callbot/engine/tools/clinic_mock_client.py`, `src/callbot/engine/tools/fake_clinic.py`,
`src/callbot/engine/policy/guardrails.py`.

## Bằng chứng trong repo

| Acceptance criterion | Vị trí code | Test chứng minh |
| --- | --- | --- |
| Đọc **hết mọi trang** slot (không chỉ trang đầu) | `ClinicGateway.list_open_slots` + `_all_pages` (`clinic_gateway.py:67-94`): loop tới `has_more=False`, cap `MAX_PAGES=20` | `test_list_open_slots_walks_every_page_and_normalizes` (`test_clinic_gateway.py:140-160`): 230 slot / 3 trang (100+100+30) đọc đủ; contract test `test_slots_pagination_with_limit_1_walks_all_records` (`test_clinic_api_contract.py:90-100`) trên mock thật/fake |
| Cửa sổ `from`/`to` đúng định dạng RFC 3339, tối đa 14 ngày (giới hạn của mock) | `SLOT_WINDOW_DAYS = 14` (`clinic_gateway.py:41`), `iso_local` (`normalize.py:16-18`) | `test_list_open_slots_sends_rfc3339_window_of_14_days` (`test_clinic_gateway.py:163-168`); contract `test_slots_window_validation` (`test_clinic_api_contract.py:119-120`) |
| Chuẩn hóa slot: mock trả `start_time`/`end_time`, engine đọc `starts_at`/`ends_at` | `normalize_slot` (`normalize.py:30-40`) | `test_slot_maps_mock_start_time_to_starts_at_and_keeps_raw_keys`, `test_slot_without_id_or_start_is_bad_response` (`test_normalize.py:23-40`); contract `test_slots_have_mock_shape_with_start_time` (`test_clinic_api_contract.py:103-108`) xác nhận mock **không** tự trả `starts_at` — chuẩn hóa là việc của Gateway |
| **Không bịa slot** — chỉ được đề xuất khung giờ do chính `GET /slots` của cuộc gọi trả về (SF-02) | `guardrails.assert_slot_offered` (`guardrails.py:24-29`): `ctx.find_slot(slot_id) is None` → `SevereFailureBlocked("SF-02")`; gọi từ `reschedule()` (`clinic_gateway.py:126`) và `book()` (`clinic_gateway.py:145`) | `test_ambiguous_slot_choice_does_not_pick_first_slot` (`test_orchestrator.py:187-198`) — không tự chọn slot khi mơ hồ; toàn bộ luồng reschedule/booking thành công đều đi qua guard này trước khi ghi (không có đường vòng) |
| **Đổi lịch nguyên tử**: đặt slot mới + giải phóng slot cũ trong cùng một lần cập nhật | `reschedule_appointment` fake (`fake_clinic.py:415-473`) cập nhật `taken_slots`/`_slot_of`/`appt` trong một hàm `apply()` chạy dưới `_write` (không có bước trung gian có thể quan sát nửa vời) | Contract test `test_reschedule_is_atomic_and_releases_old_slot` (`test_clinic_api_contract.py:176-197`): sau reschedule, slot mới biến khỏi `GET /slots`, slot cũ xuất hiện lại, `appointment.starts_at` đổi đúng 1 lần |
| **Tạo appointment đúng một lần** (idempotent theo key) | `create_appointment` (`clinic_gateway.py:139-159`, `fake_clinic.py:285-321`): `book()` dùng key `book:{slot_id}`, không đọc version (`read_version=False`, tạo mới không có `If-Match`) | Contract test `test_create_appointment_books_once_and_consumes_slot` (`test_clinic_api_contract.py:224-240`): gọi lại **cùng key** → trả về **cùng** `appointment_id` (không tạo bản thứ hai); slot bị tiêu thụ khỏi `GET /slots` |
| **Không tạo appointment trùng trong cùng cuộc gọi** (chặn gọi `book()` lần 2) | `ClinicGateway.book` (`clinic_gateway.py:141-142`): `if ... or ctx.created_appointment_id is not None: raise SevereFailureBlocked("SF-01", "Chỉ inbound mới được tạo 1 appointment")` | **Chưa có unit test gọi trực tiếp** `gateway.book()` hai lần trong cùng `ctx` để khóa riêng nhánh này ở tầng Gateway — chỉ được đảm bảo gián tiếp qua luồng hội thoại (Dialogue chỉ gọi `book()` một lần sau khi `ctx.finish`) — xem Ghi chú |
| **Không tạo patient** — Gateway chỉ dùng `patient_id` có sẵn (từ T-01), không có endpoint tạo patient | `ports.ClinicAPI` Protocol (`ports.py:31-86`) không khai báo method tạo/patch patient nào; `book()` nhận `ctx.patient_id` đã set từ trước, không tự suy patient | Về kiến trúc: không có đường gọi nào trong `tools/` có thể tạo patient (không method nào tồn tại để gọi); `test_create_appointment_books_once_and_consumes_slot` xác nhận patient không tồn tại → `404 NOT_FOUND`, không tự tạo |
| Trả lỗi **slot hết** (`SLOT_TAKEN`) rõ ràng, không lẫn với lỗi khác | `_write` (`clinic_gateway.py:228-229`): `if exc.code == "SLOT_TAKEN": raise SlotTaken(...)` (subclass riêng của `ClinicWriteRejected`) | Contract `test_reschedule_is_atomic_and_releases_old_slot` dòng 179-183: slot không tồn tại → `409 SLOT_TAKEN`; end-to-end `test_reschedule_slot_taken_reoffers_and_needs_new_confirmation` (`test_orchestrator.py:168-184`): `SlotTaken` → Dialogue đọc lại `/slots`, đề xuất lại, **cần xác nhận mới** (`ctx.evidence == []`), không ghi (`clinic.writes == []`) |
| Trả lỗi **version conflict** khi ghi (reschedule dùng `If-Match`) | `_write` retry 1 lần cho `VERSION_CONFLICT`, giống mọi thao tác ghi khác (đã kiểm ở F-05 bằng `transfer`) | Dùng chung cơ chế đã test — chưa có test `VERSION_CONFLICT` gọi thẳng `reschedule_appointment` riêng (chỉ có `SLOT_TAKEN`); xem Ghi chú |

## File liên quan

Không đổi (đã đúng từ F-05, evidence này chỉ xác nhận lại bằng test có sẵn):
- `src/callbot/engine/tools/clinic_gateway.py`
- `src/callbot/engine/tools/clinic_mock_client.py`
- `src/callbot/engine/tools/fake_clinic.py`
- `src/callbot/engine/tools/normalize.py`
- `src/callbot/engine/policy/guardrails.py`

Test đối chiếu (không sửa):
- `tests/engine/tools/test_clinic_gateway.py`
- `tests/engine/tools/test_clinic_api_contract.py`
- `tests/engine/tools/test_normalize.py`
- `tests/engine/test_orchestrator.py`

## Luồng hiện tại

```text
Đọc slot:
Dialogue (A) cần offer slot -> ClinicGateway.list_open_slots(ctx, now)
  -> cửa sổ [now, now+14d] RFC3339 -> _all_pages(get_slots) đọc hết trang (cap 20 trang)
  -> normalize_slot mỗi bản ghi -> ghi đè ctx.slots (nguồn thật duy nhất cho lượt này)

Reschedule / Book:
Dialogue có slot_id do người gọi chọn TỪ ctx.slots
  -> ClinicGateway.reschedule(ctx, slot_id) / book(ctx, slot_id)
       -> fsm.check_write                                : trạng thái/hành động chờ khớp
       -> guardrails.assert_slot_offered(ctx, slot_id)    : SF-02, slot phải có trong ctx.slots
       -> guardrails.assert_action_confirmed              : có AGREE đúng lượt/câu hỏi/slot
       -> [book] direction=="inbound" và created_appointment_id is None, faild -> SF-01
       -> _write(key theo call_id:turn:reschedule|book:slot_id, ...)
            SLOT_TAKEN      -> SlotTaken (Dialogue đọc lại /slots, chọn None, đề xuất lại, hỏi lại)
            VERSION_CONFLICT lần 1 -> đọc lại version, gửi lại cùng key
            khác            -> ClinicWriteRejected
  -> ghi thành công -> outcome RESCHEDULED/BOOKED; book() còn set ctx.created_appointment_id
                        để lần gọi book() kế tiếp trong CÙNG cuộc gọi bị chặn ở SF-01
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`; môi trường xác
minh này còn thiếu `fakeredis` so với `pyproject.toml`, đã `pip install fakeredis` riêng để chạy được
`tests/conftest.py`).

```powershell
make check
```

Chỉ test liên quan T-09:

```powershell
python -m pytest tests\engine\tools\test_clinic_gateway.py tests\engine\tools\test_clinic_api_contract.py tests\engine\tools\test_normalize.py tests\engine\test_orchestrator.py -q
```

Contract test trên mock thật (reset instance chung — **báo kênh team trước khi chạy**):

```powershell
$env:CLINIC_MOCK_LIVE = "1"; python -m pytest tests\engine\tools\test_clinic_api_contract.py -q
```

## Kết quả xác minh cục bộ (21-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | 12 file cần format lại, không file nào thuộc phạm vi T-09 (drift CRLF có sẵn, cùng loại đã ghi nhận ở evidence F-05/T-03) |
| `python -m pytest tests\engine\tools\test_clinic_gateway.py tests\engine\tools\test_clinic_api_contract.py tests\engine\tools\test_normalize.py tests\engine\test_orchestrator.py -q` | Pass (91 passed, 18 skipped = biến thể `live`) |
| `python -m pytest -q` (toàn repo) | Pass (1126 passed, 24 skipped), không có lỗi nào |
| Contract test `live` (`CLINIC_MOCK_LIVE=1`) | Chưa chạy — code không đổi so với F-05, không cần chạy lại riêng; lần chạy live gần nhất thuộc F-05 |

## Ghi chú

- Không phát hiện gap logic. Toàn bộ khoảng trống là **thiếu evidence doc riêng** cho T-09 — chức năng
  được cài đủ trong F-05 vì A cần offer/reschedule/book slot cho T-10/T-11 ngay từ đầu.
- **Hai khoảng trống về test nên cân nhắc bổ sung, không chặn coi T-09 là "đã làm":**
  1. Không có unit test gọi trực tiếp `ClinicGateway.book()` **hai lần trong cùng `ctx`** để khóa riêng
     guard `ctx.created_appointment_id is not None` ở tầng Gateway (`clinic_gateway.py:141-142`) — hiện
     chỉ được đảm bảo gián tiếp vì Dialogue không có đường gọi `book()` lần 2 sau khi phiên đã `ENDED`.
  2. Không có test `VERSION_CONFLICT` gọi thẳng `reschedule_appointment`/`create_appointment` (chỉ có
     `SLOT_TAKEN` cho reschedule) — cơ chế retry dùng chung `_write` đã test kỹ qua `transfer`/`confirm`/
     `unreachable`, nhưng chưa có case khóa riêng cho hai thao tác này.
  3. `MAX_PAGES = 20` (chống cursor hỏng ở `clinic_gateway.py:92-94`) chưa có test nào ép tràn 2000+ bản
     ghi để xác nhận `ClinicAPIError("PAGINATION_OVERFLOW")` được raise đúng.
- Việc tiếp theo không thuộc T-09: retry có giới hạn/backoff cho lỗi tạm thời ngoài `VERSION_CONFLICT`/
  `SLOT_TAKEN` (429/503) — thuộc T-12, hiện **chưa triển khai**.

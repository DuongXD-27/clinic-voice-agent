# Evidence: T11 — luồng đặt lịch inbound theo eval mentor qc-ib-01..10

## Mục tiêu

Đặt lịch inbound đạt đủ 10 case qc-ib của mentor (ground truth), sau khi harness gửi `caller_number`.
- Case BOOKED: 01, 02, 07, 10.
- Case TRANSFERRED: 03–06, 08, 09.

Plan: [`docs/plans/t11-booking-inbound-2026-10-13.md`](../plans/t11-booking-inbound-2026-10-13.md).

Base: `main` @ `724e503`, gồm PR #132 của Hoàn: đọc ngày sinh theo mốc "sinh", giữ yêu cầu đặt lịch trong `ctx.early_book`, chuẩn hóa số gọi đến. Phần trùng với plan lấy bản của Hoàn; nhánh này xây tiếp trên đó.

Kiến trúc giữ nguyên: luật trước, model (Jev, dự phòng Luna) chỉ đọc câu luật không có đường đi. 10 kịch bản mentor do luật quyết hết: test khẳng định 0 lần gọi model.

## Bằng chứng trong repo

| Tiêu chí | Bằng chứng |
| --- | --- |
| 10 kịch bản thật đạt trên seed gốc (`slot_91d2`) và mock deploy (khung demo), ở 3 chế độ model (không model / model treo / model đọc sai) | `test_mentor_booking_case` trong `tests/engine/test_mentor_eval_booking.py` (72 ca) |
| Không gọi model ở lượt nào của case mentor | Cùng test, `calls == 0` (cả tầng hiểu ý lẫn tầng chọn khung) |
| Nhu cầu nói ở bước danh tính không tính hiểu sai, chỉ miễn một lần (D-2) | `_identity` trong `manager.py`; `test_booking_need_at_identity_turn_is_exempt_only_once` |
| Xác minh xong, có nhu cầu mà chưa nêu giờ: hỏi ngày / buổi; chỉ nêu khoa thì hỏi lại một lần (G3, G4, G20) | `_early_book`, `_booking_need`; `test_booking_need_asks_the_time_and_department_is_never_spoken` |
| Câu chỉ nêu giờ / khoa / "gần nhất" ở câu hỏi nhu cầu là đặt lịch, do luật quyết | `_booking_reply` trong `extractor.py`; `extraction/booking.py` (`booking_answer`) |
| "Còn lịch nào gần nhất" → một khung sớm nhất, hỏi có/không (G18) | `_offer_earliest`; "gần nhất" trong `_ANY` của `slot_choice.py` |
| Không có giờ khách xin → báo, rồi mời **một** khung gần nhất (G21, D-12) | `_offer_nearest`, `_requested_moment`; `test_missing_time_offers_one_nearest_slot` |
| "Không có thì giờ em vừa nói cũng được" → đồng ý đúng khung vừa mời (G15) | `_slot_readback`, `agrees_to_offered` |
| "Giờ khác không được" / bỏ đặt lịch → chuyển `PATIENT_REQUEST`, 0 ghi (G7, G8) | `_gives_up`, `_give_up`, `_rounds_exhausted` |
| Tên "Hoàng Văn Không Có" được nhận (G19) | `_function_word_in_given_name` trong `full_name.py` |
| Nhờ tạo hồ sơ → `PATIENT_NOT_FOUND`; đặt hộ, hủy / đổi lịch có sẵn → `OUT_OF_SCOPE`, không cần xác minh (G11, G12, G22) | `_inbound_handoff`; `test_out_of_scope_requests_at_identity_turn_transfer_without_verifying` |
| Kể triệu chứng → `CLINICAL_QUESTION`, kể cả khi đã tự chọn khoa (owner 13-10, D-11). Lượt khai tên có đọc ra tên thì không tính ("Nguyễn Văn Ho") | `_inbound_symptom` trong `policy_engine.py`; `test_symptoms_transfer_even_with_a_chosen_department`, `test_symptom_word_inside_a_name_is_not_a_symptom`, `test_department_without_symptoms_still_books` |
| Khung vừa bị người khác lấy (mock trả 404 "slot … not found") → đọc lại /slots, mời lại (G9) | `_slot_gone` trong `clinic_gateway.py`; dòng WS01 của bộ edge case |
| Không có `caller_number` → chuyển máy lượt 1, 0 tra cứu (D-10) | `test_without_caller_number_hands_off_at_turn_one` |
| Model chọn khung không xen vào câu đặt lịch luật đã quyết | `_apply_slot_semantic` trong `extractor.py` |

## File liên quan

- `src/callbot/engine/extraction/booking.py` (mới)
- `src/callbot/engine/dialogue/manager.py`
- `src/callbot/engine/extraction/extractor.py`
- `src/callbot/engine/extraction/full_name.py`
- `src/callbot/engine/extraction/slot_choice.py`
- `src/callbot/engine/policy/policy_engine.py`
- `src/callbot/engine/session/context.py`
- `src/callbot/engine/tools/clinic_gateway.py`
- `tests/engine/test_mentor_eval_booking.py` (mới)
- `tests/engine/test_identity_dialogue.py`: `test_request_before_identity_asks_to_verify_first` đổi kỳ vọng có chủ đích, xem Ghi chú
- `eval/book/inbound_scenarios.csv` (mới, 65 kịch bản mức cuộc gọi)
- `scripts/booking_scenarios_eval.py` (mới)
- `eval/reschedule/cases.csv`: R150 đổi nhãn, xem Ghi chú

## Luồng hiện tại

```text
POST /v1/calls (inbound, caller_number)
  -> tra /patients theo số: 0 hồ sơ / không có số -> lượt 1 TRANSFERRED PATIENT_NOT_FOUND
  -> lượt danh tính: tạo hồ sơ / đặt hộ / hủy-đổi-xác nhận / triệu chứng -> chuyển ngay
     nhu cầu đặt lịch -> giữ (ctx.early_book), câu chỉ nêu nhu cầu không tính hiểu sai (1 lần)
  -> đủ tên + ngày sinh -> verify (sai -> PATIENT_NOT_FOUND, không nói yếu tố nào sai)
  -> có giờ: GET /slots -> 1 khung: hỏi có/không | nhiều: trang 2 khung | không có giờ đó: 1 khung gần nhất
     chưa có giờ: hỏi ngày/buổi | "gần nhất": 1 khung sớm nhất
  -> đồng ý rõ khung vừa mời -> POST /appointments đúng 1 lần -> BOOKED
     "giờ khác không được" / bỏ đặt -> TRANSFERRED PATIENT_REQUEST, 0 ghi
```

## Quy trình xác minh

```powershell
$env:PYTHONUTF8 = "1"
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests -q --ignore=tests/transports/livekit/test_worker_speech_settings.py
python -m pytest tests/engine/test_mentor_eval_booking.py -q
python scripts/booking_scenarios_eval.py --only M --show
python scripts/reschedule_eval.py --baseline --label t11-booking
```

## Kết quả xác minh cục bộ (2026-10-13)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass (371 file) |
| `python -m pytest tests -q` (bỏ module cần `livekit`, máy local không cài) | Pass: 5704 passed, 26 skipped |
| `tests/engine/test_mentor_eval_booking.py` | Pass: 85 |
| `booking_scenarios_eval.py`, 19 dòng mentor | 19/19 grade, 19/19 strict |
| `booking_scenarios_eval.py`, toàn bộ 65 dòng | 61/65 grade, 60/65 strict, 0 lệnh ghi sai (trên `6c2dff5`: 30/65, 19/65) |
| `reschedule_eval.py --baseline` | 156/160, giống từng câu với `main` `724e503`. 0 lệnh ghi sai, 0 lần gọi model |
| `confirm_eval`, `cancel_eval`, `no_answer_eval` (`--baseline`), `identity_eval` | Giống hệt `main` `724e503` |

## Ghi chú

- **Câu hỏi nhu cầu.** Câu hỏi đúng nguyên văn Hình 0 ("Anh chị muốn khám khoa nào và khoảng thời gian nào ạ?") là câu TTS tĩnh mới. Thêm câu này cần:
  1. PM duyệt chữ;
  2. chạy `tts_utterance_catalog.py`;
  3. thu âm bằng Vbee;
  4. phát hành lại cache.

  Nếu thiếu các bước đó, các test catalog TTS (74 câu) sẽ trượt. Tạm thời bot dùng câu đã có cache: "Anh chị muốn đặt vào ngày nào hoặc buổi nào ạ?". Kết quả 10 case không đổi, vì kịch bản mentor không phụ thuộc chữ của câu hỏi.
- **`test_request_before_identity_asks_to_verify_first`** (PR #132). Kỳ vọng cũ là đọc khung ngay sau xác minh. Cách đó làm qc-ib-01 trượt trên seed gốc: lượt 4 "Khám tổng quát" rơi vào câu mời một khung, rồi lượt 5 bị tính là hiểu sai lần 2. Kỳ vọng mới là hỏi ngày/buổi.
- **R150 (`eval/reschedule/cases.csv`).** Khi đặt lịch, "thôi không đặt nữa" nay chuyển máy `PATIENT_REQUEST` (G7, PRD R-10), giống outbound qc-rs-08. Nhãn cũ là `KEEP_OLD`, tức hỏi lại nhu cầu.
- **Câu "cần hỗ trợ gì" → "tôi muốn đặt lịch"** (chưa nêu giờ) vẫn đọc 2 khung sớm nhất và mời nêu ngày khác (D-1), như trước.
- **Còn trượt trong bộ edge case.** Năm dòng còn trượt đều ngoài 10 case mentor, cùng nằm ở phần dùng chung với Reschedule, nên để sau.
  - OA02, OA05, OA06: hỏi "giờ khác" khi đã hết khung, rồi chọn lại khung cũ.
  - WS02: "khoan đã".
  - GU02: "gọi lại sau" ra lý do `OUT_OF_SCOPE`, kỳ vọng strict là `PATIENT_REQUEST`.
- **Chưa làm:** G6 (cửa sổ /slots từ ngày xin; cửa sổ hiện là 14 ngày nên đủ cho mock); G10; G13; G14 (nhãn `BOOK` cho tầng model chọn khung); G16.

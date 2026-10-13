# Evidence: Inbound không có `caller_number` — hỏi tên, ngày sinh rồi số điện thoại (eval mentor qc-ib-*)

## Mục tiêu

Sau PR 0 ([inbound-null-caller-number](inbound-null-caller-number-2026-10-13.md)), harness mở được cuộc
gọi nhưng bot chuyển máy ngay lượt 1 vì không có số để tra hồ sơ. Bốn case kỳ vọng `BOOKED` (qc-ib-01,
02, 07, 10) vẫn fail: `status: expected BOOKED, got MISSING`, không có lệnh ghi nào.

Bước mới (chỉ inbound): câu mở đầu vẫn hỏi mở họ tên, rồi ngày sinh như khi có số (§1.1.9 "MUST still
obtain name and date of birth"). Có đủ hai giá trị mà chưa có hồ sơ (`identity_lookup = AWAITING_PHONE`)
thì bot xin số điện thoại đã đăng ký (`ASK_PHONE`), Verifier tra `GET /patients?phone=` theo số đó
(`lookup_spoken_phone`) rồi đối chiếu tên + ngày sinh đã khai (`_verify`) như luồng có `caller_number`.
Outbound không đổi.

## Hành vi

| Tình huống ở `ASK_PHONE` | Kết quả |
| --- | --- |
| Số đọc được, có đúng một hồ sơ khớp tên + ngày sinh | `AWAITING_INTENT`, hỏi nhu cầu; đặt lịch tiếp như thường (§1.1.10) |
| Số đọc được, hồ sơ không khớp tên / ngày sinh, hoặc không có hồ sơ | `TRANSFERRED` / `PATIENT_NOT_FOUND`, câu `IDENTITY_FAILED_TRANSFER` — không nói yếu tố nào sai (§1.1.2) |
| Clinic lỗi khi tra | `TRANSFERRED` / `SYSTEM_ERROR` |
| Không đọc được số, số không đúng dạng (9 chữ số, đầu số lạ), nêu nhu cầu thay vì đọc số | hỏi lại một lần (`ASK_PHONE_AGAIN` / `ASK_PHONE_FOR_REQUEST`), lần hai `TRANSFERRED` / `NOT_UNDERSTOOD` (§1.1.5) — cùng cách với tên, ngày sinh |
| "Ai đấy?", giữ máy, im lặng, xin nhắc lại | như các câu hỏi danh tính khác: giới thiệu lại / nhắc lại câu hỏi, không tốn lượt hỏi lại |
| Ngoài phạm vi, xin gặp nhân viên, lâm sàng | Policy chuyển máy như ở bước tên / ngày sinh |

Số người gọi đọc chỉ để tìm ứng viên (§1.1.9), không vào trace; không gọi Clinic trước khi có số.

Đầu số nhận ở cả `caller_number` lẫn số người gọi đọc (`verification/phone.py`): `0912345600`,
`+84912345600`, `0084912345600`, `84912345600` (không có dấu +), `840912345600` (84 + số nội địa còn số
0). Số đọc rời ("không chín một hai ba bốn năm sáu không không", "tám bốn chín một hai...") và tự sửa
("0912345601, à không, 0912345600" — lấy dãy sau cùng, R-44) do `extraction/phone.py` đọc.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Không có số: hỏi tên, ngày sinh rồi mới xin số; chưa có số không gọi mock | `test_inbound_without_caller_number_asks_name_dob_then_phone_before_any_lookup` (`tests/engine/test_identity_dialogue.py`); `test_prepare_inbound_without_caller_number_waits_for_spoken_phone` (`tests/engine/verification/test_identity_verifier.py`) |
| Đầu số `0`, `+84`, `84`, `840` đều tra cùng một số | `tests/engine/verification/test_phone.py`; `test_lookup_spoken_phone_normalizes_every_prefix_then_loads_candidates` |
| Số đọc rời, nhóm số, không dấu, tự sửa | `tests/engine/extraction/test_phone.py` |
| Tra xong mới đối chiếu; sai ngày sinh / không có hồ sơ -> `PATIENT_NOT_FOUND`, Clinic lỗi -> `SYSTEM_ERROR`; đặt lịch tới `BOOKED` | `tests/engine/test_inbound_booking_flow.py` (nhóm "Inbound không có caller_number") |
| Payload harness qc-ib-01 chạy trọn tới `BOOKED` qua HTTP | `test_inbound_without_caller_number_asks_identity_then_phone_and_books` (`tests/transports/http/test_calls.py`) |
| Có số gọi đến nhưng không dùng được / không có hồ sơ: vẫn chuyển máy lượt 1, không hỏi số khác | `test_inbound_with_unusable_caller_number_starts_and_transfers_without_write`; `test_unregistered_inbound_is_transferred_at_turn_one_without_asking_name` |

## Còn mở: audio tĩnh cho 12 câu mới

12 câu tĩnh mới (`ASK_PHONE`, `ASK_PHONE_AGAIN`, `ASK_PHONE_VERIFY_SHARED`, `INTRODUCE_AGAIN_ASK_PHONE`,
mỗi nhóm 3 cách nói) chưa có audio trong release `assets/tts/static/2026-10-08-v2`: khi chạy, 12 câu
này đi qua provider (Vbee) như câu động, 74 câu cũ vẫn dùng cache. Đã thêm vào danh sách PM duyệt
(`tts-static-cache/tts-utterances-pm-review-2026-10-12.md`, mã A75–A86). Thứ tự còn lại do chủ TTS làm
sau khi PM chốt chữ: `scripts/tts_utterance_catalog.py --date <ngày>` → thêm nhóm mới vào reduction map
→ `scripts/tts_static_shortlist.py` → `scripts/tts_build_static.py --synthesize` (Vbee, trả phí) → nghe
duyệt → `scripts/tts_release_static.py` → trỏ `config/tts_static.yaml` sang release mới. Cho tới lúc đó
`tests/eval/test_tts_build_static.py` và `tests/speech/tts/test_static_cache.py` báo "Catalog cũ" (đúng
thiết kế: template đổi thì phải xuất lại catalog trước khi thu).

## File liên quan

- `src/callbot/engine/verification/identity.py` (`LookupStatus.AWAITING_PHONE`, `lookup_spoken_phone`),
  `src/callbot/engine/verification/phone.py`
- `src/callbot/engine/extraction/phone.py`, `extractor.py` (`ASK_PHONE` chỉ luật, không hỏi model),
  `schema.py` (`QuestionId.ASK_PHONE`, `ExtractionResult.phone`)
- `src/callbot/engine/dialogue/manager.py` (`_ask_phone`, `_phone`), `templates.py` (`ASK_PHONE*`,
  `INTRODUCE_AGAIN_ASK_PHONE`), `inbound.py`
- `src/callbot/engine/session/context.py` (`IdentityLookup`, `IdentityStep`)
- `docs/reference/http-api.md`, `scripts/tts_utterance_catalog.py` (12 câu tĩnh mới, nhóm Identity)

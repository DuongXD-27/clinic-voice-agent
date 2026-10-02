# Evidence: TTS — Kiểm audio đọc đúng lời bot, 5 kịch bản đang chấm (29/09, tuần 3)

## Mục tiêu

§4.1.3 contract: audio phải đọc **đúng `utterance`**, không thêm, bớt hay đổi nghĩa. Chương trình lấy mẫu ở review tuần 6, và sai lệch có hệ thống bị xử như sửa mock. Task này làm hai việc:

1. Thêm test tự động chặn mọi thay đổi text trước TTS trên đường HTTP.
2. Nghe toàn bộ câu thoại của 5 kịch bản đang chấm (Identity, Confirm, No-answer, Cancel, Transfer) bằng giọng Vbee đang chạy prod.

Người dùng yêu cầu thêm: đánh giá ngữ điệu (có bị ngang không) và khả năng điều chỉnh.

Kế hoạch: `docs/plans/tts-w3-w6.md`, mục T3 29/09 "Kiểm audio đọc đúng lời bot".

## Bằng chứng

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Test "text gửi TTS = utterance" cho cả `/v1/calls` và `/turn` | `test_audio_mode_speaks_exactly_the_utterance_every_turn` trong `tests/transports/http/test_calls.py`. Chạy 4 cuộc gọi `mode=audio` (Identity+Confirm; Identity hỏi lại ngày sinh + Cancel hai lượt; No-answer 3 lượt im lặng; Transfer). Assert `FakeTTS.spoken` bằng đúng danh sách `utterance` của mọi response, và mọi response có `audio_url`. Tầng dưới (gateway → provider chính/dự phòng nhận đúng text) đã có test `test_primary_error_falls_back_once_and_logs_code_not_text` |
| Liệt kê 100% câu của 5 kịch bản | `scripts/tts_fidelity_audit.py` lấy câu từ registry `STATIC_UTTERANCES` / `RENDERERS` của `templates.py`, không chép tay. Script cảnh báo nếu có template mới chưa xếp kịch bản. Kết quả: 34 câu (17 Identity, 7 Confirm, 4 No-answer, 5 Cancel, 2 Transfer; một số renderer có 2 biến thể). Reschedule/Booking để task 05/10 và 12/10 |
| Câu có phần động điền bằng dữ liệu Clinic Mock | Renderer đọc lịch được điền bằng 11 lịch seed của `FakeClinicAPI.mentor_mock()` (apt_00417, apt_00418–427). Bản nghe dùng apt_00417 (có phút: "3 giờ 30 chiều"); độ dài lớn nhất tính trên 11 lịch × 3 tên cơ sở |
| Không câu nào vượt 300 ký tự | Dài nhất 205 ký tự: `SILENCE_REPROMPT` lặp lại câu đọc lịch dài nhất. 0 câu vượt `MAX_TEXT_CHARS = 300`, nên không câu nào phải dựa vào ElevenLabs vì độ dài |
| Sinh audio để nghe | 34/34 câu sinh thành công bằng `hn_female_ngochuyen_full_48k-fhg`, speed 1.0. Thời gian sinh 0,70–2,27 s/câu. WAV ở `temp/tts/fidelity/` (không commit) |
| Bảng nghe đúng/sai | **Chờ người nghe điền** `temp/tts/fidelity/listening_sheet.csv` (cột `doc_dung`, `ngu_dieu`, `ghi_chu`); nghe bằng `temp/tts/fidelity/index.html` |

## Ngữ điệu: điều chỉnh được gì trên Vbee

Kiểm ngày 29/09 bằng API của tài khoản team (`GET https://vbee.vn/api/v1/voices`, `POST https://api.vbee.vn/v1/tts`):

| Phát hiện | Chi tiết |
| --- | --- |
| Giọng đang dùng là giọng đọc review/tin tức | `hn_female_ngochuyen_full_48k-fhg` thuộc nhóm `review`, cache `ngochuyen-news`. Mô tả của Vbee: "phù hợp với các nội dung review phim". Đây là lý do dễ nghe ngang và đều khi hỏi đáp |
| Realtime sync chỉ nhận 5 giọng Việt | Chỉ giọng có `has_tts_sync = true`: Ngọc Huyền (HN, review), Tường Vy (SG, **callcenter**), Mai Phương (HN, education), Thảo Trinh (SG, book), Lan Trinh (SG, story) |
| Giọng biểu cảm/tổng đài không dùng được qua realtime | Ngọc Huyền 2.0 (`…_24k-st`), Ngọc Huyền nâng cao (`…_24k-stl`), Tường Vy nâng cao, Hương Giang (Huế, callcenter) đều trả `400 "Voice does not support TTS sync"` |
| Tham số payload | Realtime chỉ có `voiceCode`, `speed`, `outputFormat`, `sampleRate`, `bitrate`. Không tìm thấy tham số pitch/style/emotion hay SSML trong tài liệu công khai |

Các cách chỉnh ngữ điệu còn lại, vẫn giữ §4.1.3:

1. **Sửa câu chữ và dấu câu trong template** (Hoàn làm): thêm dấu phẩy để ngắt, tách câu dài, bỏ ngoặc kép “…”. Utterance đổi theo nên audio vẫn khớp. **Không** chèn ngắt nghỉ hay SSML ở lớp TTS.
2. **`VBEE_SPEED`**: chỉnh nhịp, không đổi được cao độ.
3. Đổi giọng: chỉ còn Tường Vy là giọng tổng đài, nhưng giọng miền Nam. Theo quyết định của team, giữ Ngọc Huyền và không tốn thêm quota để so giọng.

## Quyết định 29/09: đọc thời gian khám chậm hơn bằng dấu phẩy (tạm chốt)

**Vấn đề (người nghe):** trong các câu đọc lịch, phần thời gian khám bị đọc quá nhanh, ví dụ "3 giờ 30 chiều ngày 14 tháng 10 tại Vinmec Times City".

Vbee không cho chỉnh tốc độ riêng một phần câu. Đã sinh 3 bản của câu 18 `APPOINTMENT_SUMMARY` (apt_00417) để so sánh; file nằm ở `temp/tts/fidelity/mau_doc_cham/`:

| Bản | Cách làm | Độ dài | Kết quả nghe |
| --- | --- | --- | --- |
| A | Bản đang chạy, speed 1.0 | 8,8 s | Phần thời gian nhanh |
| B | Tách 3 đoạn, đoạn thời gian đọc speed 0.8, ghép PCM | 9,5 s | Chậm hơn nhưng chỗ nối kém tự nhiên; tốn 3 request/câu và cần logic nhận diện đoạn thời gian |
| **C** | **Thêm dấu phẩy quanh phần thời gian**, speed 1.0 | 9,7 s | **Tự nhiên nhất → chọn** |

Câu C: "Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều**,** ngày 14 tháng 10**,** tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ?"

**Chốt:** sửa câu chữ ở template, **không** sửa ở lớp TTS. Utterance đổi theo nên audio vẫn khớp nguyên văn (§4.1.3), không tốn thêm request và không tăng độ trễ.

**Việc cần làm (Hoàn, Engine), trong `src/callbot/engine/dialogue/templates.py`:**

1. `speak_datetime`: thêm dấu phẩy giữa giờ và ngày, `"… {period}, ngày {day} tháng {month}"`.
2. `attendance_facts`: thêm dấu phẩy trước cơ sở, `"{speak_datetime(...)}, tại {clinic_name(...)}"`.
3. Sửa các test đang so nguyên văn chuỗi cũ: `tests/engine/test_confirm_dialogue.py`, `tests/engine/test_cancel_dialogue.py`, `tests/engine/policy/test_output_guard.py`. Output Guard render lại bằng chính renderer nên tự khớp, không cần sửa guard.

`speak_datetime` dùng chung, nên thay đổi ảnh hưởng cả 5 câu đọc lịch của Confirm (`APPOINTMENT_SUMMARY`, `ATTENDANCE_READBACK`, `ATTENDANCE_REREAD`, `KEEP_APPOINTMENT`, `CONFIRMED_DONE`) và câu Reschedule/Booking (`OFFER_SLOTS`, `SLOT_READBACK`, `SLOT_CHOICE`, `RESCHEDULED_DONE`, `BOOKED_DONE`). Riêng `OFFER_SLOTS` đọc nhiều khung giờ cách nhau bằng dấu `;`, nên nghe lại ở task 05/10.

Sau khi Hoàn merge: chạy lại `python scripts/tts_fidelity_audit.py`, nghe lại các câu Confirm và cập nhật mục này.

## File liên quan

- `tests/transports/http/test_calls.py`: thêm `test_audio_mode_speaks_exactly_the_utterance_every_turn` (4 case).
- `scripts/tts_fidelity_audit.py` (mới): liệt kê câu 5 kịch bản, tính độ dài lớn nhất, sinh WAV, xuất phiếu nghe + trang nghe. `--dry-run` không gọi Vbee.
- `docs/plans/tts-w3-w6.md`: mục T3 29/09.

## Quy trình xác minh

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/transports/http/test_calls.py -k speaks_exactly -q
python scripts/tts_fidelity_audit.py --dry-run     # liệt kê 34 câu + độ dài, không tốn quota
python scripts/tts_fidelity_audit.py               # sinh WAV (~3.000 ký tự quota Vbee)
python scripts/tts_fidelity_audit.py --combine-only   # chỉ ghép lại WAV đã có, không tốn quota
# Nghe liền 34 câu (3 phút 36 giây, mỗi câu cách 1 s): temp/tts/fidelity/<giọng>@1_tat_ca.wav
# Tra câu theo phút:giây: temp/tts/fidelity/<giọng>@1_moc_thoi_gian.txt; điền listening_sheet.csv
```

## Kết quả xác minh cục bộ (2026-09-29)

| Command | Kết quả |
| --- | --- |
| `python -m pytest tests/transports/http/test_calls.py -k speaks_exactly -q` | Pass (4 passed) |
| `python -m ruff check src tests scripts/tts_fidelity_audit.py` | Pass |
| `python -m ruff format --check src tests scripts/tts_fidelity_audit.py` | Pass |
| `python -m pytest -q` (với `PYTHONUTF8=1`) | 3416 passed, 18 failed. Cả 18 lỗi đều do máy local thiếu `soxr` (`ModuleNotFoundError`, dependency resample mới từ commit STT trên `main`); không liên quan task này. Cài lại `pip install -e ".[dev,speech]"` rồi chạy lại |
| `python scripts/tts_fidelity_audit.py` | 34/34 câu sinh được, 0 lỗi, 0 câu > 300 ký tự |

Không đặt `PYTHONUTF8=1` thì trên Windows `tests/test_compose_speech_config.py` lỗi `UnicodeDecodeError` lúc collect (đọc file bằng cp1252). Lỗi có sẵn, không do task này.

## Ghi chú

- **Câu dài khi phát:** `SILENCE_REPROMPT` kèm câu đọc lịch dài 11,2 s audio, `APPOINTMENT_SUMMARY` dài 8,8 s. Không ảnh hưởng trần 8 s (trần tính đến lúc tải xong file, không tính thời gian phát), nhưng người nghe dễ chen ngang. Nên cân nhắc với Hoàn.
- **Ngoặc kép “hủy lịch”** trong `CANCEL_CHOICE` / `CANCEL_REASON_NOTED`: cần nghe xem Vbee có ngắt nghỉ lạ không.
- Bảng nghe chưa điền. Câu nào đọc sai thì báo Hoàn sửa template, không sửa ở lớp TTS.

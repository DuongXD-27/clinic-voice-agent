# Kiểm chứng Audio Mode parity — 01/10/2026

## Thay đổi đã triển khai

1. Core kiểm tra thứ tự, request trùng và phiên đã đóng trước khi gọi resolver ASR.
   Transcript thành công được lưu trước xử lý nghiệp vụ; retry PROCESSING dùng lại
   transcript và thời điểm cũ, retry COMPLETED dùng action cũ. Lỗi STT không đặt chỗ lượt.
2. HTTP cố định mode theo cuộc gọi và khóa toàn bộ nhận dạng → Core → xuất audio bằng
   khóa Redis riêng. Cùng request concurrent không nhân đôi ASR/Core/TTS.
3. Output Guard vẫn là chốt duy nhất trước commit. TTS nhận nguyên utterance đã Guard;
   audio mode chỉ trả thành công khi WAV đã lưu, URL có thể tải ngay. WAV được thay thế
   nguyên tử; hash utterance giúp dùng lại artifact khi retry.
4. Lỗi TTS/thiếu audio/storage trả `503 AUDIO_OUTPUT_UNAVAILABLE`, không chuyển máy bù
   hay đổi outcome đã ghi. Terminal output đang chờ có biên nhận Redis tối đa 120 giây,
   không gia hạn; retry đúng request chỉ xuất audio, rồi xóa biên nhận. Session vẫn purge
   ngay. Không có biên nhận hoặc hết TTL thì giữ `CALL_ENDED`, không ghi Clinic lần hai.
5. LiveKit EOF bình thường đứng sau tất cả lượt đã chốt. Lỗi/cleanup vẫn ưu tiên sentinel;
   không làm mất một lượt khi hàng đợi đầy ở cuối luồng bình thường.

Không thay đổi điều kiện xác minh danh tính, xác nhận hủy lần hai, lựa chọn slot từ
Clinic, atomic reschedule hay giới hạn nguồn `NO_ANSWER`/`LINE_BUSY`.

## Ma trận parity trên Core thật

| Flow | Kịch bản | HTTP text/audio | LiveKit Bridge/text |
| --- | --- | --- | --- |
| Identity | Tên và DOB đúng; chưa ghi Clinic | Đạt | Đạt |
| Confirm | Đồng ý sau read-back → CONFIRMED | Đạt | Đạt |
| Cancel | Yêu cầu hủy và xác nhận riêng → CANCELLED | Đạt | Đạt |
| Transfer | Yêu cầu tư vấn thuốc → TRANSFERRED | Đạt | Đạt |
| Reschedule | Chọn slot được đưa ra, xác nhận → RESCHEDULED | Đạt | Đạt |
| No answer | Ba lượt im lặng outbound → UNREACHABLE/SILENCE | Đạt | Đạt |
| Booking inbound | Xác minh, chọn slot, xác nhận → đúng một BOOKED | Đạt | Đạt |

HTTP đối chiếu utterance, state/outcome, counters, slot đã chọn, chuỗi API, writes và
bản ghi Clinic. Bridge dùng orchestrator thật và SDK media thật tại ranh giới frame;
pipeline cấp lượt đã chốt, room và TTS giả để không cần server/provider. Bridge cũng
đối chiếu utterance gửi TTS, state/outcome gửi data channel và API/bản ghi Clinic.

Ca biên HTTP: voicemail, ba im lặng inbound không tạo appointment, danh tính sai,
hai lượt không hiểu, lời nói về line busy/no answer không trở thành phone status,
Output Guard thay câu có nguy cơ lộ lịch trước khi TTS nhận nó.

Regression phục hồi: lỗi/timeout/thiếu audio/TTS rỗng/storage sau commit, đổi request,
retry concurrent, worker bị ngắt sau reserve, mode conflict, phục hồi ở transport
instance khác, TTL không gia hạn, biên nhận đã hết hạn, mất Redis khi lưu biên nhận,
artifact cache khớp utterance, thay WAV thất bại không để file dở.

## Kết quả chạy tại Windows

| Kiểm tra | Kết quả |
| --- | --- |
| Toàn bộ backend | **3744 passed, 9 skipped**, 125,25 giây |
| Ruff lint và format | Đạt; 314 file Python đúng format |
| OpenAPI so với schema UI | Đạt, không đổi schema |
| Regression LiveKit | **43 passed** |
| ASR local opt-in | **3 passed**: identity, confirm, voicemail |
| API Luna | **0 lượt gọi** |

Chạy backend:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -X utf8 scripts/export_openapi.py --check
```

Chạy ASR thật riêng:

```powershell
$env:CALLBOT_REAL_ASR = '1'
.venv\Scripts\python.exe -X utf8 -m pytest tests/transports/http/test_audio_real_asr.py -q -s
Remove-Item Env:CALLBOT_REAL_ASR
```

ASR dùng `zipformer` self-host với model/asset có sẵn, clip 8 kHz trong `eval/stt-bench`:
`STT_ID_02`, `STT_DOB_01`, `STT_CF_01`, `STT_SIG_04`. Transcript tên/DOB thật được Core
xác minh; confirm ghi CONFIRMED, voicemail ghi UNREACHABLE đúng nhánh. Các lượt này
kiểm tra cả tải WAV trả về trong ngưỡng 8 giây, với TTS giả; không gọi semantic fallback.

## Giới hạn và phần cần provider/dữ liệu

- 7/7 là parity luồng/state/API trên Core thật với input được điều khiển. Bộ clip có
  nhãn hiện chỉ cho kiểm chứng ASR tích hợp identity/confirm/voicemail; chưa đủ clip
  trọn luồng cancel, reschedule và booking để tuyên bố ASR thật đạt 7/7.
- TTS giả trả PCM mẫu; test chỉ chứng minh giao đúng utterance và artifact sẵn sàng.
  Chưa chứng minh giọng nói trung thực theo contract §4.1.3, chất lượng TTS hoặc latency
  toàn hệ thống với provider thật. Các mẫu local không phải số đo p95 production.
- Biên nhận output có thể chứa lịch đã được phép nói trong utterance, giữ tạm tối đa
  120 giây; không giữ transcript, extraction hay hồ sơ. Worker chết giữa commit terminal
  và lưu biên nhận không thể phục hồi câu cũ; fail closed vẫn ngăn ghi Clinic lần hai.

## Phạm vi review và CI

Toàn bộ triển khai và kiểm chứng được gom trong [PR #66](https://github.com/phamtuanviet/callbot-vinmec/pull/66),
trên nhánh `fix/audio-request-replay`, kế thừa PR #64. Kết quả CI Linux và UI được
theo dõi tại các check của PR; bảng trên ghi kết quả chạy local Windows.

Review bổ sung regression cho start/turn đồng thời: kiểm tra mode phải nằm trong
khóa transport để request text không được nhận nhầm vào cuộc gọi audio vừa khởi tạo.

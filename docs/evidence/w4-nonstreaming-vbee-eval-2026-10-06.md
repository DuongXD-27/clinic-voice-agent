# W4 — voice request/response non-streaming: kết quả 06/10/2026

**PASS 7/7 flow trong eval HTTP local, STT GipFormer1.5 thật và TTS Vbee thật.**
Audio input → STT → Core/FSM/Policy → Output Guard → TTS → audio output đã đi qua đường HTTP của ứng dụng.
State và API action parity với text đạt ở cả bảy flow.

Code được kiểm chứng: `e0c2d47c78faa9e2a60f7208e84c568c63500b45`.
Không sửa application code hoặc `.env`. Chỉ bổ sung bộ chạy và bằng chứng đánh giá.
Phạm vi W4 không bao gồm realtime streaming, SIP hoặc live call.

## Kết quả từng flow

| Flow | Kết quả | Outcome | WAV bot, gồm mở đầu | Clinic writes | Lượt chậm nhất (ms) |
| --- | --- | --- | ---: | ---: | ---: |
| Identity | PASS | Xác minh danh tính; chưa kết thúc | 3 | 0 | 1391.20 |
| Confirm | PASS | CONFIRMED | 4 | 1 | 1366.15 |
| Cancel | PASS | CANCELLED | 5 | 1 | 1325.14 |
| Transfer | PASS | TRANSFERRED | 2 | 1 | 1101.12 |
| Reschedule | PASS | RESCHEDULED | 6 | 1 | 1284.20 |
| No-answer | PASS | UNREACHABLE | 4 | 1 | 986.80 |
| Booking inbound | PASS | BOOKED | 6 | 1 | 1128.44 |

Tổng 20 lượt audio có giọng người gọi và ba lượt silence, cộng bảy lời mở đầu: **30 WAV bot**.
No-answer dùng ba lượt `silence_ms=2000` theo contract; không gọi STT cho silence.
Identity được kiểm đến bước xác minh danh tính, chưa phải outcome terminal; không phát sinh write.
Mỗi flow terminal có đúng một write vào Clinic giả.

## Cách chạy và đối chiếu

- FastAPI TestClient chạy route thật `/v1/calls` và `/v1/calls/{call_id}/turn` trong process.
- Clip người gọi được upload qua `/demo-api/audio`, tải lại và decode qua loader nội bộ TestClient.
- STT model: `g-group-ai-lab/gipformer1.5-68M-rnnt`, chạy local. `zipformer` chỉ là tên selector/adapter hiện tại trong code.
- TTS: `vbee`, voice `hn_female_ngochuyen_full_48k-fhg`; gateway dùng `synthesize`, payload `mode=sync`, PCM mono 8 kHz. Dữ liệu HTTP được gom đủ thành WAV trước khi trả audio URL.
- Không gọi `synthesize_stream` hoặc live-call transport. Việc provider trả body HTTP theo chunk không thay đổi contract request/response non-streaming được nghiệm thu.
- Text baseline sử dụng chính transcript nhận từ STT. So sánh toàn bộ response trừ call_id/audio_url; state, turn, identity, counters, slot và pending action; chuỗi API operation/method/path/status/code; writes và bản ghi Clinic.
- TTS nhận đúng utterance đã qua Guard ở cả 30 phản hồi; provider thực tế luôn là Vbee, không dùng fallback.
- Tải lại 30 audio URL bằng HTTP local: tất cả 200, WAV PCM16 mono 8 kHz, có frame và biên độ khác 0. File, hash và utterance tương ứng nằm trong audio manifest.
- Clinic và Redis dùng FakeClinicAPI/fakeredis. Clock nghiệp vụ cố định `2026-10-06T10:00:00+07:00`. Không thao tác dữ liệu bệnh viện hoặc Redis đang chạy.
- Name/semantic LLM fallback và tracing export tắt trong tiến trình eval. Chỉ cho phép HTTP POST tới endpoint Vbee đã cấu hình; không có HTTP ngoài khác bị thử gọi.

Regression trước đó: **215 pytest passed**, gồm parity, retry/replay, real ASR opt-in, Output Guard và audio storage. Kết quả nằm trong bộ bằng chứng local cùng thư mục.

## Độ trễ và quota

30 request Vbee đều HTTP 200 và nhận được audio; không retry provider.
Tổng văn bản thực sự gửi: **3.023 ký tự**, dưới giới hạn 5.000 ký tự của eval.
Con số này là lượng văn bản gửi, không phải số credits hoặc tiền đã trừ: chưa đọc số dư trước/sau, nên không khẳng định hóa đơn của tài khoản.
Không nạp tiền, không gọi STT cloud hoặc LLM trả phí.

Lượt HTTP audio chậm nhất **1391.20 ms**, trung bình **919.60 ms**; cả 30 lượt dưới 8 giây.
Thời gian route mở đầu tính từ trước POST đến nhận response; lượt turn tính cả gọi route và tải/kiểm WAV nội bộ, không tính upload clip trước đó.
Số đo bao gồm kết nối Vbee thật; không phải latency của deployment production qua mạng client và không dùng để suy ra p95 production.

## Thu âm và review giọng

**Không cần thu thêm.** Dùng lại clip QA của người dùng ở `C:/qa-audio-20260928/wav` và ba clip tên/DOB/confirm đã có trong repository.
Booking sử dụng bản sao local cắt lời dẫn từ giây 1,78; STT nhận đúng `TÔI MUỐN ĐẶT LỊCH KHÁM`. Không sửa clip gốc.
Cancellation dùng cùng clip ở hai turn riêng, gửi lượt xác nhận sau câu hỏi reconfirm của bot.

Đã kiểm tự động cấu trúc và tín hiệu WAV, chưa chấm chủ quan độ tự nhiên/phát âm bằng nghe người.
Mẫu kết thúc Booking nằm trong artifact ở `outputs/booking/5.wav`. Xem cách giải nén/nghe bên dưới.

## Bộ bàn giao trong repository

Bộ bằng chứng được lưu tại [w4-nonstreaming-2026-10-06](w4-nonstreaming-2026-10-06/README.md), không phụ thuộc thư mục `temp/` của máy người chạy.

- [Kết quả từng flow, state và API parity](w4-nonstreaming-2026-10-06/results.json)
- [Ledger 30 request và 3.023 ký tự](w4-nonstreaming-2026-10-06/cost-ledger.json)
- [Manifest 30 WAV bot, utterance và thông số provider](w4-nonstreaming-2026-10-06/audio-manifest.json)
- [Artifact WAV đầu vào/đầu ra và provenance](w4-nonstreaming-2026-10-06/artifacts/voice-audio.zip)
- [SHA-256 và kích thước từng file trong artifact](w4-nonstreaming-2026-10-06/artifact-manifest.json)
- [Kết quả 215 regression — JUnit XML](w4-nonstreaming-2026-10-06/regression/results.xml)
- [Regression summary](w4-nonstreaming-2026-10-06/regression/run-summary.json)
- [Replay STT thật + TTS giả 7/7](w4-nonstreaming-2026-10-06/regression/real-audio-replay.json)
- [Bộ chạy portable](../../scripts/w4_voice_eval.py)

Artifact chứa **30 WAV bot, 10 WAV đầu vào** (chín clip dùng trong eval và bản booking gốc để đối chiếu phần cắt), cùng script và dữ liệu nguyên gốc của lần chạy trong `provenance/`. Dữ liệu JSON bàn giao chỉ đổi path metadata sang đường dẫn bên trong archive; đo lường, state, utterance và API parity giữ nguyên.

Chạy từ root repo, không cần `.env`, model hoặc thư viện ngoài Python khi chỉ kiểm tra bằng chứng:

```powershell
python scripts/w4_voice_eval.py
python scripts/w4_voice_eval.py --extract-audio temp/w4-voice-audio
```

Lệnh đầu kiểm SHA-256, 30 WAV PCM16 mono 8 kHz có tín hiệu, parity 7/7, ledger và 215 regression; **không chạy lại eval hoặc gọi provider**. Lệnh thứ hai kiểm lại rồi giải nén 40 WAV, không ghi đè file có sẵn. Có thể nghe `temp/w4-voice-audio/outputs/booking/5.wav` hoặc bất kỳ flow/turn khác.

Nếu chủ động chạy một vòng eval mới với Vbee thật, dùng môi trường dev/speech đã cài, model GipFormer1.5 local và credentials Vbee trong `.env`:

```powershell
python -X utf8 scripts/w4_voice_eval.py --run-vbee --budget-chars 5000
```

Cờ `--run-vbee` sẽ tiêu thụ quota mới. Bộ chạy lấy clip từ artifact có sẵn, giới hạn ký tự 1–5.000, không retry/fallback, chỉ cho phép HTTP tới endpoint Vbee. Output vòng mới lưu trong `temp/w4-voice-eval/`, không ghi đè bằng chứng nghiệm thu đã bàn giao.
Script lịch sử bên trong `provenance/` lưu để audit lần chạy cũ; script ở `scripts/` dùng để tái lập trên máy khác. Phần đóng gói bàn giao chỉ kiểm offline, không gọi thêm Vbee và không chạy lại 215 test.

Lượt thiết lập đầu tiên dừng do console Windows không in được tiếng Việt, trước khi gọi Vbee; bật UTF-8 rồi chạy hoàn tất. Không tính lượt thiết lập đó là lỗi sản phẩm hoặc lần gọi trả phí.

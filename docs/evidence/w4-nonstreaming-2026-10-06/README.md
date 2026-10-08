# Bộ bàn giao voice non-streaming W4 — 06/10/2026

**7/7 flow PASS**, STT GipFormer1.5 local + TTS Vbee thật; state/API action parity với text.
30 phản hồi WAV, 30 request Vbee, 3.023 ký tự. Regression: 215 passed, không skip.
Clinic/Redis giả; HTTP TestClient trong process; không nghiệm thu streaming, SIP hoặc live call.

[Báo cáo nghiệm thu và giới hạn kết luận](../w4-nonstreaming-vbee-eval-2026-10-06.md).

## Kiểm tra miễn phí sau khi clone

Chạy ở root repo, chỉ cần Python 3.11+, không cần model/credentials hoặc thư viện ngoài:

```powershell
python scripts/w4_voice_eval.py
```

Đây là kiểm tra **bằng chứng đã ghi**, không phải chạy lại 215 test hay eval provider.
Script kiểm archive/file SHA-256, cấu trúc và tín hiệu 30 WAV, parity text/audio của 7 flow,
quan hệ utterance/turn/WAV, ledger và JUnit XML.

## Nghe WAV và lấy clip tái lập

```powershell
python scripts/w4_voice_eval.py --extract-audio temp/w4-voice-audio
```

Lệnh giải nén 40 WAV đã có, không gọi API và không ghi đè file có sẵn:

- `inputs/`: chín clip sử dụng trong eval và một bản booking gốc trước khi cắt lời dẫn.
- `outputs/<flow>/<turn>.wav`: 30 WAV Vbee; turn `0` là lời mở đầu.
- Mẫu chốt Booking: `temp/w4-voice-audio/outputs/booking/5.wav`.

Không cần người dùng thu thêm. No-answer dùng ba lượt `silence_ms=2000`, không cần clip silence.
Chất lượng giọng/phát âm bằng nghe người chưa được chấm trong phép kiểm tự động này.

## Tái lập eval mới — có gọi Vbee

Dùng môi trường dự án đã cài các extra `dev,speech,speech-zipformer` theo `pyproject.toml`,
assets GipFormer1.5 local và `.env` có `VBEE_API_TOKEN`/`VBEE_APP_ID` hợp lệ.
Các field `ZIPFORMER_*`/selector `zipformer` là tên nội bộ cũ; model cần là
`g-group-ai-lab/gipformer1.5-68M-rnnt`. Xem cấu hình/paths ở `.env.example` và
`config/asr.yaml`; các asset ONNX không được đóng gói trong artifact audio.

```powershell
python -X utf8 scripts/w4_voice_eval.py --run-vbee --budget-chars 5000
```

Mặc định script chỉ verify offline. Phải chọn `--run-vbee` để gọi provider thật;
cờ này tiêu thụ quota mới, không phải bước cần làm để review bàn giao.
Giới hạn tổng ký tự 1–5.000, dừng khi flow lỗi, không retry provider hoặc TTS fallback.
STT local, LLM/name fallback và tracing export tắt trong tiến trình; Clinic/fakeredis giả.
Chỉ cho phép HTTP POST Vbee; giữ nguyên `.env` và code ứng dụng.
Output mới ở `temp/w4-voice-eval/vbee-eval-<timestamp>/`, có thể đổi bằng `--output-dir`.

## Nội dung bàn giao

| File | Nội dung |
| --- | --- |
| [results.json](results.json) | 7/7 provider thật, từng lượt, state/API parity, latency |
| [cost-ledger.json](cost-ledger.json) | 30 HTTP 200 nhận audio, 3.023 ký tự gửi, không retry |
| [audio-manifest.json](audio-manifest.json) | 30 WAV bot, hash, utterance/turn, thông số Vbee |
| [artifact-manifest.json](artifact-manifest.json) | SHA-256/kích thước archive và từng entry |
| [artifacts/voice-audio.zip](artifacts/voice-audio.zip) | 30 WAV bot + 10 input WAV + 4 file provenance, khoảng 2,84 MB |
| [regression/results.xml](regression/results.xml) | JUnit: 215 tests, 0 failures/errors/skipped |
| [regression/run-summary.json](regression/run-summary.json) | Bộ test và chính sách chặn mạng của regression |
| [regression/real-audio-replay.json](regression/real-audio-replay.json) | STT thật + TTS giả 7/7, làm trước provider run |
| [regression/recording-plan-check.json](regression/recording-plan-check.json) | Kiểm câu QA ở Core trước khi dùng clip |
| [scripts/w4_voice_eval.py](../../../scripts/w4_voice_eval.py) | Script portable: verify, extract, opt-in paid replay |

Path trong `results.json`/manifest audio tính từ root archive khi giải nén.
URL `http://testserver/...` là URL HTTP của lần đo TestClient, không phải link tải đang hoạt động;
dùng `outputs/` để nghe WAV đã lưu. Không cần thư mục `C:/qa-audio-20260928` của máy gốc.

`provenance/` trong ZIP giữ script chạy thực tế và JSON nguyên gốc có path lịch sử.
Bản JSON ngoài ZIP chỉ rebased path metadata; `flows` khớp nguyên gốc, được verifier đối chiếu.
Script portable bổ sung đường dẫn theo repo/clip artifact và cờ opt-in để tái lập;
không coi việc verify/đóng gói là một lần eval mới.

Khi bàn giao, mang cả thư mục này, script và báo cáo. Tất cả nằm ngoài đường dẫn Git ignore;
không cần force-add `temp/`, `.env`, model assets hoặc output của vòng chạy mới.

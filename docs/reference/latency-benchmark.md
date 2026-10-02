# Bộ benchmark độ trễ (scripts/bench/)

Một bộ đo cố định để so **trước / sau** một thay đổi (đầu tiên: Vbee streaming, nhánh `feature/tts-w3-vbee-streaming`). Chạy trên EC2 prod, cùng image và cấu hình đang phục vụ. Kết quả lưu ở host `/opt/callbot/bench-results/<nhãn>/` nên không mất khi deploy. Kết quả **không chứa text hội thoại**, chỉ có thời gian, số ký tự, provider và mã lỗi (NFR-16).

## Thuật ngữ

| Tên | Nghĩa trong bộ đo |
|---|---|
| **TTFA** (time to first audio) | Thời gian tới âm thanh đầu tiên. Phần 1: từ lúc gọi TTS tới chunk đầu. Phần 3: từ lúc Engine trả câu (data channel) tới frame đầu có tiếng ở phía người gọi. Trace: "TTFA Vbee" là byte audio đầu của Vbee về server |
| **TTS total** | Thời gian tới chunk cuối, tức sinh đủ câu. Xấp xỉ phần TTS của Đường A (HTTP gom cả câu) |
| **E2E latency** | Phần 3: từ lúc khách nói xong tới lúc bot có tiếng. Đây là con số khách cảm nhận |
| **STT (endpointing + ASR)** | Phần 3: từ lúc khách nói xong tới lúc bot chốt lượt, gồm thời gian VAD chờ im lặng và ASR |
| **Turn latency** | Phần 2: response + tải `audio_url`, đúng cách harness tính (§4.1.2, trần 8 s) |
| **RTF** (real-time factor) | Thời lượng audio / TTS total. Lớn hơn 1 là sinh nhanh hơn phát |
| **Stall** | Tổng thời gian bên phát hết audio phải chờ chunk sau (giật), mô phỏng phát từ chunk đầu |
| **Barge-in stop latency** | Từ lúc khách bắt đầu nói chen tới lúc bot im |
| **p50 / p95** | Trung vị / phân vị 95. p95 chỉ hiện khi có từ 10 mẫu trở lên |

## Đo gì

| Phần | Chạy ở | Đo | Trả lời câu hỏi |
|---|---|---|---|
| 1. TTS (`tts_component.py`) | container `livekit-worker` | Gọi `SpeechSynthesizer.synthesize_stream`, tức đúng chỗ worker LiveKit gọi TTS, với 3 câu cố định (45 / 113 / 234 ký tự), xen kẽ, có câu khởi động. Mỗi câu ghi: **TTFA**, **TTS total**, RTF, **Stall**. Tuỳ chọn: **cancel** (gọi `cancel()` 300 ms sau chunk đầu) và **fallback** (trỏ Vbee vào cổng đóng, chỉ trong process bench) | Streaming giảm TTFA bao nhiêu theo độ dài câu; có stall không; cancel có dừng ngay không; TTFA khi phải đọc bằng ElevenLabs |
| 2. HTTP (`http_turns.py`) | container `bot`, gọi qua Caddy `https://vmec-callbot.tech` | Như harness `mode=audio`: mở phiên outbound, mỗi lượt upload WAV người gọi → `/turn` → tải `audio_url` (client riêng, không kèm key). Ghi response, tải audio, **turn latency** (trần 8 s), định dạng WAV | Đường A có nằm trong 8 s không, p95 bao nhiêu (§4.1.2, §5) |
| 3. LiveKit (`livekit_call.py`) | container `bot` đóng vai người gọi | Xin token như trang demo, vào phòng, phát câu người gọi theo nhịp thật (im lặng giữa các câu như mic), nghe track của bot. Mỗi lượt có 4 mốc: khách nói xong → bot chốt lượt → Engine trả câu → bot có tiếng (hai mốc giữa lấy từ data channel `callbot.transcript`), cho ra **E2E latency = STT + Engine + TTFA**. Tuỳ chọn: **barge-in** 1,5 s sau khi bot bắt đầu đáp, đo barge-in stop latency | Khách thực sự chờ bao lâu, phần nào do STT / Engine / TTS; ngắt lời có dừng kịp không |
| Trace (`traces.py`) | container đã phục vụ cuộc gọi | Lọc trace JSONL đúng các cuộc gọi bench (theo `call_key` = HMAC của call_id), tách thời gian STT / Engine / TTS phía server | Phần 2 và 3 chậm ở đâu, nhìn từ server |

`run.sh` chạy cả bộ; `compare.py` tóm tắt một lần chạy hoặc so hai lần.

## Chạy

Chép bộ đo lên EC2 (một lần, và mỗi khi sửa script):

```powershell
scp -i $env:USERPROFILE\.ssh\vmec-bot.pem -r scripts\bench ubuntu@vmec-callbot.tech:/opt/callbot/
```

Trên EC2:

```bash
cd /opt/callbot
bash bench/run.sh truoc --dry-run       # in số ký tự quota dự kiến từng phần, chưa gọi gì
bash bench/run.sh truoc                 # lần "trước": chạy TRƯỚC khi deploy thay đổi
# ... deploy thay đổi ...
bash bench/run.sh sau                   # lần "sau": cùng profile, cùng lịch hẹn
python3 bench/compare.py bench-results/truoc bench-results/sau > bench-results/so-sanh.md
```

Tuỳ chọn của `run.sh`:
- `--profile quick|full`
- `--parts tts,http,livekit`: chỉ chạy một số phần
- `--appointment apt_004xx`: lịch hẹn cho phần 2 và 3

Mỗi nhãn chỉ chạy một lần: thư mục đã có thì `run.sh` dừng, để không ghi đè số cũ.

Lấy kết quả về máy:

```powershell
scp -i $env:USERPROFILE\.ssh\vmec-bot.pem -r ubuntu@vmec-callbot.tech:/opt/callbot/bench-results .\temp\
```

Đo phần 2 từ máy local (thêm mạng Internet VN, gần với harness ở xa hơn):

```powershell
python scripts/bench/http_turns.py --label truoc-local > temp/http-local.json
```

## Quota mỗi lần chạy

| Profile | TTS | HTTP | LiveKit | Câu người gọi | Tổng Vbee | ElevenLabs |
|---|---|---|---|---|---|---|
| `quick` (mặc định) | 1.221 (3 lần × 3 câu) | ~330 (1 cuộc, 2 lượt) | ~330 (1 cuộc, 2 lượt) | 54, chỉ khi chưa cache | **~1.900** | 0 |
| `full` | 2.473 (5 lần + 2 lần hủy) | ~990 (3 cuộc) | ~1.320 (3 cuộc + nói chen) | 85 | **~4.900** | 226 (2 lần dự phòng) |

Số của HTTP và LiveKit là ước lượng (~110 ký tự mỗi câu bot). `--dry-run` in số theo đúng tham số. So trước / sau tốn gấp đôi. Câu người gọi được cache trong `/tmp/bench-cache` của container, nên mất cache khi deploy và lần "sau" sinh lại (~54 ký tự). Vbee sinh cùng câu ra cùng audio nên vẫn so được.

## Đọc kết quả

- **Phần 1 — TTFA vs TTS total:** bản chưa stream thì hai số bằng nhau (cả câu đến một lần). Bản stream thì TTFA là thứ khách nghe trên LiveKit, còn TTS total xấp xỉ thời gian TTS của Đường A. Phần 1 tạo `SpeechSynthesizer` mới như worker làm mỗi cuộc gọi, nên bản cũ còn mất thêm chi phí tạo client HTTP mỗi câu (đã bỏ ở task 29/09).
- **Phần 3 — "bot có tiếng":** là frame đầu vượt ngưỡng năng lượng (`--rms`, mặc định 300). Số này gồm cả đoạn lặng đầu câu của provider và độ trễ mạng LiveKit. Hai phần này như nhau giữa hai lần chạy cùng provider, nên **so chênh lệch thì đúng**, còn giá trị tuyệt đối hơi cao hơn thực tế.
- **Phần 3 — câu chào:** E2E tính từ lúc vào phòng, gồm cả thời gian LiveKit giao job cho worker và gọi Clinic, nên dao động. Để so TTS thì xem TTFA.
- **Lượt "ASR không ra chữ":** bot không nhận ra câu người gọi, đây là lượt im lặng do hết giờ chờ. Lượt này bị loại khỏi trung vị.
- **p95:** chỉ hiện khi có từ 10 mẫu trở lên. Muốn có p95 Đường A thì chạy `full` hoặc tăng `--calls`.
- **Nhiễu:** chạy hai lần cùng khung giờ, khi không có cuộc gọi thật nào khác trên prod. Chênh dưới ~50 ms giữa hai lần là trong mức dao động (29/09: cùng một câu dao động 158–261 ms).

## Lưu ý

- **Clinic mock dùng chung:** phần 2 và 3 mở cuộc gọi outbound thật trên lịch hẹn `--appointment` (mặc định `apt_00427`, lịch demo thêm từ 24/09). Câu người gọi mặc định chỉ làm bot hỏi lại danh tính, không dẫn tới chuyển máy hay ghi kết quả. Nếu mở phiên lỗi `OUTBOUND_START_FAILED` (lịch đã bị đổi trạng thái), chọn lịch khác trong `apt_00418` – `apt_00427`.
- **Trace mất khi deploy** (không có volume cho `/app/traces`), nên `run.sh` đọc trace ngay sau mỗi phần.
- `run.sh` chỉ ghi vào `bench-results/` và `/tmp` trong container. Không đụng `.env`, `image.env` hay file khác trong `/opt/callbot`.
- Phần 3 cần worker LiveKit đang chạy và nhận job (cùng `LIVEKIT_AGENT_NAME` với bot).

## Kiểm script không tốn quota

Trỏ `VBEE_ENDPOINT` vào một server giả trả PCM chunked và đặt `VBEE_API_TOKEN` / `VBEE_APP_ID` giả. Sau đó chạy phần 1 (`--gap 0.1 --reps 2`) và phần 2 (`--base-url` trỏ vào một bot HTTP giả). `compare.py` chạy được trên kết quả giả. Phần 3 cần LiveKit thật, nên lần chạy đầu nên dùng `--parts livekit` với profile `quick` (~400 ký tự).

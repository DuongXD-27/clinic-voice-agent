# Evidence: TTS — Xác nhận audio mode trên prod (28/09, tuần 3)

## Mục tiêu

Từ 28/09 harness chấm ở `mode=audio` (contract Listing 1): mọi response HTTP phải có `audio_url`, tải được ngay và tổng mỗi lượt ≤ 8 s tính đến khi tải xong audio (§4.1.2, §5.3). Task này kiểm cấu hình TTS trên EC2, sửa chỗ thiếu và đo thời gian từng lượt giống harness. Kế hoạch: `docs/plans/tts-w3-w6.md`, mục T2 28/09.

## Bằng chứng

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Prod dùng Vbee chính, ElevenLabs dự phòng | Trước khi sửa, `SpeechSettings()` chạy trong container `bot` cho `TTS fallback: None`, vì `/opt/callbot/.env` thiếu `TTS_FALLBACK_PROVIDER` nên lấy mặc định `null` (`config/speech.yaml`). Đã thêm `TTS_PROVIDER=vbee`, `TTS_FALLBACK_PROVIDER=elevenlabs` và `ELEVENLABS_TIMEOUT_S=3` (backup `.env.bak-2809`), sau đó `docker compose up -d` |
| Trường hợp xấu nhất nằm trong 8 s | Vbee 3 s (`VBEE_TIMEOUT_S` mặc định) + ElevenLabs 3 s = 6 s, còn khoảng 2 s cho ASR, Engine và tải WAV. Mặc định ElevenLabs 4 s sẽ thành 7 s |
| Mọi lượt có `audio_url` tải được | `scripts/audio_smoke.py`: 4/4 lượt có `audio_url`, tải HTTP 200 không kèm key (xem bảng dưới) |
| Tổng mỗi lượt < 8 s | Lượt lớn nhất 3,79 s |
| WAV đúng định dạng | 4/4 file là PCM16 mono 8 kHz |
| `mode=text` trả `audio_url = null` | `audio_smoke.py`: `mode=text: ok (audio_url = null)` |

## Kết quả đo trên prod (28/09/2026, 22:52)

`python scripts/audio_smoke.py` chạy từ máy local tới `https://vmec-callbot.tech`, call `smoke-audio-0928225204`, outbound `apt_00417`. Câu người gọi được sinh bằng TTS local, upload qua `/demo-api/audio/...` rồi gửi `audio_url`, giống harness.

| Lượt | Response (s) | Tải audio (s) | Tổng (s) | WAV |
|---|---|---|---|---|
| mở phiên | 1,16 | 0,65 | 1,81 | 8 kHz mono, 6,9 s |
| 1 | 1,12 | 0,61 | 1,73 | 8 kHz mono, 6,9 s |
| 2 | 1,14 | 0,61 | 1,75 | 8 kHz mono, 6,9 s |
| 3 | 3,27 | 0,52 | 3,79 | 8 kHz mono, 3,3 s |

Kết quả: **PASS**. Tổng lớn nhất 3,79 s so với trần 8 s.

Thời gian được đo từ máy local, nên đã gồm độ trễ mạng Việt Nam → Singapore. Harness đo từ vị trí của nó, nên số của harness có thể khác.

## File liên quan

- `scripts/audio_smoke.py` (mới): mở cuộc gọi `mode=audio`, chạy N lượt, đo response + tải `audio_url`, kiểm WAV và `mode=text`. Exit 1 nếu có lượt ≥ 8 s, thiếu audio hoặc WAV sai.
- `/opt/callbot/.env` trên EC2 (không nằm trong repo; CD không ghi đè file này).
- `docs/plans/tts-w3-w6.md`: sửa bước 2–3 của task 28/09.

## Quy trình xác minh

Kiểm cấu hình thật trong container (chạy trên EC2, thư mục `/opt/callbot`):

```bash
docker compose --env-file .env --env-file image.env exec bot python -c "
from speech.settings import SpeechSettings
from inference.tts.gateway import create_tts_gateway
s = SpeechSettings()
g = create_tts_gateway(s.tts_provider, fallback=s.tts_fallback_provider)
print('TTS chinh   :', s.tts_provider)
print('TTS fallback:', g.fallback.provider_name if g.fallback else None)
"
```

Đo từ máy local (thư mục `callbot-vinmec`):

```powershell
$env:PYTHONIOENCODING = "utf-8"
python scripts/audio_smoke.py            # thêm --api-key sk_... nếu key trong .env local khác prod
```

## Ghi chú

- **Log khởi động không hiện provider.** Dòng `ASR ..., TTS ..., TTS fallback ...` trong `build_speech_bundle` dùng `logger.info`, nhưng container chạy `uvicorn` không có cấu hình logging nên log INFO của app không được in. Vì vậy `docker compose logs bot | grep TTS` luôn rỗng. Tạm thời kiểm bằng lệnh `exec ... python -c` ở trên. Cảnh báo fallback (`TTS vbee lỗi [...], chuyển sang elevenlabs`) ở mức WARNING nên vẫn xuất hiện trong log. Nếu muốn thấy log INFO thì cần thêm cấu hình logging (việc riêng, chưa làm).
- **Toàn bộ audio lúc đo do Vbee sinh.** Chạy `docker compose --env-file .env --env-file image.env logs --since 1h bot | grep "chuyển sang"` ngay sau lần đo cho kết quả rỗng, tức là không có lượt nào phải fallback sang ElevenLabs.
- **Hai lượt đầu bot chào lại** vì câu người gọi mặc định ("Alo, tôi nghe đây.") không phải câu trả lời danh tính. Đây là hành vi của Engine, không liên quan TTS. Script chỉ đo thời gian, không chấm hội thoại.
- **Plan có hai chỗ sai, đã sửa.** Bước 2 thiếu `--env-file` (compose báo `Cần IMAGE trong image.env`). Bước 3 ghi "gửi `text`", nhưng `mode=audio` trả `422 TEXT_NOT_ALLOWED` nên phải gửi `audio_url`.
- Việc tiếp theo, 29/09: kiểm "text gửi TTS = `utterance`" và dùng chung kết nối Vbee.

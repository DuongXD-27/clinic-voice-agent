# Evidence: TTS — Dùng chung kết nối Vbee (29/09, tuần 3)

## Mục tiêu

Trước đây `VbeeTTS.synthesize` tạo một `httpx.Client` mới cho mỗi câu, nên câu nào cũng bắt tay TCP + TLS lại với `api.vbee.vn`. Plan ước tính phần này tốn khoảng 300–400 ms mỗi câu. Task này đổi sang một client dùng chung, đóng khi app/worker tắt. Sau đó đo trước/sau trên EC2 để có số cho tiêu chí p95 (§5).

Kế hoạch: `docs/plans/tts-w3-w6.md`, mục T3 29/09 "Đường A+B — Giảm độ trễ TTS".

## Kết luận

**Trên EC2, dùng chung kết nối gần như không giảm độ trễ.** Bắt tay TCP + TLS từ EC2 (ap-southeast-1) tới Vbee chỉ mất **~9 ms**, không phải 300–400 ms như plan ước tính. Con số trong plan là số đo từ mạng Việt Nam, nơi riêng phần bắt tay đã mất 0,5–1,7 s. first_byte trung vị giảm 13 ms (207 → 194 ms). Mức này nhỏ hơn độ dao động giữa các request (158–261 ms), p95 không đổi.

Vẫn giữ thay đổi, vì:

- rủi ro thấp: server giữ kết nối rảnh ≥ 60 s, client chỉ giữ 30 s;
- bớt được một lần bắt tay mỗi câu;
- là nền cho client stream của task 30/09.

Không đưa thay đổi này vào báo cáo latency như một cải thiện.

**Vì sao bắt tay chỉ ~9 ms:** `api.vbee.vn` → `gcp.vbee.vn` → `k8s-ingressn-nginxing-….elb.ap-southeast-1.amazonaws.com` (13.214.47.81). Tức là Vbee chạy sau load balancer AWS ở Singapore, cùng vùng với EC2 bot, nên RTT chỉ khoảng 1 ms. TCP (1 RTT) + TLS 1.3 (1–2 RTT) + CPU mã hoá ra khoảng 9 ms. Đo lại từ máy local ở VN ngày 30/09 (RTT ~80 ms): TCP 77–120 ms + TLS 184–321 ms = 260–440 ms, đúng khoảng plan ước tính. Số đo EC2 khớp với nhau: first_byte của cách cũ chỉ hơn cách mới ~13 ms, gần bằng thời gian bắt tay. Tự kiểm trên EC2 không tốn quota: `curl -so /dev/null -w 'tcp %{time_connect} tls %{time_appconnect}\n' https://api.vbee.vn/v1/tts` (trả 401 vì không có token).

Phụ: Vbee từ EC2 sinh xong câu ngắn trong ~210 ms. TTS không phải phần chậm của mỗi lượt: ở T2 28/09, response mất ~1,1 s mỗi lượt, phần lớn là ASR và Engine.

## Kết quả đo trên EC2 (2026-09-30)

`scripts/tts_probe.py --kinds ngan --reps 8`, chạy trong container `bot` trên EC2 prod (image hiện tại, script tự dựng client). Giọng `hn_female_ngochuyen_full_48k-fhg`, câu ngắn 45 ký tự: "Dạ, anh chị cho em xin ngày tháng năm sinh ạ?". Cách nhau 2 s giữa hai request, đổi thứ tự cũ/mới mỗi vòng. Tốn 765 ký tự quota.

| Cách | n | Kết nối mới | Bắt tay trung vị | first_byte trung vị | first_byte p95 | total trung vị | total p95 | > 3 s |
|---|---|---|---|---|---|---|---|---|
| Cũ: client mới mỗi câu | 8 | 8/8 | 9 ms | 207 ms | 257 ms | 212 ms | 288 ms | 0 |
| Mới: dùng lại kết nối | 8 | 0/8 | — | 194 ms | 261 ms | 212 ms | 262 ms | 0 |

Từng request (ms, connect / first_byte / total):

| Vòng | Cũ | Mới |
|---|---|---|
| 1 | 9 / 193 / 288 | 0 / 224 / 225 |
| 2 | 9 / 207 / 208 | 0 / 261 / 262 |
| 3 | 9 / 204 / 205 | 0 / 192 / 193 |
| 4 | 8 / 205 / 206 | 0 / 182 / 183 |
| 5 | 14 / 214 / 216 | 0 / 158 / 252 |
| 6 | 8 / 207 / 208 | 0 / 197 / 198 |
| 7 | 9 / 257 / 259 | 0 / 243 / 245 |
| 8 | 9 / 224 / 226 | 0 / 188 / 189 |

**Chỉ đo câu ngắn.** Plan ghi 3 loại câu (ngắn / vừa / dài). Dùng lại kết nối chỉ bỏ phần bắt tay ở đầu request, phần này như nhau với mọi độ dài câu, nên đo thêm câu vừa và câu dài chỉ tốn quota (mặc định ~4.000 ký tự) mà không cho thêm thông tin. Muốn đo đủ 3 loại: bỏ `--kinds`.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Một `httpx.Client` tạo một lần, dùng cho mọi câu | `VbeeTTS.__init__` tạo `self._client` (`src/inference/tts/providers/vbee.py`); `synthesize` gọi `self._client.stream(...)`. Test `test_consecutive_sentences_share_one_client`: 3 câu, factory chỉ được gọi 1 lần, client chưa đóng |
| Giữ kết nối rảnh đủ lâu giữa hai lượt | Mặc định của httpx chỉ giữ 5 s, ngắn hơn khoảng cách giữa hai lượt nói. Thêm `VBEE_KEEPALIVE_S` (`config/tts.yaml`: 30 s) → `httpx.Limits(keepalive_expiry=...)`. Test `test_default_client_keeps_idle_connection_for_configured_time` |
| `close()` khi app/worker tắt | `VbeeTTS.close()` → `TTSGateway.close()` (đóng cả provider dự phòng, vẫn đóng dự phòng khi provider chính lỗi) → `SpeechSynthesizer.close()`. HTTP: lifespan trong `main.py` đã gọi `speech.tts.close` khi tắt. LiveKit: `worker.py` gọi `bundle.tts.close()` khi cuộc gọi kết thúc (mỗi job một bundle). Test `test_close_reaches_primary_and_fallback`, `test_close_still_closes_fallback_when_primary_close_fails`, `test_close_skips_provider_without_close` |
| Giữ nguyên trần tổng và phân loại lỗi | Deadline `timeout_s`, 429/5xx/timeout → `TTSUnavailable`, 4xx → `TTSRejected`, 200 mà trả JSON → `bad_response`: code không đổi, các test cũ trong `test_vbee.py` vẫn pass. `test_client_survives_errors_and_closes_once`: sau lỗi 503, câu sau vẫn dùng cùng client |
| Số đo trước/sau trên EC2 | Bảng trên; script `scripts/tts_probe.py` |

## Server Vbee giữ kết nối rảnh bao lâu

Đo từ máy local (`--reps 0 --idle 5,15,30,60`, client giữ 3600 s để chỉ server quyết định): cả 4 mốc đều **dùng lại** được kết nối cũ. Vậy server giữ kết nối rảnh ≥ 60 s, và `keepalive_s = 30` của client nằm dưới mức đó. Nếu có lúc client gửi đúng khi server vừa đóng kết nối thì lỗi thành `connection_failed` → gateway chuyển ElevenLabs cho câu đó.

## File liên quan

- `src/inference/tts/providers/vbee.py`: client dùng chung, `_default_client`, `close()`.
- `src/inference/tts/config.py`, `config/tts.yaml`: `keepalive_s` / `VBEE_KEEPALIVE_S`.
- `src/inference/tts/gateway.py`: `TTSGateway.close()`.
- `src/speech/bundle.py`: `SpeechSynthesizer.close()`.
- `src/callbot/transports/livekit/worker.py`: đóng TTS khi job kết thúc.
- `tests/inference/tts/providers/test_vbee.py`, `tests/inference/tts/test_gateway_fallback.py`.
- `scripts/tts_probe.py` (mới): so cách cũ và cách mới, đo thời gian server giữ kết nối rảnh.

## Quy trình xác minh

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/inference/tts -q
python -m ruff check src tests scripts/tts_probe.py
python -m ruff format --check src tests scripts/tts_probe.py
python scripts/tts_probe.py --kinds ngan --reps 8 --dry-run   # chỉ in số ký tự quota sẽ tốn
```

Đo trên EC2 (image không có `scripts/`, đẩy file qua stdin):

```powershell
scp -i $env:USERPROFILE\.ssh\vmec-bot.pem scripts\tts_probe.py ubuntu@vmec-callbot.tech:/opt/callbot/
```
```bash
cd /opt/callbot
docker compose --env-file .env --env-file image.env exec -T bot python - --kinds ngan --reps 8 < tts_probe.py | tee probe-2909.txt
```

## Kết quả xác minh cục bộ (2026-09-30)

| Command | Kết quả |
| --- | --- |
| `python -m pytest tests/inference/tts tests/speech/test_asr_tts_gateway.py tests/transports/http/test_calls.py` | Pass (184 passed; bỏ 2 test resample cần `soxr`) |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests scripts/tts_probe.py` | Pass. `scripts/audio_smoke.py` và `scripts/tts_bench_set.py` chưa format từ trước, không thuộc task này |
| `python -m pytest -q` (với `PYTHONUTF8=1`) | 3537 passed, 18 failed. 17 lỗi do máy local thiếu `soxr` (đã ghi ở `tts-utterance-fidelity.md`). 1 lỗi `tests/speech/test_pipeline_asr_lag.py::test_slow_asr_does_not_stall_vad_and_turn_waits_for_final` (STT, fail cả 3 lần chạy lại). Test này không import file nào task này sửa, cần báo Việt |

## Ghi chú

- **Đo từ local không dùng được:** mạng Việt Nam lúc đo chậm chung (GET Google ~0,8–1 s), bắt tay tới Vbee 0,5–1,7 s, 4/12 request ReadTimeout. Chỉ dùng số local cho phần "server giữ kết nối rảnh".
- **Chưa làm `httpx.AsyncClient` dùng chung** (bước 2 của plan): để cho task stream 30/09. Client async phải đóng bằng `await` và gắn với event loop của worker LiveKit, nên làm cùng lúc với `synthesize_stream` sẽ dùng nó.
- **ElevenLabs (dự phòng) không đổi:** adapter dùng WebSocket, mỗi câu một phiên WebSocket nên không gom kết nối kiểu httpx được.
- **Sau khi deploy:** chạy lại `python scripts/audio_smoke.py` từ local để kiểm hồi quy (audio_url, WAV, không lượt nào chuyển ElevenLabs), như T2 28/09.
- **Plan cần sửa:** mục Hiện trạng ghi "mỗi câu mở mới, mất ~300–400 ms". Trên EC2 thực tế chỉ ~9 ms.

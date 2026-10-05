# Evidence: TTS — Vbee phát giọng theo luồng (30/09, tuần 3)

## Mục tiêu

Trên đường LiveKit (Đường B), Vbee chưa có `synthesize_stream` nên `SpeechSynthesizer` gọi `synthesize` trong thread: chờ Vbee trả đủ cả câu rồi mới đẩy một khối PCM cho `CallBridge` phát. Khi khách nói chen, cũng không có cách nào đóng request đang chạy tới Vbee.

Task này thêm vào `VbeeTTS`:
- `synthesize_stream(text)`: phát từng chunk ngay khi Vbee trả về;
- `cancel()`: dừng stream và đóng hẳn request khi khách nói chen.

Client async dùng chung (chuyển từ task 29/09) và đóng khi job LiveKit kết thúc.

Kế hoạch: `docs/plans/tts-w3-w6.md`, mục T4 30/09 "Đường B — Vbee phát giọng theo luồng". Làm ngày 02/10, trễ 2 ngày so với plan.

## Kết luận

**Code xong:** stream, cancel, client async dùng chung, đóng kết nối khi job kết thúc. 26 test mới; cả suite pass (3742 passed lúc xong task).

**Hành vi của Vbee trên EC2** (trace bản main, chưa có stream, bảng ở mục "Số đo trên EC2"): Vbee gửi audio dần, byte đầu về trước khi sinh xong cả câu. Đây là điều kiện để stream có tác dụng.

**Số đo trên prod sau khi deploy** (05/10, image `97e139c`; trước: 02/10, image `9344380`). Bộ benchmark `scripts/bench/`, chi tiết ở [benchmark-streaming-truoc-sau.md](benchmark-streaming-truoc-sau.md):
- Tại `SpeechSynthesizer`: câu 234 ký tự TTFA 1063 → 268 ms; câu 113 ký tự 576 → 445 ms; câu 45 ký tự không đổi (242 → 250 ms). TTS total không đổi, Stall 0.
- Cuộc gọi LiveKit (2 cuộc trước, 2 cuộc sau): TTFA các lượt 885–992 ms → 553–744 ms. Khoảng từ byte đầu của Vbee tới lúc nghe tiếng giảm từ 324–403 ms xuống 117–136 ms.
- Câu chào chưa nhanh hơn (848 / 1066 → 1232 / 1029 ms) vì byte đầu của Vbee cho câu chào về chậm hơn ở cả hai lần sau; chưa rõ nguyên nhân, theo dõi bằng trace tuần 4.
- Đường A không đổi (TTS total 749 → 708 ms). Không lỗi, không fallback.

Cách đo ở [latency-benchmark.md](../reference/latency-benchmark.md).

**Giá trị của task với Đường B:**
- bot phát được chunk đầu ngay khi Vbee gửi, không chờ sinh xong cả câu (các lượt LiveKit: TTFA 885–992 → 553–744 ms);
- `cancel()` đóng hẳn request tới Vbee khi khách nói chen (barge-in, Phụ lục B.2), không để request chạy ngầm;
- đường Vbee đồng bộ với ElevenLabs/OpenAI: cả ba đều có `synthesize_stream` + `cancel`, `CallBridge` không phải xử lý riêng.

**Đường A (HTTP chấm điểm) không đổi:** vẫn gom cả câu.

## Số đo trên EC2 (2026-10-02)

**1. Trace prod của một smoke test.** Chạy `python scripts/audio_smoke.py --appointment apt_00427` (1 cuộc gọi `mode=audio`, 4 câu bot, ~400 ký tự quota), rồi `scripts/tts_trace_report.py --rows` đọc span `speech.tts.synthesize` của Đường A. Image `9344380` (chưa có code stream), giọng `hn_female_ngochuyen_full_48k-fhg`.

| Câu | Ký tự | TTFA Vbee (ms) | TTS total (ms) | TTS total − TTFA (ms) | TTFA / TTS total |
|---|---|---|---|---|---|
| 1 | 112 | 584 | 908 | 324 | 64% |
| 2 | 110 | 490 | 763 | 273 | 64% |
| 3 | 110 | 534 | 720 | 186 | 74% |
| 4 | 51 | 260 | 302 | 42 | 86% |

Trên EC2, Vbee cùng vùng AWS nên phần truyền gần như bằng 0. Vì vậy khoảng "TTS total − TTFA" là thời gian Vbee còn đang sinh sau khi đã gửi byte đầu.

**2. Benchmark "trước", phần TTS** ([benchmark-streaming-truoc-sau.md](benchmark-streaming-truoc-sau.md)). Ba câu cố định, mỗi câu 3 lần. Bản chưa stream nên TTFA = TTS total.

| Câu | Ký tự | TTS total p50 (min–max) ms | RTF |
|---|---|---|---|
| ngắn | 45 | 242 (185–249) | 11,2 |
| vừa | 113 | 576 (355–605) | 12,4 |
| dài | 234 | 1063 (1009–1122) | 13,4 |

**Nhận xét:**
- **TTS total tăng theo độ dài câu**, khoảng 4–5 ms mỗi ký tự: ~0,25 s với câu 45 ký tự, ~0,6–0,8 s với câu ~110 ký tự, ~1,06 s với câu 234 ký tự.
- **Đường A chờ cả câu**, nên TTS chiếm phần đáng kể của mỗi lượt. Trace benchmark "trước": Turn p50 1345 ms, trong đó TTS total 749 ms. Nhận định ban đầu "TTS ~0,2 s, không phải nút thắt" chỉ đúng với câu ngắn.
- **RTF 11–13:** Vbee sinh nhanh hơn tốc độ phát hơn 10 lần, nên khi stream không bị giật.
- **Không dùng `ttfa_ms` của span LiveKit trên image cũ làm số "trước" của Đường B.** Với Vbee chưa stream, span ghi `ttfa_ms` là byte đầu của Vbee, dù bot phải chờ đủ câu mới phát. Nghĩa là span ghi sớm hơn lúc khách thực sự nghe. Sau nhánh này, gateway đo đúng lúc chunk đầu được đưa sang phát.
- **Số mẫu còn ít.** Đủ thấy xu hướng, chưa đủ p95. p95 sẽ lấy từ trace các cuộc gọi tuần 4.

## Kết quả chạy thật ở local (2026-10-02, mạng VN) — chỉ dùng để kiểm code stream

Lần chạy này xác nhận code phát đúng từng chunk và ghép byte lẻ đúng. **Không dùng số thời gian ở đây cho latency**: độ trễ mạng VN che mất thời gian sinh của Vbee. Nhận định ban đầu rút ra từ lần chạy này ("Vbee gửi khi đã sinh xong cả câu") không đúng trên EC2, xem mục Số đo trên EC2.

```text
python scripts/tts_say.py "Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, ngày 14 tháng 10, tại Vinmec Times City ạ." --provider vbee --stream --out temp/tts/stream.wav
```

Giọng `hn_female_ngochuyen_full_48k-fhg`, câu 113 ký tự (tốn 113 ký tự quota), PCM 8 kHz. Script tạo client mới nên lần này có bắt tay TCP + TLS từ VN (260–440 ms theo evidence 29/09).

| Chỉ số | Giá trị |
|---|---|
| Số chunk | 52 |
| Chunk đầu | 1424 ms |
| Chunk cuối (về hết) | 1588 ms |
| Khoảng từ chunk đầu tới chunk cuối | 164 ms |
| Thời lượng audio | 7166 ms (114.656 byte) |

Các đợt chunk về theo thời gian (ms kể từ lúc gửi):

| Đợt | Thời điểm | Số chunk |
|---|---|---|
| 1 | 1424–1426 | 4 |
| 2 | 1473–1477 | 13 |
| 3 | 1532–1535 | 26 |
| 4 | 1586–1587 | 9 |

Cỡ chunk khớp với ghi chú trong plan: Vbee hay cắt **4090 B rồi 6 B**, có lúc **4088 B rồi 8 B**, cùng vài chunk lẻ (3774, 40, 282, 1438 B). Phần ghép byte lẻ đã xử lý được các trường hợp này. File WAV ghép lại dài đúng 7166 ms.

**So với các lần đo trước:**
- 18/09 (bake-off, ADR-002): byte đầu 4,3–5,7 s cho mọi độ dài câu.
- Nay từ VN: 1,4 s, gồm cả bắt tay.
- 29/09 trên EC2: câu ngắn có byte đầu ~200 ms.

Số đo 26/09 trong plan ("Vbee stream theo vế câu, byte đầu 230–700 ms") khớp với số EC2: TTFA Vbee ~260 ms (51 ký tự) đến ~530 ms (110 ký tự).

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| `synthesize_stream` yield từng chunk ngay khi về, request giống `synthesize` | `VbeeTTS.synthesize_stream` (`src/inference/tts/providers/vbee.py`): `async with client.stream(...)` → `aiter_bytes()` → `yield`. Test `test_stream_yields_chunks_in_order_with_same_request_as_sync` |
| Dùng `httpx.AsyncClient` chung, keepalive theo `VBEE_KEEPALIVE_S`, đóng bằng `aclose()` khi job kết thúc | Client tạo ở lần stream đầu (`_default_async_client`, cùng `_limits()` với client sync), nên đường HTTP không mở thêm client. `VbeeTTS.aclose()` → `TTSGateway.aclose()` → `SpeechSynthesizer.aclose()`. `worker.py` gọi `await bundle.tts.aclose()` khi job kết thúc. Test `test_streams_share_one_async_client_and_aclose_closes_both`, `test_sync_only_use_never_opens_async_client`, `test_default_async_client_keeps_idle_connection_for_configured_time`, `test_aclose_prefers_async_close_and_reaches_fallback`, `test_aclose_still_closes_fallback_when_primary_fails` |
| Chunk lẻ byte ghép đúng, chỉ yield số byte chẵn | Giữ byte lẻ (`carry`) ghép vào chunk sau; byte lẻ cuối luồng bị bỏ như `synthesize`. Test `test_stream_carries_odd_byte_into_next_chunk`, `test_stream_drops_trailing_odd_byte` |
| Lỗi HTTP ra đúng lớp, giữ trần tổng thời gian | Dùng chung `_check_response` với `synthesize`: 429/5xx/timeout → `TTSUnavailable`; 4xx → `TTSRejected`; 200 mà trả JSON → `bad_response`; không có audio → `no_audio`; text rỗng / > 300 ký tự bị từ chối, không gửi request. Test `test_stream_http_status_is_classified`, `test_stream_bad_body_is_unavailable`, `test_stream_network_errors_are_unavailable`, `test_stream_rejects_bad_text_without_request` |
| Trần tổng không cắt câu dài đang phát | Trần `timeout_s` (3 s) chỉ cộng **thời gian chờ Vbee**, không cộng lúc `CallBridge` đang giữ generator. Bên phát kéo chunk theo nhịp audio thật (`capture_frame` chờ hàng đợi phát), nên nếu đo theo đồng hồ thì câu nào dài hơn 3 s audio cũng bị cắt giữa chừng. Test `test_stream_deadline_ignores_time_spent_playing`, `test_stream_deadline_counts_time_waiting_for_vbee` |
| `cancel()` đóng hẳn request, không còn chunk nào sau đó | `cancel()` đặt cờ và `await response.aclose()`. Lỗi đọc sinh ra do chính `cancel()` đóng response được coi là dừng chủ động: không ném lỗi, nên không kích hoạt fallback. Test `test_cancel_between_chunks_stops_stream_and_closes_request`, `test_cancel_while_waiting_for_vbee_ends_stream_without_error`, `test_cancel_before_first_chunk_yields_nothing`, `test_next_stream_after_cancel_plays_normally` |
| Cả chuỗi `SpeechSynthesizer` → Vbee chạy stream | `test_vbee_stream_reaches_synthesizer_chunk_by_chunk_and_cancel_closes_it` (`tests/speech/test_asr_tts_gateway.py`): nhận đủ 3 chunk riêng thay vì 1 khối; `cancel()` và `aclose()` tới được Vbee |
| Thử với Vbee thật, in thời điểm từng chunk | `scripts/tts_say.py --stream`; kết quả ở bảng trên |

**Kiểm `cancel()` với httpx thật:** unit test dùng `MockTransport`, không có socket, nên đã chạy thêm với một server local stream chậm (script tạm, không commit). Kết quả:
- `response.aclose()` gọi từ task khác xong trong ~2 ms;
- task đang đọc nhận `httpx.ReadError`;
- server thấy `ConnectionResetError`, tức request bị đóng thật;
- client vẫn gửi request sau bình thường.

Stream giả `_HeldStream` trong test mô phỏng đúng hành vi này.

## File liên quan

- `src/inference/tts/providers/vbee.py`: `synthesize_stream`, `cancel`, `aclose`, client async; tách `_check_length`, `_check_response`, `_connection_failed`, `_no_audio` để hai đường dùng chung.
- `src/inference/tts/gateway.py`: `TTSGateway.aclose()`.
- `src/speech/bundle.py`: `SpeechSynthesizer.aclose()`.
- `src/callbot/transports/livekit/worker.py`: `await bundle.tts.aclose()` khi job kết thúc.
- `scripts/tts_say.py`: cờ `--stream`.
- `tests/inference/tts/providers/test_vbee.py`, `tests/inference/tts/test_gateway_fallback.py`, `tests/speech/test_asr_tts_gateway.py`.

## Luồng hiện tại (Đường B)

Sau task 01/10, stream đi qua gateway, có fallback ([tts-stream-fallback.md](tts-stream-fallback.md)):

```text
CallBridge._speak(text)
  -> SpeechSynthesizer.synthesize_stream(text)
  -> TTSGateway.synthesize_stream: Vbee lỗi trước chunk đầu -> ElevenLabs đọc đúng câu đó
  -> VbeeTTS.synthesize_stream: POST /v1/tts (mode=sync, pcm 8 kHz) qua AsyncClient chung
       -> mỗi chunk HTTP: ghép byte lẻ -> yield PCM16
  -> CallBridge cắt frame 20 ms -> AudioSource.capture_frame (nhịp phát thật)

Khách nói chen:
  InterruptionController -> CallBridge.cancel() -> SpeechSynthesizer.cancel() -> TTSGateway.cancel()
    -> VbeeTTS.cancel(): đặt cờ + response.aclose()  (request tới Vbee đóng ngay)
    -> AudioSource.clear_queue() + hủy task đang phát

Job kết thúc: worker -> tracer.close -> await bundle.tts.aclose() (client stream + sync) -> clinic.close
```

Đường A (HTTP chấm điểm) **không đổi**: vẫn `TTSGateway.synthesize`, gom cả câu, có fallback ElevenLabs.

## Quy trình xác minh

```powershell
$env:PYTHONUTF8 = "1"
python -m pytest tests/inference/tts tests/speech/test_asr_tts_gateway.py -q
python -m ruff check src tests scripts/tts_say.py
python -m ruff format --check src/inference/tts src/speech/bundle.py src/callbot/transports/livekit/worker.py tests/inference/tts tests/speech/test_asr_tts_gateway.py scripts/tts_say.py
```

Thử với Vbee thật (tốn số ký tự của câu):

```powershell
python scripts/tts_say.py "<câu>" --provider vbee --stream --out temp/tts/stream.wav
```

Muốn thử script mà không tốn quota: trỏ `VBEE_ENDPOINT` vào một server local trả PCM chunked, và đặt `VBEE_API_TOKEN` / `VBEE_APP_ID` giả. Lần chạy như vậy ngày 02/10: 5 chunk 4090 / 6 / 4096 / 4095 / 3000 B ra 4090 / 6 / 4096 / 4094 / 3000 B, byte lẻ được ghép đúng.

## Kết quả xác minh cục bộ (2026-10-02)

| Command | Kết quả |
| --- | --- |
| `python -m pytest tests/inference/tts -q` | Pass (96 passed) |
| `python -m pytest tests/inference/tts/providers/test_vbee.py` × 10 lần liên tiếp | Pass cả 10 lần (36 passed). Kiểm các test có đo thời gian không chập chờn |
| `python -m ruff check src tests scripts/tts_say.py` | Pass |
| `python -m ruff format --check` (các file trong task) | Pass |
| `python -m pytest -q` (với `PYTHONUTF8=1`) | Pass (3742 passed, 19 skipped) |

Chạy `pytest` trên Windows mà không đặt `PYTHONUTF8=1` thì `tests/test_compose_speech_config.py` lỗi đọc file (cp1252). Lỗi này do môi trường, không do code.

## Ghi chú

- **Fallback và observability trên stream:** task này để stream gọi thẳng provider, nên tạm thời mất fallback và span LiveKit thiếu `voice`. Cả hai đã xử lý ở task 01/10 ([tts-stream-fallback.md](tts-stream-fallback.md)). Hai task merge cùng nhau trong nhánh `feature/tts-w3-vbee-streaming`.
- **Số đo trước / sau:** dùng bộ benchmark `scripts/bench/` ([benchmark-streaming-truoc-sau.md](benchmark-streaming-truoc-sau.md)). Đã đo "sau" ngày 05/10.
- **p95 và câu dài thật:** lấy từ trace các cuộc gọi tuần 4 (06/10, diễn tập 09/10). Trace nằm trong container và mất khi deploy, nên đọc bằng `scripts/tts_trace_report.py` trước khi deploy, hoặc thêm volume cho `/app/traces` (việc của người làm observability).
- **Hướng giảm tiếp, chưa làm:** tách `utterance` thành từng câu nhỏ (theo dấu chấm).
  - Đường B: TTFA chỉ còn bằng thời gian sinh câu đầu tiên.
  - Đường A: sinh các câu **song song** rồi nối lại, TTS total ≈ câu dài nhất thay vì cộng dồn.
  - Điều kiện: giữ nguyên nội dung (§4.1.3) và nghe kiểm chỗ nối (khoảng lặng, ngữ điệu).
  - Cần chốt với PM vì đổi cách gọi TTS trên đường chấm điểm.

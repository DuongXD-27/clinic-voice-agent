# Task TTS tuần 3 → tuần 6 (28/09 – 24/10)

**Owner:** Hưng (TTS) · phối hợp Việt (STT) và Hoàn (Engine) · **Viết ngày:** 27/09/2026 · **Cập nhật:** 01/10/2026
**Nguồn:** `tailieu/callbot-contract-vi.md` (AIHR-PC-001 rev 1.1) là căn cứ chính. PRD v1.6 và Master plan được ghi rõ ở cột *Căn cứ* khi dùng tới.

**Quy ước cột *Căn cứ*:** `MUST` = contract bắt buộc · `§5` = ảnh hưởng điểm · `Phụ lục B` = contract khuyến nghị · `MP` = Master plan · `SP` = mục tiêu sản phẩm (luồng streaming hoàn chỉnh).

---

## 1. Hai đường phải làm song song

| | A. Đường chấm HTTP | B. Luồng streaming (LiveKit → điện thoại) |
|---|---|---|
| Ai dùng | Harness của mentor (team không tự chạy được) | Cuộc gọi thật: web LiveKit bây giờ, điện thoại ở cuộc gọi live tuần 6 |
| Luồng | `/turn` → STT → Engine → `utterance` → TTS → file WAV → `audio_url` | Mic → STT stream + VAD → Engine → TTS stream → phát ra loa, ngắt được khi khách nói chen |
| TTS cần | Tổng thời gian thấp, file sẵn sàng trước response, đọc đúng `utterance` | Âm đầu tiên nhanh, phát liên tục, dừng ngay khi bị ngắt, có fallback trên stream |
| Căn cứ | Listing 1–2, §4.1.2, §4.1.3, §5, §5.3, §5.4 | §1.3.1, §1.3.2, §6.2, §6.5, Phụ lục B.2 (media loop, barge-in 4 thao tác) |

**Một core, hai đường (§1.3.2):** TTS trên đường streaming dùng chung module và gateway với HTTP. Không viết logic hội thoại riêng cho điện thoại.

## 2. Contract nói gì về TTS

| Điều khoản | Nội dung | Hệ quả cho TTS |
|---|---|---|
| Listing 1 | `mode=audio` **từ tuần 3**; `audio_url` null ở chế độ text | Từ 28/09 mọi response HTTP phải có `audio_url` |
| §4.1.2 · §5.3 | ≤ 8 s mỗi lượt, tính đến khi **tải xong `audio_url`**; audio sẵn sàng ngay khi response trả về | TTS + fallback + ghi file phải nằm gọn trong 8 s |
| §4.1.3 | Audio đọc **đúng `utterance`**: không thêm, không bớt, không đổi nghĩa. Lấy mẫu ở review tuần 6; sai lệch có hệ thống bị xử như **mock đã sửa**, tức hỏng mọi lần chấm | Không sửa câu trước TTS; không bao giờ phát audio của câu khác thay cho `utterance`. Áp dụng cho **cả hai đường** |
| §5 · §5.4 | p95 cấp lượt + chi phí (token + âm thanh) mỗi phiên = 15% điểm; format báo cáo công bố trên kênh chương trình | Đo p95 và chi phí TTS |
| Bảng 1 | Vào bộ test: Identity, Confirm, No-answer (tuần 2) · Cancel, Transfer (tuần 3) · Reschedule (tuần 4) · Booking (tuần 5) | Kiểm câu thoại mỗi kịch bản trước tuần nó được chấm |
| §1.3.1 · §1.3.3 | Tuần 6 PHẢI có một cuộc gọi live (đạt/không đạt); chỉ gọi người đã đồng ý | Luồng B phải chạy được trên điện thoại thật |
| Phụ lục B.2 | Barge-in gồm 4 thao tác: **dừng phát TTS**, ngắt sinh của model, giữ partial turn, reset trạng thái lượt. Gọi số +84 thì test ở tuần 5 | TTS chịu thao tác 1 và cung cấp dữ liệu cho thao tác 3 |

## 3. Hiện trạng (27/09)

| Phần | Đã có | Chưa có |
|---|---|---|
| TTS trên HTTP | Vbee chính + ElevenLabs dự phòng trong gateway; WAV 8 kHz ghi xong trước response; đọc nguyên `utterance`; **audio mode trên prod đã verify 28/09 (PASS, tổng lớn nhất 3,79 s / 8 s)** | ~~Dùng chung kết nối Vbee~~ (xong 29/09; trên EC2 bắt tay chỉ ~9 ms, không phải ~300–400 ms như ước tính từ mạng VN); số chi phí/phiên |
| TTS trên LiveKit | `CallBridge` phát TTS theo chunk và gọi `cancel()` khi bị ngắt; xoá hàng đợi phát; **Vbee có `synthesize_stream` / `cancel()`, stream đi qua gateway có fallback ElevenLabs (xong)** | Báo Engine phần câu đã phát khi bị ngắt / lỗi giữa câu (07/10) |
| STT (Việt) | STT stream + VAD, `InterruptionController`, chống bot tự nghe mình (SNR) | — |
| Engine (Hoàn) | Core dùng chung cho HTTP và LiveKit | Giữ partial turn theo phần bot đã nói (P-03) |
| Vbee | Trên EC2 (trace 02/10): ~51 ký tự byte đầu 260 ms / xong 302 ms; ~110 ký tự byte đầu ~530 ms / xong ~760 ms (~6–8 ms/ký tự). Gửi dần, byte đầu khi đã sinh ~70% thời gian câu | Chưa có số câu > 150 ký tự và p95 (lấy từ trace tuần 4) |

---

## 4. Task theo tuần

Mỗi task gồm:
- **Gửi PM:** 1–2 câu tóm tắt để dán vào sheet hoặc daily.
- **Nội dung:** các bước làm cụ thể (file, cách làm, cách test).
- **Xong khi:** điều kiện để tick Done.
- **Căn cứ**, **Đầu ra** và **Nhánh** git.

### Nhánh git

Gộp task theo vùng code / loại đầu ra, không theo ngày: mỗi tuần một nhánh cho Đường A (test, đo, evidence) và một nhánh cho Đường B (code streaming); phần code lớn tách riêng. Tên theo quy ước `<loại>/tts-w<tuần>-<chủ-đề>` với prefix repo đang dùng (`feature/`, `fix/`, `docs/`); không ghi ngày trong tên vì một nhánh kéo dài 2–3 ngày. Tạo nhánh từ `main` mới nhất; trong nhánh vẫn commit và viết evidence theo từng task (vd. `test(tts): 29/09 kiểm utterance fidelity 5 kịch bản`).

| Nhánh | Gộp task | PR trước |
|---|---|---|
| `feature/tts-w3-vbee-streaming` | 29/09 dùng chung kết nối Vbee · 30/09 Vbee stream + `cancel()` · 01/10 fallback trên stream | 01/10 |
| `feature/tts-w3-grading-path` | 29/09 kiểm audio đọc đúng lời bot · 01/10 chi phí/phiên · 02/10 Gate W3 | 02/10 |
| `feature/p01-livekit-sip` | 05/10 P-01: cấu hình LiveKit SIP + softphone (dời từ 29/09) | 06/10 |
| `feature/tts-w4-livekit-vbee` | 05/10 chốt phối hợp STT / Engine / TTS · 06/10 cuộc gọi LiveKit chạy Vbee | 06/10 |
| `feature/tts-w4-playback-control` | 07/10 bot im khi khách nói chen · 08/10 chuyển máy và cúp máy | 08/10 |
| `docs/tts-w4-gate` | 05/10 kiểm câu Reschedule · 09/10 diễn tập #1 · 10/10 Gate W4 | 10/10 |
| `feature/tts-w5-phone-audio` | 13/10 giọng nói trên điện thoại thật (chỉ khi phải sửa code, vd. μ-law / resample) | 13/10 |
| `docs/tts-w5-freeze-gate` | 12/10 kiểm câu Booking · 14/10 audit · 15/10 freeze + runbook · 16/10 Gate W5 | 16/10 |
| `fix/tts-<lỗi>` | Mỗi lỗi từ diễn tập / dự phòng tuần 6 một nhánh nhỏ (vd. `fix/tts-cancel-leak`) | khi sửa xong |
| `docs/tts-w6-handover` | 23–24/10 bàn giao | 24/10 |

### Tuần 3 (28/09 – 02/10): đường chấm ổn định, bắt đầu stream Vbee

#### T2 28/09 · Đường A — Xác nhận audio mode trên prod ✅ Đã xong

> Kết quả: PASS, tổng lớn nhất 3,79 s so với trần 8 s, không lượt nào phải fallback. Evidence: `docs/evidence/tts-audio-mode-prod.md`, script `scripts/audio_smoke.py` (chưa commit).

**Gửi PM:** Verify audio mode trên production từ ngày harness chuyển sang chấm audio: mỗi turn đều có audio, audio sẵn sàng ngay khi response trả về và tổng latency (kể cả thời gian tải audio) không vượt 8 s. Đồng thời xác nhận config Vbee primary + ElevenLabs fallback, set timeout để trường hợp phải fallback vẫn nằm trong budget.

**Nội dung:**
1. **Kiểm tra config trên EC2.** Mở `/opt/callbot/.env`, cần có:
   - `TTS_PROVIDER=vbee`, `TTS_FALLBACK_PROVIDER=elevenlabs`
   - `VBEE_API_TOKEN`, `VBEE_APP_ID`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`

   Thêm `ELEVENLABS_TIMEOUT_S=3`: trường hợp xấu nhất Vbee 3 s + ElevenLabs 3 s = 6 s, còn khoảng 2 s cho STT, Engine và tải file. Để mặc định 4 s thì lên 7 s, quá sát 8 s.
2. **Khởi động lại và kiểm tra config thật trong container.** Chạy `docker compose --env-file .env --env-file image.env up -d`. Lệnh compose nào cũng phải có đủ hai `--env-file`, kể cả `logs`/`exec`. Log INFO của app không được in (uvicorn không cấu hình logging), nên `logs bot | grep TTS` luôn rỗng; thay vào đó chạy `SpeechSettings()` + `create_tts_gateway` bằng `exec bot python -c ...` (lệnh đầy đủ ở `docs/evidence/tts-audio-mode-prod.md`). Phải thấy `vbee` / `elevenlabs`. Nếu thiếu key thì app không khởi động, đây là hành vi cố ý.
3. **Tự gọi thử giống harness.** Header `Authorization: Bearer <BOT_API_KEYS>`.
   - `POST /v1/calls` với `mode=audio`, sau đó 3–4 lượt `POST /v1/calls/{id}/turn`. Lượt người gọi phải gửi `audio_url` (`text` bị từ chối với `422 TEXT_NOT_ALLOWED`): sinh clip bằng TTS, upload qua `PUT /demo-api/audio/{call_id}/{turn}.wav`.
   - Mỗi lượt đo: thời gian response, thời gian tải `audio_url`, tổng.
   - Kiểm tra file WAV mở được, đúng 8 kHz mono.
4. **Kiểm chế độ text.** Gọi lại một cuộc với `mode=text` → `audio_url` phải là `null`.
5. **Viết script.** Gom bước 3 thành `scripts/audio_smoke.py` (in bảng thời gian) để các ngày sau chạy lại được.

**Xong khi:** config trong container đúng provider (Vbee + ElevenLabs); mọi lượt có `audio_url` tải được; tổng mỗi lượt < 8 s; `mode=text` trả `null`.
**Căn cứ:** Listing 1–2, §4.1.2, §5.3 · **Đầu ra:** bảng thời gian từng lượt + `scripts/audio_smoke.py` · **Nhánh:** `restructure-tts` (đã xong)

#### T3 29/09 · Đường A — Kiểm audio đọc đúng lời bot

**Gửi PM:** Kiểm tra utterance fidelity cho 5 scenario đang được chấm (Identity, Confirm, No-answer, Cancel, Transfer): audio phải khớp đúng nội dung utterance, không thêm, bớt hay đổi nghĩa. Bổ sung test tự động để chặn mọi thay đổi text trước TTS, vì sai lệch có tính hệ thống sẽ bị xử như sửa mock khi chương trình lấy mẫu ở tuần 6.

**Nội dung:**
1. **Test tự động** trong `tests/transports/http/`:
   - Dùng TTS giả, ghi lại text nhận được.
   - Assert text gửi TTS **đúng bằng** `utterance` trong response, cho cả `/v1/calls` và `/turn`.
   - Đây là test chặn mọi thay đổi sau này vô tình sửa câu trước khi đọc.
2. **Liệt kê câu.** Lấy toàn bộ câu trong `src/callbot/engine/dialogue/templates.py` của 5 kịch bản: Identity, Confirm, No-answer (cả 3 câu nhắc im lặng), Cancel, Transfer.
   - Câu có phần động (ngày giờ, khoa) thì điền bằng dữ liệu mẫu trong Clinic Mock (pt_3401–3410).
3. **Sinh audio và nghe.** Chạy `python scripts/tts_say.py "<câu>" --provider vbee` cho từng câu. Nghe và ghi vào bảng: câu · đọc đúng/sai · ghi chú (sai chữ nào, ngắt nghỉ lạ).
4. **Kiểm độ dài câu.** Tính độ dài lớn nhất của từng câu khi đã điền dữ liệu. Vbee từ chối câu > 300 ký tự (`MAX_TEXT_CHARS`), gateway sẽ chuyển ElevenLabs.
   - Câu nào có thể vượt 300 thì ghi lại và sinh thử bằng ElevenLabs.
5. **Câu Vbee đọc sai:** báo Hoàn đổi câu chữ trong template (vd. viết lại cho dễ đọc). **Không** sửa câu ở lớp TTS, vì như vậy audio sẽ khác `utterance`.

**Xong khi:** test "text gửi TTS = utterance" pass; 100% câu của 5 kịch bản đã nghe và ghi kết quả; không câu nào vượt 300 ký tự mà không có fallback.
**Căn cứ:** §4.1.3, Bảng 1 · **Đầu ra:** test + bảng câu đã nghe (đưa vào evidence Gate W3) · **Nhánh:** `feature/tts-w3-grading-path`

#### T3 29/09 · Đường A+B — Giảm độ trễ TTS ✅ Đã xong

> Kết quả: đã dùng chung kết nối, test pass. Trên EC2 gần như không giảm độ trễ: bắt tay TCP + TLS tới Vbee chỉ ~9 ms, first_byte trung vị 207 → 194 ms (trong mức dao động), p95 không đổi. Vẫn giữ thay đổi (rủi ro thấp, nền cho stream 30/09), nhưng không báo là cải thiện latency. `AsyncClient` dùng chung chuyển sang task 30/09. Evidence: `docs/evidence/tts-vbee-connection-reuse.md`, script `scripts/tts_probe.py` (đã xoá 02/10, thay bằng bộ benchmark `scripts/bench/`).

**Gửi PM:** Tối ưu latency TTS bằng cách reuse connection tới Vbee thay vì mở connection mới cho mỗi câu, bỏ được phần handshake lặp lại ở mỗi turn. Benchmark trước/sau trên EC2 để có số đo cho tiêu chí latency.

**Nội dung:**
1. **Dùng chung kết nối.** Trong `src/inference/tts/providers/vbee.py`, hiện mỗi câu tạo `httpx.Client()` mới (`with self._client_factory() as client`), nên câu nào cũng bắt tay TCP + TLS lại từ đầu.
   - Chuyển thành một `httpx.Client` tạo một lần trong `__init__` và dùng lại (httpx.Client an toàn khi nhiều thread gọi).
   - Thêm `close()`, gọi khi app tắt.
2. **Chuẩn bị cho async.** Tạo sẵn một `httpx.AsyncClient` dùng chung cho `synthesize_stream` (task 30/09).
3. **Giữ nguyên hành vi.** Vẫn giữ trần tổng `timeout_s` (deadline) và cách phân loại lỗi như cũ.
4. **Unit test** bằng `httpx.MockTransport`: nhiều câu liên tiếp chỉ dùng một client; lỗi 429/5xx/timeout vẫn ra đúng lớp lỗi.
5. **Đo trên EC2** bằng script đo byte (bản đo 26/09 nằm ở scratchpad của phiên chat, cần chép vào `scripts/tts_probe.py` trước khi mất): so kết nối mới mỗi câu với kết nối dùng lại, 3 loại câu (ngắn / vừa / dài).

**Xong khi:** test pass; số đo trên EC2 cho thấy giảm thời gian tới byte đầu so với trước.
**Căn cứ:** §5 (p95), §6.5 · **Đầu ra:** bảng số trước/sau · **Nhánh:** `feature/tts-w3-vbee-streaming`

#### T3 29/09 · Đường B — P-01 Chuẩn bị telephony ➜ dời sang T2 05/10

> **Dời ngày (01/10).** Phần tìm hiểu nhà cung cấp đã xong 29/09 ([telephony-provider-research-2026-09-29.md](../reference/telephony-provider-research-2026-09-29.md)). Phần còn lại đang chờ PM: pháp nhân, ngân sách, và **tự host LiveKit SIP hay dùng LiveKit Cloud** (§9 của file research). Dời phần setup sang 05/10, xem task cùng tên ở tuần 4. Các task TTS tuần 3–4 chạy trên web demo LiveKit nên không bị chặn.
>
> Vẫn làm trong tuần 3 (việc nhỏ, không phụ thuộc lựa chọn hạ tầng):
> - Gửi bộ câu hỏi chung cho nhà cung cấp (mục 8.4 file research), vì thời gian chờ trả lời là phần chậm nhất.
> - Nhờ PM chốt các câu ở §9 file research trước 05/10, nhất là câu 4 (tự host hay Cloud).

#### T4 30/09 · Đường B — Vbee phát giọng theo luồng ✅ Đã xong 

> **Kết quả** ([evidence](../evidence/tts-vbee-streaming.md)): `synthesize_stream` + `cancel()` + `AsyncClient` chung + `aclose()` khi job kết thúc; 26 test mới, cả suite pass. Trần 3 s chỉ tính thời gian chờ Vbee (không tính lúc đang phát, nếu không câu dài > 3 s audio bị cắt). Trace EC2 (02/10, bản main) xác nhận Vbee gửi audio dần, byte đầu về trước khi sinh xong câu. Benchmark "sau" trên prod (05/10, [chi tiết](../evidence/benchmark-streaming-truoc-sau.md)): câu 234 ký tự TTFA 1063 → 268 ms; các lượt LiveKit TTFA 885–992 → 553–744 ms; câu chào chưa nhanh hơn (byte đầu Vbee chậm, theo dõi tuần 4); Đường A không đổi. Kèm `cancel()` đóng request khi nói chen. (Số đo local hôm trước bị mạng VN che, không dùng.) Fallback trên stream đã bổ sung ở task 01/10.

**Gửi PM:** Implement streaming cho Vbee: phát audio theo từng chunk ngay khi provider sinh ra thay vì chờ đọc xong cả câu, giúp giảm thời gian tới âm thanh đầu tiên trên cuộc gọi realtime. Hỗ trợ cancel request để dừng ngay khi user barge-in.

**Nội dung:**
1. **Hàm stream.** Thêm `async def synthesize_stream(text) -> AsyncIterator[bytes]` vào `VbeeTTS`:
   - Dùng một `httpx.AsyncClient` chung (chuyển từ task 29/09), `keepalive_expiry` theo `VBEE_KEEPALIVE_S`; đóng bằng `aclose()` khi job LiveKit kết thúc (`worker.py` đã gọi `bundle.tts.close()`).
   - Gọi `async_client.stream("POST", endpoint, json=payload)`, đọc `aiter_raw()`, `yield` từng chunk ngay khi về.
   - Vbee trả chunk lẻ byte (vd. 4090 B rồi 6 B): giữ byte lẻ lại ghép vào chunk sau, chỉ `yield` số byte chẵn (PCM16).
   - Giữ trần tổng thời gian và cách phân loại lỗi giống `synthesize`: 429/5xx/timeout → `TTSUnavailable`; 4xx → `TTSRejected`; 200 nhưng trả JSON → `TTSUnavailable`.
2. **Hàm hủy.** Thêm `async def cancel()`: đặt cờ hủy và `await response.aclose()` để **đóng hẳn request** đang chạy.
3. **Unit test** bằng stream giả:
   - chunk về đúng thứ tự;
   - chunk lẻ byte được ghép đúng;
   - lỗi HTTP ra đúng lớp;
   - gọi `cancel()` giữa chừng thì không còn chunk nào sau đó.
4. **Thử với Vbee thật:** thêm cờ `--stream` cho `scripts/tts_say.py`, in thời điểm từng chunk về.

**Xong khi:** test pass; chạy thật thấy chunk đầu về trước khi sinh xong cả câu.
**Căn cứ:** SP, §6.5 · **Đầu ra:** code + test · **Nhánh:** `feature/tts-w3-vbee-streaming`

#### T5 01/10 · Đường B — Dự phòng khi Vbee lỗi trên cuộc gọi thời gian thực ✅ Đã xong (02/10)

> **Kết quả** ([evidence](../evidence/tts-stream-fallback.md)): `TTSGateway.synthesize_stream` + `cancel()`; `SpeechSynthesizer` đi qua gateway. Vbee lỗi trước chunk đầu → ElevenLabs đọc đúng câu đó; lỗi giữa câu → dừng êm (không ném lỗi để không cắt cả cuộc gọi), ghi `error_code`; cả hai lỗi → ném lỗi như cũ. Span LiveKit có lại `voice` / `fallback_used`. 16 test mới, cả suite pass; kiểm thêm với httpx thật + server giả (503, rớt giữa câu). Còn lại: báo Engine phần câu đã phát và cho `CallBridge` đọc `error_code` → làm cùng 07/10.

**Gửi PM:** Bổ sung fallback cho streaming path: khi Vbee lỗi hoặc timeout, hệ thống tự failover sang ElevenLabs cho đúng câu đang đọc, user không bị im lặng hay nghe sai câu. Nếu lỗi xảy ra khi đã phát được một phần thì dừng lại, không đọc lặp từ đầu.

**Nội dung:**
1. **Vấn đề hiện tại.** `SpeechSynthesizer.synthesize_stream` trong `src/speech/bundle.py` gọi thẳng provider (`getattr(provider, "synthesize_stream")`), bỏ qua gateway, nên stream **không có fallback**.
2. **Gateway.** Thêm `TTSGateway.synthesize_stream(text)` trong `src/inference/tts/gateway.py`:
   - Provider chính lỗi **trước chunk đầu tiên** → ghi log (provider, loại lỗi, mã; không ghi text) → stream bằng provider dự phòng **đúng câu đó**.
   - Lỗi **sau khi đã phát** một phần → dừng, ghi log, **không** đọc lại từ đầu, vì đọc lại sẽ lặp câu và audio khác `utterance`.
   - Thêm `TTSGateway.cancel()` → gọi `cancel()` của provider đang chạy.
3. **Bundle.** Sửa `SpeechSynthesizer.synthesize_stream` và `cancel` để đi qua gateway.
4. **Sample rate.** Hai provider phải cùng sample rate trên stream (Vbee 8000, ElevenLabs `pcm_8000` = 8000). Khác nhau thì resample trước khi `yield`.
   - **Observability:** stream qua gateway phải điền `last_stream_result` (`provider_actual`, `voice`, `fallback_used`) để span `speech.tts.synthesize` của LiveKit có `voice` và tính được `tts_cost` (từ 02/10 đang thiếu, xem evidence stream).
5. **Unit test:** Vbee lỗi trước chunk đầu → nhận audio ElevenLabs; Vbee lỗi giữa chừng → dừng, không có audio ElevenLabs; cả hai lỗi → ném lỗi, `CallBridge` xử lý như hiện nay.

**Xong khi:** test fallback trên stream pass; test cũ của gateway (HTTP) vẫn pass.
**Căn cứ:** SP, §4.1.3 · **Đầu ra:** code + test · **Nhánh:** `feature/tts-w3-vbee-streaming`

#### T5 01/10 · Đường A — Chi phí giọng nói mỗi cuộc gọi

**Gửi PM:** Tính cost per session của TTS theo từng scenario, dựa trên số ký tự mỗi cuộc gọi và đơn giá của Vbee (cộng phần fallback sang ElevenLabs). Số liệu dùng cho tiêu chí latency + cost và trình bày theo format chương trình công bố.

**Nội dung:**
1. **Số ký tự mỗi cuộc gọi.** Chạy các kịch bản đang có eval (`scripts/*_eval.py` hoặc regression local trên `clinic_mock_sim`) với một TTS đếm ký tự. Ghi tổng ký tự TTS mỗi cuộc gọi theo kịch bản: Confirm, Cancel, Transfer, No-answer, Reschedule, Booking.
2. **Đơn giá.** Vbee theo gói đang dùng (ký tự/tháng ÷ giá gói); ElevenLabs Flash theo bảng giá niêm yết (chỉ tính phần fallback; tỉ lệ fallback đếm từ log WARNING `chuyển sang` trên prod, log INFO không được in).
3. **Công thức.** USD/phiên = ký tự × đơn giá Vbee + ký tự fallback × đơn giá ElevenLabs. Ghi thêm USD/1.000 cuộc gọi.
4. **Format.** Xem format báo cáo chi phí chương trình đã công bố trên kênh chưa (§5.4). Có rồi thì trình bày theo đó; chưa có thì ghi vào mục 7 để hỏi.

**Xong khi:** có bảng USD/phiên theo từng kịch bản, ghi rõ nguồn đơn giá.
**Căn cứ:** §5, §5.4, Phụ lục B · **Đầu ra:** bảng USD/phiên · **Nhánh:** `feature/tts-w3-grading-path`

#### T6 02/10 · Đường A — Gate W3

**Gửi PM:** C

**Nội dung:** viết `docs/evidence/tts-gate-w3.md` theo `TEMPLATE.md`, gồm:
- config đang chạy trên prod (kiểm trong container, xem evidence 28/09);
- bảng thời gian từng lượt (28/09) và số trước/sau khi dùng chung kết nối (29/09);
- test "text gửi TTS = utterance" + bảng câu đã nghe của 5 kịch bản;
- test đường lỗi: Vbee lỗi → ElevenLabs; cả hai lỗi → `utterance` vẫn trả, `audio_url = null`;
- bảng chi phí/phiên;
- tiến độ stream Vbee (30/09 – 01/10).

**Xong khi:** file evidence đủ các mục trên, có link test và số liệu.
**Căn cứ:** MP (Gate W3) · **Đầu ra:** `tts-gate-w3.md` · **Nhánh:** `feature/tts-w3-grading-path`

### Tuần 4 (05/10 – 10/10): nối streaming end-to-end với STT và Engine

#### T2 05/10 · Đường B — Chốt phối hợp STT / Engine / TTS

**Gửi PM:** Chốt interface realtime giữa STT (Việt), Engine (Hoàn) và TTS: các event khi bot bắt đầu nói, phát xong hoặc bị ngắt. Phân vai rõ 4 thao tác barge-in (dừng phát TTS, dừng generation, giữ partial turn, reset turn) để ba phần không chờ nhau khi tích hợp.

**Nội dung:**
1. **Sự kiện TTS phát ra** (mỗi sự kiện kèm `call_id`, số lượt, thời điểm):
   - `tts_started`, `first_audio` (chunk đầu được phát), `done`;
   - `cancelled`, kèm **phần text đã phát** (ước tính theo số giây audio đã phát trên tổng số giây).
2. **Ghi lại hiện trạng trong code.** `CallBridge._speak` đã báo `on_bot_speaking_changed` và `on_bot_started_speaking` cho STT; `CallBridge.cancel()` đã xoá hàng đợi phát.
3. **Đề xuất phân vai 4 thao tác barge-in** (chốt lại trong buổi họp):
   1. Dừng phát TTS — Hưng
   2. Ngắt sinh của model — Hoàn
   3. Giữ partial turn (dùng phần text đã phát) — Hoàn
   4. Reset trạng thái lượt — Việt / Hoàn
4. **Ghi kết quả** vào `docs/reference/` (một bảng interface + phân vai).

**Xong khi:** Việt và Hoàn đồng ý bảng interface và phân vai.
**Căn cứ:** §1.3.2, Phụ lục B.2, MP · **Đầu ra:** bảng interface + phân vai · **Nhánh:** `feature/tts-w4-livekit-vbee`

#### T2 05/10 · Đường A — Kiểm câu thoại đổi lịch

**Gửi PM:** Kiểm tra utterance fidelity cho scenario Reschedule trước khi vào test set tuần 4: các câu offer slot, đọc lại lịch mới và xác nhận đổi lịch. Câu nào đọc sai hoặc quá dài sẽ báo Engine chỉnh template.

**Nội dung:** làm giống task 29/09 cho kịch bản Reschedule:
- câu đề xuất khung giờ ("Dạ, hiện còn khung 1 là …, khung 2 là …");
- câu báo ngày đã kín;
- câu đọc lại lịch mới, câu xác nhận đã đổi.

Điền dữ liệu mẫu với số khung tối đa mỗi lượt (R-25: tối đa 2 khung) để có câu dài nhất, rồi kiểm ≤ 300 ký tự. Nghe và ghi bảng.

**Xong khi:** 100% câu Reschedule đã nghe và ghi kết quả; câu đọc sai đã báo Hoàn.
**Căn cứ:** §4.1.3, Bảng 1 (tuần 4) · **Đầu ra:** bảng câu đã nghe · **Nhánh:** `docs/tts-w4-gate`

#### T2 05/10 · Đường B — P-01 Chuẩn bị telephony (dời từ 29/09)

**Gửi PM:** P-01 Chuẩn bị telephony cho live call tuần 6: setup LiveKit SIP (inbound trunk + dispatch rule) và softphone làm phương án dự phòng, test call vào bot qua SIP. Song song chốt carrier/SIP trunk, đăng ký số và duyệt chi phí, mục tiêu gọi được từ điện thoại thật trước 13/10.

**Nội dung:**
1. **Đầu vào.** PM đã chốt (hoặc đang chờ) các câu ở §9 [file research](../reference/telephony-provider-research-2026-09-29.md): pháp nhân, carrier đường nhanh, tự host hay LiveKit Cloud, ngân sách COST-005. Chưa chốt tự host hay Cloud thì vẫn setup trên LiveKit Cloud: nếu sau chuyển sang tự host chỉ phải chạy lại cùng file JSON.
2. **Cấu hình LiveKit SIP phía mình.** Lưu toàn bộ JSON và lệnh `lk` vào repo để chạy lại được trên server LiveKit khác:
   - Dispatch rule **chung cho mọi trunk** (không gắn `trunk_ids`): mỗi cuộc gọi một room riêng, đưa worker vào theo `agent_name`. Trunk carrier thêm sau tự đi theo rule này.
   - Inbound trunk riêng cho softphone (username/password), giữ lâu dài làm phương án dự phòng.
3. **Softphone gọi thử.** Ép codec G.711 cho giống audio carrier. Kiểm: worker nhận cuộc gọi, audio hai chiều, ASR nghe được audio 8 kHz (ghi transcript cho Việt đánh giá), bot cúp máy đúng.
4. **Khi carrier xong (mục tiêu trước 13/10):** thêm inbound trunk của carrier (số + IP hoặc digest), gọi thử từ điện thoại thật.
5. **Trước 08/10** (task chuyển máy): hỏi carrier có hỗ trợ REFER không; ghi lại cách chuyển sang phương án dự phòng.
6. **Ưu tiên demo inbound** (khách gọi vào đặt lịch): chỉ cần một số nhận cuộc gọi, tránh hạn chế khi gọi ra số di động +84 (Phụ lục B.2, NĐ 330/2026 Điều 38).

**Xong khi:** softphone gọi được vào bot qua LiveKit SIP, audio hai chiều; cấu hình SIP đã lưu trong repo; đã ghi tình trạng carrier và khả năng transfer. Gọi từ điện thoại thật chuyển sang tiêu chí của task 13/10.
**Căn cứ:** Task gốc P-01 (B), §1.3.1, §1.3.4, Phụ lục B.2 · **Đầu ra:** cấu hình LiveKit SIP, ghi chú test call softphone, tình trạng carrier · **Nhánh:** `feature/p01-livekit-sip`

#### T3 06/10 · Đường B — Cuộc gọi thời gian thực chạy giọng Vbee

**Gửi PM:** Tích hợp Vbee streaming vào LiveKit và chạy end-to-end STT → Engine → TTS trên web demo. Đo latency từng stage (end-of-turn, response, first audio, playout) để biết phần nào đang chậm nhất trong luồng realtime.

**Nội dung:**
1. **Bật Vbee cho worker.** Đặt `TTS_PROVIDER=vbee`, `TTS_FALLBACK_PROVIDER=elevenlabs` cho LiveKit worker (worker dùng chung `SpeechSettings` với HTTP).
   - `AudioSource` sẽ được tạo ở 8000 Hz theo `stream_sample_rate` của Vbee.
2. **Gọi thử** qua trang demo LiveKit `/demo/livekit-demo.html`: chạy 1 cuộc Confirm và 1 cuộc Cancel.
3. **Đo 4 mốc mỗi lượt** (lấy từ trace/log): khách nói xong (STT chốt lượt) → Engine trả câu → TTS chunk đầu → frame đầu được phát. Tách thời gian STT / Engine / TTS.
4. **Kiểm cách chia chunk.** Không còn chuyện đẩy cả câu thành một frame lớn; câu dài phát liên tục, không đứt.

**Xong khi:** cuộc gọi LiveKit chạy Vbee end-to-end; có bảng thời gian 4 mốc.
**Căn cứ:** SP, Phụ lục B.2 · **Đầu ra:** bảng thời gian end-to-end · **Nhánh:** `feature/tts-w4-livekit-vbee`

#### T4 07/10 · Đường B — Bot im khi khách nói chen

**Gửi PM:** Barge-in phía TTS: khi user nói chen, bot dừng phát ngay, hủy request đang chạy tới provider và bỏ audio của turn cũ. Đồng thời báo cho Engine phần câu bot đã kịp nói để giữ đúng context cho turn tiếp theo.

**Nội dung:**
1. **Chuỗi hủy.** Khi `InterruptionController` xác nhận ngắt lời → `CallBridge.cancel()` → `SpeechSynthesizer.cancel()` → `TTSGateway.cancel()` → `VbeeTTS.cancel()` đóng request (đã làm 30/09 – 01/10). Kiểm tra cả chuỗi chạy đúng.
2. **Bỏ chunk cũ.** Chunk của lượt cũ về muộn thì bỏ, không phát: so số lượt của chunk với lượt hiện tại.
3. **Phần text đã phát.** Tính từ số byte đã `capture_frame` (÷ 16.000 byte/giây ở 8 kHz) so với tổng thời lượng dự kiến, quy ra phần text tương ứng. Gửi cho Engine qua sự kiện `cancelled` (đầu vào thao tác 3 của Hoàn).
4. **Test:**
   - TTS giả phát chậm, gọi hủy giữa chừng: không còn chunk nào được phát sau khi hủy; request đã đóng.
   - Ngắt lời 2 lần liên tiếp: không phát lẫn audio của lượt cũ.
5. **Đo** thời gian từ lúc xác nhận ngắt lời đến lúc hết tiếng (trên cuộc gọi LiveKit thật).

**Xong khi:** test pass; trên cuộc gọi thật bot im khi bị ngắt lời, Engine nhận được phần text đã phát.
**Căn cứ:** Phụ lục B.2, MP · **Đầu ra:** test + số ms từ ngắt đến im · **Nhánh:** `feature/tts-w4-playback-control`

#### T5 08/10 · Đường B — Chuyển máy và cúp máy

**Gửi PM:** Xử lý transfer và disconnect trên LiveKit: bot phát hết câu transfer rồi mới handoff sang nhân viên, không bị cắt giữa chừng. Khi user cúp máy, hệ thống dừng TTS stream, đóng request tới provider và cleanup resource.

**Nội dung:**
1. **Chuyển máy.** Câu chuyển máy phải phát hết (`wait_for_playout`) rồi mới bàn giao / kết thúc phiên.
   - `CallBridge` đang có timeout 20 s cho bước chờ này (`_PLAYOUT_TIMEOUT_S`); kiểm tra không bị cắt câu.
2. **Cúp máy.** Khách cúp máy khi bot đang nói → `aclose()` phải hủy stream TTS và **đóng request Vbee**, không để request chạy ngầm.
3. **Test:** chuyển máy giữa câu dài; cúp máy khi bot đang nói; cúp máy khi đang chờ Vbee trả chunk đầu.

**Xong khi:** 3 test pass; sau khi cúp máy không còn request Vbee treo.
**Căn cứ:** MP, §1.3.2 · **Đầu ra:** test chuyển máy / cúp máy · **Nhánh:** `feature/tts-w4-playback-control`

#### T6 09/10 · Đường B — Diễn tập #1

**Gửi PM:** Rehearsal #1 trên LiveKit cùng STT và Engine: chạy lần lượt các scenario end-to-end, ghi lại latency, số lần fallback, barge-in có dừng kịp không và câu đọc sai. Lỗi TTS nhỏ fix trong ngày, lỗi lớn đưa vào danh sách có owner.

**Nội dung:**
- Chạy lần lượt các kịch bản trên LiveKit: Identity, Confirm, Cancel, Transfer, Reschedule, No-answer (im lặng), và một lượt khách nói chen.
- Mỗi cuộc ghi: thời gian tới âm đầu từng lượt, số lần fallback, ngắt lời có dừng kịp không, câu đọc sai.
- Lỗi TTS: fix trong ngày nếu nhỏ, ghi lại nếu lớn.

**Xong khi:** mọi kịch bản chạy hết một lượt; danh sách lỗi có owner và trạng thái.
**Căn cứ:** MP · **Đầu ra:** danh sách lỗi · **Nhánh:** `docs/tts-w4-gate` (lỗi cần sửa code: `fix/tts-<lỗi>`)

#### T7 10/10 · Đường B — Gate W4

**Gửi PM:** Tổng hợp Gate W4 evidence cho TTS trên realtime path: streaming Vbee, fallback khi provider lỗi, barge-in và bảng latency end-to-end. Kèm kết quả rehearsal #1 và các lỗi đã fix.

**Nội dung:** viết `docs/evidence/tts-gate-w4.md`, gồm:
- test stream Vbee, fallback trên stream, hủy request;
- bảng thời gian end-to-end (06/10);
- số ms từ ngắt lời đến im (07/10);
- test chuyển máy / cúp máy (08/10);
- kết quả diễn tập #1 và lỗi đã fix.

**Xong khi:** file evidence đủ các mục trên.
**Căn cứ:** MP (Gate W4) · **Đầu ra:** `tts-gate-w4.md` · **Nhánh:** `docs/tts-w4-gate`

### Tuần 5 (12/10 – 16/10): điện thoại thật, Booking vào test, freeze

#### T2 12/10 · Đường A — Kiểm câu thoại đặt lịch

**Gửi PM:** Kiểm tra utterance fidelity cho scenario Booking inbound trước khi vào test set tuần 5: các câu hỏi nhu cầu, offer slot và xác nhận đặt lịch. Đồng thời đóng các lỗi TTS còn tồn từ rehearsal #1.

**Nội dung:** làm giống 29/09 cho Booking inbound:
- câu hỏi nhu cầu (khoa, thời gian);
- câu đề xuất khung giờ;
- câu đọc lại để xác nhận;
- câu báo đã đặt lịch;
- câu chuyển máy khi không tìm thấy hồ sơ.

Kiểm độ dài, nghe và ghi bảng. Xử lý nốt các lỗi TTS còn tồn từ diễn tập #1.

**Xong khi:** 100% câu Booking đã nghe; lỗi TTS từ diễn tập #1 đã đóng hoặc có kế hoạch.
**Căn cứ:** §4.1.3, Bảng 1 (tuần 5) · **Đầu ra:** bảng câu đã nghe · **Nhánh:** `docs/tts-w5-freeze-gate`

#### T3 13/10 · Đường B — Giọng nói trên điện thoại thật

**Gửi PM:** Chạy TTS trên đường điện thoại thật qua LiveKit SIP với carrier đã chuẩn bị ở P-01: audio nghe rõ qua điện thoại, barge-in hoạt động. Đây là bước chuẩn bị trực tiếp cho live call bắt buộc ở tuần 6, chỉ gọi tới người đã đồng ý.

**Nội dung:**
1. **Cách nối** theo carrier / SIP đã chuẩn bị ở task P-01 (05/10). Đi qua LiveKit SIP thì cuộc gọi vào phòng LiveKit, worker xử lý như cuộc gọi web; TTS không phải sửa gì thêm.
2. **Chọn kịch bản demo.** Phụ lục B.2 gợi ý demo kịch bản **khách gọi vào** (Booking) sẽ dễ hơn gọi đi số +84.
3. **Gọi thử** 2–3 cuộc: giọng nghe rõ qua điện thoại, không rè hay vỡ tiếng, ngắt lời hoạt động.
4. **Chỉ gọi** thành viên team hoặc người của chương trình đã đồng ý (§1.3.3).
5. **Phương án dự phòng.** Kiểm lại softphone SIP đã dựng ở P-01 vẫn gọi được vào trunk (Phụ lục B.2).

**Xong khi:** ít nhất 1 cuộc gọi điện thoại thật chạy trọn kịch bản, nghe rõ giọng bot.
**Căn cứ:** §1.3.1, §1.3.3, Phụ lục B.2 · **Đầu ra:** kết quả cuộc gọi thử · **Nhánh:** `feature/tts-w5-phone-audio` (chỉ khi phải sửa code)

#### T4 14/10 · Đường A+B — Diễn tập #2 và tự kiểm audio

**Gửi PM:** Rehearsal #2 trên điện thoại thật theo kịch bản demo đã chọn. Kết hợp self-audit utterance fidelity: lấy mẫu các cuộc gọi đã chạy và đối chiếu audio với utterance giống cách chương trình sẽ kiểm ở review tuần 6.

**Nội dung:**
1. **Diễn tập** trên điện thoại thật theo kịch bản demo đã chọn.
2. **Tự audit §4.1.3.** Chạy 10 cuộc gọi qua HTTP bằng `scripts/audio_smoke.py`, lưu lại `utterance` và file audio của từng lượt (trace không chứa text theo NFR-16 nên không lấy utterance từ trace). Nghe từng lượt, đối chiếu, ghi mọi chỗ thêm / bớt / đổi nghĩa.
3. **Có sai lệch** thì tìm nguyên nhân (câu template khó đọc hay lỗi provider) và sửa ngay. Sai lệch lặp lại có hệ thống là rủi ro hỏng mọi lần chấm.

**Xong khi:** diễn tập chạy trọn; bảng audit 10 cuộc gọi, 0 sai lệch nghĩa.
**Căn cứ:** §4.1.3, MP · **Đầu ra:** báo cáo audit · **Nhánh:** `docs/tts-w5-freeze-gate`

#### T5 15/10 · Đường A+B — Freeze và runbook

**Gửi PM:** Freeze TTS config (provider, voice, timeout, fallback) cho release candidate. Viết runbook vận hành để team tự xử lý được khi provider gặp sự cố: đổi provider, xử lý rate limit/quota, rollback.

**Nội dung:**
1. **Freeze.** Ghi lại provider, voice (`hn_female_ngochuyen_full_48k-fhg`), model ElevenLabs, các timeout. Từ sau hôm nay không đổi nữa.
2. **Runbook** `docs/reference/tts-runbook.md`:
   - danh sách biến môi trường TTS và ý nghĩa;
   - đổi provider bằng env (vd. chuyển ElevenLabs thành chính) và cách khởi động lại;
   - bảng triệu chứng → xử lý: 401/402 (key, gói), 429 (quota), 5xx / timeout (provider sập → fallback);
   - kiểm tra quota Vbee / ElevenLabs còn bao nhiêu;
   - rollback về image trước (CD giữ image cũ).
3. **Nhờ một người khác** trong team đọc runbook và làm thử một lần đổi provider.

**Xong khi:** config đã ghi và khoá; runbook có người khác làm theo được.
**Căn cứ:** §5 (25% vận hành, bàn giao), MP · **Đầu ra:** runbook · **Nhánh:** `docs/tts-w5-freeze-gate`

#### T6 16/10 · Đường A+B — Gate W5

**Gửi PM:** Tổng hợp Gate W5 evidence cuối cho TTS trên cả HTTP scoring path và realtime path, bao gồm kết quả điện thoại thật, audit utterance fidelity, config đã freeze và runbook.

**Nội dung:** evidence cuối gồm:
- tổng hợp Gate W3 + W4;
- kết quả kiểm câu Reschedule / Booking;
- cuộc gọi điện thoại thật (13/10);
- audit §4.1.3 (14/10);
- config đã freeze và runbook (15/10).

**Xong khi:** file evidence đủ các mục trên.
**Căn cứ:** MP (Gate W5) · **Đầu ra:** evidence cuối · **Nhánh:** `docs/tts-w5-freeze-gate`

### Tuần 6 (19/10 – 24/10)

#### 19–22/10 — Dự phòng

**Gửi PM:** Contingency sau Gate W5: chỉ hotfix các lỗi ưu tiên cao phát sinh, chạy lại regression liên quan sau mỗi lần sửa và không thay đổi config đã freeze.

**Nội dung:** chỉ sửa lỗi ưu tiên cao; mỗi lần sửa chạy lại test liên quan và `scripts/audio_smoke.py`; không đổi config đã freeze.
**Căn cứ:** MP · **Nhánh:** `fix/tts-<lỗi>` (mỗi lỗi một nhánh)

#### 21–22/10 — Cuộc gọi live

**Gửi PM:** Standby TTS cho live call bắt buộc: trước giờ gọi kiểm tra quota và health của Vbee/ElevenLabs, chạy smoke test; trong lúc gọi monitor log lỗi và fallback.

**Nội dung:** trước giờ gọi, kiểm tra quota Vbee / ElevenLabs, chạy `scripts/audio_smoke.py` và một cuộc gọi thử; trong lúc gọi theo dõi log TTS (lỗi, fallback).
**Căn cứ:** §1.3.1 · **Nhánh:** không cần (chỉ vận hành)

#### 23–24/10 — Bàn giao

**Gửi PM:** Handover TTS cho review tuần 6: finalize ADR-002 (lý do chọn Vbee, số đo thực tế, cost, giới hạn còn lại) và tài liệu bàn giao; chuẩn bị sẵn evidence utterance fidelity khi chương trình lấy mẫu.

**Nội dung:**
- ADR-002 bản cuối: số đo thật, lý do chọn Vbee, chi phí thực tế, giới hạn còn lại;
- phần TTS trong tài liệu bàn giao;
- gom các bảng kiểm §4.1.3 để sẵn khi chương trình lấy mẫu.

**Căn cứ:** §4.1.3, §5 (25%), Phụ lục B · **Nhánh:** `docs/tts-w6-handover`

---

## 5. Phụ thuộc

| Cần | Từ ai | Hạn |
|---|---|---|
| Output Guard chạy trước TTS (TTS chỉ đọc câu đã qua guard) | Hoàn | 01/10 |
| Interface sự kiện STT ↔ TTS (bot đang nói, khách nói chen) | Việt | 05/10 |
| Ngắt sinh của model + giữ partial turn (thao tác 2, 3 barge-in) | Hoàn | 07/10 |
| Chốt §9 file research telephony: pháp nhân, carrier, tự host hay LiveKit Cloud (P-01) | PM | 05/10 |
| Duyệt chi phí carrier / số điện thoại (P-01); Telnyx cần ~72 giờ kích hoạt nên trễ nhất 08/10 để kịp 13/10 | PM | 05/10 |

## 6. Không làm (trái hoặc không có căn cứ)

| Việc | Lý do |
|---|---|
| Phát câu "xin lỗi" từ cache khi TTS lỗi | Audio khác `utterance`, vi phạm §4.1.3 |
| Cache toàn bộ câu kịch bản demo | Dễ phát audio lệch `utterance` |
| Đặt ngưỡng ms tự nghĩ ra cho TTFA / barge-in | Contract không đặt; chỉ đo và báo số, ngưỡng do team chốt với PM |

## 7. Cần hỏi

| Câu hỏi | Vì sao | Hỏi ai |
|---|---|---|
| Format báo cáo chi phí mỗi phiên đã công bố chưa? | §5.4 | Kênh chương trình |
| Cả hai provider TTS lỗi thì `audio_url = null` ở `mode=audio` được chấm thế nào? | Contract không nói; §8.3 khuyến khích nêu điểm mơ hồ | Kênh chương trình |
| P-01 chưa có trên sheet: xác nhận Hưng làm owner và thêm dòng 05/10 (dời từ 29/09) | Task gốc giao P-01 cho B; §1.3.1 là cổng đạt/không đạt | PM |

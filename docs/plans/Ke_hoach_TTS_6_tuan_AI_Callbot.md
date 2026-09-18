# Kế hoạch TTS 6 tuần — AI Callbot

Sep 17, 2026 · Trạng thái: **chờ PM duyệt**

## 1. Mục tiêu và ràng buộc

TTS phải sẵn sàng trên đường chấm điểm **trước tuần 3** (28/9), vì contract chuyển mode sang audio từ tuần 3; 2 ngày còn lại của tuần 1 dùng để dựng MVP thô bằng API, các tuần sau eval và chọn provider dựa trên số đo thật.

Ràng buộc rút từ contract, ADR-002 và task sheet:

| Nguồn                  | Ràng buộc                                                                                                                                               | Hệ quả cho TTS                                                                                |
|------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| Contract §4.1.2, §5.3  | Mỗi lượt ≤ 8 s, tính từ lúc harness gửi /turn đến khi **tải xong audio_url**                                                                            | Ngân sách TTS + ghi file + phục vụ file ≈ 1,5–2 s; audio phải ghi xong trước khi trả response |
| Contract §4.1.3        | audio_url phải đọc trung thực utterance; chương trình lấy mẫu ở review tuần 6, sai lệch có hệ thống bị xử như sửa mock                                  | Không cắt/đổi câu; mọi chuẩn hoá số → chữ phải giữ nguyên nghĩa và có test                    |
| Contract §5, Phụ lục B | Latency + cost = 15% điểm; "kiểm tra chi phí STT/TTS ở tuần 2"                                                                                          | Tuần 2 phải có số đo P95 và chi phí/phiên thật                                                |
| Contract Phụ lục B.2   | Barge-in = 4 thao tác (dừng phát, ngắt sinh, giữ partial, reset lượt)                                                                                   | TTS cần streaming + cancel cho phần điện thoại tuần 5–6                                       |
| Contract §5.2          | Cuộc gọi thật tuần 6 là gate                                                                                                                            | TTS phải xuất được μ-law/PCM 8 kHz cho Phone Adapter                                          |
| ADR-002                | 3 ứng viên Vbee, ElevenLabs Flash v2.5, Azure AI Speech; trạng thái "chưa kiểm thử"                                                                     | Tuần 2 bake-off theo đúng 6 tiêu chí của ADR, cập nhật ADR thành "Accepted"                   |
| Task sheet             | S-02 TTS & audio response, S-03 ngân sách latency/cost, P-03/P-04 barge-in, R-01 Output Guard trước TTS                                                 | Kế hoạch này chi tiết hoá S-02 và phần TTS của S-03/P-03/P-04                                 |
| Code hiện có           | TTSProvider.synthesize(text) -\> AudioSegment, NullTTS, AudioArtifactStore lưu WAV 8 kHz tại audio/\<call_id\>/\<turn\>.wav, tts_provider mới có "none" | MVP chỉ cần thêm một provider vào interface có sẵn, không đụng core                           |

Giả định lịch: tuần 1 = 14–20/9, tuần 2 = 21–27/9, tuần 3 = 28/9–4/10, tuần 4 = 5–11/10, tuần 5 = 12–18/10, tuần 6 = 19–25/10.

## 2. Nguyên tắc triển khai

Dựng bằng API trước, chọn provider bằng số đo sau, và giữ interface TTSProvider ổn định để đổi provider chỉ là đổi config.

1.  **MVP thô = ElevenLabs Flash v2.5 qua WebSocket streaming** (eleven_flash_v2_5, output_format=pcm_8000), lấy được key trong ngày, gom chunk thành WAV cho đường HTTP và đo TTFA ngay từ tuần 1. Dự phòng: Azure AI Speech F0 nếu ElevenLabs free tier không đủ quota cho demo.

2.  **Mọi provider cùng một interface**: synthesize(text) -\> AudioSegment cho đường HTTP; stream(text) -\> AsyncIterator\[bytes\] có từ tuần 1 với ElevenLabs, tuần 4 thêm cancel() và chuẩn hoá cho các provider khác. Core, Output Guard và Phone Adapter không biết provider nào đang chạy.

3.  **Quyết định bằng eval lặp lại được**: một bộ câu test cố định + một script chạy cho mọi provider, kết quả ghi vào docs/evidence/. Không chọn theo số liệu vendor công bố (đúng tinh thần ADR tiêu chí 5).

4.  **Trung thực với utterance là bất biến**: chuẩn hoá văn bản trước TTS (ngày, giờ, số điện thoại, mã lịch) chỉ đổi cách đọc, không đổi nghĩa; mọi rule có unit test. Quan trọng hơn với Flash v2.5 vì model này không hỗ trợ apply_text_normalization=on (ADR-002 đã ghi điểm yếu đọc số).

5.  **Đo từ tuần 2, không đợi tuần 5**: mỗi turn ghi tts_provider, số ký tự, TTFA, thời gian synth, thời gian ghi file, chi phí ước tính vào trace (R-02).

6.  **Luôn có fallback**: provider phụ + cache câu cố định (chào, hỏi tên/DOB, chuyển máy) để không bao giờ trả audio_url rỗng khi đang ở mode audio.

## 3. Tổng quan 6 tuần

Hai mốc cứng: **audio mode chạy trên đường chấm từ 28/9** và **cuộc gọi thật có barge-in tuần 19–25/10**; mọi tuần khác phục vụ hai mốc này.

| Tuần | Ngày      | Chủ đề                  | Đầu ra chính                                                                                                                               | Task sheet             |
|------|-----------|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|------------------------|
| 1    | 17–19/9   | MVP thô bằng API        | ElevenLabsTTS (Flash v2.5, WebSocket streaming) cắm vào TTSProvider, /v1/calls và /turn trả audio_url nghe được trên local, có số TTFA thô | S-02                   |
| 2    | 21–27/9   | Eval & bake-off         | Bộ … câu test, script eval, số đo P50/P95 + chi phí/phiên cho 3 provider, ADR-002 cập nhật → chọn provider chính                           | S-03, ADR-002          |
| 3    | 28/9–4/10 | Lên đường chấm điểm     | Timeout/retry/fallback, cache câu cố định, serving audio ngoài mạng, trace per-turn, Output Guard trước TTS, deploy prod                   | S-02, S-03, R-01, R-03 |
| 4    | 5–11/10   | Streaming & barge-in    | stream() + cancel(), đo TTFA, VAD phát hiện người gọi nói chen khi bot đang phát, interface với Phone Adapter                              | P-03, P-04             |
| 5    | 12–18/10  | Điện thoại & chất lượng | TTS chạy trên cuộc gọi thật (μ-law 8 kHz), barge-in đủ 4 thao tác, từ điển phát âm, regression suite, báo cáo cost/latency cuối            | P-04, S-03             |
| 6    | 19–25/10  | Freeze & bàn giao       | Khoá provider/version, audit utterance vs audio 30 cuộc gọi, runbook, ADR-002 "Accepted", diễn tập                                         | R-05, R-06             |

Tuần 1–3 phục vụ đường HTTP chấm điểm; tuần 4–6 phục vụ đường điện thoại, không đụng lại code đã ổn định của đường chấm.

## 4. Tuần 1 (thứ 5–thứ 7, 17–19/9): MVP thô bằng API

Kết thúc thứ 7: gọi POST /v1/calls với mode: audio trên máy local nhận được audio_url mở ra nghe đúng câu chào; Không tối ưu, không eval; streaming có sẵn nhưng chỉ dùng để gom chunk và đo TTFA.

<table>
<colgroup>
<col style="width: 17%" />
<col style="width: 48%" />
<col style="width: 34%" />
</colgroup>
<thead>
<tr class="header">
<th>ID</th>
<th>Việc</th>
<th>Điều kiện hoàn thành</th>
</tr>
<tr class="odd">
<th>TTS-1.1</th>
<th><p><strong>Mở tài khoản ElevenLabs, chọn giọng tiếng Việt, kiểm tra hạn mức có đủ cho demo</strong></p>
<p>Chi tiết công việc:<br />
Tạo tài khoản ElevenLabs, lấy API key, chọn 1 voice tiếng Việt (hoặc voice đa ngôn ngữ) và ghi voice_id; kiểm tra quota free tier (10k ký tự/tháng) có đủ cho demo, không đủ thì nâng Starter</p></th>
<th>Key trong .env; gọi thử bằng curl endpoint /stream ra file tiếng Việt nghe được</th>
</tr>
<tr class="header">
<th>TTS-1.2</th>
<th><p><strong>Viết module kết nối Eleven Labs (Flash v2.5, streaming) theo interface TTS có sẵn của bot</strong></p>
<p>Chi tiết công việc:</p>
<p>Viết speech/tts/elevenlabs.py: class ElevenLabsTTS nối WebSocket /v1/text-to-speech/{voice_id}/stream-input với model_id=eleven_flash_v2_5, output_format=pcm_8000; stream(text) yield từng chunk PCM (decode base64), synthesize(text) gom chunk → AudioSegment 8 kHz; timeout 4 s; lỗi WS/HTTP → raise lỗi có tên</p></th>
<th>Unit test với WS mock; test tích hợp (skip nếu không có key) sinh được segment 8 kHz</th>
</tr>
<tr class="odd">
<th>TTS-1.3</th>
<th><p><strong>Thêm cấu hình để bật/tắt TTS bằng biến môi trường. Không ảnh hưởng chế độ text</strong></p>
<p>Chi tiết công việc:</p>
<p>Mở SpeechSettings.tts_provider thành Literal["none","elevenlabs"], thêm elevenlabs_api_key, elevenlabs_voice_id, elevenlabs_model (mặc định eleven_flash_v2_5); nối vào create_tts(); cập nhật .env.example</p></th>
<th>tts_provider=elevenlabs khởi tạo được app, none vẫn chạy như cũ</th>
</tr>
<tr class="header">
<th>TTS-1.4</th>
<th><p><strong>Nối TTS vào 2 endpoint chấm điểm khi ở chế độ audio (phối hợp A)</strong></p>
<p>Nối TTS vào response của /v1/calls và /turn khi mode == audio (phối hợp A, S-02): synth utterance → AudioArtifactStore.save() → gán audio_url; mode text giữ null</p></th>
<th>Response audio mode có audio_url dạng &lt;public_base_url&gt;/audio/&lt;call_id&gt;/&lt;turn&gt;.wav</th>
</tr>
<tr class="odd">
<th>TTS-1.5</th>
<th><p><strong>Đảm bảo file audio tải được ngay khi response khi trả về (đúng yêu cầu contract 5.3)</strong></p>
<p>Kiểm tra/thêm route tĩnh phục vụ audio_dir (nếu A chưa có), đảm bảo chunk cuối (isFinal) nhận xong và file ghi xong trước khi trả response</p></th>
<th>curl audio_url ngay sau response trả về 200 và WAV hợp lệ</th>
</tr>
<tr class="header">
<th>TTS-1.6</th>
<th><p><strong>Đo thời gian TTS thêm vào mỗi lượt, ghi nhận câu đọc sai</strong></p>
<p>Log thời gian: mở WS, <strong>TTFA</strong> (chunk đầu tiên), chunk cuối, ghi file, tổng; chạy 20 lượt liên tiếp lấy số thô; ghi chú câu nào đọc sai số/ngày (Flash v2.5 không chuẩn hoá số)</p></th>
<th>Bảng 20 lượt: P50/P95 TTFA và tổng thời gian thêm vào mỗi turn</th>
</tr>
<tr class="odd">
<th>TTS-1.7</th>
<th><p><strong>Demo 1 cuộc gọi audio cho team + PM</strong></p>
<p>Demo cho team + PM: 1 cuộc gọi outbound confirm ở mode audio, nghe 3–4 turn; ghi vào README mục "Bật audio mode"; liệt kê lỗi phát âm nghe thấy để đưa vào bộ eval tuần 2</p></th>
<th>Demo chạy được; danh sách lỗi phát âm ban đầu</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Ngoài phạm vi tuần 1: chuẩn hoá số → chữ, cache, fallback, cancel() giữa chừng, deploy. Streaming tuần 1 chỉ để gom chunk thành WAV và đo TTFA; chưa đẩy chunk ra điện thoại. Nếu WS stream-input gây khó trong ngày thứ 5, dùng tạm HTTP /stream (chunked) cùng model và format, giữ nguyên các task còn lại; nếu ElevenLabs không cấp key được, chuyển sang Azure F0 REST.

## 5. Tuần 2 (21–27/9): bộ eval, bake-off 3 provider, chi phí

Cuối tuần 2 ADR-002 có số đo thật cho cả 3 ứng viên và team chốt provider chính + provider dự phòng cho đường chấm điểm tuần 3.

| ID      | Việc                                                                                                                                                                                                                                        | Điều kiện hoàn thành                                                 |
|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| TTS-2.1 | Bộ test … câu lấy từ template hội thoại thật của bot (Dialogue Manager): câu chào, hỏi tên/DOB, đọc lại lịch (ngày, giờ, cơ sở), đề xuất slot, xác nhận huỷ, chuyển máy; có tên riêng 3 miền, tên khoa, số điện thoại, mã lịch hẹn, giờ 24h | File tests/data/tts_eval.jsonl (text, entity cần đọc đúng, loại câu) |
| TTS-2.2 | Lớp chuẩn hoá trước TTS speech/tts/normalize.py: ngày 14/10 → "mười bốn tháng mười", giờ 09:30 → "chín giờ ba mươi", số điện thoại đọc từng số, mã lịch đọc từng ký tự; bật/tắt theo provider                                               | Unit test mỗi rule; không đổi nghĩa utterance (§4.1.3)               |
| TTS-2.3 | Thêm adapter AzureTTS và VbeeTTS cùng interface với ElevenLabsTTS đã có từ tuần 1; Vbee cần mua gói (42 USD/năm theo ADR) hoặc xin trial                                                                                                    | 3 provider chạy được qua tts_provider=\<nêm\>                        |
| TTS-2.4 | Script scripts/tts_eval.py: với mỗi provider × 60 câu → synth, hạ 8 kHz, ghi: latency P50/P95, TTFA (nếu streaming), số ký tự, chi phí ước tính; round-trip qua ASR của team để tính CER + **entity exact match** (tên, ngày, giờ, số)      | Báo cáo docs/evidence/tts-bakeoff-w2.md tự sinh                      |
| TTS-2.5 | Nghe chấm thủ công: 3 người trong team chấm 20 câu khó nhất theo thang 1–5 (tự nhiên, đọc đúng entity, nghe rõ qua 8 kHz)                                                                                                                   | Điểm trung bình mỗi provider, liệt kê từ đọc sai                     |
| TTS-2.6 | Chi phí/phiên: đo số ký tự trung bình một cuộc gọi 7 kịch bản (từ harness run tuần 2) × đơn giá 3 provider; đưa vào S-03                                                                                                                    | Bảng USD/phiên và USD/1.000 cuộc gọi                                 |
| TTS-2.7 | Cập nhật ADR-002: ma trận 6 tiêu chí bằng số đo, đề xuất provider chính/dự phòng, review với PM thứ 6 26/9                                                                                                                                  | ADR-002 trạng thái "Đề xuất — đã kiểm thử", có quyết định            |

Ngưỡng chấp nhận để lên đường chấm: entity exact match ≥ 95% trên bộ 60 câu, P95 synth + ghi file ≤ 2 s với câu 200 ký tự, chi phí TTS ≤ 30% tổng chi phí/phiên.

## 6. Tuần 3 (28/9–4/10): audio mode lên đường chấm điểm

Harness chạy mode audio từ đầu tuần này, nên mục tiêu là không lượt nào vượt 8 s và không lượt nào thiếu audio_url vì TTS.

| ID      | Việc                                                                                                                                                                                                                               | Điều kiện hoàn thành                                                   |
|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| TTS-3.1 | Chuyển provider chính theo quyết định tuần 2; timeout TTS 2,5 s; retry 1 lần; quá timeout → provider dự phòng; cả hai lỗi → ghi trace và trả audio từ cache câu "xin lỗi, anh/chị vui lòng nhắc lại" chỉ khi Output Guard cho phép | Test giả lập provider chậm/lỗi; không response nào vượt 8 s            |
| TTS-3.2 | Cache câu cố định (chào, hỏi tên, hỏi DOB, chuyển máy, kết thúc) sinh sẵn lúc khởi động, key theo hash(text, voice, provider)                                                                                                      | Turn 0 không gọi TTS; đo giảm latency và chi phí                       |
| TTS-3.3 | Serving audio: kiểm tra tốc độ tải audio_url từ mạng ngoài (harness tải ngay, thời gian tải tính vào lượt); header Content-Length, Cache-Control; dọn file cũ sau 24 h                                                             | Tải WAV 8 kHz 10 s từ ngoài \< 300 ms                                  |
| TTS-3.4 | Đồng thời: harness có thể chạy nhiều cuộc gọi song song → client HTTP dùng chung, giới hạn concurrency, kiểm tra quota/429 của provider                                                                                            | Load test 10 cuộc gọi song song, P95 vẫn ≤ ngưỡng                      |
| TTS-3.5 | Trace per-turn (R-02, phối hợp A): tts_provider, tts_chars, tts_ms, tts_cost_usd, audio_bytes, fallback_used                                                                                                                       | Trường xuất hiện trong trace JSONL, đối chiếu được với kết quả harness |
| TTS-3.6 | Output Guard chạy trước TTS (R-01, A chủ trì): TTS chỉ nhận utterance đã qua guard; text chuẩn hoá không ghi đè utterance trả về                                                                                                   | Test: utterance trong response = text trước chuẩn hoá                  |
| TTS-3.7 | Deploy prod và smoke test (R-03, A chủ trì): secret TTS trong CI/CD, public_base_url đúng domain đã đăng ký, smoke gọi 1 cuộc audio và tải audio_url                                                                               | Smoke pass trên prod trước lần chấm đầu tiên của tuần 3                |
| TTS-3.8 | Theo dõi lần chấm đầu: lọc trace các lượt có tts_ms cao hoặc fallback, sửa trong tuần                                                                                                                                              | Báo cáo ngắn: P95 toàn lượt, tỷ lệ fallback, chi phí TTS/phiên thực tế |

## 7. Tuần 4 (5–11/10): streaming TTS, cancel và VAD cho barge-in

Đường điện thoại cần audio ra theo chunk và dừng được giữa chừng; tuần này làm PoC đo được, chưa nối vào cuộc gọi thật.

| ID      | Việc                                                                                                                                                                                                                                                | Điều kiện hoàn thành                                                                     |
|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| TTS-4.1 | Chốt interface với B (Phone Adapter, P-02/P-04): StreamingTTSProvider.stream(text) -\> AsyncIterator\[bytes\] (PCM 8 kHz hoặc μ-law, frame 20 ms) và cancel(); sự kiện tts_started, tts_chunk, tts_done, tts_cancelled                              | Interface + fixture giả để B phát triển song song                                        |
| TTS-4.2 | **Hoàn thiện streaming cho provider chính: ElevenLabs đã có stream() từ tuần 1 → chuyển sang multi-context WS để có cancel() theo context; nếu tuần 2 chọn Azure thì làm WebSocket v2 + stop API; đo TTFA** và thời gian từ cancel() đến chunk cuối | TTFA P95 \< 500 ms; cancel → không chunk mới sau 100 ms                                  |
| TTS-4.3 | Hỗ trợ sinh audio khi LLM đang stream token: cắt theo câu/dấu phẩy rồi đẩy sang TTS, giữ thứ tự chunk; đo tổng thời gian đến âm thanh đầu tiên so với cách đợi hết câu                                                                              | Số đo so sánh; bật/tắt bằng config                                                       |
| TTS-4.4 | VAD phát hiện người gọi nói chen khi bot đang phát: đánh giá VAD hiện có (RMS threshold) so với Silero VAD / webrtcvad trên audio 8 kHz có tiếng bot dội lại; chọn ngưỡng và thời gian xác nhận (ví dụ 200 ms tiếng nói liên tục)                   | Báo cáo false-trigger và độ trễ phát hiện trên 30 clip; quyết định VAD dùng cho barge-in |
| TTS-4.5 | Nối VAD → cancel() → thoát sự kiện cho core (P-03, A chủ trì): TTS ghi lại phần text đã phát (theo chunk đã gửi) để core giữ partial turn                                                                                                           | Demo local: phát câu dài, nói chen → dừng, core nhận spoken_prefix                       |
| TTS-4.6 | Cập nhật bộ eval: thêm TTFA và cancel latency cho mọi provider có streaming                                                                                                                                                                         | Báo cáo tts-streaming-w4.md                                                              |

VAD ở đây chỉ phục vụ barge-in trên đường điện thoại; VAD cho end-of-turn của STT thuộc ADR-001 và owner STT, hai bên dùng chung module speech/vad.

## 8. Tuần 5 (12–18/10): tích hợp điện thoại, tinh chỉnh phát âm, regression

Cuối tuần 5 bot nói được trên cuộc gọi thật qua Phone Adapter của B, ngắt lời được, và bộ eval TTS chạy trong CI.

| ID      | Việc                                                                                                                                                                 | Điều kiện hoàn thành                                                   |
|---------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| TTS-5.1 | Nối streaming TTS vào Phone Adapter (P-04, cùng B): output μ-law 8 kHz, jitter buffer nhỏ, phát câu chào ngay khi nhấc máy                                           | Cuộc gọi thật nghe rõ câu chào \< 1 s sau khi kết nối                  |
| TTS-5.2 | Barge-in end-to-end trên điện thoại, đủ 4 thao tác: dừng phát, ngắt sinh TTS/LLM, giữ partial, reset lượt; xử lý audio còn trong buffer của tổng đài (ADR-002 lưu ý) | 10 lần nói chen: bot im trong \< 300 ms, không lượt cũ ghi đè lượt mới |
| TTS-5.3 | Chống bot tự nghe mình: VAD bỏ qua khi đang phát nếu mức năng lượng khớp echo; phối hợp owner STT                                                                    | Không false barge-in trong 20 lượt bot nói                             |
| TTS-5.4 | Từ điển phát âm / SSML cho từ đọc sai phát hiện ở tuần 2–4 (tên khoa, tên bác sĩ, "Vinmec", mã lịch); chọn giọng cuối cùng, tốc độ đọc                               | Entity exact match ≥ 98% trên bộ eval                                  |
| TTS-5.5 | Regression suite: bộ eval chạy trong CI với provider chính (mỗi đêm hoặc khi đổi config), cảnh báo khi latency/EM tụt                                                | Job CI xanh, ngưỡng ghi trong tests/                                   |
| TTS-5.6 | Báo cáo cost/latency cuối cho S-03: P95 TTS, chi phí TTS/phiên từ trace prod tuần 3–5, so với ước tính tuần 2                                                        | Bảng trong docs/evidence/, số vào báo cáo baseline                     |
| TTS-5.7 | Test tải cuối trên prod: 20 cuộc gọi audio song song, xác nhận quota provider đủ cho lần chấm cuối                                                                   | Không 429, P95 toàn lượt \< 8 s                                        |

## 9. Tuần 6 (19–25/10): freeze, audit fidelity, diễn tập, bàn giao

Không đổi provider, giọng hay rule chuẩn hoá sau thứ 3 20/10; tuần này chỉ sửa lỗi nghiệm thu và chuẩn bị review.

| ID      | Việc                                                                                                                                                                                            | Điều kiện hoàn thành                                   |
|---------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| TTS-6.1 | Khoá cấu hình: provider, voice, model version, rule chuẩn hoá; ghi vào release note cùng R-06                                                                                                   | Config được tag, CI chặn thay đổi                      |
| TTS-6.2 | Audit §4.1.3: lấy ngẫu nhiên 30 cuộc gọi đã chấm, nghe đối chiếu audio với utterance từng turn, ghi sai lệch                                                                                    | 0 sai lệch nghĩa; báo cáo để trình ở review            |
| TTS-6.3 | Runbook TTS: xoay key, quota còn lại, cách đổi sang provider dự phòng bằng env, xử lý 429/503, dọn audio_dir                                                                                    | Runbook trong docs/, B (vận hành) đọc và thử lại được  |
| TTS-6.4 | ADR-002 → trạng thái "Accepted": ma trận số đo cuối, lý do chọn, chi phí thực tế, giới hạn còn lại                                                                                              | ADR ký bởi người ra quyết định                         |
| TTS-6.5 | Diễn tập cuộc gọi thật 2 lần trên bản release (cùng A/B, R-06): kiểm tra câu chào, barge-in, chuyển máy; có phương án dự phòng nếu provider TTS sập ngày demo (cache toàn bộ câu kịch bản demo) | Diễn tập pass; cache demo sẵn sàng                     |
| TTS-6.6 | Sửa lỗi nghiệm thu liên quan TTS (R-05) và chuẩn bị 3 slide cho review: quyết định provider, số đo, bài học                                                                                     | Lỗi ưu tiên cao đóng; slide nộp PM trước review 1 ngày |

## 10. Phụ thuộc và rủi ro

TTS phụ thuộc vào A ở ba điểm nối (response HTTP, Output Guard, trace) và vào B ở Phone Adapter; cần chốt interface sớm để không chờ nhau.

| Phụ thuộc                                                               | Cần từ ai           | Cần trước |
|-------------------------------------------------------------------------|---------------------|-----------|
| Điểm gọi TTS trong handler /v1/calls và /turn + route phục vụ audio_dir | A (F-02, S-02)      | 18/9      |
| Output Guard trả utterance cuối trước khi TTS                           | A (R-01)            | 30/9      |
| Trường trace per-turn                                                   | A (R-02)            | 30/9      |
| Secret TTS trong CI/CD, public_base_url prod                            | A (R-03)            | 28/9      |
| Interface audio ra / sự kiện barge-in của Phone Adapter                 | B (P-02, P-04)      | 6/10      |
| Cancel LLM và giữ partial turn trong core                               | A (P-03)            | 13/10     |
| VAD end-of-turn dùng chung module                                       | Owner STT (ADR-001) | 6/10      |

| Rủi ro                                                                                                             | Ảnh hưởng                                           | Giảm thiểu                                                                                                                                                    |
|--------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| ElevenLabs free tier hết quota (10k ký tự) giữa demo, hoặc không lấy được tài khoản Azure/Vbee cho bake-off tuần 2 | MVP trễ, bake-off thiếu ứng viên                    | Nâng ElevenLabs Starter (5 USD/tháng, 30k ký tự) ngay thứ 5 nếu cần; Azure F0 làm dự phòng; Vbee không có trial thì ghi "không đo được" trong ADR thay vì chờ |
| TTS đọc sai số/ngày → harness chấm như utterance sai (§4.1.3)                                                      | Mất điểm case, rủi ro bị coi là sai lệch hệ thống   | Lớp chuẩn hoá có test; entity exact match là ngưỡng chặn; audit tuần 6                                                                                        |
| Provider chậm/429 khi harness chạy song song                                                                       | Vượt 8 s, mất điểm latency                          | Timeout + fallback + cache câu cố định; load test tuần 3 và 5                                                                                                 |
| Thời gian tải audio_url tính vào lượt                                                                              | P95 tăng dù TTS nhanh                               | WAV 8 kHz mono, serving tĩnh, đo từ mạng ngoài tuần 3                                                                                                         |
| Streaming/cancel của provider chính không đạt (Vbee thiếu tài liệu)                                                | Barge-in yếu trên cuộc gọi thật                     | Cho phép đường điện thoại dùng provider khác đường HTTP nếu tuần 4 cho thấy cần                                                                               |
| Bảo mật: gửi tên/DOB bệnh nhân lên TTS hosted                                                                      | Vi phạm tiêu chí 6 ADR-002 nếu provider lưu dữ liệu | Ưu tiên provider không lưu text/audio (Azure công bố không retain); ghi trong ADR                                                                             |
| Việc phối hợp A/B trượt lịch                                                                                       | TTS xong nhưng không nối được                       | Fixture/fake theo interface để test độc lập; đưa ngày cần vào standup                                                                                         |

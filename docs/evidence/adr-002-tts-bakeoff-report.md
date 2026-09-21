# ADR-002 (bổ sung) — Kết quả kiểm thử Provider Text-to-Speech cho Voicebot Y tế Tiếng Việt

**Trạng thái:** Đề xuất — **đã kiểm thử 2/3 ứng viên** (bổ sung cho ADR-002 "Đề xuất, chưa kiểm thử" ngày 15-09-2026)
**Ngày:** 20-09-2026 (cập nhật 21-09: ElevenLabs đo đủ 6 tiêu chí bằng bộ đo chung)
**Người đo / soạn:** B (Hưng) · **Người ra quyết định:** Nguyễn Tuấn Dương · **Cần PM duyệt:** chọn provider chính + dự phòng cho audio mode tuần 3 (28/9)
**Dữ liệu gốc:** `ZeroTTS/report.md` + 5 CSV (Colab T4, 20/9); **bộ đo chung `scripts/tts_bench.py` → `docs/evidence/tts-bench/matrix.md`** (ElevenLabs 54 lần đo 20–21/9; ZeroTTS nhập từ Colab); phiếu nghe 3 người cho tiêu chí 1 & 4 — **đang chờ điền**

---

## 0. Tóm tắt cho PM (đọc 2 phút)

**Câu hỏi:** Dùng TTS nào để bot nói tiếng Việt trên đường chấm điểm (từ 28/9, mỗi lượt ≤ 8 s) và sau đó trên cuộc gọi thật (tuần 5–6, cần ngắt lời)?

**Đã đo thật 2 ứng viên** (Azure chưa đo — chưa có tài khoản):

| Ứng viên | Kết quả một dòng | Dùng được cho đường chấm 28/9? |
|---|---|---|
| **ElevenLabs Flash v2.5** | Đo đủ 27 câu × 2: **P95 tổng 0,88 s**, TTFA 0,54 s, streaming thật, 0 % đứt tiếng, dừng sau cancel ~0,15 s. Giọng Việt bản địa cần gói Starter **5 USD/tháng**; gói Free chỉ có giọng gốc tiếng Anh (đọc tiếng Việt được nhưng lơ lớ — chất lượng do 3 người nghe chấm, chưa có phiếu). | **Có về tốc độ** — chất lượng giọng Việt chấm sau khi nâng Starter |
| **ZeroTTS** (mã nguồn mở, tự host) | Giọng Việt tự nhiên, nghe thử đọc đúng tên/số/ngày/thuật ngữ, dữ liệu bệnh nhân **không rời hệ thống**. Nhưng sinh **chậm hơn nói 2,3 lần** kể cả trên GPU T4 (câu chào 8–20 s) → không phát liên tục được. | **Không** (tốc độ) |
| Azure AI Speech | Chưa đo. | — |

**Đề xuất:**
1. **Provider chính cho tuần 1–3: ElevenLabs Flash v2.5**, nâng gói **Starter (5 USD/tháng)** để dùng giọng Việt bản địa (đã chọn sẵn giọng "Trang" Bắc + 2 giọng dự phòng). Đây là chi phí duy nhất cần duyệt ngay. Ngay sau khi nâng, chạy lại bộ đo chung (10 phút) rồi 3 người nghe phiếu để chấm chất lượng giọng Việt.
2. **Dự phòng:** Azure AI Speech F0 (miễn phí 0,5 triệu ký tự/tháng) — cần 1 người mở tài khoản và đo bằng cùng notebook trong tuần 2.
3. **ZeroTTS:** loại khỏi đường chấm; ghi nhận làm **phương án dài hạn** cho bảo mật dữ liệu nếu sau này có máy chủ CPU mạnh và tác giả cải thiện tốc độ.

**Rủi ro chính nếu chọn ElevenLabs:** dữ liệu (tên, ngày sinh bệnh nhân trong câu bot nói) đi ra máy chủ nước ngoài — cần PM/pháp chế xác nhận chấp nhận được cho giai đoạn đồ án, kèm biện pháp giảm thiểu ở §6.

---

## 1. Bối cảnh (Context)

Giữ nguyên bối cảnh ADR-002: TTS chỉ chịu trách nhiệm *văn bản phản hồi → âm thanh*; trạng thái hội thoại, xác thực, nghiệp vụ nằm ở backend. Hai mốc cứng từ contract và kế hoạch TTS 6 tuần:

- **28/9 (tuần 3):** harness chuyển `mode: audio`; mỗi lượt ≤ 8 s tính đến khi harness **tải xong `audio_url`** (§4.1.2, §5.3). Ngân sách cho TTS + ghi file ≈ 1,5–2 s. Audio phải là bản đọc **trung thực** của `utterance` (§4.1.3).
- **19–25/10 (tuần 6):** cuộc gọi thật có barge-in (dừng phát, ngắt sinh, giữ partial, reset lượt — Phụ lục B.2); audio μ-law/PCM 8 kHz.

Tuần 1 đã hoàn thành phần tích hợp: interface `TTSProvider` chung, adapter `ElevenLabsTTS` (WebSocket `stream-input`), đổi provider bằng `TTS_PROVIDER` trong `.env`. Báo cáo này bổ sung **số đo thật** cho ADR-002, thay cho thông tin công bố của nhà cung cấp.

## 2. Tiêu chí lựa chọn (Selection Criteria)

Giữ nguyên 6 tiêu chí và thứ tự ưu tiên của ADR-002. Bổ sung **cách đo** và **ngưỡng** lấy từ kế hoạch TTS 6 tuần (§5, TTS-4.2):

| # | Tiêu chí | Cách đo trong báo cáo này | Ngưỡng chấp nhận |
|---|---|---|---|
| 1 | Chất lượng tiếng Việt, đọc đúng entity (tên, ngày giờ, số, mã, thuật ngữ y tế) | 27 câu thật của bot (từ `dialogue/templates.py`) → **3 người nghe** WAV, đánh 1/0 "đọc đúng mọi entity" và điểm tự nhiên 1–5 (phiếu `listening_sheet.csv`). Không dùng ASR tự động làm trọng tài (xem §7). | ≥ 95 % câu đúng mọi entity |
| 2 | Streaming & Time-to-First-Audio | TTFA (chunk đầu), **RTF** = thời gian sinh ÷ độ dài audio, số lần "đứt tiếng" nếu phát ngay chunk đầu | TTFA P95 < 500 ms; **RTF < 1** (điều kiện để phát liên tục) |
| 3 | Barge-in: dừng sinh, bỏ chunk chưa phát | Gọi `cancel()` sau 400 ms; đo độ trễ dừng, số chunk thừa, giây audio phải bỏ | Không chunk mới sau 100 ms |
| 4 | Tương thích điện thoại | Cùng bộ WAV qua mô phỏng đường dây (8 kHz, băng 300–3400 Hz, G.711 μ-law, nhiễu SNR 25 dB) → 3 người nghe bản `__tel8k`, chấm "nghe rõ" 1–5; cộng kiểm tra định dạng xuất (8 kHz/μ-law thẳng hay phải resample) | Nghe rõ ≥ 4/5, không mất entity |
| 5 | Độ trễ P95 & chi phí | P50/P95 tổng thời gian sinh trên toàn bộ câu; USD/tháng theo giá niêm yết hoặc giờ máy AWS | **P95 sinh + ghi file ≤ 2 s** (đường HTTP) |
| 6 | Bảo mật dữ liệu | Checklist: text rời hạ tầng? nhà cung cấp lưu? xuyên biên giới? | Không đo bằng code — PM/pháp chế quyết |

## 3. Phương pháp và môi trường đo

| | ElevenLabs | ZeroTTS |
|---|---|---|
| Ngày | **20–21/9** | 18/9 (laptop) + **20/9 (Colab T4)** |
| Máy đo | Laptop Windows, gọi API qua Internet | Laptop 16 luồng (RAM 81 %) và **Colab GPU T4, CUDA, 2 vCPU** |
| Giọng | Sarah (premade, gốc Anh, `language_code=vi`) — giọng Việt "Trang" `BlZK9tHPU6XXjwOSIiYA` bị `402 paid_plan_required` ở gói Free | Bảo Trang, Kim Oanh, Mai Chi (+ Quang Minh trên laptop) |
| Định dạng | `pcm_8000` / `pcm_16000` qua WebSocket `stream-input`, `language_code=vi` | 48 kHz float → hạ 8/16 kHz |
| Bộ câu | **27 câu × 2 lặp = 54 lần**, 0 lỗi (cùng bộ với ZeroTTS) | **27 câu thật × 2 lặp × 3 giọng = 162 lần**, 0 lỗi |
| Tiêu chí 1, 4 (người nghe) | Phiếu đã sinh, **chưa có người điền** | Phiếu đã sinh, **chưa có người điền**; người đo đã nghe thử các câu khó trên web demo: đúng |

Bộ 27 câu bao gồm: 7 câu cố định (chào, hỏi tên/DOB, chuyển máy…), 5 câu ngày giờ theo đúng định dạng `speak_datetime` ("9 giờ 30 sáng ngày 14 tháng 10"), 4 tên riêng ba miền, 2 ngày sinh, 2 số điện thoại + 1 mã lịch hẹn, 5 câu thuật ngữ y tế/khoa, 1 câu dài 229 ký tự. Toàn bộ nằm trong `scripts/tts_bench_set.py` (dùng chung cho notebook Colab và `scripts/tts_bench.py`) để **lặp lại được** cho mọi provider (đúng nguyên tắc 3 của kế hoạch: "quyết bằng eval lặp lại được").

## 4. Kết quả từng ứng viên

### 4.1. ElevenLabs Flash v2.5 (WebSocket `stream-input`, `pcm_8000`)

Đo bằng bộ đo chung ngày 20–21/9 trên laptop qua Internet: 27 câu × 2 lặp = 54 lần, 0 lỗi, giọng **Sarah** (premade gốc Anh, ép `language_code=vi`) vì gói Free chặn giọng Việt Library qua API (`402 paid_plan_required`). Số liệu thô: `docs/evidence/tts-bench/elevenlabs__sarah-free*/`.

| Tiêu chí | Kết quả đo | Đánh giá |
|---|---|---|
| 1 | Chờ 3 người nghe (`docs/evidence/tts-bench/elevenlabs__sarah-free/listening_sheet.csv`, 27 WAV ở `temp/tts-bench/elevenlabs__sarah-free/wav/`). Nghe nhanh của người đo: giọng Sarah đọc tiếng Việt rõ chữ nhưng accent Anh, từ y tế và số điện thoại kém tự nhiên. Con số này là của giọng *sai* — giọng Việt chỉ có ở Starter. | **chưa chấm** (Free, giọng Anh) → chấm giọng Việt sau khi nâng Starter |
| 2 | **TTFA P50 541 / P95 610 ms**; tổng P50 644 / P95 884 ms; **RTF 0,21 / P95 0,33**; **0 % đứt tiếng** trên 54 lần; stream thật (chunk đầu chứa ~30 % câu, 3–4 chunk/câu). TTFA > 500 ms vì handshake WS mỗi câu (~300 ms) — tuần 4 giữ kết nối sẽ hạ. | **Medium** theo ngưỡng 500 ms; **High** về phát liên tục |
| 3 | Đóng WS sau cancel: **87–156 ms** mới dừng nhận; đã nhận **0,9 s** audio phải bỏ (chunk đầu lớn). Ngưỡng TTS-4.2 là 100 ms → sát ngưỡng; multi-context WS (theo tài liệu) cho cancel theo context, chưa đo. | **Medium** |
| 4 | Xuất thẳng `pcm_8000` (và `ulaw_8000`), không cần resample → định dạng **High**. Bản `__tel8k` đã sinh cho 27 câu, chờ phiếu nghe. | **High** định dạng · nghe rõ **chưa chấm** |
| 5 | **P95 tổng 884 ms, câu chào P95 813 ms → đạt ngưỡng 2 s với biên 2×.** Chi phí 750 ký tự/cuộc, Flash tính 0,5 credit/ký tự: 500 cuộc/tháng ≈ Creator 22 USD + credit mua thêm ≈ **48 USD**; 5 000 cuộc ≈ Scale 330 USD; 50 000 cuộc ≈ 2 250 USD. Starter 5 USD = 30k credit = 60k ký tự ≈ **80 cuộc** — đủ demo + tuần 2, không đủ chấm điểm liên tục. | **High** (tốc độ) · chi phí Medium ở quy mô lớn |
| 6 | SOC 2 Type II, TLS, key qua header; **có lưu lịch sử generation** mặc định; máy chủ ngoài VN → chuyển dữ liệu cá nhân xuyên biên giới (NĐ 13/2023). Adapter không log text. | **Medium** |

**Kết luận ElevenLabs:** về **tốc độ và streaming** là ứng viên duy nhất đạt ngưỡng đường chấm (P95 < 1 s, không đứt tiếng, dừng được). Về **chất lượng** chưa có điểm: giọng đang đo là giọng *sai* (gốc Anh); quyết định cuối dựa trên phiếu nghe giọng Việt sau khi nâng Starter (một lệnh 10 phút + 3 người nghe 27 câu).

### 4.2. ZeroTTS (zeroweight-ai/ZeroTTS, MIT, 202M tham số, ONNX, self-host)

Ứng viên thứ 4, ngoài danh sách ADR-002 gốc; đưa vào vì đáp ứng tiêu chí 6 tuyệt đối và tác giả công bố "RTF 0,5 trên CPU 8 luồng, TTFA ~70 ms, đọc số/ngày không cần chuẩn hoá".

**Tiêu chí 2 & 5 — Colab T4 GPU (CUDA), 3 giọng, 54 lần sinh/giọng:**

| Giọng | TTFA P50 / P95 | Tổng sinh P50 / **P95** | RTF P50 / P95 | Câu bị đứt tiếng khi stream | Đệm cần để không đứt (P95) |
|---|---|---|---|---|---|
| Bảo Trang | 297 / 431 ms | 7,9 s / **21,5 s** | 2,34 / 2,57 | **100 %** | 13,6 s |
| Kim Oanh | 287 / 404 ms | 10,3 s / **23,2 s** | 2,31 / 2,36 | 100 % | 13,8 s |
| Mai Chi | 287 / 411 ms | 8,5 s / **20,1 s** | 2,31 / 2,55 | 100 % | 12,1 s |

Đối chiếu laptop (CPU 8 luồng, 18/9): RTF 1,5–1,9, câu chào 9–10 s. **GPU T4 không cải thiện** — RTF phẳng 2,3 ở mọi độ dài câu cho thấy nút cổ chai ở phần chạy tuần tự trên CPU (Colab chỉ 2 vCPU) và trao đổi CPU↔GPU, không ở phép nhân ma trận. Câu chào 112 ký tự: **20 s**; câu tóm tắt 229 ký tự: **29 s**.

**Tiêu chí 1 — đọc đúng entity (người nghe):** phiếu 3 người đã sinh cho 3 giọng (`docs/evidence/tts-bench/zerotts__*/listening_sheet.csv`, WAV ở `temp/tts-bench/zerotts__*/wav/`), **chưa điền**. Người đo đã nghe thử trên web demo của tác giả các câu khó nhất (khoa Tim mạch, Chẩn đoán hình ảnh, Tai Mũi Họng, bác sĩ Lê Minh Khôi, "cho em xin ngày tháng năm sinh", Đặng Khắc Duy Khương): **đọc đúng hết**. Lần chấm tự động bằng ASR trên Colab (Whisper large-v3) đánh sai chính những câu này ("tai mũi **hỏng**", "năm **xinh**", "**Liên Bình** Khôi") — là lỗi của ASR, không phải của TTS, nên số đó **không dùng** trong báo cáo (xem §7).

**Tiêu chí 4 — điện thoại:** xuất 48 kHz float, phải hạ 8 kHz phía mình (định dạng **Medium**). Bản `__tel8k` đã sinh cho 81 WAV, chờ phiếu nghe "nghe rõ" 1–5.

**Tiêu chí 3 — barge-in:** `cancel()` sau 400 ms dừng **0 ms**, 0 chunk thừa, 0,08 s audio phải bỏ (generator trong process, dừng tức thì). Số đẹp một phần vì model chậm: đến 400 ms mới có 0,08 s audio. → **High** về cơ chế.

**Tiêu chí 5 — chi phí AWS** (từ giây-máy đo thật: ~73 ms máy/ký tự → 55 s máy/cuộc gọi 750 ký tự):

| Instance (ap-southeast-1, on-demand) | Bật 24/7 (đường chấm) | Chỉ giờ bận, 500 / 5.000 cuộc/tháng |
|---|---|---|
| c7i.xlarge (4 vCPU) | ~161 USD/tháng | 3 / 33 USD |
| c7i.2xlarge (8 vCPU) | ~314 USD/tháng | 7 / 65 USD |
| g4dn.xlarge (T4) | ~474 USD/tháng | 10 / 99 USD |

Với hiệu năng đo được, **không instance nào trong bảng đạt 8 s/lượt**; chi phí là thứ yếu. → **Low**.

**Tiêu chí 6:** model chạy trong EC2/VPC của team, không bên thứ ba, không xuyên biên giới, license MIT. → **High** (mạnh nhất trong 4 ứng viên).

### 4.3. Microsoft Azure AI Speech — chưa đo

Giữ nguyên thông tin ADR-002 (giọng `vi-VN-HoaiMyNeural`, WebSocket v2 + stop API, xuất thẳng Raw8Khz μ-law/PCM, không retain text/audio, F0 miễn phí 0,5 triệu ký tự/tháng). Là ứng viên duy nhất chưa có số; cần mở tài khoản và chạy notebook trong tuần 2 để có dự phòng thật.

## 5. Ma trận đánh giá (số đo thật, 20-09-2026)

| Tiêu chí | ElevenLabs Flash v2.5 | ZeroTTS self-host | Azure AI Speech |
|---|---|---|---|
| 1. Chất lượng / entity (người nghe) | chưa chấm (Free, giọng Anh) → chấm giọng Việt sau Starter | chưa chấm phiếu; nghe thử web demo đúng hết câu khó | chưa đo |
| 2. Streaming / TTFA | **High** phát liên tục (RTF 0,2, 0 % đứt); TTFA 0,54 s = Medium | Low (RTF 2,3) | chưa đo |
| 3. Barge-in | Medium (dừng 0,09–0,16 s, bỏ 0,9 s audio) | High | High* |
| 4. Điện thoại | High định dạng (`pcm_8000` thẳng) · nghe rõ chưa chấm | Medium định dạng (48 kHz, tự hạ tần) · nghe rõ chưa chấm | High* |
| 5. P95 & chi phí | **High** (P95 0,88 s; 5–48 USD/tháng ở 500 cuộc) | Low (20 s; 160–470 USD/tháng) | chưa đo |
| 6. Bảo mật | Medium | **High** | High* |
| **Đạt ngưỡng đường chấm 28/9?** | **Có** (tốc độ) — chất lượng chờ phiếu nghe giọng Việt | Không | ? |

\* theo tài liệu nhà cung cấp, chưa đo. Ma trận tự sinh với ngưỡng cố định: `docs/evidence/tts-bench/matrix.md`; tiêu chí 1 & 4 tự cập nhật khi phiếu nghe được điền.

**Lựa chọn đề xuất:** **ElevenLabs Flash v2.5 (gói Starter) làm provider chính**; Azure F0 làm dự phòng sau khi đo; ZeroTTS loại khỏi đường chấm, giữ hồ sơ.

## 6. Hệ quả và việc phải làm nếu chọn ElevenLabs

| Việc | Ai | Hạn |
|---|---|---|
| Duyệt chi phí Starter 5 USD/tháng (tuần 2 tăng Creator 22 USD nếu chấm điểm liên tục) | PM | 22/9 |
| Nâng gói, chạy `python scripts/tts_bench.py --provider elevenlabs --voice BlZK9tHPU6XXjwOSIiYA --label elevenlabs:trang --repeats 2` (≈3 phút) cho giọng "Trang" và 2 giọng dự phòng; 3 người điền phiếu nghe (27 câu × 2 bản ≈ 15 phút/người); `--matrix` | B + 2 người | 24/9 |
| Giảm thiểu tiêu chí 6: chỉ gửi `utterance` đã qua Output Guard; không gửi `patient_id`/mã nội bộ; không log text (đã làm trong adapter); tắt/xoá lịch sử generation định kỳ; ghi vào ADR | B + A | 30/9 |
| Cache câu cố định (chào, hỏi tên/DOB, chuyển máy) sinh sẵn lúc khởi động → lượt 0 không gọi TTS, giảm ký tự tiêu thụ ~30 % | B | tuần 3 (TTS-3.2) |
| Timeout 2,5 s + retry 1 + fallback provider dự phòng Azure (khi đo xong) | B | tuần 3 (TTS-3.1) |
| Mở tài khoản Azure F0, đo bằng notebook | A hoặc B | tuần 2 |
| Chuẩn hoá số → chữ trước TTS (Flash v2.5 không có text normalizer) — ZeroTTS cho thấy template hiện tại "9 giờ 30 sáng ngày 14 tháng 10" đã đọc được, cần xác nhận với ElevenLabs | B | tuần 2 (TTS-2.2) |

## 7. Bài học từ lần đo

1. **Số công bố ≠ số đo**: ZeroTTS "RTF 0,5" đo ra 1,5–2,3 trên hai loại máy khác nhau; ElevenLabs TTFA công bố ~75 ms, đo qua Internet từ VN 0,54 s. Mọi quyết định còn lại (Azure, giọng ElevenLabs) phải qua cùng notebook.
2. **TTFA tốt không đủ**: ZeroTTS có TTFA 0,3 s nhưng RTF > 1 → phát streaming đứt 100 % câu. Tiêu chí 2 phải đo cả hai.
3. **Không dùng ASR làm trọng tài chất lượng TTS tiếng Việt.** Đã thử Whisper (faster-whisper): cùng một bộ WAV ZeroTTS cho "entity đúng" 85 % với `large-v3`, 74–78 % với `medium`, 41–44 % với `small`; các câu bị đánh sai ("tai mũi hỏng", "năm xinh", "Liên Bình Khôi") khi người nghe lại đều đúng — ASR thiên về từ phổ biến nên luôn phạt oan từ y tế và tên riêng. Kết luận: tiêu chí 1 & 4 do **3 người nghe** theo phiếu; ASR chỉ có thể dùng để gợi ý câu cần nghe kỹ, không để ra điểm.
4. **Từ y tế là điểm yếu chung** cần từ điển phát âm/SSML (TTS-5.4) bất kể provider.

## Phụ lục — Tệp và cách lặp lại

- **Bộ đo chung:** `scripts/tts_bench.py` + bộ câu `scripts/tts_bench_set.py` → `docs/evidence/tts-bench/matrix.md` (tự chấm High/Medium/Low theo ngưỡng cố định) và `docs/evidence/tts-bench/<label>/` (CSV + summary.json). Lệnh: `--provider elevenlabs [--voice] [--label] [--repeats]`; `--import-dir <CSV Colab> --wav-dir <WAV Colab>`; `--matrix` (đọc phiếu nghe mới, dựng lại ma trận). Phiếu nghe: mỗi dòng một câu, cột `can_nghe_dung` liệt kê entity phải đúng, `wav_sach`/`wav_dien_thoai` là file cần nghe; mỗi người điền `entity` (1/0), `tu_nhien` (1–5), `ro_8k` (1–5).
- Kết quả ZeroTTS đo trên Colab T4 (notebook chạy riêng, không lưu trong repo) nhập vào ma trận bằng `--import-dir ../ZeroTTS`.
- Kết quả ZeroTTS 20/9 (Colab): `ZeroTTS/latency_raw.csv`, `bargein.csv`, `wav/` (81 WAV sạch) — đã nhập vào ma trận; các CSV chấm bằng ASR trong folder đó không dùng nữa.
- Adapter trong repo (nhánh `tts-week1`): chỉ `src/callbot/speech/tts/elevenlabs.py`, `TTS_PROVIDER=elevenlabs|none`. thử nhanh: `python scripts/tts_say.py "câu" --provider elevenlabs --voice <id>`.

## Ghi chú — hai nhà cung cấp trong nước đã thử và loại (Vbee, Viettel AI)

Cả hai đều được tích hợp thử và đo bằng cùng câu thật của bot, sau đó gỡ khỏi repo vì **không đạt tiêu chí 2 (streaming)**; ghi lại đây để không thử lại từ đầu.

| | Vbee Realtime API (`POST api.vbee.vn/v1/tts`, `mode=sync`) | Viettel AI TTS (`POST viettelai.vn/tts/speech_synthesis`) |
|---|---|---|
| Ngày đo | 18/9 (laptop, qua Internet) | 20/9 (laptop, qua Internet) |
| Streaming | Có luồng "realtime" theo tài liệu, nhưng đo thật byte audio đầu chỉ về **khi đã tổng hợp xong**: TTFA **4,3–5,7 s** cho mọi độ dài câu (8 ký tự cũng ~4,5 s), cả 5 giọng, cả pcm/wav/mp3. Request chỉ validate về trong 64 ms → không phải mạng. Đã đối chiếu tài liệu chính thức, mọi trường gửi đúng; đã hỏi Vbee support, chưa có phản hồi. | **Không cung cấp luồng streaming.** Tài liệu chỉ có một endpoint trả file wav/mp3 trọn; đo ở mức byte: header `chunked` nhưng byte đầu về sau **1,3 s** (câu 54 ký tự) → **2,8 s** (câu 262 ký tự), tức tổng hợp xong mới gửi; thêm `stream: true` bị bỏ qua; 5 đường HTTP `/stream|streaming|v2` và 4 đường `wss://` đều 404. |
| Định dạng | `pcm` 8 kHz thẳng (header `x-audio-sample-rate: 8000`) | WAV 22,05 kHz, không chọn được 8 kHz → phải hạ tần phía mình |
| Giọng | 5 giọng Việt Bắc/Nam nghe tự nhiên | 16 giọng Việt ba miền (`GET /tts/voices`), giọng Quỳnh Anh ngữ điệu tổng đài |
| Bảo mật | Máy chủ trong nước (NĐ 13); key qua header | Máy chủ trong nước; **token đi trong body JSON** → không được log body |
| Vì sao loại | TTFA 4–6 s vượt ngân sách TTS 1,5–2 s gần 3 lần, có lượt vượt cả 8 s/lượt của hợp đồng | Câu ngắn ~1,5 s vừa chớm ngưỡng, câu dài ~3 s vượt; không ngắt được giữa câu |
| Khi nào xem lại | Nếu Vbee xác nhận tài khoản chưa bật gói Realtime thật và số đo về ~0,5 s như tài liệu | Nếu Viettel trả lời có gói streaming (đã gửi câu hỏi 20/9) |

Code adapter Vbee còn trong lịch sử git (commit `7c7c1cd`, `src/callbot/speech/tts/vbee.py`); adapter Viettel đơn giản (~150 dòng, HTTP + `decode_wav`) viết lại được nhanh nếu cần.

# Kế hoạch cải tiến xử lý âm thanh LiveKit (phần trước core engine) — 28/09/2026

Đánh giá 10 đề xuất kiến trúc đã nhận + 4 điểm tự rà soát trong code, chốt **nên làm / không
nên làm / để sau**, và lộ trình. Đây là kế hoạch gốc; trạng thái triển khai và kết quả đo xem
`docs/evidence/livekit-audio-plan-execution-2026-09-28.md`. Hiện trạng ban đầu:
`docs/reference/livekit-audio-architecture-2026-09-28.md`.

**Quan trọng — đọc tài liệu thực thi trước khi coi bảng dưới đây là quyết định cuối.** Sau khi
đo thật, một số kết luận "nên làm"/"nên thử nghiệm" ở đây đã bị **số đo phản bác** và bị từ
chối, không bật:
- **Đề xuất 1** (khử nhiễu/tách giọng phía server): đo qua LiveKit Cloud thật cho thấy NC/BVC
  làm WER và tỉ lệ mất câu **tệ hơn** không lọc gì, ở gần mọi điều kiện. **Từ chối — code đã gỡ
  hẳn khỏi repo**, không chỉ tắt cờ.
- **Đề xuất 6** (hotwords theo state): beam đủ rộng để sửa "hủy lịch" nghe nhầm cũng **đảo
  nghĩa** nhiều câu khác — "ừ" (đồng ý) → "KHÔNG ĐỒNG Ý" nhiều lần, kể cả câu của bot vọng lại.
  Với callbot xác nhận hủy/giữ lịch, đây là rủi ro đảo ý người dùng. **Từ chối — code đã gỡ hẳn
  khỏi repo**, không chỉ tắt cờ.
- **Đề xuất 4** (Speech Admission): không dừng ở "giữ tắt" — code đã **xoá hẳn** module.
- **Đề xuất 2** (một VAD dùng chung): bộ phân loại dùng chung an toàn tuyệt đối (0/869 trial
  khác kết quả khi đối chiếu) và đã bật được (cờ tắt mặc định). Nhưng bước "đổi VAD chính
  production sang Silero" cho kết quả trái chiều thật (tốt hơn nhiều cho câu dài/latency dưới
  nhiễu, tệ hơn rõ cho câu ngắn — đúng loại câu quan trọng nhất) nên **chưa đổi** `vad_provider`
  production.

Các mục A, B, D, 8 và việc nhỏ ở mục 7 (`partial_interval_ratio`, hangover Silero cấu hình
được) đã làm xong và giữ đúng như kế hoạch.

**Ràng buộc**

1. Giữ model ASR hiện tại (gipformer1.5, bản offline, chạy qua sherpa-onnx) — chưa có model
   streaming tiếng Việt thay thế.
2. Không sửa core engine (`src/callbot/engine/`). Chỉ sửa phần trước core: transport LiveKit,
   `src/speech/`, provider ASR. Được dùng những gì core **đã trả ra** (`BotAction.state`) và
   hợp đồng core **đã có** (`silence_ms`).
3. Mọi thay đổi phải đo trước/sau trên cùng dữ liệu, bật/tắt được bằng cấu hình khi thử.

---

## 1. Kết luận nhanh (LÚC LẬP KẾ HOẠCH — xem cột "Sau khi đo 28/09" và tài liệu thực thi)

### 10 đề xuất

| # | Đề xuất | Kết luận lúc lập kế hoạch | Sau khi đo 28/09 |
|---|---|---|---|
| 1 | Khử nhiễu / tách giọng phía server | ✅ Nên làm — thử nghiệm có đo | ❌ **TỪ CHỐI, code đã gỡ** — NC/BVC tệ hơn không lọc ở gần mọi điều kiện đo qua LiveKit Cloud thật |
| 2 | Một VAD dùng chung | ✅ Nên làm — tái cấu trúc theo bước | ⚠️ **Một nửa**: bộ phân loại dùng chung AN TOÀN, đã bật được (cờ tắt); đổi VAD chính sang Silero thì KHÔNG (câu ngắn tệ hơn) |
| 3 | Bỏ chunked-offline, dùng streaming thật | ❌ Không làm bây giờ | (không đổi — chưa làm) |
| 4 | Đổi vai trò Speech Admission | ❌ Không đầu tư thêm — giữ tắt, gỡ khi có VAD chung | ✅ Đã **xoá hẳn** code |
| 5 | Validator dùng state / expected_input | ⚠️ Không nới lỏng — chỉ phần từ đệm, có điều kiện | (không đổi — điều kiện chưa đủ, chưa làm) |
| 6 | Hotwords theo state | ✅ Nên thử nghiệm | ❌ **TỪ CHỐI, code đã gỡ** — beam đủ rộng để sửa lỗi mục tiêu cũng đảo nghĩa "đồng ý"↔"không đồng ý" nhiều câu khác |
| 7 | Bộ sửa lỗi ASR theo nghiệp vụ trước core | ⚠️ Làm có điều kiện — sau hotwords | ❌ Điều kiện không còn (hotwords bị từ chối) — chưa làm |
| 8 | Tách VAD khỏi backpressure của ASR | ✅ Nên làm | ✅ Đã làm, luôn bật |
| 9 | Cổng "giọng tiền cảnh" trước barge-in | ❌ Không làm riêng — xem lại sau mục 1 | (không đổi — mục 1 đã từ chối nên không xem lại) |
| 10 | Tách profile web / điện thoại | ⏸ Để sau — khi làm SIP | (không đổi — chưa làm) |

### 4 điểm tự rà soát (không có trong đề xuất)

| # | Việc | Kết luận | Lý do ngắn |
|---|---|---|---|
| A | Gửi lượt im lặng cho core | ✅ **Nên làm sớm** | Core đã có luật im lặng, nhưng LiveKit luôn gửi `silence_ms=0` — người dùng im thì bot chờ mãi |
| B | Lấy độ tin cậy ASR từ model hiện tại | ✅ **Nên thử** | Model có trả xác suất từng token (`ys_log_probs`), pipeline đang bỏ đi |
| C | Bộ đo cho kết quả ổn định + chốt cấu hình mục tiêu | ✅ **Làm đầu tiên** | Số đo cấp lượt nói dao động giữa các lần chạy; local đo cấu hình khác production |
| D | Chỉ nhận audio của người gọi | ✅ **Nên làm** (nhỏ) | Mọi track của mọi participant đang gộp chung một hàng đợi |

---

## 2. Đánh giá chi tiết

Mỗi mục: **hiện trạng** (có dẫn chứng) → **khả thi?** → **kết luận** → nếu làm: **làm gì, đo gì,
rủi ro**.

### 2.1 Đề xuất 1 — Khử nhiễu / tách giọng phía server ✅

- **Hiện trạng.** Chỉ có xử lý trong trình duyệt (AEC, NS, AGC, voiceIsolation); server không
  biết trình duyệt thực sự đã làm gì. Đo 25/09: với tiếng người nói xung quanh, mọi phiên bản code
  đều cho WER > 1 và 12/12 mẫu chỉ có giọng nền sinh lượt giả.
- **Khả thi: có.** `rtc.AudioStream.from_track` (bản đang cài) có sẵn tham số
  `noise_cancellation`. PyPI có `livekit-plugins-noise-cancellation` 0.3.2,
  `livekit-plugins-krisp` 0.4.3, `livekit-plugins-ai-coustics` 0.3.2. Chỗ lắp: một chỗ trong
  `CallBridge._pump_track`.
- **Phải kiểm tra trước khi làm:** license/chi phí của từng plugin (plugin của LiveKit chỉ chạy
  với LiveKit Cloud); CPU trên máy 2 vCPU; tên hàm cụ thể theo tài liệu plugin.
- **Cách đo.**
  - Server bật/tắt: dựng một participant giả phát file WAV (câu nói trộn nhiễu văn phòng / giọng
    nền của bộ đo) vào phòng; worker nhận qua `AudioStream` có/không khử nhiễu, ghi dump, chạy
    pipeline. Cùng đầu vào → so sánh công bằng.
  - Phía trình duyệt: chỉ đo được bằng cuộc gọi thật đọc cùng kịch bản. So 3 cấu hình:
    A. chỉ NS trình duyệt (hiện tại) · B. chỉ tách giọng phía server · C. AEC trình duyệt + tách
    giọng server. **Không bật hai bộ khử nhiễu mạnh cùng lúc.**
- **Tiêu chí nhận:** với giọng nền, lượt giả và WER giảm rõ; với sạch / nhiễu văn phòng không tệ
  hơn; câu trả lời ngắn vẫn giữ được; độ trễ và CPU thêm chấp nhận được.
- **Rủi ro:** model tách giọng cắt mất giọng người gọi nói nhỏ / xa mic → bắt buộc đo trên câu
  ngắn.

### 2.2 Đề xuất 2 — Một VAD dùng chung ✅

- **Hiện trạng.** Local chạy tới 4 bản Silero độc lập trên cùng frame (VAD chính, bộ chốt câu
  của ASR, Admission, Validator). Bug 26/09 (câu kẹt trong ASR) sinh ra đúng từ việc Admission và
  bộ chốt câu của ASR lệch nhau 1 frame. Production dùng WebRTC cho VAD chính và bộ chốt câu.
- **Khả thi: có**, hoàn toàn trước core. Đã có sẵn mảnh ghép quan trọng: `AsrSegmentEnd` —
  pipeline tự báo ASR chốt/bỏ câu, nên ASR không cần bộ phân loại riêng nữa.
- **Thiết kế.** Một `SpeechDetector` cho mỗi cuộc gọi, phân loại **1 lần/frame**, xuất
  `SpeechState(is_speech, speech_ms, silence_ms, rms, noise_floor, snr)` và sự kiện bắt đầu /
  kết thúc. Mọi nơi (TurnController, Interruption, evidence, ASR) đọc cùng một nguồn. Giữ các cơ
  chế đã sửa: pre-speech 300 ms trong ASR, bù độ trễ onset 300 ms cho nền nhiễu.
- **Phải chọn bằng số liệu:** Silero (ít nhầm nhiễu nhưng báo trễ ~0,25 s và giữ thêm 0,5 s)
  hay WebRTC (nhanh nhưng hay nhầm nhiễu); tham số giữ trạng thái (hangover).
- **Làm theo 3 bước**, mỗi bước đo lại toàn bộ:
  1. ASR dùng ranh giới của VAD chính (bỏ bộ phân loại riêng của ZipFormer).
  2. Evidence dùng chung bộ phân loại (bỏ bản Silero của Validator).
  3. Gỡ Admission (mục 2.4).
- **Kèm theo:** tinh chỉnh thời gian chờ hết câu. Đây mới là phần lớn độ trễ một lượt (local:
  hangover 0,5 s + chờ 0,6 s ≈ 1,1–1,4 s từ lúc hết tiếng tới lúc chốt lượt), không phải decode.
- **Rủi ro:** thay đổi ở lõi pipeline → bắt buộc phát lại các cuộc gọi lỗi đã lưu (dump) và bộ đo
  sau mỗi bước.

### 2.3 Đề xuất 3 — Streaming ASR thật ❌ (không làm bây giờ)

- **Không làm** vì: chưa có model streaming tiếng Việt (cả bản mới nhất
  `sherpa-onnx-zipformer-vi-30M-int8-2026-02-09` cũng là offline); ràng buộc giữ model hiện tại.
  Provider ElevenLabs realtime đã có sẵn — giữ làm phương án dự phòng, chỉ đo khi có ngân sách.
- **Số đo thật trên máy dev** (gipformer, 2 luồng): decode 1 s audio mất 23 ms, 3 s → 49 ms,
  10 s → 150 ms, 15 s → 229 ms (RTF ≈ 0,015).
  - Câu trả lời ngắn (1–3 s): tổng chi phí decode lặp lại < 0,5 s CPU/câu — **không phải nút
    thắt**.
  - Câu 10 s: decode lại ~33 lần ≈ 2,5 s CPU — đáng kể trên máy 2 vCPU.
- **Việc nhỏ nên làm với model hiện tại:** giới hạn chi phí partial cho câu dài (giãn nhịp decode
  khi buffer dài, hoặc partial chỉ decode đoạn cuối); final vẫn decode toàn bộ. Chỉ làm sau khi
  đo CPU trên máy production.

### 2.4 Đề xuất 4 — Speech Admission ❌ (không đầu tư thêm)

- Đồng ý hướng "trước ASR chỉ chặn khi chắc chắn là nhiễu". Nhưng số liệu 25/09: **tắt Admission
  tốt hơn ở 11/12 phép đo**, không làm tăng lượt giả; production vốn tắt. Admission còn là nguồn
  phức tạp (bộ đệm riêng, ranh giới riêng) và là một phía của bug 26/09.
- **Kết luận:** không thiết kế lại. Local đặt `SPEECH_ADMISSION_ENABLED=false` để đo đúng cấu
  hình production; gỡ hẳn ở bước 3 của mục 2.2. Nếu sau này cần "cổng rẻ" giảm tải ASR, nó nằm
  trong `SpeechDetector` chung.

### 2.5 Đề xuất 5 — Validator dùng state / expected_input ⚠️

- **Không làm theo hướng đề xuất** (vd. "ừ" có SNR 2,8 dB vẫn ACCEPT khi đang hỏi có/không): đó
  là tình huống ảo giác nguy hiểm nhất — một chữ "có/ừ" sinh ra từ nhiễu đúng lúc bot hỏi xác nhận
  sẽ thành đồng ý thật. Core đã cố ý phòng điều ngược lại ("dạ" không bao giờ được huỷ lịch —
  `agreement.py`, SF-05).
- **Không đủ dữ liệu phía trước core:** `BotAction` chỉ có 6 state thô (AWAITING_IDENTITY,
  AWAITING_INTENT, AWAITING_CONFIRMATION, OFFERING_SLOTS, CLOSING, ENDED), không có mã câu hỏi.
  Làm đúng "expected_input" cần core trả thêm mã câu hỏi → **để sau**.
- **Phần nên làm (có điều kiện).** Bộ lọc từ đệm ở TurnController (`is_meaningful_text`) đang bỏ
  "dạ", "ừ", "ờ" đứng riêng, trong khi **core coi chúng là câu trả lời** (`agreement.py`) → người
  dùng đáp "ừ" bị mất. Có thể cho các từ này đi qua khi state là `AWAITING_CONFIRMATION`, để core
  tự hiểu nghĩa.
  - Điều kiện: phải biết ASR sinh ra các từ này từ nhiễu thường xuyên cỡ nào. Dữ liệu hiện có quá
    mỏng (nhiễu văn phòng: 0–1 ảo giác / 12 mẫu, là "ĐÂY", "À"; giọng nền thì ASR chép cả câu dài,
    không phải từ ngắn) → cần nhãn cuộc gọi thật (trang `temp/validator-audit/index.html`).
- **Nguyên tắc giữ:** validator trước core chỉ trả lời "đây có phải lời người gọi không" (bằng
  chứng âm thanh, độ ổn định, độ tin cậy ASR). "Câu trả lời có hợp lệ không" là việc của core.

### 2.6 Đề xuất 6 — Hotwords theo state ✅ (thử nghiệm)

- **Khả thi.** sherpa-onnx 1.13.8 có `hotwords_file`, `hotwords_score`, `modeling_unit`,
  `bpe_vocab`, và `create_stream(hotwords=...)` theo từng stream → đổi danh sách theo state được.
  Cần:
  - chuyển sang `modified_beam_search` (hiện là `greedy_search`);
  - `bpe.model` của gipformer (có trên HuggingFace `g-group-ai-lab/gipformer1.5-68M-rnnt`,
    Dockerfile hiện chưa tải) để tạo `bpe_vocab`.
- **State** lấy từ `BotAction.state` — không sửa core. Ví dụ danh sách:
  - `AWAITING_CONFIRMATION`: hủy lịch, đổi lịch, giữ lịch, đồng ý, không đồng ý
  - `OFFERING_SLOTS`: thứ hai … chủ nhật, buổi sáng, buổi chiều, giờ
  - `AWAITING_INTENT`: đặt lịch, hủy lịch, đổi lịch
  - `AWAITING_IDENTITY`: **không dùng** (tên người, ngày sinh — dễ bị ép sai)
- **Giảm chi phí:** partial vẫn greedy; chỉ lần decode final dùng beam + hotwords.
- **Đo:** các câu "hủy lịch" bị nghe sai trong dump (vd. cuộc gọi `web-2c3bf8e7`); bộ có nhãn +
  bộ web (WER không được tăng, không chèn cụm nghiệp vụ vào câu khác); thời gian decode final.
- **Lưu ý:** 25/09 đã thử beam search **không** hotwords — kết quả lẫn lộn. Hotwords là thí
  nghiệm khác, phải đo riêng.

### 2.7 Đề xuất 7 — Bộ sửa lỗi ASR theo nghiệp vụ ⚠️

- **Khả thi** (thuần văn bản, đặt trước core). Nhưng rủi ro sửa sai cao: "THÙY LINH" là tên
  người thật — sửa ở bước hỏi tên sẽ phá dữ liệu định danh.
- **Chỉ làm khi đủ cả 5 điều kiện:**
  1. hotwords (mục 2.6) chưa đủ;
  2. có danh sách lỗi thật rút từ dump, không đoán;
  3. chỉ bật ở state an toàn (`AWAITING_CONFIRMATION`, `AWAITING_INTENT`), không bao giờ ở
     `AWAITING_IDENTITY`;
  4. chỉ sửa thành cụm trong từ điển nhỏ, có ngưỡng độ giống;
  5. ghi log mỗi lần sửa.
- Core đã có tầng ngữ nghĩa (LLM) cho một số câu hỏi — phải đo xem bộ sửa lỗi có giúp thêm hay
  chỉ trùng việc.

### 2.8 Đề xuất 8 — Tách VAD khỏi backpressure của ASR ✅

- **Hiện trạng.** `_fanout` chờ đưa frame vào hàng đợi VAD rồi hàng đợi ASR trong cùng một vòng;
  hàng đợi ASR đầy thì VAD cũng đứng. Log 24/09: decode 1,89 s nhưng xử lý kéo dài 4,38 s.
- **Làm:** VAD và evidence nhận frame không phụ thuộc ASR; ASR có hàng đợi riêng, đo độ trễ tồn
  đọng (ASR lag) và ghi log khi vượt ngưỡng; **không bỏ frame lời nói**.
- **Điểm dễ sai:** khi ASR chậm mà VAD đã báo hết câu, TurnController hiện chỉ chờ 300 ms rồi chốt
  bằng partial → sẽ chốt bằng partial cũ, thiếu chữ. Phải thêm quy tắc: ASR còn tồn audio của câu
  thì chờ final (có trần thời gian).
- **Đo:** test với ASR chậm nhân tạo — độ trễ `speech_end` và text có đủ không.

### 2.9 Đề xuất 9 — Cổng giọng tiền cảnh trước barge-in ❌ (không làm riêng)

- Đo 25/09 trên cuộc gọi thật: tiếng nói khác trong cùng cuộc gọi chỉ nhỏ hơn giọng người gọi
  (trung vị) 3,2 dB, có lúc **to hơn** 19,7 dB → lọc theo độ to / SNR sẽ chặn nhầm người gọi.
- Cổng barge-in hiện tại đã yêu cầu ≥ 200 ms + partial ASR có nghĩa + không giống câu bot + SNR /
  validator.
- Nếu mục 2.1 có tách giọng, xem lại: tín hiệu sau tách giọng mới là "tiền cảnh" thật.

### 2.10 Đề xuất 10 — Profile web / điện thoại ⏸ (để sau)

- Đúng về nguyên tắc (25/09 đã thấy Silero kém ổn định rõ trên audio 8 kHz có nhiễu). Nhưng
  SIP chưa có. Khi làm SIP: tách cấu hình theo transport (ngưỡng VAD, thời lượng tối thiểu, bộ
  khử nhiễu dạng telephony, codec, 8 kHz → resample 16 kHz ở biên ASR).

### 2.A Gửi lượt im lặng cho core ✅

- **Core đã có:** `silence_ms > 0` là lượt im lặng; core đếm, xử lý, 3 lượt liên tiếp →
  UNREACHABLE (`max_silent_turns`). **LiveKit:** luôn gửi `silence_ms=0` → không bao giờ có lượt
  im lặng.
- **Làm trong CallBridge** (không sửa core): sau khi bot nói xong, nếu không có `speech_start`
  trong N giây (cấu hình, ví dụ 6–8 s) → gửi `CallerInput(silence_ms=N)`. Huỷ hẹn giờ khi người
  dùng bắt đầu nói hoặc đang có candidate / barge-in.
- **Test:** hẹn giờ đúng; huỷ khi người dùng nói; không gửi khi đang có candidate; không chồng
  với lượt thật.

### 2.B Độ tin cậy ASR từ model hiện tại ✅ (thử)

- Model trả `ys_log_probs` cho từng token. Ví dụ câu "hủy lịch" bị nghe thành "THÙY LINH": xác
  suất 0,79 / 0,98 / 0,57 — sai chữ nhưng model khá tự tin. Vậy độ tin cậy **không** bắt được lỗi
  nghe nhầm; chỉ có thể giúp bắt ảo giác sinh từ nhiễu.
- **Bước 1:** tính confidence (vd. trung bình và min log-prob) gắn vào `TranscriptEvent`; chỉ ghi
  log và đưa vào bộ đo.
- **Bước 2:** nếu số liệu cho thấy tách được ảo giác (mẫu chỉ nhiễu) khỏi lời thật → dùng trong
  validator / interruption (`min_confidence` đã có chỗ sẵn). `asr_confidence` gửi core hiện không
  được core đọc → không ảnh hưởng core.

### 2.C Nền tảng đo ✅ (làm đầu tiên)

- **Bộ đo ổn định:** số liệu cấp lượt nói hiện dao động giữa các lần chạy (đẩy frame nhanh hơn
  thời gian thực, trong khi timeout là thời gian thật) → dùng đồng hồ ảo cho cả timeout.
- **Chốt cấu hình mục tiêu** (production) và đo trên đó. Hiện local = Silero + Admission +
  Validator; production = WebRTC, không Admission, không Validator.
- **Dữ liệu câu trả lời ngắn thật** (dạ, vâng, có, không, đúng rồi, hủy lịch…): bộ có nhãn chỉ
  có 2 câu ≤ 2 từ.
- **Gán nhãn** các đoạn trên cuộc gọi thật (trang nghe đã có).
- **Giữ quy trình:** mỗi lỗi từ cuộc gọi thật → phát lại dump bằng
  `eval/noise-bench/replay_dump.py` → test hồi quy.

### 2.D Chỉ nhận audio của người gọi ✅ (nhỏ)

- `_on_track_subscribed` nhận mọi track audio của mọi participant và gộp chung một hàng đợi. Chỉ
  nhận track của người gọi (participant đầu tiên / có attribute cuộc gọi). Ít rủi ro.

---

## 3. Lộ trình

```
Giai đoạn 0 — NỀN TẢNG ĐO (không đổi hành vi)          ← làm trước
  0.1  Bộ đo xác định (đồng hồ ảo cho timeout)                         [2.C]
  0.2  Chốt cấu hình mục tiêu = production; local đo theo cấu hình đó  [2.C, 2.4]
  0.3  Thu câu trả lời ngắn thật + gán nhãn đoạn cuộc gọi thật         [2.C, 2.5]
  0.4  Số đo nền (baseline): WER lượt nói, câu thật bị bỏ, lượt giả trên
       nhiễu / giọng nền, độ trễ hết tiếng → chốt lượt, CPU

Giai đoạn 1 — SỬA NHỎ, RỦI RO THẤP
  1.1  Lượt im lặng gửi core                                            [2.A]
  1.2  Chỉ nhận track của người gọi                                     [2.D]
  1.3  Confidence ASR — chỉ ghi log + đưa vào bộ đo                     [2.B bước 1]
  1.4  Tách VAD khỏi backpressure ASR + quy tắc chờ final               [2.8]

Giai đoạn 2 — THÍ NGHIỆM CÓ ĐO (bật bằng cờ cấu hình)
  2.1  Khử nhiễu / tách giọng phía server (A/B/C)                       [2.1]
  2.2  Hotwords theo state (chỉ lần decode final)                       [2.6]
  2.3  Từ đệm theo state — nếu nhãn cho thấy ảo giác hiếm              [2.5]
  2.4  Confidence làm tín hiệu chặn ảo giác — nếu số liệu tách được     [2.B bước 2]

Giai đoạn 3 — TÁI CẤU TRÚC
  3.1  VAD dùng chung, 3 bước                                           [2.2]
  3.2  Gỡ Speech Admission                                              [2.4]
  3.3  Tinh chỉnh thời gian chờ hết câu (hangover, 600 ms)              [2.2]
  3.4  Giới hạn chi phí partial cho câu dài                             [2.3]

Để sau
  - Streaming ASR thật (khi có model tiếng Việt streaming)              [2.3]
  - Validator theo mã câu hỏi (cần core trả thêm dữ liệu)               [2.5]
  - Profile điện thoại (khi làm SIP)                                    [2.10]
  - Bộ sửa lỗi nghiệp vụ (nếu hotwords chưa đủ)                         [2.7]
```

Thứ tự này có chủ ý: giai đoạn 0 phải xong trước, vì không có bộ đo ổn định thì không phân biệt
được một thay đổi tốt lên thật hay chỉ là dao động của phép đo.

---

## 4. Kiến trúc mục tiêu trong ràng buộc hiện tại

`[có]` = đã có · `[mới]` = thêm theo kế hoạch · `[sau]` = để sau

```
 Web (SIP [sau])
      │
 LiveKit Cloud ── AudioStream 16 kHz mono, chỉ track người gọi [mới]
      │
 ┌────▼─────────────────────────────────────┐
 │ KHỬ NHIỄU / TÁCH GIỌNG phía server [mới] │  (thử nghiệm A/B/C)
 └────┬─────────────────────────────────────┘
      │
 ┌────▼─────────────────────────────────────┐
 │ SPEECH DETECTOR DÙNG CHUNG [mới]          │  1 lần phân loại / frame
 │  speech start/end, pre-roll [có]          │
 │  nền nhiễu + SNR (bù onset) [có]          │
 └────┬───────────────┬─────────────────────┘
      │               └──► bằng chứng cho barge-in [có]
      │ (không bị ASR chặn [mới])
 ┌────▼─────────────────────────────────────┐
 │ ASR gipformer offline [có]               │
 │  ranh giới do Speech Detector báo [có*]   │  *AsrSegmentEnd đã có
 │  partial greedy / final beam+hotwords [mới]│
 │  confidence từ ys_log_probs [mới]         │
 └────┬─────────────────────────────────────┘
      │
 ┌────▼─────────────────────────────────────┐
 │ TURN LOGIC [có]                           │
 │  độ ổn định transcript, SNR cả câu,       │
 │  confidence [mới], từ đệm theo state [mới]│
 │  barge-in: echo text, SNR, validator      │
 │  lượt im lặng → core [mới]                │
 └────┬─────────────────────────────────────┘
      │  (bộ sửa lỗi nghiệp vụ theo state [sau])
      ▼
   CORE ENGINE (không đổi)
```

---

## 5. Tiêu chí chấp nhận chung (mọi thay đổi)

1. Bật/tắt được bằng cấu hình trong giai đoạn thử.
2. So với số đo nền, trên cùng dữ liệu:
   - lượt giả trên mẫu chỉ nhiễu / giọng nền **không tăng**;
   - câu thật bị bỏ (đặc biệt câu ngắn) **không tăng**;
   - WER lượt nói không tệ hơn;
   - độ trễ hết tiếng → chốt lượt không tăng quá ngưỡng thống nhất trước.
3. Phát lại các cuộc gọi lỗi đã lưu (dump) vẫn cho kết quả đúng.
4. Test suite + `make check` (CI) đạt.

---

## 6. Những điều **không** làm

- Không thay model ASR, không cố biến model offline thành streaming bằng hàng đợi / cắt chunk.
- Không nới lỏng validator theo `expected_input` (nguy cơ "có/ừ" do ảo giác thành đồng ý).
- Không thiết kế lại Speech Admission.
- Không lọc giọng người gọi theo độ to / SNR.
- Không sửa lỗi ASR toàn cục (chỉ theo state, theo từ điển nhỏ, nếu cần).
- Không bật hai bộ khử nhiễu mạnh (trình duyệt + server) cùng lúc khi chưa đo.
- Không sửa core engine trong kế hoạch này.

---

## 7. Kế hoạch khắc phục sau lần đo đầu tiên (28/09/2026)

Phần này cập nhật quyết định triển khai dựa trên `docs/evidence/livekit-audio-plan-execution-2026-09-28.md`. **“Chưa hiệu quả” có ba nghĩa khác nhau:** có lỗi thật trong đầu ra; phép đo chưa đáng tin; hoặc tính năng chưa được thiết kế để tăng độ chính xác. Không gộp ba trường hợp này thành một kết luận.

### 7.1 Lỗi nằm ở đâu, biết chắc điều gì?

| Hạng mục | Quan sát có thể kiểm tra lại | Diễn giải đúng và điểm chưa biết |
|---|---|---|
| Hotwords | Trên 19 câu ngắn sạch, ép danh sách `AWAITING_CONFIRMATION` cho **mọi câu** làm WER ASR so decode sạch tăng **0,227 → 1,091**. Trong 19 cặp, 8 final đổi; 7 bị biến thành `KHÔNG ĐỒNG Ý`, 1 thành `ĐỒNG Ý ĐỒNG Ý`. Một câu `OK` và nhiều câu `Ừ` cũng bị ép thành `KHÔNG ĐỒNG Ý`. | Có lỗi **thiên lệch từ khóa ở decode final** khi danh sách/điểm hotword hiện tại áp quá rộng; không phải lỗi partial hay VAD. Phép thử không có state thật, nên chưa chứng minh kết quả khi chỉ dùng đúng state. `modified_beam_search`, điểm hotword 8 và beam 64 được đổi cùng lúc: chưa tách được tác động từng biến. |
| Câu ngắn bị mất | Với profile production trên 19 câu sạch: ASR có final ở **19/19**, nhưng **10/19** không thành turn; cả 10 final bị mất là `Ừ`. `is_meaningful_text()` liệt kê `ừ` trong `_FILLER_WORDS`. Profile target còn 1 câu không có final và vài final khác không thành turn. | Lỗ mất câu chính ở **TurnController sau ASR**, không phải model nghe không ra tiếng. Để biết phần mất thêm của target do Silero, Validator hay ngưỡng thời lượng cần tách từng thành phần. Bộ 19 đoạn được chọn bằng ASR và chưa có nhãn nghe tay, nên chưa được coi là 19 câu đúng chuẩn. |
| Confidence | Trên tập proxy: 82 final thật ngắn, 9 final giả ngắn; ngưỡng 0,6 chặn **4/9 giả** và chặn nhầm khoảng **25/82 thật**. AUC xấp xỉ **0,62**; không có mẫu giả nào có confidence thấp hơn mọi mẫu thật. | Phân phối chồng lấn; một ngưỡng chung không đảm bảo không bỏ câu thật. `ys_log_probs` đo mức model tin vào chữ nó tạo ra, không xác định ai đang nói và không bắt được lỗi nghe nhầm có xác suất cao. Số mẫu giả quá ít, nhãn thật còn dựa vào decode sạch. |
| Khử nhiễu NC/BVC | Capture hiện có dài 577,55 s input nhưng ~611–615 s ở đầu ra; plain chỉ **64/111** trial có tương quan đường bao ≥0,9 với input. Tương quan trung vị NC/BVC lần lượt **0,43/0,39**; thuật toán căn từng trial bằng đường bao của chính tín hiệu đã lọc. | **Chưa thể chấm hiệu quả plugin.** Khử nhiễu làm đổi đường bao nên phép căn này có thể khớp sai đoạn; ba bộ lọc chạy đồng thời cũng có thể gây tải, nhưng chưa đo CPU để xác nhận. Số câu ngắn bị mất trong bảng NC/BVC là tín hiệu cần điều tra, không là kết luận nhân quả. |
| VAD dùng chung | B1 (target, classifier riêng) và B2 (target, dùng chung) cho cùng kết quả trên bộ web/short đã đo. | Đây là refactor nhằm **đồng nhất ranh giới và giảm số lần phân loại**, không phải bộ lọc giúp WER tự giảm. Cờ `SPEECH_SHARED_DETECTOR=true` hiện chọn Silero bất kể `VAD_PROVIDER`, nên so với production WebRTC phải tách thay đổi provider khỏi thay đổi chia sẻ classifier. |
| Tinh chỉnh timeout / partial | Đã có cờ nhưng chưa có đo tải máy production và bộ nhãn câu ngắn. | Chưa có bằng chứng “không hiệu quả”; đây là hạng mục **chưa được thử đúng điều kiện**. |

### 7.2 P0 — Sửa phép đo trước khi tối ưu thuật toán

1. **Đóng băng bộ dữ liệu có nhãn tay.** Gán nhãn nguồn nói (`caller`, `background`, `noise`), chữ người gọi thực sự nói, `BotAction.state`, thời điểm bắt đầu/kết thúc và có/không cần thành turn. Nghe lại 19 đoạn short hiện có; thêm ít nhất 50 câu ngắn từ nhiều cuộc gọi/người nói, trong đó ≥30 câu xác nhận ngắn (`ừ`, `có`, `không`, `vâng`, `OK`), ≥30 câu intent/đặt-hủy-đổi lịch, ≥50 đoạn chỉ giọng nền/nhiễu. Ghi manifest + hash file trong `temp/`; chỉ commit thống kê không chứa giọng/PII. **Xong khi:** hai người kiểm lại các trường hợp bất đồng và mỗi case có nhãn/nguồn rõ ràng; tập thử không còn dùng ASR làm ground truth.
2. **Vết quyết định theo từng case.** Bộ replay xuất mốc VAD start/end, ASR partial/final, confidence, quyết định Validator, `is_meaningful_text`, turn được gửi, latency và CPU. Phân loại thất bại thành `không VAD`, `không final`, `bị filter`, `bị Validator`, `sai chữ`, `lượt giả`. **Xong khi:** mọi case rớt turn chỉ ra đúng cửa đã chặn; không suy nguyên nhân từ WER tổng hợp.
3. **Sửa phép đo NC/BVC.** Thu riêng từng biến thể (plain, NC, BVC), cùng file PCM và cùng mức âm; không chạy ba plugin đồng thời trên máy 2 vCPU. Ghi monotonic timestamp/frame count ở nguồn và đầu nhận, đặt khoảng lặng/marker giữa trial, đo CPU/RSS và số frame mất. Căn bằng mốc thời gian/marker đã ghi, sau đó nghe kiểm thủ công các đoạn căn lỗi. Không dùng tương quan đường bao của tín hiệu đã lọc làm mốc duy nhất. **Xong khi:** ≥95% trial có ranh giới đầu/cuối kiểm được, không bị cắt chữ; chỉ chấm những trial hợp lệ và báo rõ số trial loại ra. Sau đó thử A/B/C bằng `?audio_profile=browser|raw|aec`, ghi `MediaStreamTrack.getSettings()` để biết trình duyệt thực sự áp dụng gì.
4. **Tách các biến thử.** Mọi A/B dùng cùng version code, cùng manifest và cùng profile VAD/Validator; đổi một tham số mỗi lần. Lưu cả JSON từng case, bảng chênh lệch cặp và p50/p90 latency. Chạy lặp lại để xác nhận kết luận không đổi theo lịch xử lý.

### 7.3 P1 — Khắc phục theo nguyên nhân, có cổng nhận rõ ràng

**Câu ngắn / VAD / Validator**From time, who should know? Can I?

1. Chạy ma trận `WebRTC/Silero × Validator off/on` trên bộ có nhãn; sau đó mới so classifier riêng/dùng chung với **cùng provider**. Sửa cấu hình detector dùng chung để chọn provider tường minh; không để cờ “dùng chung” tự đổi WebRTC thành Silero. Báo số câu rớt tại từng cửa và false turn theo từng state.
2. Thử ngoại lệ **chỉ cho final `Ừ`/`Dạ`/`Vâng` ở `AWAITING_CONFIRMATION`**, sau khi VAD đủ thời lượng và Validator có bằng chứng âm thanh đạt. Không cho partial ngắn tự xác nhận barge-in. Core vẫn quyết định ý nghĩa nghiệp vụ. **Chỉ nhận** nếu tăng số câu xác nhận thật thành turn, không tạo thêm false confirmation trong tập nhiễu/giọng nền có nhãn; nếu không đạt, giữ filter cũ và hỏi lại người dùng bằng luồng nghiệp vụ hiện có.
3. Sau khi chọn provider, quét `silero_min_silence_ms`, `vad_end_silence_ms`, `turn_max_wait_after_vad_end_ms` từng trục. **Chỉ nhận** cấu hình giảm p90 thời gian hết tiếng → turn ít nhất 20% mà không tăng WER, lượt giả, câu ngắn rớt hoặc lượt bị tách so baseline đã gán nhãn. Replay dump lỗi 26/09 ở mỗi cấu hình.

**Hotwords**

1. Tách ba nhánh `greedy`, `beam không hotwords`, `beam + hotwords`; đo thêm các mức `hotwords_score` thấp hơn 8 và beam size độc lập. Chỉ gắn danh sách theo state thật; thêm negative control là tên người, `OK`, `Ừ`, câu không nói về lịch. So cả text **final** và turn, không chỉ WER.
2. Kiểm tra từng mục danh sách: loại hoặc giảm điểm `KHÔNG ĐỒNG Ý` trước tiên vì đã chèn sai 7/19 lần trong phép thử rộng. **Chỉ nhận** khi không còn chèn cụm đồng ý/không đồng ý vào negative control, recall câu nghiệp vụ có nhãn tăng, WER toàn bộ không tăng quá 0,02 tuyệt đối, và p95 độ trễ final tăng không quá 300 ms trên máy 2 vCPU. Nếu không đạt, tắt hotwords; không dùng bộ sửa chữ toàn cục để che lỗi.

**Confidence**

1. Giữ ở chế độ log. Thu ít nhất 100 final giả ngắn và 300 final thật ngắn có nhãn người nghe, tách theo sạch/nhiễu/giọng nền/state và theo ASR đúng/sai. Vẽ phân phối, precision-recall và bảng số câu thật bị chặn ở từng ngưỡng trên tập kiểm tra độc lập.
2. **Chỉ bật cổng chặn** nếu có ngưỡng chặn được ≥30% ảo giác ngắn mà không chặn câu xác nhận thật nào trong 300 mẫu kiểm tra; giọng nền phải đo bằng nhãn *nguồn nói* riêng, vì confidence của chữ người khác có thể cao. Nếu không có ngưỡng như vậy, bỏ ý tưởng cổng confidence; tiếp tục log để chẩn đoán.

**NC/BVC, CPU và partial dài**

1. Trên capture hợp lệ, chọn giữa plain/NC/BVC bằng cặp trial: yêu cầu giảm ≥30% false turn do giọng nền, WER sạch tăng ≤0,02 tuyệt đối, không tăng số câu ngắn bị bỏ, p95 latency tăng ≤200 ms và CPU/RSS nằm trong giới hạn máy production. Đo A/B/C trình duyệt riêng; không bật hai bộ khử nhiễu mạnh cùng lúc theo ràng buộc ban đầu. Nếu không đạt, giữ xử lý browser và ưu tiên mic gần miệng/tai nghe.
2. Với audio 10–15 s và bot đang nói, so `ZIPFORMER_PARTIAL_INTERVAL_RATIO=0` với 0,05/0,1 trên máy 2 vCPU. Ghi decode calls, CPU, thời gian ra partial đầu, độ trễ xác nhận barge-in và final WER. Chỉ bật nếu giảm CPU rõ mà không làm trễ barge-in hoặc mất chữ cuối câu; final vẫn decode toàn bộ.

### 7.4 Thứ tự quyết định và rollback

`Dữ liệu có nhãn + phép đo đáng tin → câu ngắn/VAD → hotwords → NC/BVC → confidence (nếu còn lợi ích) → timeout/partial dài`. Mỗi thay đổi có cờ bật/tắt, so với baseline cùng dữ liệu và replay dump lỗi; **không đổi mặc định production** khi một cổng nhận ở trên chưa đạt. Lưu một bảng quyết định `bật / giữ tắt / bỏ` cùng số liệu và lý do cho từng cờ. Nếu phát sinh lượt xác nhận sai hoặc câu thật bị bỏ trong canary, tắt cờ tương ứng và phát lại case mới trước khi thử lại.

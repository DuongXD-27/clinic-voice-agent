# Tinh chỉnh xử lý âm thanh LiveKit cho môi trường nhiễu — 25/09/2026

Phạm vi: đường LiveKit web (mic trình duyệt → `CallBridge` → `STTPipeline` → ZipFormer →
`TurnController`/`TurnValidator`). Mọi thay đổi dưới đây đều được đo trước/sau trên cùng
dữ liệu; thay đổi nào đo không thấy lợi ích thì không đưa vào code.

## 1. Tóm tắt

**Đã sửa 3 lỗi thật** trong luồng xử lý (không phải tinh chỉnh tham số):

1. ASR nhận **trùng và đảo thứ tự** ~300 ms đầu câu → sai/mất chữ đầu câu ngay cả khi
   audio sạch.
2. TurnValidator đọc SNR của **khoảng lặng sau câu** thay vì của câu nói → bỏ các câu
   trả lời ngắn ("Dạ không", "Có", "Đúng không") dù người gọi nói rõ.
3. Bộ đánh giá độ ổn định transcript **không reset giữa các câu** → chuỗi trả lời thật
   "vâng" → "có" → "vâng" bị coi là ảo giác và bị bỏ.

**Kết quả** (WER của lượt nói gửi lên core — thấp hơn là tốt hơn):

| Điều kiện | Code cũ | Sau khi sửa | Sau khi sửa + tắt Admission |
|---|---|---|---|
| **Giọng thật của người thử nghiệm** (42 câu, so với decode audio sạch) | | | |
| Sạch | 0,066 | 0,047 | **0,044** |
| Nhiễu văn phòng, SNR 15 dB | 0,135 | 0,115 | **0,095** |
| Nhiễu văn phòng, SNR 8 dB | 0,164 | **0,120** | 0,139 |
| Nhiễu văn phòng, SNR 3 dB | 0,241 | 0,212 | **0,188** |
| **Bộ 40 câu có nhãn** (37 câu có lời, so với nhãn) | | | |
| Sạch | 0,173 | 0,120 | **0,113** |
| Nhiễu văn phòng, SNR 15 dB | 0,187 | 0,207 | **0,153** |
| Nhiễu văn phòng, SNR 8 dB | 0,213 | 0,223 | **0,203** |
| Nhiễu văn phòng, SNR 3 dB | 0,303 | 0,317 | **0,290** |

"Code cũ" và "Sau khi sửa" chạy với cấu hình `.env` local hiện tại (Admission bật,
Validator bật, VAD Silero).

**Khuyến nghị cấu hình:** tắt Speech Admission (`SPEECH_ADMISSION_ENABLED=false`) — xem
mục 5. Mặc định trong `config/speech.yaml` và production đã là tắt; chỉ `.env` local đang bật.

**Chưa giải quyết được:** tiếng **người nói xung quanh**. Mọi phiên bản đều cho WER > 1 và
12/12 lượt "nói giả" khi chỉ có tiếng người khác (mục 6). Cần giải pháp khử giọng nền bằng
model, không phải chỉnh tham số.

## 2. Cách đo

Bộ đo mới `eval/noise-bench/bench.py` đẩy **từng frame 30 ms** qua đúng
`STTPipeline.stream()` mà worker LiveKit dùng — Silero VAD, Speech Admission, ZipFormer
chunked-offline, `TurnController` + `TurnValidator` — và ghi lại cả text ASR final lẫn
lượt nói thực sự gửi lên core. `eval/stt-bench` cũ chỉ decode batch audio sạch, không đi qua
luồng streaming nên không thấy được các lỗi ở trên.

Mỗi trial: 1,2 s đệm + câu nói + 2,0 s đệm, trộn nhiễu liên tục suốt trial.

| | Bộ `web` (chính) | Bộ `golden` (đối chiếu) |
|---|---|---|
| Nguồn câu nói | 42 câu thật (tên, ngày sinh, xác nhận) cắt từ dump LiveKit của các cuộc gọi yên tĩnh | 37 câu có lời của `eval/stt-bench` |
| Dải tần | 16 kHz đầy đủ, qua đúng mic + trình duyệt + LiveKit | 8 kHz điện thoại, nâng lên 16 kHz |
| Tham chiếu | Model decode chính đoạn đó khi sạch | Nhãn người viết (chỉ tính câu không có chữ số) |
| Trial | 42 sạch, 84 mỗi mức nhiễu (2 đoạn nhiễu khác nhau/câu) | 37 sạch, 74 mỗi mức nhiễu |

Nhiễu văn phòng: các đoạn không có tiếng nói (theo Silero) cắt tự động từ 80 bản dump
LiveKit thật, chỉ lấy đoạn có nhiễu nghe được (≥ 20 dB). Mỗi mức nhiễu có thêm 12 trial
**chỉ có nhiễu** để đếm lượt nói giả.

Chỉ số "so với decode sạch" tách ảnh hưởng của nhiễu + luồng streaming khỏi lỗi vốn có
của model — không cần nhãn. Nhãn có chữ số ("14") bị loại vì model luôn viết bằng chữ
("mười bốn"), làm WER sai lệch có hệ thống.

So sánh với code cũ: tạo git worktree của commit `45d1a90` và chạy cùng bộ đo với
`NOISE_BENCH_SRC=<worktree>/src` — cùng dữ liệu, cùng đoạn nhiễu, chỉ khác code.

## 3. Các thay đổi đã áp dụng

### 3.1. Mỗi frame chỉ tới ASR một lần, đúng thứ tự

**Vấn đề.** `STTPipeline._fanout()` có hai bộ đệm preroll độc lập:

- `_vad_preroll` (300 ms) flush vào ASR khi VAD chính báo `speech_start`;
- `_admission_preroll` (600 ms) flush khi Admission chuyển REJECT → ADMIT.

Khi Admission tắt, mọi frame đã được gửi thẳng vào ASR, nên `_vad_preroll` gửi **lại** các
frame đó. Khi Admission bật, các frame đó đang nằm trong `_admission_preroll`, nên hai lần
flush **chồng lấn và đảo thứ tự**.

**Bằng chứng.**

- Thí nghiệm tách biệt (8 frame, VAD báo `speech_start` ở frame 3): ASR nhận
  `[1, 2, 3, 1, 2, 3, 4, 5, 6, 7, 8]` ở cả hai chế độ Admission.
- Truy vết trên audio thật (`STT_ID_09`, sạch): ASR nhận frame `[90..99]` rồi **nhảy lùi**
  về `[83..187]`. Partial ra "ĐỦ CÁI BIẾT", "DŨNG BÍCH DŨNG", final chỉ còn "DŨNG" cho câu
  "Tôi là Đỗ Đức Dũng".
- Trên 37 câu có nhãn, audio **sạch**, 7 câu bị luồng streaming làm sai chữ đầu so với
  chính model decode batch ("A LÔ" → "A LÔ A LÔ", "VÂNG TÔI SẼ ĐẾN" → "TÔI SẼ ĐẾN"…). Sau
  khi sửa, "A LÔ" và "TÔI LÀ ĐỖ ĐỨC DŨNG" đúng trở lại; các câu còn lại có nguyên nhân khác,
  chưa xử lý.

`_vad_preroll` được thêm ngày 24/09 để sửa lỗi mất chữ "Tôi". Lỗi đó thực chất nằm trong
`ZipFormerASR.stream()` và đã được sửa đúng chỗ bằng pre-speech 300 ms của ZipFormer (commit
`45d1a90`), nên `_vad_preroll` vừa thừa vừa gây hại.

**Sửa.** Gỡ `_vad_preroll` (`src/speech/asr/pipeline.py`). `_admission_preroll` là bộ đệm
duy nhất ở tầng pipeline.

**Tác động đo được.** WER mức ASR trên bộ có nhãn, sạch: 0,153 → 0,120. WER mức ASR trên
giọng thật, nhiễu văn phòng 15/8/3 dB: 0,130/0,153/0,217 → 0,102/0,119/0,201. Ở điều kiện
sạch trên giọng thật, mức ASR chênh 0,033 → 0,040 (~2 từ/300 từ, có câu tốt lên có câu xấu
đi, trong mức dao động).

**Test.** `test_each_frame_reaches_asr_once_in_order_without_admission`,
`test_each_frame_reaches_asr_once_in_order_with_admission` — đã xác nhận cả hai **fail
trên code cũ**. Ba test `test_vad_preroll_*` cũ bị thay thế vì chúng khẳng định chính hành
vi sai (và không phát hiện được lỗi vì chuỗi frame kết thúc ngay tại `speech_start`).

### 3.2. TurnValidator đọc SNR của cả câu nói

**Vấn đề.** ZipFormer chỉ phát final sau ~1,1 s im lặng (Silero giữ trạng thái speech thêm
0,5 s + chờ 0,6 s). Lúc đó pipeline đưa cho Validator SNR của **frame mới nhất — luôn là
im lặng**. Validator có luật "câu ≤ 2 từ và SNR < 3 dB → DROP", nên câu trả lời ngắn nào
cũng bị bỏ.

**Bằng chứng.** Truy vết `STT_CF_08` ("Dạ không", audio sạch): Validator nhận `rms=1.0`,
`snr=-13.6 dB` → DROP, không có lượt nói nào tới core. Câu 3 từ trở lên thoát vì luật SNR
không áp dụng. Trên giọng thật, audio sạch: code cũ bỏ 4/42 câu ASR đã nhận đúng.

**Sửa.** `UtteranceEvidenceTracker` (`src/speech/audio/noise_tracker.py`) tích luỹ năng
lượng các frame có tiếng nói của đoạn hiện tại; SNR = năng lượng trung bình đoạn nói / nền
nhiễu. Kết quả được giữ **tối đa 3 s** sau frame nói cuối (đủ cho final tới muộn), sau đó
quay về SNR theo frame — để một ảo giác xuất hiện lâu sau (vd. VAD chính là WebRTC báo
speech trên nhiễu) không thừa hưởng SNR cao của câu thật trước đó. Chỉ `TurnController`
dùng giá trị mới; `InterruptionController` giữ nguyên SNR theo frame vì không có dữ liệu
tiếng vọng để đo tác động lên nhánh ngắt lời.

**Tác động đo được.** Sau sửa, "DẠ KHÔNG" được đánh giá `snr=43 dB` → ACCEPT. Câu bị bỏ oan,
audio sạch: giọng thật 4 → 1, bộ có nhãn 2 → 0.

**Đánh đổi.** Lượt nói giả trên nhiễu thuần: 1/72 trial (bộ có nhãn, văn phòng 15 dB — một
đoạn nhiễu có âm giống giọng người, SNR 17,8 dB, ASR ra "ĐÂY"); code cũ: 0/72. Code cũ
đạt 0 vì bỏ **mọi** câu ≤ 2 từ, thật hay giả. Không ngưỡng SNR hợp lý nào chặn được đoạn
17,8 dB đó mà không chặn luôn câu trả lời thật.

**Test.** `test_short_answer_final_after_silence_is_not_dropped` (fail trên code cũ) và 4
test đơn vị cho `UtteranceEvidenceTracker`.

**Bổ sung 26/09 — bản sửa này chưa đủ.** Silero báo speech trễ ~250 ms nên phần đầu câu bị
`NoiseTracker` cập nhật thành nhiễu nền; câu ngắn vẫn có thể bị tính SNR < 3 dB và bị bỏ
(câu "hủy lịch" trong cuộc gọi thật). Xem `docs/evidence/livekit-turn-loss-2026-09-26.md` mục 2b.

### 3.3. Độ ổn định transcript xét trong từng câu

**Vấn đề.** `TranscriptEvidenceTracker` giữ cửa sổ 5 transcript gần nhất và **không bao giờ
reset**. Luật OSCILLATING (một text ngắn lặp lại xen kẽ text ngắn khác) vì vậy khớp cả
chuỗi câu trả lời thật của các lượt khác nhau.

**Bằng chứng.** `STT_SIG_03` ("Alo?" sau tiếng nhiễu đường dây): ảo giác "ĐÂY" của đoạn
trước + "A LÔ" (partial và final) → OSCILLATING → câu "A LÔ" thật bị bỏ. Trong luồng xác
nhận lịch hẹn, chuỗi "vâng" → "có" → "vâng" cũng khớp đúng mẫu này.

**Sửa.** `_drain_asr()` gọi `evidence_tracker.reset()` sau mỗi final
(`src/speech/asr/pipeline.py`).

**Tác động đo được.** Sau sửa, "ĐÂY" (ảo giác) vẫn bị DROP, "A LÔ" được ACCEPT.

**Test.** `test_stability_is_judged_per_utterance` (fail trên code cũ).

### 3.4. Trang demo: ghim phiên bản SDK, khai báo tường minh cấu hình thu âm

`livekit-demo.html` tải `livekit-client` từ CDN **không ghim phiên bản**. Bản hiện tại
(2.22.3) đã bật sẵn khử vọng, khử nhiễu, tự cân mức và `voiceIsolation` — nên không có lỗi
cấu hình nào; rủi ro là bản phát hành sau đổi mặc định mà không ai biết. Đã ghim `@2.22.3`
và khai báo `audioCaptureDefaults` tường minh (cùng giá trị mặc định + `channelCount: 1`).
**Không đổi hành vi hiện tại.** Đã kiểm tra URL tồn tại và tên tuỳ chọn khớp
`AudioCaptureOptions` của SDK; **chưa thử trên trình duyệt**.

## 4. Đã thử nhưng không áp dụng

### 4.1. Lọc "giọng người gọi" theo mức năng lượng (foreground gate)

Ý tưởng: người gọi nói gần mic nên to hơn người xung quanh; chỉ coi là "người gọi đang
nói" khi mức năng lượng gần mức giọng người gọi đã học trong cuộc gọi.

Đo trên các bản dump thật, so mức năng lượng câu theo kịch bản thử nghiệm với các đoạn nói
ngoài kịch bản trong cùng cuộc gọi (người khác, hoặc chính người thử nghiệm nói ngoài lề):
chênh lệch **trung vị chỉ 3,2 dB**, dao động từ nhỏ hơn 18 dB tới **to hơn 19,7 dB** (cuộc
gọi `f3ed5ae3`: câu "ĐÚNG RỒI" 52,6 dB trong khi tiếng nói xung quanh 72 dB). Cơ chế này sẽ
học nhầm giọng to nhất làm người gọi và chặn chính người gọi. **Đã viết rồi gỡ bỏ**, không
để lại cờ cấu hình.

### 4.2. Hạ ngưỡng xác suất Silero (0,5 → 0,4 / 0,3)

Trên giọng thật đầy đủ dải + nhiễu văn phòng, tỉ lệ frame tiếng nói Silero giữ được:

| Ngưỡng | 15 dB | 8 dB | 3 dB | Báo nhầm trên nhiễu thuần |
|---|---|---|---|---|
| 0,5 (hiện tại) | 92,2% | 88,9% | 82,9% | 0,6–3,0% |
| 0,4 | 93,5% | 91,5% | 84,4% | 2,0–5,4% |
| 0,3 | 94,5% | 92,9% | 87,3% | 5,1–7,5% |

Thêm 1–4 điểm nhưng báo nhầm tăng 2–3 lần → **giữ 0,5**.

Ghi chú: trên giọng điện thoại 8 kHz (bộ có nhãn) trong nhiễu, Silero thất thường hơn nhiều
(có lúc bỏ qua 1,5–2 s giọng nói rõ). Điều này liên quan tới đường điện thoại sau này, không
phải đường web hiện tại.

### 4.3. `modified_beam_search` thay `greedy_search` cho ZipFormer

Cải thiện mức ASR ở văn phòng 15/8 dB trên giọng thật (0,102/0,119 → 0,090/0,099) nhưng
mức lượt nói lẫn lộn, xấu hơn ở điều kiện sạch (0,047 → 0,055). Trên bộ có nhãn chỉ tốt hơn
ở 15 dB (lượt nói 0,207 → 0,197), xấu hơn hoặc bằng ở các mức còn lại. Decode cũng chậm
hơn. **Không áp dụng**, đã gỡ tuỳ chọn cấu hình thêm cho thí nghiệm.

### 4.4. Cắt bớt đoạn đuôi trước khi decode final

Final hiện decode cả ~0,6 s chờ endpoint (nhiễu thuần). Chỉ giữ 150 ms đuôi: chênh lệch
±0,01 so với không cắt, trong mức dao động. **Không áp dụng**, đã gỡ.

## 5. Khuyến nghị: tắt Speech Admission

So sánh "sau khi sửa" với Admission bật / tắt:

| | Admission bật | Admission tắt |
|---|---|---|
| Giọng thật, WER mức ASR (sạch / 15 / 8 / 3 dB) | 0,040 / 0,102 / 0,119 / 0,201 | **0,036 / 0,073 / 0,111 / 0,175** |
| Giọng thật, WER lượt nói | 0,047 / 0,115 / **0,120** / 0,212 | **0,044 / 0,095** / 0,139 / **0,188** |
| Bộ có nhãn, WER lượt nói | 0,120 / 0,207 / 0,223 / 0,317 | **0,113 / 0,153 / 0,203 / 0,290** |
| Lượt nói giả trên nhiễu thuần (72 trial) | 1 | 1 |

Tắt Admission tốt hơn ở 11/12 ô, số lượt nói giả không đổi. Lý do: sau khi Validator đọc
đúng SNR, các lớp phía sau (Validator, `is_meaningful_text`, `min_speech_ms`) đã chặn được
nhiễu; Admission không chặn thêm gì mà lại cắt mất audio thật mỗi khi Silero dao động
trong nhiễu (REJECT giữa câu → các frame ngoài 600 ms preroll bị bỏ).

Cũng giải thích vì sao với Admission bật, bộ có nhãn trong nhiễu "sau khi sửa" hơi kém
"code cũ": `_vad_preroll` cũ vô tình đẩy 300 ms thẳng vào ASR **bỏ qua Admission**, che bớt
tác hại của Admission.

Việc cần làm: đổi `SPEECH_ADMISSION_ENABLED=true` → `false` trong `.env` local. Mặc định
`config/speech.yaml` và production đã là tắt.

## 6. Vấn đề còn lại: tiếng người nói xung quanh

| Nhiễu người nói (giọng thật, 84 trial) | Code cũ | Sau khi sửa |
|---|---|---|
| Giọng nền nhỏ hơn 12 dB — WER lượt nói | 1,002 | 1,018 |
| Giọng nền nhỏ hơn 6 dB — WER lượt nói | 1,255 | 1,184 |
| Lượt nói giả khi chỉ có giọng nền | 12/12 | 12/12 |

WER > 1 nghĩa là ASR chép **nhiều từ của người khác hơn số từ đúng**, ví dụ câu "Có, tôi đến
được" ra "BẢY MƯƠI TÁM A KHÔNG CÓ TÔI ĐẾN ĐƯỢC THÁNG BA TO CHÍN BẢY TÁM". Nguyên nhân gốc:
Silero đúng khi báo "có tiếng người", nhưng không phân biệt người gọi với người khác; ZipFormer
không bao giờ thấy khoảng lặng để chốt câu, gộp hết vào một lượt. Khử nhiễu của trình duyệt
không loại được giọng người. Mục 4.1 cho thấy không tách được bằng mức năng lượng.

Đây nhiều khả năng là nguyên nhân chính khi thử ở văn phòng. Hướng đề xuất (chưa làm):

1. **Khử giọng nền bằng model phía server của LiveKit Cloud** (Background Voice
   Cancellation). SDK đang dùng (`livekit` 1.1.18) đã có tham số `noise_cancellation` ở
   `rtc.AudioStream.from_track()` — chỉ cần truyền vào tại `CallBridge._pump_track()`. Cần
   thêm gói `livekit-plugins-noise-cancellation`, chỉ chạy với LiveKit Cloud (dự án đang dùng
   Cloud). Không đo offline được bằng bộ đo này; cần thử bằng cuộc gọi thật ở văn phòng, so
   sánh bật/tắt.
2. Khi thử nghiệm ở văn phòng, dùng tai nghe có mic gần miệng — tăng chênh lệch giữa người gọi
   và giọng nền ngay từ nguồn.

## 7. Giới hạn của phép đo

- Frame được đẩy nhanh hơn thời gian thực. `TurnController` dùng đồng hồ ảo nên ngưỡng
  thời lượng đúng, nhưng timeout 300 ms sau `speech_end` chạy theo thời gian thật; vì vậy
  đôi khi lượt nói được chốt bằng partial thay vì final. Ảnh hưởng như nhau cho mọi phiên bản.
  **Bổ sung 26/09:** điều này làm số liệu cấp lượt nói (WER turn, câu bị bỏ, lượt giả) dao
  động giữa các lần chạy — cùng trial, cùng code có thể cho kết quả khác. Final ASR thì ổn
  định. Xem `docs/evidence/livekit-turn-loss-2026-09-26.md` mục 3.
- Tham chiếu của bộ giọng thật là chính model decode audio sạch; đo độ **suy giảm** do nhiễu
  và luồng streaming, không đo độ chính xác tuyệt đối.
- Bộ giọng thật chỉ có một người nói (người thử nghiệm). Giọng nền tổng hợp từ bộ có nhãn.
- **Chưa đo** nhánh ngắt lời khi bot đang nói (tiếng vọng, barge-in) — bộ đo không mô phỏng
  bot phát TTS.
- Chưa thử các thay đổi bằng cuộc gọi LiveKit thật sau khi sửa.

## 8. File thay đổi và kiểm thử

| File | Thay đổi |
|---|---|
| `src/speech/asr/pipeline.py` | Gỡ `_vad_preroll`; Validator nhận SNR cả câu; reset tracker sau final |
| `src/speech/audio/noise_tracker.py` | Thêm `UtteranceEvidenceTracker` |
| `src/speech/bundle.py` | Bỏ comment về `_vad_preroll` |
| `src/callbot/transports/http/static/livekit-demo.html` | Ghim `livekit-client@2.22.3`, khai báo `audioCaptureDefaults` |
| `tests/speech/test_pipeline_admission.py` | Thay 3 test `_vad_preroll` bằng 2 test hồi quy thứ tự/trùng lặp |
| `tests/speech/test_pipeline_validator.py` | 2 test hồi quy (câu ngắn, ổn định theo câu) |
| `tests/speech/audio/test_noise_tracker.py` | 4 test cho `UtteranceEvidenceTracker` |
| `eval/noise-bench/bench.py` | Bộ đo mới (dữ liệu/kết quả ghi vào `temp/noise-bench/`, không commit) |
| `docs/reference/livekit-voice-pipeline-2026-09-24.md` | Cập nhật theo code hiện tại |

Toàn bộ test: **2556 passed, 28 skipped**. Ruff check và format đạt trên các file Python đã
sửa. Chưa commit.

## 9. Chạy lại bộ đo

```bash
# Từ gốc repo. Cần các bản dump temp/audio/livekit_debug_web-*.wav (chỉ có trên máy dev).
PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label moi
PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label moi_golden --dataset golden
PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label moi_khong_admission \
    --set speech_admission_enabled=false
PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --compare moi moi_khong_admission
```

Mỗi lượt ~10 phút với 6 điều kiện. Kết quả chi tiết từng câu nằm trong
`temp/noise-bench/results/<label>.json`.

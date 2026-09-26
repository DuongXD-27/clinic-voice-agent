# Lượt nói bị lặp, bị ghép và bị bỏ trên LiveKit — 26/09/2026

Hai lỗi từ cuộc gọi thử trên LiveKit web (`.env` local: Speech Admission bật, Turn
Validator bật, ASR gipformer). Mọi kết luận dựa trên bản ghi `LIVEKIT_DEBUG_DUMP_AUDIO` của
chính cuộc gọi đó, phát lại qua đúng pipeline bằng `eval/noise-bench/replay_dump.py`.

| # | Lỗi | Trạng thái |
|---|---|---|
| 1 | Câu dở nằm lại trong buffer ASR → lượt giả lặp câu trước, câu sau bị ghép | **Đã sửa** |
| 2a | "Hủy lịch" bị nhận thành "thùy linh" / "tùy lịch" | Giới hạn của model ASR, chưa xử lý |
| 2b | Câu "hủy lịch" bị Turn Validator bỏ | **Đã sửa** |

## 1. Câu dở nằm lại trong buffer ASR (đã sửa)

### Hiện tượng

Cuộc gọi `web-1c94c47c`: lượt 2 lặp nguyên văn lượt 1 ("ANH TÊN LÀ NGUYỄN VĂN A NHÁ"), bot
trả lời lượt giả đó và nói đè lên câu ngày sinh; lượt 3 thành "ANH SINH ANH SINH NGÀY MƯỜI
BỐN THÁNG BA NĂM MỘT CHÍN BẢY TÁM".

Decode batch từng đoạn của bản ghi (`--offline`) — người dùng nói ngày sinh **hai lần**, mỗi
lần một "anh sinh":

| Trong file | Nội dung |
|---|---|
| 9,6–11,6 s | ANH TÊN LÀ NGUYỄN VĂN A NHÁ |
| 18,8–22,2 s | ANH SINH NGÀY MƯỜI BỐN THÁNG BA NĂM MỘT CHÍN BẢY TÁM |
| 29,1–32,4 s | ANH SINH NGÀY MƯỜI BỐN THÁNG BA NĂM MỘT CHÍN BẢY TÁM |

### Nguyên nhân

ZipFormer chỉ tự chốt câu khi thấy đủ `end_silence_ms` (600 ms) im lặng trong **các frame nó
nhận**. `_fanout()` ngừng đưa frame ở 2 chỗ mà không báo:

1. **Speech Admission hết đoạn nói** — Admission ngừng gửi im lặng đúng ở ngưỡng 600 ms và
   chặn luôn frame chạm ngưỡng, nên ZipFormer chỉ thấy 570 ms. Câu 1 nằm lại buffer; khi câu 2
   bắt đầu, preroll 600 ms im lặng của Admission được flush vào, ZipFormer đủ im lặng và chốt
   **câu 1** thành final — lượt 2 giả. Log live khớp: lượt 2 được chốt đúng 250 ms sau
   `speech_start` (= `turn_min_speech_ms`), quá nhanh để là câu mới.
2. **Bot bắt đầu nói giữa câu** — bot trả lời lượt giả trong lúc người dùng đang nói ngày
   sinh; từ đó frame không vào ASR, phần "anh sinh" nằm lại và bị ghép vào câu nói lại.

### Bằng chứng (phát lại bản ghi theo thời gian thực)

| Kịch bản | Code trước khi sửa | Sau khi sửa |
|---|---|---|
| Admission bật, không bot | Final của câu trước phát ra ở đầu câu sau, thành lượt giả | 3 lượt đúng |
| Admission bật, giả lập bot nói 19,35–28,75 s | "ANH SINH NGÀY ANH SINH NGÀY MƯỜI BỐN…" | 3 lượt đúng |
| Admission tắt, không bot | 3 lượt đúng | 3 lượt đúng |
| Admission tắt, giả lập bot nói đè | "ANH SINH NGÀY ANH SINH NGÀY…" | 3 lượt đúng |
| Code trước 25/09, Admission bật | "ANH ANH SINH NGÀY…" + lượt giả "ANH ANH" | — |

Dòng cuối: lỗi có từ trước, không do thay đổi ngày 25/09.

### Sửa

`AsrSegmentEnd` (`src/speech/types.py`) — tín hiệu `_fanout()` chèn vào luồng frame của ASR
mỗi khi ngừng đưa audio:

- `FINALIZE` khi Admission chuyển ADMIT→REJECT: ASR chốt câu ngay như khi đủ im lặng
  (vẫn giữ ngưỡng `min_decode_ms` chống ảo giác trên audio siêu ngắn).
- `DISCARD` khi bot bắt đầu nói, hoặc ứng viên ngắt lời bị bác: ASR bỏ phần dở, không phát
  event — TurnController cũng bỏ đoạn này khi bot dứt lời.
- **Không** DISCARD khi `InterruptionState.INTERRUPTED`: ngắt lời đã xác nhận, bot chưa dừng
  hẳn — phần người dùng đã nói được giữ để chốt thành turn.

ZipFormer xử lý cả hai. ElevenLabs chỉ xử lý FINALIZE (commit); DISCARD bị bỏ qua vì audio
đã gửi lên server không rút lại được.

### Xác minh

- 8 test mới (`tests/speech/test_pipeline_asr_segments.py`, 3 test trong
  `tests/speech/test_zipformer_stream.py`). 6 test hồi quy thất bại trên code chưa sửa, đạt
  sau khi sửa; 2 test canh chừng (ngắt lời đã xác nhận không bị bỏ; không gửi tín hiệu thừa)
  đạt ở cả hai.
- Toàn bộ test suite: **2564 passed, 28 skipped**; ruff đạt.
- Bộ đo nhiễu (`eval/noise-bench`, Admission bật): final ASR chỉ đổi ở 11/721 trial, chủ yếu
  kịch bản nhiều người nói. Lượt nói giờ dùng final thay vì partial. Một câu có nhãn bị tách
  đôi ("ngày mười bốn tháng mười | đúng không") — khi tắt Admission câu này vốn cũng bị tách;
  kết quả "đúng" trước đây là do chính lỗi câu kẹt ghép hai đoạn lại.

### Còn lại

- Admission bật, ngắt lời đã xác nhận nhưng người dùng ngừng nói đúng lúc bot dừng: phần
  ngắt lời vẫn có thể nằm lại buffer. Chưa gặp thực tế.
- Nhánh FINALIZE của ElevenLabs chưa có test (repo chưa có fake cho provider này).

## 2. Câu "hủy lịch" bị mất và bị nhận thành "tùy lịch"

Cuộc gọi `web-2c3bf8e7`. Người dùng nói "hủy lịch" hai lần: lần 1 không thành lượt nào, lần 2
thành lượt "TÙY LỊCH EM NHÉ". Bản ghi lệch log live 43,1 s.

### 2a. ASR nghe sai — không do pipeline

Decode batch từng đoạn (không qua pipeline): lần 1 → "THÙY LINH", lần 2 → "TÙY LỊCH EM NHÉ".
Model sai ngay trên audio nguyên đoạn. Hướng thử: hotwords (contextual biasing của
sherpa-onnx) cho cụm nghiệp vụ — cần `modified_beam_search`, phải đo riêng.

### 2b. Turn Validator bỏ câu vì SNR bị tính sai (đã sửa)

Phát lại: final "THÙY LINH" → validator `snr=-3.2 dB` → câu ≤ 2 từ và SNR < 3 dB → **DROP**.
Cùng câu đó Admission đo được 17,7 dB lúc ADMIT.

Dò từng frame đường evidence của validator (`temp/validator-audit/scripts/evidence_trace.py`):

| Thời điểm | Silero (bộ của validator) | rms frame | noise floor |
|---|---|---|---|
| 67,14 s | không speech | 153 | 145 |
| 67,17–67,41 s | **không speech** | 2.700–4.300 | 145 → **1.337** |
| 67,44–68,07 s | speech | 30–1.250 (trung bình 392) | 1.337 |

**Nguyên nhân.** Silero báo speech trễ ~270 ms (đúng `min_speech_duration` 0,25 s mặc định
của sherpa-onnx). Phần to nhất của câu rơi vào khoảng trễ và bị `NoiseTracker.observe()` cập
nhật thành nhiễu nền; SNR của câu chỉ còn tính trên phần đuôi so với nền đã bị đẩy lên.
Admission không bị vì nó chỉ cập nhật floor khi `no_speech` **và** SNR thấp. Cách tính trước
25/09 (SNR frame lúc final) cũng DROP câu này (−17,8 dB); bản sửa 25/09 chưa xử lý điểm này.

**Phạm vi trên cuộc gọi thật** (350 đoạn Silero trong 87 bản ghi): 70 đoạn bị tính < 3 dB,
trong khi độ to thực của cả 70 đoạn so với nền 3 s trước nó (đo thẳng từ audio, không qua
NoiseTracker) đều ≥ 10 dB, trung vị 45 dB. Luật SNR đang bỏ câu vì số đo sai. Nhưng chữ ASR
của các đoạn đó chưa chứng minh được là người dùng nói — nên hướng sửa được chọn bằng dữ liệu
**biết chắc thật/giả** thay vì dựa vào chúng.

**Đánh giá** (`eval/noise-bench/validator_snr_eval.py`, deterministic, không ASR, không timer):
THẬT = 79 câu (bộ có nhãn + câu cắt từ cuộc gọi), bản đầy đủ và bản cắt còn 0,7 s (giống câu
1–2 từ), sạch và nhiễu văn phòng 15/8/3 dB; GIẢ = 200 trial chỉ có nhiễu (văn phòng, giọng
nền), mọi đoạn Silero báo speech ở đó đều không phải người gọi. Ngưỡng 3 dB như cấu hình:

| Cách đo | Thật ngắn bị bỏ, sạch/15/8 dB | Thật ngắn bị bỏ, 3 dB | Giả bị chặn |
|---|---|---|---|
| Cũ (trước 26/09) | 37/217 | 29/70 | 24/91 |
| B: EMA hoãn 300 ms + tính onset vào câu | 4/217 | 16/70 | 5/91 |
| C: nền = phân vị 20 | 1/217 | 3/70 | 6/91 |
| C+B | 0/217 | 1/70 | 4/91 |
| **D: nền = trung vị + tính onset vào câu (đã áp dụng)** | **0/217** | 6/70 | **20/91** |

Cách cũ chặn được 24/91 đoạn giả là **nhờ chính lỗi đo**, đổi lại bỏ 1/6 câu thật ngắn khi có
nhiễu. B/C sửa được câu thật nhưng gần như mất khả năng chặn giả (phân vị thấp làm nhiễu dao
động như giọng nền luôn "to hơn nền"). D giữ gần nguyên khả năng chặn giả (24 → 20) và không
còn bỏ câu thật ở sạch/15/8 dB. Ở 3 dB, 6/70 câu thật vẫn bị bỏ — đúng thiết kế của luật (SNR
thật ~3 dB). Nâng ngưỡng lên 6 dB với D chặn thêm 6 đoạn giả nhưng bỏ thêm 5 câu thật ở
sạch/15/8 dB và 11 câu ở 3 dB — giữ ngưỡng 3 dB.

Trên cuộc gọi thật với D: câu "hủy lịch" 36,2 dB → thành lượt nói; 367 đoạn chỉ còn 1 đoạn
< 3 dB ("À", vốn đã bị lọc là từ đệm).

**Sửa** (`UtteranceEvidenceTracker`, chỉ đường TurnController — Admission và
InterruptionController không đổi): frame không-speech chỉ vào nền sau 300 ms, nếu Silero báo
speech trước đó thì chúng là đầu câu và được tính vào năng lượng câu; nền = trung vị 3 s frame
không-speech gần nhất (theo kịp khi nhiễu môi trường tăng thật). Code cho kết quả trùng mô
phỏng D ở 692/692 đoạn.

**Xác minh.** `test_loud_onset_reported_late_by_vad_counts_as_speech_not_noise` thất bại trên
bản 25/09, đạt trên bản mới; thêm 2 test canh chừng (âm thanh ngang nền dao động vẫn SNR thấp;
nền theo kịp nhiễu tăng). Phát lại cuộc gọi `web-2c3bf8e7`: đủ 7 lượt, có "THÙY LINH". Toàn
bộ test suite: **2567 passed, 28 skipped**.

**Còn lại.** Với các đoạn to trên cuộc gọi thật, luật SNR (đúng thiết kế) không còn chặn; nếu
có ảo giác sinh ra từ âm thanh to không phải lời nói (ho, tiếng động, bot vọng lại) thì cần
tín hiệu khác — hướng hợp lý là độ tin cậy token của ASR. Trang nghe
`temp/validator-audit/index.html` (70 đoạn) vẫn dùng được để kiểm tra điều này trên dữ liệu
thật; đoạn 03 ("THÙY LINH") là câu "hủy lịch" đã xác nhận.

## 3. Giới hạn của bộ đo nhiễu

Ở cấp **lượt nói**, `eval/noise-bench/bench.py` không ổn định giữa các lần chạy: cùng trial,
cùng code, chạy 2 lần cho kết quả khác (vd. "VẤN ĐỀ": bản cũ lần 1 bỏ / lần 2 giữ, bản mới
ngược lại). Bộ đo đẩy frame nhanh hơn thời gian thực, còn timeout 300 ms của TurnController
và thời gian decode là thời gian thật. Số liệu cấp lượt nói (kể cả báo cáo 25/09) phải hiểu
kèm sai số này; final ASR thì ổn định. Bộ đo cũng chỉ thử một câu mỗi trial nên không bắt
được lỗi xuyên câu như mục 1.

## 4. File

- Sửa: `src/speech/types.py`, `src/speech/asr/pipeline.py`, `src/speech/audio/noise_tracker.py`,
  `src/inference/asr/providers/zipformer.py`,
  `src/inference/asr/providers/elevenlabs_realtime.py`.
- Test: `tests/speech/test_pipeline_asr_segments.py` (mới), `tests/speech/test_zipformer_stream.py`,
  `tests/speech/audio/test_noise_tracker.py`.
- Tài liệu: `docs/reference/livekit-voice-pipeline-2026-09-24.md` mục 2.1, 2.2, 3, 5, 6, 10.6, 10.7.
- Công cụ: `eval/noise-bench/replay_dump.py`, `eval/noise-bench/validator_snr_eval.py` (mới).
- Dữ liệu rà soát validator (chỉ máy dev): `temp/validator-audit/` — `segments.json`,
  `items.json`, `clips/`, `index.html`, `scripts/`.

## 5. Chạy lại

```bash
# Người dùng nói gì (decode batch từng đoạn)
.venv/bin/python eval/noise-bench/replay_dump.py temp/audio/livekit_debug_web-1c94c47c-66ce-4bf6-bc0f-c10123c4e245.wav --offline
# Phát lại qua pipeline, giả lập bot nói đè
.venv/bin/python eval/noise-bench/replay_dump.py temp/audio/livekit_debug_web-1c94c47c-66ce-4bf6-bc0f-c10123c4e245.wav --bot 19.35:on,28.75:off
# Quyết định validator cho câu "hủy lịch"
.venv/bin/python eval/noise-bench/replay_dump.py temp/audio/livekit_debug_web-2c3bf8e7-f427-4afb-a556-4c8bfb5b5a3f.wav
# Đường evidence từng frame quanh câu bị bỏ (phản ánh code hiện tại)
.venv/bin/python temp/validator-audit/scripts/evidence_trace.py temp/audio/livekit_debug_web-2c3bf8e7-f427-4afb-a556-4c8bfb5b5a3f.wav 66.8 68.8
# So sánh cách đo SNR trên dữ liệu biết chắc thật/giả
set -a; . ./.env; set +a; .venv/bin/python eval/noise-bench/validator_snr_eval.py
```

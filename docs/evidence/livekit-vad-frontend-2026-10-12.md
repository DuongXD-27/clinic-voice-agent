# Evidence: Khử nhiễu chỉ cho bộ phân loại tiếng nói (Silero) trên LiveKit — 12/10/2026

Phạm vi: đường LiveKit (web và SIP), phần audio đi vào bộ phân loại tiếng nói dùng chung
(`SharedSpeechDetector`) — `speech/audio/vad_frontend.py`, `STTPipeline._fanout`. ASR, chốt lượt
(TurnController), Validator, tăng âm giọng nhỏ không đổi; **ASR vẫn nghe audio gốc**.

| # | Việc | Kết quả |
|---|---|---|
| 1 | Bộ đo `eval/noise-bench/frontend_eval.py`: 3 bộ có nhãn (golden, PM, VietMed — hội thoại y khoa thật 8 kHz), nhiễu DEMAND + đường phố / TV thật, giọng nhỏ, khử nhiễu trình duyệt, kênh SIP có `phone_overrides`, đếm lượt giả trên đoạn chỉ nhiễu | **Giữ** — công cụ đo |
| 2 | Phát hiện: kênh điện thoại (8 kHz, G.711) **Silero điếc trong nhiễu** — mất 11/89 (văn phòng 8 dB), 51/89 (giao thông 5 dB), 76/89 (đường phố 5 dB), 86/89 (căng tin 5 dB) câu; tiếng đường phố Việt Nam làm mất câu cả trên web (46/89, qua khử nhiễu trình duyệt 15/89) | Điểm yếu đã đo, chưa sửa mặc định |
| 3 | Front-end khử nhiễu cho Silero (`vad_frontend`: GTCRN / WebRTC NS (+AGC) / DPDFNet), kết quả gắn với frame gốc | **Thêm, TẮT mặc định** — cứu gần hết câu mất trong nhiễu, nhưng thêm lượt giả khi nền là giọng người (TV, căng tin) |
| 4 | Silero bật cờ trên im lặng số sau khi khử nhiễu (ASR bịa "Ừ", "EM" cuối câu) | **Sửa** — nền nhiễu trắng −70 dBFS (`vad_frontend_floor_dbfs`) |
| 5 | Chế độ "hold" (bắt đầu đoạn nói khi cả bản gốc lẫn bản khử nhiễu cùng gắn cờ, giữ theo bản khử nhiễu) | **Từ chối, đã gỡ** — không cứu được câu mất, giọng nhỏ mất thêm 14 → 29/89 |
| 6 | Bật SIP: `vad_frontend: gtcrn` + `quiet_speech_gain_enabled: true` trong `phone_overrides` | **Chưa bật — chờ owner**: số đo và cách bật ghi sẵn trong config/speech.yaml |

## Vì sao làm ở bộ phân loại, không ở ASR

Khử nhiễu đưa thẳng vào ASR đã thử nhiều lần và luôn làm GipFormer tệ đi (WebRTC NS, Speex,
RNNoise, GTCRN, DPDFNet, DeepFilterNet3, Krisp, LiveKit NC/BVC, ai-coustics —
[pm-preprocess-neural-2026-10-02.md](pm-preprocess-neural-2026-10-02.md),
[livekit-audio-plan-execution-2026-09-28.md](livekit-audio-plan-execution-2026-09-28.md) §8): dấu vết
khử nhiễu là thứ model chưa gặp lúc huấn luyện. Lần này không đụng vào thứ ASR nghe.

Nhưng chính Silero quyết định ASR nghe đoạn nào: đoạn ZipFormer bắt đầu ở frame Silero gắn cờ đầu
tiên (trừ pre-roll), kết thúc sau 600 ms không có cờ, audio final cắt ở frame có cờ cuối + 300 ms;
TurnController chốt lượt theo sự kiện VAD. Không có cờ thì ASR không hề được gọi.

## Thiết kế

`STTPipeline._fanout` đưa frame (sau tăng âm giọng nhỏ nếu có) qua `VadFrontend.process`, rồi
`SharedSpeechDetector.classify(frame, analysis=...)`: bộ phân loại nghe bản đã xử lý, kết quả gắn với
frame GỐC — mọi consumer (VAD chính, bộ chốt câu của ASR, bằng chứng SNR, tăng âm, ngắt lời) tra lại
theo frame như trước. ASR, mức âm cho SNR, tiếng vọng vẫn nhận frame gốc.

- `vad_frontend`: `off` | `webrtc` (WebRTC NS của libwebrtc qua `livekit.rtc`) | `webrtc_agc` (thêm
  AGC) | `gtcrn` / `dpdfnet` (`sherpa_onnx.OnlineSpeechDenoiser`). Chỉ với `vad_provider=silero`: đầu
  ra có độ dài thay đổi theo bước hop của bộ khử nhiễu, Silero tự gom cửa sổ 512 mẫu (cắt lại cho đúng
  30 ms sẽ thêm trễ). Thiếu model / thư viện: cảnh báo, chạy như `off`.
- `vad_frontend_floor_dbfs` (mặc định −70): nhiễu trắng nền cộng sau khử nhiễu (mục 4).
- `vad_frontend_gain_db`: tăng âm sau khử nhiễu, chỉ cho bộ phân loại (đo ở màn lọc, không dùng).
- Dockerfile tải `gtcrn_simple.onnx` (520 KB) và đặt `VAD_FRONTEND_MODEL_PATH`, để bật bằng config
  không cần build lại image.

Chi phí (1 luồng CPU, frame 30 ms):

| Front-end | CPU / frame 30 ms | Trễ thêm |
|---|---|---|
| WebRTC NS (+AGC) | 0,14 ms (RTF 0,005) | 0 |
| GTCRN | ~2 ms (RTF 0,067) | 0 (nhả mẫu ngay trong lần gọi nhận vào) |
| DPDFNet baseline / 2 | 6,6 / 9,3 ms | 60 / 30 ms |

Mỗi cuộc gọi LiveKit chạy trong process riêng (livekit-agents): GTCRN ~7% một lõi cho cuộc gọi đó.

## Cách đo

`eval/noise-bench/frontend_eval.py` (mới):

- `pipeline`: đúng `STTPipeline.stream()` của worker (bench.run_pipeline: Silero, GipFormer,
  TurnController + Validator, đồng hồ ảo; `speaker_gate_mode=off` vì độ trễ của bộ đo sai khi cổng
  giọng bật). `--channel phone` áp `phone_overrides` như worker làm với participant SIP (bench.py thì
  không). WER lượt so với nhãn người — chuẩn hoá: chữ hoa, bỏ dấu câu, số đọc thành chữ (năm 19xx đọc
  từng chữ số như người gọi đọc ngày sinh), dấu thanh kiểu mới ("HÒA") như tokens GipFormer. Trễ chốt
  lượt là giây ảo từ hết câu tới lúc chốt (không gồm thời gian decode). Lượt giả: số đoạn 8 s CHỈ có
  nhiễu (người gọi im lặng) thành lượt; `--noise-only --noise-trials 36` cho phép đếm nhiều hơn.
  Các cấu hình dùng chung seed theo thứ tự trial — so được từng cặp trial.
- `vad`: chỉ Silero (nhanh) — câu bị bỏ sót hẳn (không có đoạn cờ ≥ 240 ms quanh câu), lúc nhả cuối
  câu, báo nhầm trên đoạn chỉ nhiễu.

Dữ liệu có nhãn (89 câu mỗi điều kiện trong `pipeline`):

| Bộ | Nguồn | Đặc điểm |
|---|---|---|
| golden | `eval/stt-bench` | 37 câu điện thoại thật của người gọi, 8 kHz |
| pm | `temp/PM_Public_Eval_STT` (`sach`) | 31 câu đọc thật 16 kHz, giọng Hà Nội, câu thoại callbot |
| vietmed3 | VietMed test ([HF](https://huggingface.co/datasets/leduckhai/VietMed), MIT) | hội thoại y khoa thật 8 kHz, nhiều vùng miền; 3 câu mỗi `rec_condition` (Tel, Consultation, Diagnosis, Talkshow, Podcast, Lectures, News), 2–10 s |
| (vad) vietmed4, web, short | như trên / dump LiveKit | web/short không nhãn |

Nhiễu: `office` (nền thật cắt từ dump LiveKit), `cafe` (DEMAND PCAFETER — căng tin, nhiều người nói),
`traffic` (DEMAND STRAFFIC), `hallway` (DEMAND OHALLWAY), `street` (PM `duong.wav` — đường phố Việt
Nam), `tv` (PM `tv.wav` — TV có người nói), `babble` (3 giọng golden); DEMAND:
[zenodo 1227121](https://zenodo.org/records/1227121) (CC BY-SA 3.0). Biến thể: `~q25` cả cuộc gọi nhỏ
25 dB (câu đầu cuộc gọi — tăng âm giọng nhỏ chưa kịp chạy), `~bns` khử nhiễu trình duyệt (WebRTC NS +
lọc thông cao như `livekit-client` mặc định) trước khi tới worker.

```bash
python eval/noise-bench/frontend_eval.py pipeline --label base --channel phone \
    --datasets golden,pm,vietmed3 --conditions clean,office@8,cafe@5,traffic@5 \
    --set speaker_gate_mode=off --set vad_frontend=off
python eval/noise-bench/frontend_eval.py pipeline --label gtcrn --channel phone ... \
    --set vad_frontend=gtcrn --set vad_frontend_floor_dbfs=-70
python eval/noise-bench/frontend_eval.py pipeline --label halluc --channel phone --datasets golden \
    --conditions cafe@5,office@8,traffic@5,street@5,hallway@5,tv@10,babble@6 --noise-only --noise-trials 36 ...
python eval/noise-bench/frontend_eval.py report base gtcrn
```

Kết quả thô: `temp/aq/results/` (không commit). Máy đo đang tải nặng (load 30–60), nên ZipFormer chạy 1
luồng ở các lần sau (`ZIPFORMER_NUM_THREADS=1`) — không đổi kết quả vì bộ đo dùng đồng hồ ảo.

## Kết quả — kênh điện thoại (SIP mô phỏng: 8 kHz, G.711)

Ô: WER lượt · câu không thành lượt (/89) · trễ chốt lượt p50/p90 (s). GTCRN = `vad_frontend=gtcrn`,
nền −70 dBFS.

| Điều kiện | Hiện tại | GTCRN | Lượt giả đoạn chỉ nhiễu (/12) |
|---|---|---|---|
| sạch | 0,086 · 1 · 1,09/1,99 | 0,085 · 1 · 1,16/1,93 | — |
| văn phòng 8 dB | 0,207 · 11 · 1,16/2,05 | **0,102 · 1** · 1,24/2,00 | 0 → 0 |
| giao thông 5 dB | 0,628 · 51 · 1,01/2,02 | **0,124 · 3** · 1,21/1,96 | 0 → 0 |
| đường phố 5 dB | 0,889 · 76 · 0,95/1,26 | **0,167 · 2** · 1,22/2,42 | 0 → 0 |
| hành lang 5 dB | 0,242 · 11 · 1,06/1,96 | **0,101 · 2** · 1,22/2,00 | 0 → 0 |
| căng tin 5 dB | 0,979 · 86 · — | **0,201 · 4** · 4,68/4,70 | 0 → 1 |
| TV nói 10 dB dưới người gọi | 0,522 · 46 · 1,04/2,06 | 0,344 · 2 · 4,68/4,70 | (bảng dưới) |

Trên từng bộ (văn phòng 8 dB): golden 0,306 → 0,106, PM 0,228 → 0,050, VietMed 0,137 → 0,128.
Mất câu ở bản hiện tại là mất hẳn: ASR không có final nào (Silero không gắn cờ frame nào). Trễ chốt
lượt trong căng tin / TV chạm trần bộ đo: tiếng người phía sau giữ "đang nói" tới hết trial.
Trễ trên golden sạch +0,2 s p50 (0,79 → 0,99): bản hiện tại nhả nhanh một phần vì đuôi trial mô phỏng
là im lặng số tuyệt đối (G.711 lượng tử dither thành 0), đường SIP thật thường có nền đường dây.

**Lượt giả** (`--noise-only`, 36 đoạn 8 s mỗi loại nền, mức như trial có câu):

| Nền (người gọi im lặng) | Hiện tại | GTCRN nền −70 | GTCRN nền −60 |
|---|---|---|---|
| văn phòng 8 dB | 1 ("ĐÂY") | 0 | 0 |
| giao thông, đường phố, hành lang | 0 | 0 | 0 |
| căng tin | 0 | **3** ("EM RẤT LÀ XIN LỖI", "CHÚNG TÔI RẤT LÀ XIN LỖI"…) | 3 |
| TV có người nói | 0 | **31** ("VÂNG ĐỒNG Ý RỒI CHÍN BA BỐN LĂM"…) | 32 |
| 3 người nói gần (babble) | 36 | 35 | 35 |

Nhiễu không phải giọng người: không thêm lượt giả nào. Nền là giọng người: GTCRN giữ giọng (đúng việc
của nó), Silero nghe được, ASR chép lời TV / người xung quanh — bản hiện tại không có lượt giả ở đó vì
nó cũng không nghe được chính người gọi (TV: mất 46/89 câu). Nâng ngưỡng Silero cho bản khử nhiễu
(0,6–0,8, màn lọc `vad`) không tách được: báo nhầm trên nền căng tin vẫn 17–24/24 đoạn.

**Giọng nhỏ** (`level_eval.py --channel phone`, golden, 2 câu khởi động; WER lượt, `phone_overrides`):

| | sạch 0 / −15 / −25 dB | văn phòng 20 dB 0 / −15 / −25 dB | ảo giác văn phòng |
|---|---|---|---|
| hiện tại (tăng âm tắt) | 0,120 / 0,147 / 0,367 | 0,207 / 0,593 / 0,973 | 1 / 0 / 1 |
| GTCRN | 0,113 / 0,140 / 0,400 | 0,100 / 0,133 / 0,393 | 0 / 0 / 0 |
| GTCRN + `quiet_speech_gain_enabled` | 0,127 / **0,100** / **0,260** | 0,107 / **0,127** / **0,313** | 1 / 0 / 0 |

Tăng âm cho SIP bị tắt 11/10 vì tiếng lạo xạo G.711 làm Silero báo nhầm; có front-end thì không còn
thêm lượt ảo giác ở các điều kiện này.

**Ngắt lời** (`barge_in_eval.py`, câu bot đầu tiên, có tiếng vọng): GTCRN làm xác nhận ngắt lời chậm
hơn và ít hơn ở điện thoại echo −30 dB — xác nhận 26 → 16/39, trễ lượt p90 1,48 → 3,21 s, mất chữ người
gọi 0,51 → 0,57; một lần bot tự ngắt lời vì tiếng vọng (0 → 1/12) ở cả −30 và −20 dB. Web: trễ lượt
p90 1,86 → 3,35 s (−30 dB), 2,04 → 3,19 s (−20 dB), số xác nhận gần như không đổi.

## Kết quả — kênh web (16 kHz)

Ô như trên. `webrtc_agc` = WebRTC NS + AGC, nền −70 dBFS.

| Điều kiện | Hiện tại | GTCRN | WebRTC NS + AGC | Lượt giả (/12) |
|---|---|---|---|---|
| sạch | 0,085 · 1 · 1,11/1,92 | 0,090 · 1 · 1,16/1,93 | 0,083 · 0 · 1,09/1,92 | — |
| cả cuộc gọi nhỏ 25 dB | 0,357 · 14 · 2,35/4,68 | 0,327 · 22 · 1,49/2,68 | **0,149 · 1** · 1,19/2,02 | — |
| văn phòng 8 dB | 0,120 · 1 · 1,46/2,24 | 0,113 · 0 · **1,27/1,97** | 0,105 · 0 · 1,34/2,39 | 0 → 0 → 0 |
| hành lang 5 dB | 0,123 · 1 · 1,48/2,54 | 0,117 · 1 · **1,20/1,97** | 0,112 · 1 · 1,37/2,44 | 0 → 0 → 0 |
| giao thông 5 dB, qua khử nhiễu trình duyệt | 0,153 · 1 · 1,43/2,54 | 0,155 · 2 · **1,11/1,96** | 0,153 · 1 · 1,23/2,27 | 0 → 0 → 1 |
| đường phố 5 dB | 0,650 · 46 · 0,89/1,92 | **0,205 · 6** · 1,26/2,38 | 0,229 · 3 · 1,24/2,40 | 0 → 1 → 1 |
| đường phố 5 dB, qua khử nhiễu trình duyệt | 0,352 · 15 · 1,11/1,98 | 0,245 · 3 · 1,18/2,35 | **0,232 · 2** · 1,31/2,51 | 0 → 1 → 4 |
| căng tin 5 dB | 0,236 · 6 · 4,68/4,70 | 0,205 · 5 · 4,68/4,70 | 0,200 · 4 · 4,68/4,70 | 1 → 1 → 2 |
| căng tin 5 dB, qua khử nhiễu trình duyệt | 0,247 · 4 · 4,68/4,69 | 0,254 · 5 · 4,68/4,70 | 0,220 · 3 · 4,68/4,70 | 4 → 7 → 4 |

Cả cuộc gọi nhỏ 25 dB trên từng bộ: golden (8 kHz) 0,340 → GTCRN 0,736 (GTCRN nén mất giọng điện
thoại nhỏ) → WebRTC AGC 0,268; PM 0,394 → 0,087 → 0,054; VietMed 0,347 → 0,213 → 0,130.

**Lượt giả, 36 đoạn mỗi loại nền** (web):

| Nền | Hiện tại | WebRTC NS + AGC |
|---|---|---|
| văn phòng, hành lang, giao thông | 2, 0, 0 | 2, 0, 0 |
| căng tin / qua khử nhiễu trình duyệt | 1 / 9 | 2 / 11 |
| đường phố qua khử nhiễu trình duyệt | 0 | **17** (toàn "Ừ" — bộ lọc từ đệm giữ "ừ" như câu trả lời có) |
| TV có người nói | 0 | **33** |

Kênh web đã qua khử nhiễu trình duyệt nên thường sạch (nền trung vị −82,5 dBFS); lợi ích front-end ở
web chủ yếu là trễ chốt lượt trong nhiễu đều (−0,2…−0,3 s p50, −0,3…−0,6 s p90 với GTCRN), giọng nhỏ
câu đầu cuộc gọi (WebRTC AGC) và đường phố — nhưng cả hai đều thêm lượt giả.

## Màn lọc chỉ Silero (web, 157 câu: golden + PM + VietMed + web + câu ngắn)

Câu bị bỏ sót hẳn · lúc nhả cuối câu (ms, trung bình các bộ) · đoạn chỉ nhiễu có báo nhầm (/12):

| Điều kiện | Gốc | WebRTC NS | WebRTC NS+AGC | GTCRN | GTCRN +6 dB | GTCRN +12 dB | DPDFNet |
|---|---|---|---|---|---|---|---|
| sạch | 2 · 600 | 2 | 0 | 6 | 6 | 3 | 15 |
| nhỏ 25 dB | 46 · 877 | 60 | 10 | 46 | 23 | 8 | 54 |
| nói xa 15 dB (văn phòng 20 dB) | 32 · 1166 | 34 | 8 | 27 · 573 | 11 | 7 | 37 |
| văn phòng 8 dB | 2 · 885 · 0 | 3 · 667 · 0 | 2 · 671 · 0 | 7 · 607 · 3 | 7 · 615 · 3 | 5 · 637 · 4 | 13 · 637 · 7 |
| đường phố 5 dB | 84 · 0 | 20 · 0 | 25 · 1 | 15 · 0 | 8 · 0 | 4 · 4 | 7 · 3 |
| giao thông 5 dB | 7 · 937 · 0 | 7 · 986 | 4 · 978 | 5 · 607 · 0 | 4 · 607 · 2 | 3 · 622 · 4 | 9 |
| hành lang 5 dB | 3 · 941 · 2 | 4 · 870 · 4 | 4 · 866 · 5 | 6 · 600 · 2 | 4 · 607 · 5 | 2 · 622 · 6 | 9 · 652 · 10 |
| căng tin 5 dB | 2 · 2081 · 12 | 0 · 12 | 0 · 12 | 0 · 2602 · 12 | 0 · 12 | 0 · 12 | 15 · 675 · 3 |

DPDFNet nén cả tiếng nói ngắn (sạch: 15/157 câu bị bỏ sót, câu ngắn 11/19) và tốn 6,6 ms/frame + 60 ms
trễ — loại. Tăng âm cho bộ phân loại sau GTCRN cứu giọng nhỏ nhưng tăng báo nhầm ở văn phòng / hành lang.

## Silero bật cờ trên im lặng số sau khi khử nhiễu

Lần đo đầu (GTCRN, không nền) có lượt thêm chữ cuối câu trên audio SẠCH: "…MỘT CHÍN BẢY TÁM **Ừ**"
(golden STT_DOB_07, kênh điện thoại), "…TIẾNG BẾP **EM**", trễ chốt lượt +1,5 s; web: STT_ID_05,
STT_ID_09 thêm "Ừ". Lần theo từng frame: sau câu, audio là im lặng số (toàn 0), bản thô và bản khử nhiễu
giống hệt nhau, nhưng Silero nghe bản khử nhiễu (trước đó câu nói rất sạch, đuôi tắt dần tới −110 dBFS)
**bật cờ "đang nói" giữa đoạn toàn 0** 0,65 s; ASR decode đoạn đó ra "Ừ". Silero nghe bản thô (có nền
đường dây −75 dBFS trước khi về 0) thì không. Ca khác (golden STT_SIG_03 "Alo?"): tiếng động rất nhỏ
(−53…−65 dBFS) trước câu — khử nhiễu xoá nền xen giữa, các cụm tiếng nhỏ thành "giọng sạch", Silero gắn
cờ từ 1,8 s tới hết câu, lượt "A LÔ" mất.

Sửa: cộng nhiễu trắng nền cố định sau khử nhiễu. Ba ca trên, chạy lại đúng trial qua pipeline đầy đủ:

| Ca | Gốc | GTCRN | Nền −80 | Nền −70 | Nền −60 |
|---|---|---|---|---|---|
| STT_DOB_07 | đúng, 8,13 s | thêm "Ừ", 9,63 s | đúng, 8,13 s | đúng, 8,67 s | đúng, 8,91 s |
| STT_SIG_04 | "…BÍT", 7,95 s | "…BẾP EM", 9,45 s | "…BÍT", 7,95 s | "…BÍT", 7,95 s | "…BÍP", 7,98 s |
| STT_SIG_03 | "A LÔ" | mất lượt | "A LÔ" (final thừa "ĐÂY" bị bỏ) | như −80 | "A LÔ" |

Chọn −70 dBFS. Cả bộ: web sạch 0,095 → 0,090 (gốc 0,085), hành lang 0,146 → 0,117, giao thông 0,179 →
0,155; điện thoại sạch mất lượt 2 → 1, văn phòng 0,119 → 0,102.

## Đã thử và loại — chế độ "hold"

Ý tưởng: chỉ bắt đầu đoạn nói khi cả Silero trên bản gốc lẫn Silero trên bản khử nhiễu cùng gắn cờ
(điểm bắt đầu là tập con của bản hiện tại — không thể thêm lượt giả), đã đang nói thì giữ theo bản khử
nhiễu (nhả cuối câu nhanh trong nhiễu). Lượt giả đúng là không tăng (điện thoại 36 đoạn mỗi loại: tổng 1
như hiện tại; web: TV 0 → 1, căng tin qua trình duyệt 9 → 7). Nhưng:

| Điều kiện (ALL) | Hiện tại | hold |
|---|---|---|
| web cả cuộc gọi nhỏ 25 dB | 0,357 · 14 | **0,474 · 29** (GTCRN nén giọng nhỏ → điều kiện "cả hai cùng gắn cờ" chặn mất) |
| web văn phòng 8 dB | 0,120 · 1 · 1,46/2,24 | 0,131 · 1 · 1,26/1,97 |
| điện thoại văn phòng / giao thông | 0,207 · 11 / 0,628 · 51 | 0,203 · 11 / 0,602 · 51 (vẫn điếc) |
| web đường phố 5 dB | 0,650 · 46 | 0,616 · 47 |

Đã gỡ code, chỉ giữ số đo.

## Kiểm chứng

| Lệnh / test | Kết quả |
|---|---|
| `tests/speech/audio/test_vad_frontend.py` (mới, 8 ca): bản phân tích rỗng không thay bằng frame gốc; tăng âm chỉ cho bộ phân loại; nền −70 dBFS thay im lặng số; thiếu model chạy như `off`; pipeline gửi frame gốc cho ASR trong khi bộ phân loại nghe front-end; GTCRN thật khử nhiễu và không giữ quá một frame; WebRTC giữ đúng độ dài frame | Pass |
| `STT_EVAL_ENABLED=false python -m pytest -o pythonpath=src tests` (config mới: `vad_frontend: off`) | 5334 passed, 9 skipped |
| `ruff check` / `ruff format --check` (src, tests, eval/noise-bench) | Pass |

## Còn mở

- **Bật cho SIP hay không** là quyết định của owner (config/speech.yaml `phone_overrides` ghi sẵn số đo
  và hai khoá cần thêm): SIP ở chỗ ồn hiện gần như không nghe được người gọi; bật thì nghe được, nhưng
  TV / người xung quanh thành lượt khi người gọi im lặng và ngắt lời chậm hơn. Nên đi cùng cổng giọng
  người gọi (`speaker_gate_mode`, model CAM++ chưa có trong image Docker — 08/10 chặn 36/36 lượt chỉ có
  giọng người khác trên mô phỏng).
- Mọi số ở đây là mô phỏng (nhiễu trộn, G.711 mô phỏng); chưa có dump cuộc gọi SIP thật nào để đo nền
  đường dây thật.
- Web: đường phố Việt Nam vẫn làm mất 15/89 câu dù qua khử nhiễu trình duyệt; câu đầu của người gọi nói
  nhỏ mất 14/89 — WebRTC AGC cho Silero cứu được (1/89) nhưng thêm "Ừ" trên tiếng đường phố.
- Căng tin / TV: trễ chốt lượt chạm trần đo (tiếng người phía sau giữ "đang nói") ở mọi cấu hình.

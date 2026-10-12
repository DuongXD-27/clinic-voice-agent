# Evidence: Chọn VAD cho LiveKit STT — Silero v4 / v5 / v6, TEN, FireRedVAD, WebRTC — 13/10/2026

Phạm vi: bộ phân loại tiếng nói dùng chung của đường LiveKit (`SharedSpeechDetector` — VAD chính, bộ
chốt câu của ZipFormer, SNR của Turn Validator, ngắt lời), web và SIP. ASR, TurnController,
Validator, tăng âm giọng nhỏ không đổi. HTTP `/v1/stt` vẫn Silero v4.

| # | Việc | Kết quả |
|---|---|---|
| 1 | Bộ đo mức model `eval/vad-bench/vad_compare.py` (mới): 6 VAD qua CÙNG bộ làm mượt của production, 271 câu Việt có nhãn khung, 30 điều kiện, 26 loại nền chỉ nhiễu, testset nhãn tay của TEN VAD; ngưỡng mặc định và ngưỡng hiệu chỉnh trên nửa A / đánh giá trên nửa B; KTC 95% bootstrap | **Giữ** — công cụ đo |
| 2 | So 6 VAD | **Silero v6.2.3 tốt nhất cân bằng**: bỏ sót câu −10,9 điểm % [−12,5; −9,4] so với v4; báo nhầm trên nhiễu không phải giọng người 6,20% → 3,96% thời gian; nhả cuối câu trong nhiễu đều p90 1,19 → 0,77 s; 1,3% một lõi. Là model duy nhất vẫn bỏ sót ít hơn v4 khi bị ép báo nhầm không hơn v4 ở cả hai loại nền |
| 3 | Chạy v6 qua sherpa-onnx (đường production hiện tại) lệch bản chính thức: 98,3% khung trùng, đầu câu muộn p50 30 ms / p90 60 ms; qua pipeline WER web kém hơn 0,008 [0,003; 0,012] | **Thêm** `SileroOnnxClassifier` (onnxruntime, đúng `OnnxWrapper` chính thức + máy trạng thái của sherpa): với v4 trùng sherpa 100% khung |
| 4 | Pipeline đầy đủ, cặp trial cùng seed, 110 câu có nhãn người mỗi điều kiện | Điện thoại: WER lượt 0,482 → 0,160 [Δ −0,352; −0,291], mất lượt 338 → 11/880; người gọi nói nhỏ 0,382 → 0,204, mất lượt 80 → 41/330. Web: 0,236 → 0,171 [Δ −0,078; −0,053], mất lượt 137 → 32/1430; với pre-roll 1000 ms của nhánh `fix/stt-noise-turn-loss`: 0,261 → 0,187 [Δ −0,095; −0,054], mất lượt 120 → 22/880. Nhiễu không phải giọng người (văn phòng, đường phố, giao thông, hành lang, xe buýt, nhà ga, tiếng động trong nhà): lượt giả không tăng (web 3 → 0, điện thoại 0 → 0); căng tin web 7 → 7, điện thoại 0 → 0 |
| 5 | Đổi lại | Người gọi im lặng mà nền là giọng người (TV, đài, người khác nói): lượt giả web 154 → 203/216, điện thoại 157 → 206/216 (v4 đã chép 71–73%); tiếng người không lời (ho, cười…) +1/24 web, +2/24 điện thoại; ngắt lời có tiếng vọng điện thoại: bot tự ngắt lời 1/12 (v4 0) ở cả −30 và −20 dB, xác nhận ở −30 dB 26 → 17/39 |
| 6 | Bật mặc định? | **Chưa** — theo quy tắc không thêm lượt giả. Một khoá `silero_vad_version: v6` (cả hai kênh) hoặc trong `phone_overrides` (chỉ SIP); Dockerfile tải sẵn model (sha256 cố định). Chờ owner |

## Vì sao đo VAD

Silero quyết định ASR nghe đoạn nào: đoạn ZipFormer bắt đầu ở frame có cờ đầu tiên (trừ pre-roll),
kết thúc sau 600 ms không cờ, final cắt ở frame có cờ cuối + 300 ms; TurnController chốt lượt theo sự
kiện VAD. Không có cờ thì ASR không được gọi. 12/10 đã đo: Silero v4 trên kênh SIP mô phỏng gần như
không gắn cờ trong nhiễu (mất 11–86/89 câu —
[livekit-vad-frontend-2026-10-12.md](livekit-vad-frontend-2026-10-12.md)). Lần này đổi chính model.

## Ứng viên

| VAD | Bản / nguồn | Chạy bằng | CPU (giây CPU / giây audio, 1 luồng) |
|---|---|---|---|
| Silero v4 (đang chạy) | ONNX bản k2-fsa (`silero_vad.onnx`, 644 KB) | sherpa-onnx | 0,0127 |
| Silero v5.1.2 | ONNX chính thức snakers4/silero-vad (MIT) | onnxruntime | 0,0133 |
| Silero v6.2.3 | ONNX chính thức snakers4/silero-vad (MIT, 2,3 MB) | onnxruntime (sherpa-onnx: 0,0243) | 0,0133 |
| TEN VAD | thư viện dựng sẵn của TEN-framework/ten-vad, hop 256 mẫu | ctypes (cần libc++) | 0,0188 |
| FireRedVAD Stream-VAD | DFSMN nhân quả 568K tham số, fbank + CMVN | PyTorch (nạp `weights_only=True`) | 0,0124 |
| WebRTC VAD mode 1 / 3 | py-webrtcvad, khung 30 ms, nhị phân | C | 0,0003 |

## Cách đo — mức model (`eval/vad-bench/vad_compare.py`)

- **Giọng có nhãn khung 10 ms**: 271 câu — VIVOS (`temp/datasets/vivos/test.parquet`: 240 câu đọc, 64
  người nói, 16 kHz) + PM (31 câu thoại callbot thu thật, Hà Nội). Nhãn lấy từ năng lượng audio SẠCH trước khi trộn (khung trong 40 dB
  so với khung to nhất của câu, lấp khoảng < 150 ms giữa từ, bỏ cụm < 50 ms) — không dùng model hay
  ASR nào để gán nhãn. Đối chiếu thêm 30 file nhãn tay của TEN VAD testset (LibriSpeech, GigaSpeech,
  DNS Challenge).
- **Luồng**: 3 câu nối nhau, nghỉ 0,6–2,5 s, nhiễu trộn liên tục cả luồng, SNR tính trên đoạn có
  giọng. 30 điều kiện × 90 luồng (270 câu) — tổng 14,9 giờ; 26 loại nền chỉ có nhiễu × 10 đoạn 20 s
  (1,4 giờ).
- **Điều kiện**: sạch, cả cuộc gọi nhỏ 20 / 30 dB, vang RT60 0,6 s; văn phòng (nền thật cắt từ dump
  LiveKit) 15 / 5 dB; DEMAND ([zenodo 1227121](https://zenodo.org/records/1227121)) căng tin 10 / 5,
  giao thông 10 / 5, hành lang, xe buýt, nhà ga, quảng trường, bếp, phòng khách 5 dB; đường phố Việt
  Nam (PM `duong.wav`) 10 / 5 / 0 dB; ESC-50 (tiếng người không lời, trong nhà, ngoài đường) 5 dB;
  qua khử nhiễu trình duyệt (WebRTC NS + lọc thông cao như `livekit-client`); kênh điện thoại (8 kHz,
  G.711 μ-law) sạch / văn phòng / đường phố / căng tin / giao thông; TV có người nói.
- **Cùng hậu xử lý cho mọi model**: xác suất theo cửa sổ của từng model → `smooth` (đúng
  `SileroVadModel::IsSpeech` của sherpa-onnx: bắt đầu khi > θ liên tục 250 ms, giữ khi > θ − 0,15, nhả
  sau 500 ms dưới θ). So model, không so cách hậu xử lý của từng thư viện. Silero v6 qua sherpa chạy
  đúng lớp production (cờ của sherpa, không qua `smooth`).
- **Chỉ số**: câu bỏ sót (cờ phủ < 50% khung có giọng), trễ nhận ra đầu câu, nhả cuối câu p50 / p90,
  câu bị cắt vụn, khoảng nghỉ ≥ 1,3 s bị nối liền; trên đoạn chỉ nhiễu: % thời gian báo nhầm; AUC khung
  (xác suất thô, không phụ thuộc ngưỡng).
- **Ngưỡng**: θ = 0,5 (mặc định của mọi model) và θ hiệu chỉnh trên nửa A (luồng chẵn / lẻ), báo cáo
  trên nửa B. Hiệu số câu bỏ sót so với v4: KTC 95% bootstrap theo luồng.

```bash
python eval/vad-bench/vad_compare.py run --label full1 --vivos 240 --noise-streams 10 --tenset \
    --models silero_v4,silero_v5,silero_v6,sherpa_v6,ten,firered,webrtc1,webrtc3,gtcrn_v4 \
    --workers 11 --libcxx <thư mục có libc++.so.1>
python eval/vad-bench/vad_compare.py report --label full1
```

## Kết quả mức model (θ = 0,5, nửa B)

Câu bỏ sót / số câu:

| Nhóm tình huống | Silero v4 | Silero v5 | **Silero v6** | v6 qua sherpa | TEN | FireRed | WebRTC 1 | WebRTC 3 |
|---|---|---|---|---|---|---|---|---|
| sạch / nhỏ / vang (540) | 25 | 27 | **14** | 20 | 8 | 15 | 4 | 110 |
| nhiễu nền đều (1755) | 184 | 67 | **56** | 72 | 130 | 61 | 8 | 16 |
| tiếng động rời ESC-50 (405) | 18 | 21 | **8** | 11 | 10 | 9 | 0 | 1 |
| qua khử nhiễu trình duyệt (270) | 19 | 12 | **9** | 10 | 22 | 6 | 5 | 8 |
| kênh điện thoại (675) | 364 | 46 | **30** | 33 | 220 | 11 | 1 | 4 |
| nền là giọng người (405) | 27 | 4 | **9** | 8 | 1 | 1 | 1 | 1 |
| **hiệu so với v4** (trừ nền giọng người), điểm % | 0 | −9,3 [−10,8; −7,7] | **−10,9 [−12,5; −9,4]** | −10,1 [−11,7; −8,6] | −4,9 [−6,0; −3,9] | −11,1 [−12,6; −9,5] | −13,6 | −10,0 |

Trong nhiễu nền đều (1755 câu): trễ đầu câu p50 · nhả cuối câu p50 / p90 (s) · câu cắt vụn · khoảng
nghỉ bị nối:

| Silero v4 | Silero v5 | **Silero v6** | v6 qua sherpa | TEN | FireRed | WebRTC 1 | WebRTC 3 |
|---|---|---|---|---|---|---|---|
| 0,33 · 0,77/1,19 · 36 · 15 | 0,32 · 0,62/0,81 · 38 · 8 | **0,32 · 0,62/0,77 · 45 · 9** | 0,36 · 0,66/0,81 · 39 · 7 | 0,32 · 0,66/1,42 · 42 · 52 | 0,29 · 0,57/0,97 · 73 · 45 | 0,00 · 2,54/13,51 · 22 · 714 | 0,00 · 2,28/12,64 · 36 · 625 |

Kênh điện thoại: trễ đầu câu p50 v4 0,51 s, v6 0,32 s (v4 chỉ bắt được câu to, và bắt muộn).

Báo nhầm trên đoạn chỉ nhiễu (% thời gian, nửa B):

| Nền | Silero v4 | Silero v5 | **Silero v6** | v6 qua sherpa | TEN | FireRed | WebRTC 1 | WebRTC 3 |
|---|---|---|---|---|---|---|---|---|
| nhiễu không phải giọng người (19 loại, gồm im lặng, ESC-50, điện thoại) | 6,20% | 1,59% | **3,96%** | 3,63% | 14,63% | 8,81% | 66,06% | 57,42% |
| nền có giọng người (TV 5 / 10 / 15 dB, căng tin) | 36,08% | 70,20% | **56,02%** | 58,11% | 79,23% | 88,40% | 93,62% | 84,93% |

Chi tiết đáng chú ý: xe buýt 30,8% → 16,3%; quảng trường 21,6% → 9,8%; phòng khách 53,9% → 44,8%.
Trong nhóm có giọng người, v6 báo nhầm ÍT hơn v4 trên căng tin (5 dB 88,7% → 8,8%; 10 dB 68,7% → 3,3%)
nhưng NHIỀU hơn hẳn trên TV: `tv.wav` 10 dB v4 0,0%, mọi model khác 95–99% — v4 "không nghe" file TV
này, nhưng cũng bỏ sót 20/135 câu của người gọi nói trên nền TV đó (v6: 0/135).

AUC khung (xác suất thô):

| Điều kiện | Silero v4 | Silero v5 | **Silero v6** | TEN | FireRed |
|---|---|---|---|---|---|
| sạch | 0,985 | 0,981 | **0,982** | 0,986 | 0,990 |
| nhỏ 30 dB | 0,909 | 0,977 | **0,977** | 0,989 | 0,986 |
| đường phố 0 dB | 0,881 | 0,930 | **0,937** | 0,879 | 0,959 |
| căng tin 5 dB | 0,916 | 0,947 | **0,949** | 0,893 | 0,936 |
| điện thoại, đường phố 5 dB | 0,907 | 0,947 | **0,959** | 0,888 | 0,937 |
| điện thoại, căng tin 5 dB | 0,907 | 0,914 | **0,946** | 0,862 | 0,916 |
| TV 10 dB | 0,939 | 0,922 | **0,904** | 0,856 | 0,747 |
| TEN VAD testset (nhãn tay) | 0,891 | 0,902 | **0,934** | 0,941 | 0,942 |

**Ở cùng mức báo nhầm** (θ hiệu chỉnh trên nửa A sao cho báo nhầm không hơn v4 ở CẢ hai loại nền,
báo cáo nửa B): Silero v6 (θ 0,95) vẫn bỏ sót ít hơn v4 −3,8 điểm % [−5,4; −2,1]; v5 +3,6 [+2,0;
+5,2], TEN +28,4 [+26,7; +30,3], FireRed +0,4 [−1,2; +2,1] — không model nào khác làm được.

Vì sao không chọn:

- **FireRedVAD**: AUC cao nhất ở nhiều điều kiện, bỏ sót ngang v6, nhưng ở cùng ngưỡng báo nhầm nhiễu
  thường 8,81% (v6 3,96%), nền giọng người 88%, cắt vụn câu 73 vs 45, nối khoảng nghỉ 45 vs 9; chạy
  bằng PyTorch (thêm phụ thuộc lớn vào image).
- **TEN VAD**: kênh điện thoại bỏ sót 220/675 câu (v6 30), báo nhầm nhiễu thường 14,6%; cần libc++.
- **WebRTC VAD**: gần như luôn bật trong nhiễu (báo nhầm 57–66% thời gian, nhả cuối câu p90 > 12 s).
- **Silero v5**: báo nhầm nhiễu thường thấp hơn v6 (1,59%) nhưng nền giọng người cao hơn (70%), bỏ sót
  nhiều hơn ở sạch / nhỏ (27 vs 14) và điện thoại (46 vs 30).

## Silero v6 qua sherpa-onnx lệch bản chính thức

Production chạy Silero bằng `sherpa_onnx.VoiceActivityDetector`. Nạp ONNX v6 vào đó chạy được, nhưng
cờ khác bản chính thức (`OnnxWrapper` của snakers4: cửa sổ 512 mẫu + 64 mẫu ngữ cảnh, trạng thái
[2, 1, 128]): trên 39 655 khung 30 ms (sạch, nhỏ 20 dB, văn phòng, đường phố, căng tin, điện thoại)
trùng 98,3%; đầu câu muộn hơn ở 78% câu, p50 30 ms, p90 60 ms. Với pre-roll 300 ms của ZipFormer web,
chừng đó đủ cắt âm đầu ở một số câu. Qua pipeline (web, 13 điều kiện, cặp trial cùng seed): WER lượt
0,178 → 0,171, hiệu −0,008 [−0,012; −0,003], câu tốt hơn 259 / tệ hơn 138, mất lượt 43 → 32/1430.

`src/speech/asr/vad/silero_onnx.py` (`SileroOnnxClassifier`): model chạy thẳng bằng onnxruntime như
bản chính thức, quyết định "đang nói" bằng đúng máy trạng thái `IsSpeech` của sherpa. Kiểm chứng: cùng
model v4 thì cờ trùng `SileroVadClassifier` (sherpa, production) 100,000% của 24 393 khung; model v6
trùng bản chính thức + `smooth` của bộ đo 100,000%. Model v4 (đầu vào x, h, c) và v5/v6 (input, state,
sr) tự nhận theo tên đầu vào của file.

(Bản phân tích đầu tiên báo "sherpa muộn ~0,3 s" là sai: script phân tích tạm làm mượt cờ của sherpa
thêm một lần. Các bảng của `vad_compare.py report` không bị lỗi này.)

## Kết quả pipeline đầy đủ (`eval/noise-bench/frontend_eval.py`)

Đúng `STTPipeline.stream()` của worker (Silero, ZipFormer, TurnController + Validator, đồng hồ ảo,
`speaker_gate_mode=off` vì độ trễ của bộ đo sai khi cổng giọng bật). 110 câu có nhãn người mỗi điều
kiện: golden (37 câu điện thoại thật, 8 kHz), PM (31 câu web thật, 16 kHz), VietMed test
([HF](https://huggingface.co/datasets/leduckhai/VietMed), MIT; 6 câu mỗi `rec_condition`, hội thoại y khoa
thật 8 kHz). `--channel phone` áp `phone_overrides` (pre-roll 1000 ms, tắt tăng âm) như worker làm với
participant SIP. Lượt giả: đoạn 8 s CHỈ có nhiễu (người gọi im lặng) thành lượt, 24 đoạn mỗi loại nền.
Hai cấu hình dùng chung seed theo thứ tự trial — so từng cặp; KTC 95% bootstrap theo câu
(`frontend_eval.py paired`).

```bash
COMMON="--datasets golden,pm,vietmed6 --noise-trials 24 --set speaker_gate_mode=off --set vad_frontend=off"
python eval/noise-bench/frontend_eval.py pipeline --label vad_phone_v4 --channel phone $COMMON \
    --conditions clean,office@8,street@5,traffic@5,hallway@5,cafe@5,esc_human@5,tv@10
python eval/noise-bench/frontend_eval.py pipeline --label vad_phone_v6o --channel phone $COMMON ... \
    --set silero_vad_version=v6 --set silero_vad_v6_model_path=src/speech/asr/vad/assets/silero_vad_v6.onnx
python eval/noise-bench/frontend_eval.py paired vad_phone_v4 vad_phone_v6o
```

### Kênh điện thoại (SIP mô phỏng: 8 kHz, G.711)

Ô trễ: trễ chốt lượt p50 / p90 (s). Lượt giả: /24 đoạn chỉ nhiễu.

| Điều kiện | WER lượt v4 → v6 | ΔWER [KTC 95%] | câu tốt hơn / tệ hơn | không thành lượt /110 | trễ v4 → v6 | lượt giả |
|---|---|---|---|---|---|---|
| sạch | 0,120 → 0,108 | −0,012 [−0,030; +0,001] | 10 / 5 | 1 → 1 | 1,16/2,00 → 1,22/1,87 | — |
| văn phòng 8 dB | 0,192 → 0,112 | −0,080 [−0,122; −0,046] | 34 / 6 | 9 → 1 | 1,24/2,11 → 1,26/1,99 | 0 → 0 |
| đường phố 5 dB | 0,835 → 0,194 | −0,642 [−0,707; −0,569] | 98 / 1 | 86 → 1 | 0,95/1,85 → 1,28/2,15 | 0 → 0 |
| giao thông 5 dB | 0,690 → 0,127 | −0,563 [−0,643; −0,482] | 87 / 3 | 64 → 0 | 1,00/1,96 → 1,23/1,99 | 0 → 0 |
| hành lang 5 dB | 0,293 → 0,113 | −0,181 [−0,248; −0,118] | 39 / 6 | 19 → 1 | 1,10/1,98 → 1,23/1,99 | 0 → 0 |
| căng tin 5 dB | 0,965 → 0,202 | −0,764 [−0,808; −0,712] | 100 / 1 | 103 → 3 | 0,92/1,65 → 1,98/4,69 | 0 → 0 |
| tiếng người không lời ESC-50 5 dB | 0,234 → 0,133 | −0,101 [−0,152; −0,058] | 35 / 10 | 10 → 2 | 1,44/3,84 → 1,29/2,05 | **0 → 2** ("MỘT", "Ừ") |
| TV nói 10 dB dưới người gọi | 0,528 → 0,294 | −0,234 [−0,326; −0,144] | 58 / 24 | 46 → 2 | 1,23/2,06 → 4,68/4,70 | **0 → 21** |
| **tất cả** | **0,482 → 0,160** | **−0,322 [−0,352; −0,291]** | 461 / 56 | **338 → 11 /880** | | 0 → 23 /168 |
| người gọi nói nhỏ 20 dB | 0,294 → 0,170 | −0,124 [−0,195; −0,054] | 31 / 20 | 16 → 8 | 2,39/2,58 → 1,28/1,88 | — |
| nhỏ 25 dB | 0,353 → 0,200 | −0,153 [−0,235; −0,077] | 47 / 21 | 22 → 13 | 2,16/4,68 → 1,31/1,90 | — |
| nhỏ 30 dB | 0,497 → 0,241 | −0,256 [−0,333; −0,179] | 61 / 8 | 42 → 20 | 2,14/4,69 → 1,35/1,93 | — |

Trễ của v4 trong nhiễu nặng trông thấp hơn vì v4 chỉ ra lượt ở vài câu to, dễ (đường phố 24/110, căng
tin 7/110). Căng tin / TV: trễ chạm trần bộ đo vì tiếng người phía sau giữ "đang nói" tới hết trial.

### Kênh web (16 kHz)

| Điều kiện | WER lượt v4 → v6 | ΔWER [KTC 95%] | câu tốt hơn / tệ hơn | không thành lượt /110 | trễ v4 → v6 | lượt giả |
|---|---|---|---|---|---|---|
| sạch | 0,105 → 0,114 | +0,009 [−0,003; +0,024] | 10 / 14 | 1 → 1 | 1,18/1,92 → 1,20/1,87 | — |
| cả cuộc gọi nhỏ 25 dB | 0,381 → 0,208 | −0,173 [−0,245; −0,103] | 70 / 18 | 17 → 12 | 2,46/4,68 → 1,31/1,89 | — |
| văn phòng 8 dB | 0,137 → 0,126 | −0,011 [−0,027; +0,002] | 21 / 14 | 3 → 0 | 1,62/2,58 → 1,23/2,01 | 1 → 0 |
| đường phố 5 dB | 0,627 → 0,209 | −0,418 [−0,502; −0,338] | 82 / 6 | 57 → 3 | 1,11/1,96 → 1,33/2,04 | 0 → 0 |
| đường phố 5 dB, qua khử nhiễu trình duyệt | 0,307 → 0,206 | −0,101 [−0,138; −0,068] | 60 / 8 | 13 → 1 | 1,22/2,04 → 1,22/2,04 | 0 → 0 |
| giao thông 5 dB, qua khử nhiễu trình duyệt | 0,143 → 0,141 | −0,002 [−0,013; +0,009] | 19 / 12 | 1 → 0 | 1,54/2,57 → 1,19/1,98 | 0 → 0 |
| hành lang 5 dB | 0,124 → 0,125 | +0,001 [−0,011; +0,012] | 13 / 13 | 2 → 0 | 1,60/2,66 → 1,25/1,98 | 0 → 0 |
| xe buýt 5 dB | 0,117 → 0,120 | +0,003 [−0,011; +0,021] | 14 / 14 | 2 → 1 | 1,52/3,44 → 1,25/1,96 | 2 → 0 |
| nhà ga 5 dB | 0,182 → 0,157 | −0,025 [−0,043; −0,008] | 22 / 10 | 5 → 2 | 1,66/2,65 → 1,28/2,04 | 0 → 0 |
| tiếng người không lời ESC-50 5 dB | 0,179 → 0,172 | −0,007 [−0,023; +0,009] | 25 / 17 | 3 → 2 | 1,42/2,46 → 1,30/2,02 | **0 → 1** ("VÂNG XIN LỖI") |
| tiếng trong nhà ESC-50 5 dB | 0,162 → 0,137 | −0,025 [−0,052; −0,001] | 23 / 14 | 5 → 3 | 1,29/2,02 → 1,26/2,00 | 0 → 0 |
| căng tin 5 dB, qua khử nhiễu trình duyệt | 0,206 → 0,219 | +0,014 [−0,018; +0,054] | 18 / 17 | 3 → 5 | 4,68/4,70 → 2,20/4,69 | 7 → 7 |
| TV nói 10 dB dưới người gọi | 0,400 → 0,288 | −0,112 [−0,180; −0,049] | 55 / 29 | 25 → 2 | 1,48/2,19 → 4,68/4,70 | **1 → 20** |
| **tất cả** | **0,236 → 0,171** | **−0,065 [−0,078; −0,053]** | 432 / 186 | **137 → 32 /1430** | | 11 → 28 /264 |

Điều kiện sạch web: golden (giọng điện thoại 8 kHz đưa vào kênh 16 kHz) 0,079 → 0,106 — câu
"Ngày 14 tháng 8 năm 1978" (STT_DOB_04) nửa đầu rất nhỏ: v6 có 8 cửa sổ liên tiếp > 0,5 (224 ms, cần
250 ms) rồi tụt, chỉ bắt được "CHÍN BẢY TÁM"; v4 giữ cả câu. Cùng câu qua kênh điện thoại thì v6 bắt
đủ. Ở mức nhỏ 25 dB, golden trên web v6 mất trọn 5 câu ngày sinh mà v4 còn ra được một phần; PM (giọng
web thật) cùng mức thì v6 tốt hơn hẳn (0,394 → 0,037). Điểm yếu này chỉ thấy khi giọng băng hẹp rất
nhỏ đi vào kênh web — kênh điện thoại thật (bảng trên, nhỏ 20–30 dB) v6 tốt hơn ở cả golden.

### Người gọi im lặng, nền là giọng người

`--noise-only --noise-trials 36`: đoạn 8 s chỉ có giọng người phía sau, mức tính so với giọng người gọi
trung vị. Đài / TV thật = VietMed News, Talkshow, Podcast; một người khác = giọng web khác người; 3
người = trộn 3 giọng golden; `tv.wav` = TV của bộ PM.

| Nền (người gọi im lặng) | web v4 → v6 /36 | điện thoại v4 → v6 /36 |
|---|---|---|
| đài / TV thật, 10 dB dưới người gọi | 32 → 36 | 33 → 36 |
| đài / TV thật, 15 dB dưới | 30 → 36 | 29 → 36 |
| một người khác nói, 10 dB dưới | 31 → 35 | 31 → 33 |
| một người khác nói, 15 dB dưới | 25 → 36 | 28 → 36 |
| 3 người nói gần, 10 dB dưới | 35 → 35 | 35 → 35 |
| TV `tv.wav`, 10 dB dưới | 1 → 25 | 1 → 30 |
| **tất cả** | **154 → 203 /216** | **157 → 206 /216** |

Không VAD nào tách được giọng người gọi với giọng người khác ở mức gần nhau — v4 cũng chép 71–73%
đoạn; nó "an toàn" với `tv.wav` vì không nghe được file đó (và vì vậy mất 25–46/110 câu người gọi nói
trên nền TV đó). Việc này thuộc cổng giọng người gọi (`speaker_gate_mode`, CAM++ chưa có trong image
Docker), không thuộc VAD.

### Ngắt lời có tiếng vọng (`barge_in_eval.py`, câu bot đầu tiên)

39 trial người gọi chen vào, 12 trial chỉ có tiếng vọng (người gọi im). Mất chữ người gọi so với chữ
ASR của chính đoạn đó lúc sạch (thiết kế sẵn của bộ đo — chỉ để so hai cấu hình); số xác nhận và số
lần bot tự ngắt lời không phụ thuộc nhãn.

| Kênh / mức vọng | xác nhận ngắt lời | trễ xác nhận p50 (s) | mất chữ người gọi | bot tự ngắt lời (chỉ vọng) | trễ lượt p90 (s) |
|---|---|---|---|---|---|
| điện thoại −30 dB | 26 → 17 /39 | 0,93 → 1,47 | 0,513 → 0,579 | **0 → 1 /12** | 1,48 → 1,36 |
| điện thoại −20 dB | 16 → 17 | 1,32 → 1,44 | 0,597 → 0,587 | **0 → 1 /12** | 1,40 → 1,50 |
| web −30 dB | 18 → 17 | 1,29 → 1,26 | 0,555 → 0,582 | 0 → 0 | 1,86 → 1,33 |
| web −20 dB | 15 → 16 | 1,32 → 1,35 | 0,592 → 0,590 | 0 → 0 | 2,04 → 1,52 |

Lần theo từng trial (chạy lại điện thoại −30 / −20 dB, cùng seed, ra đúng các số trên):

- **Xác nhận ít hơn ở −30 dB**: ứng viên ngắt lời sinh từ sự kiện VAD *bắt đầu nói*
  (`speech/turn/interruption.py`). Bot nói từ 0,5 s, người gọi chen vào lúc 1,5 s. v6 nghe được tiếng
  bot vọng lại ở −30 dB: ở 36/39 trial ứng viên mở từ tiếng vọng (~1,0 s) và VAD giữ "đang nói" qua lúc
  người gọi chen vào — không có sự kiện bắt đầu mới; chỉ 3/39 trial có ứng viên sau lúc người gọi nói
  (v4: 21/39 — v4 thường không nghe tiếng vọng nhỏ, nên lời người gọi tạo ứng viên mới). 9 trial v4 xác
  nhận mà v6 không ("KHÔNG ĐƯỢC", "TÔI LÀ NGUYỄN VĂN A"…), không trial nào ngược lại. Lời chen chưa xác nhận vẫn
  được giữ và decode khi bot dứt lời (`turn_keep_unconfirmed_barge_in`), nên chữ người gọi mất ít hơn
  nhiều so với số xác nhận (0,513 → 0,579). Ở −20 dB v4 cũng nghe tiếng vọng nên hai bên ngang nhau.
- **Bot tự ngắt lời**: cả 12 trial chỉ vọng đều có ứng viên ở cả v4 và v6; v6 xác nhận 1 trial mỗi mức
  ("Anh chị cho em xin ngày, tháng, năm sinh" ở −30 dB, xác nhận lúc 3,36 s; "Em chưa nghe rõ. Anh chị
  nhắc lại ngày…" ở −20 dB, 4,77 s) — ASR nghe đoạn vọng dài hơn và ra chữ không khớp câu bot.
- Hướng sửa nếu bật v6 (chưa làm): trong lúc bot nói, sinh ứng viên theo mức tăng xác suất / năng lượng
  so với mức tiếng vọng thay vì chỉ theo sự kiện bắt đầu nói.

### Web với pre-roll 1000 ms (nhánh `fix/stt-noise-turn-loss`, d1a19c3)

Nhánh song song đổi pre-roll web 300 → 1000 ms. Đo lại cùng trial với `--set asr_pre_speech_ms=1000`:

| Điều kiện | WER lượt v4 → v6 | ΔWER [KTC 95%] | câu tốt hơn / tệ hơn | không thành lượt /110 | lượt giả /24 |
|---|---|---|---|---|---|
| sạch | 0,100 → 0,101 | +0,001 [−0,006; +0,010] | 8 / 6 | 1 → 1 | — |
| cả cuộc gọi nhỏ 25 dB | 0,298 → 0,185 | −0,113 [−0,187; −0,043] | 45 / 20 | 17 → 11 | — |
| văn phòng 8 dB | 0,123 → 0,113 | −0,010 [−0,024; +0,004] | 13 / 3 | 2 → 0 | 0 → 0 |
| đường phố 5 dB | 0,580 → 0,204 | −0,375 [−0,459; −0,294] | 73 / 4 | 55 → 1 | 0 → 0 |
| đường phố 5 dB, qua khử nhiễu trình duyệt | 0,254 → 0,189 | −0,066 [−0,099; −0,038] | 35 / 8 | 12 → 0 | 0 → 0 |
| căng tin 5 dB, qua khử nhiễu trình duyệt | 0,193 → 0,239 | +0,046 [−0,002; +0,107] | 16 / 22 | 3 → 5 | 8 → 7 |
| tiếng người không lời ESC-50 5 dB | 0,154 → 0,150 | −0,004 [−0,023; +0,013] | 16 / 14 | 1 → 2 | 1 → 0 |
| TV nói 10 dB dưới người gọi | 0,385 → 0,316 | −0,070 [−0,149; +0,010] | 39 / 38 | 29 → 2 | 3 → 22 |
| **tất cả** | **0,261 → 0,187** | **−0,074 [−0,095; −0,054]** | 245 / 115 | **120 → 22 /880** | 12 → 29 /144 |

Pre-roll 1000 ms xoá chênh lệch ở điều kiện sạch (0,105 → 0,114 với 300 ms; 0,100 → 0,101 với 1000 ms).

**Căng tin kém hơn — do cách gộp lượt, không do VAD bỏ sót.** Dựng lại đúng trial (VietMed Lectures,
30 chữ, cùng seed): ASR ra đủ câu, Validator CHẤP NHẬN (ổn định, độ tin cậy 0,91, SNR 15,5 dB); trong
cửa sổ gộp lượt 700 ms, v6 nghe tiếng người ở căng tin ngay sau câu → final thứ hai "HẠ ĐẸP" (độ tin
cậy 0,47) gộp vào cùng lượt → cả lượt bị chấm "dao động" và bỏ, mất luôn câu thật. v4 ít nghe tiếng
nền nên ít dính. Commit fefe572 của nhánh `fix/stt-noise-turn-loss` ("drop only the noise segment
that follows an accepted sentence") sửa đúng lỗi này: chạy lại trial đó với TurnController của
fefe572 thì lượt được chốt đủ 30 chữ, chỉ bỏ "HẠ ĐẸP".

## Quyết định

- **Option tốt nhất: Silero v6.2.3 chạy qua onnxruntime** (`silero_vad_version: v6`). Hơn v4 ở mọi
  nhóm điều kiện có người gọi nói, rõ nhất trên SIP (v4 gần như điếc trong nhiễu) và người gọi nói nhỏ;
  không thêm lượt giả trên nhiễu không phải giọng người; nhả cuối câu nhanh hơn; CPU như v4.
- **Mặc định: CHƯA bật** (giữ v4). Theo quy tắc của dự án, thay đổi làm tăng lượt giả trên đoạn người
  gọi im lặng thì không bật mặc định chỉ vì WER tốt hơn: v6 thêm lượt giả khi nền là giọng người
  (+49/216 web, +49/216 điện thoại), tiếng người không lời (+1, +2 /24) và 1/12 lần bot tự ngắt lời vì
  tiếng vọng điện thoại.
- Owner quyết định một trong:
  - **Chỉ SIP** — thêm `silero_vad_version: v6` vào `phone_overrides`: SIP hiện mất 8–94% câu trong
    nhiễu (văn phòng 8 dB → căng tin 5 dB) và 15–38% câu khi người gọi nói nhỏ (v6: 0–3%, 7–18%); đổi
    lại như trên.
  - **Cả hai kênh** — `silero_vad_version: v6` (hoặc `SILERO_VAD_VERSION=v6`).
  - Nên đi cùng cổng giọng người gọi khi CAM++ vào image (chặn TV / người khác sau khi có giọng mẫu).
- Thay `vad_frontend: gtcrn` (12/10) cho việc cứu SIP: v6 làm cùng việc bằng chính model (không thêm tầng
  khử nhiễu), ~1,3% một lõi so với ~7%.

## Cấu hình

- `config/speech.yaml`: `silero_vad_version: v4` (mặc định), `silero_vad_v6_model_path`,
  `silero_threshold: 0.5`; cách bật cho SIP ghi trong khối `phone_overrides`.
- `src/speech/bundle.py` `_build_silero`: v6 → `SileroOnnxClassifier` với model v6; thiếu file v6 thì
  cảnh báo và chạy v4 (cuộc gọi không bao giờ mất VAD). v4 → `SileroVadClassifier` như trước.
- Dockerfile: tải `silero_vad_v6.onnx` từ tag v6.2.3, kiểm sha256
  `1a153a22…d8788e3` (đúng file đã đo), đặt `SILERO_VAD_V6_MODEL_PATH` — bật bằng config / biến môi
  trường, không cần build lại.

## Kiểm chứng

| Lệnh / test | Kết quả |
|---|---|
| `tests/speech/vad/test_silero_onnx.py` (mới, 8 ca): v4 qua onnxruntime trùng sherpa từng frame; bắt đầu sau 250 ms > ngưỡng, giữ trên ngưỡng − 0,15, nhả sau 500 ms; không xoá mốc im khi xác suất chen giữa hai ngưỡng; v6 gắn cờ câu TTS thật và nhả sau câu; `silero_vad_version` chọn đúng bộ phân loại; thiếu file v6 → v4 + cảnh báo; `phone_overrides` nhận khoá | Pass |
| Đổi sang khoá `silero_vad_version` (refactor): 110 trial web sạch chạy lại cùng seed | trùng 110/110 (final, lượt, thời điểm chốt) với lần đo v6 trước đó |
| `STT_EVAL_ENABLED=false python -m pytest -o pythonpath=src tests` (mặc định `silero_vad_version: v4`) | 5342 passed, 9 skipped |
| `ruff check src tests eval/noise-bench eval/vad-bench` / `ruff format --check` | Pass |
| `barge_in_eval.py` ghi được file JSON kết quả (trước đây hỏng ở bước cuối vì giá trị numpy) | chạy lại điện thoại −30 / −20 dB ra đúng số trong log cũ |

Kết quả thô: `temp/aq/vad/full1.pkl`, `temp/aq/results/pipe_*.json`, `temp/aq/barge_*.log` (không commit).

## Còn mở

- Mọi số là mô phỏng (nhiễu trộn, G.711 mô phỏng, tiếng vọng mô phỏng); chưa có dump cuộc gọi SIP thật.
- Nền là giọng người: cần cổng giọng người gọi trong image (CAM++), không VAD nào giải quyết được.
- Tiếng vọng điện thoại: v6 nghe được tiếng bot vọng lại nhỏ mà v4 bỏ qua — 1/12 lần bot tự ngắt lời ở
  cả −30 và −20 dB.
- Giọng băng hẹp rất nhỏ đi vào kênh web (golden trên web) là chỗ duy nhất v6 kém v4 rõ.

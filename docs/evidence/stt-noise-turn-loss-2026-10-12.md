# Evidence: STT LiveKit sai chữ, mất câu khi có nhiễu (12/10/2026)

## Mục tiêu

Cuộc gọi LiveKit có nhiễu thường sai vài chữ làm đổi nội dung. Cần tìm lỗi nằm ở đâu và sửa, có tính độ trễ, không thêm lượt ảo giác.

Chỉ đo trên **nhãn người**:
- golden STT: bỏ câu rỗng và câu có chữ số trong nhãn;
- câu sạch 16 kHz của bộ PM Hà Nội;
- trộn nhiễu thật ở SNR định trước: văn phòng (đoạn không có giọng cắt từ dump cuộc gọi LiveKit), TV, đường phố (của bộ PM);
- thêm 90 đoạn 6 s chỉ có nhiễu để đếm lượt giả.

Không dùng chữ ASR làm nhãn. Bộ `web` của noise-bench lấy chữ decode bản sạch làm tham chiếu nên không thấy được lỗi mà cả hai lần decode đều mắc, ví dụ chữ đầu bị cắt.

"Câu sai nghĩa" là câu có ít nhất một lỗi chạm từ quyết định nghĩa:
- phủ định: không/chưa/đừng;
- ý định: có/vâng/hủy/đổi/xác nhận/khám/lịch…;
- số, giờ, ngày.

## Kết luận

- **Khoảng một nửa lỗi khi ồn nằm ở pipeline, không ở model.**
  - Cùng audio có nhiễu, model decode đúng đoạn có lời: WER 32%.
  - Pipeline worker trên cùng audio đó: WER 61%. 224/621 câu mất hẳn.
- Hai lỗi pipeline đã sửa:
  1. Cửa sổ gộp lượt: nhiễu sau câu làm mất trọn câu thật, hoặc thêm "Ừ" vào câu.
  2. Pre-roll 300 ms cắt mất chữ đầu ngắn như "Không, …", "Khoan, …", "Dạ, …".
- Đổi model, beam search, khử nhiễu trước ASR: không giúp (mục "Đã thử, không áp dụng").
- Còn mở: Silero bỏ sót giọng trong tiếng đường phố/TV.
  - Hạ ngưỡng Silero lấy lại nhiều câu, nhưng thêm lượt giả từ tiếng TV, nên chưa bật.

## Chẩn đoán: pipeline so với cắt câu hoàn hảo

69 câu mỗi điều kiện; câu đặt giữa 1,2 s nhiễu trước và 2 s nhiễu sau.

| Điều kiện | Cắt câu hoàn hảo: WER · câu sai nghĩa | Pipeline: WER · câu sai nghĩa | Câu mất hẳn |
|---|---|---|---|
| Sạch | 7,0% · 8 | 9,1% · 14 | 1 |
| Văn phòng 10 dB | 9,1% · 10 | 14,6% · 16 | 1 |
| Văn phòng 5 dB | 9,8% · 12 | 21,5% · 22 | 3 |
| Đường phố 10 dB | 15,7% · 16 | 45,4% · 35 | 15 |
| Đường phố 5 dB | 20,7% · 23 | 80,6% · 44 | 42 |
| TV 10 dB | 30,9% · 31 | 63,7% · 42 | 24 |

Ba kiểu lỗi:

- **Chữ đầu bị cắt, kể cả khi sạch.**
  - Ví dụ: "Không, tôi chưa xác nhận" → "TÔI CHƯA XÁC NHẬN"; "Vâng, tôi sẽ đến" → "TÔI SẼ ĐẾN"; "Khoan, giờ đó không đúng" → "GIỜ ĐÓ KHÔNG ĐÚNG"; "Dạ, tôi nghe" → "TÔI NGHE".
  - Chữ đầu ngắn (~0,25 s) rồi ngừng thì không đủ `min_speech_duration` 0,25 s của Silero. Cờ tiếng nói bật ở chữ sau, trễ 0,8–1,0 s so với lúc bắt đầu nói (đo trên chính các câu này).
  - Pre-roll 300 ms của ZipFormer không với tới chữ đầu.
- **Câu thật bị bỏ vì nhiễu ngay sau câu.**
  - Ví dụ: câu "TÔI LÀ ĐỖ … DŨNG" đã qua Validator, đang chờ `turn_merge_window_ms` (700 ms), thì nhiễu sau câu thành đoạn ASR "Ừ" với partial lật qua lại.
  - Validator chấm cả lượt gộp bằng bằng chứng của đoạn nhiễu (OSCILLATING) và DROP cả câu.
  - Khi "Ừ" kém chắc thì nó bị nối vào: "TÔI LÀ BÙI VĂN A Ừ".
- **Silero không nhận ra giọng trong tiếng đường phố/TV.** Cả câu không có final ASR nào: đường phố 10 dB mất 14/69 câu, 5 dB mất 41/69.

## Đã sửa

### 1. Cửa sổ gộp chỉ bỏ đoạn nhiễu, không bỏ câu đã qua Validator

`TurnController._drop_continuation`:
- Khi lượt đã qua Validator và đang chờ cửa sổ gộp, đoạn nói tiếp được xét riêng bằng bằng chứng của chính nó.
- Đoạn chỉ có từ đệm mà đứng riêng cũng bị bỏ (cùng luật `_try_emit`), hoặc partial lật qua lại: bỏ riêng đoạn đó, chốt phần đã qua.
- Chữ thật mà kém chắc vẫn nối như trước. Ví dụ "… KHÔNG PHẢI" + "MƯỜI HAI" (0,35) trong tiếng đường phố. Luật một-hai-chữ-kém-chắc của Validator chỉ dành cho lượt đứng riêng.

Số đo trên các trial có đoạn nói tiếp trong cửa sổ gộp (24 câu, golden + PM, mọi loại nhiễu):

| | Trước | Sau |
|---|---|---|
| Câu mất hẳn | 2 | 0 |
| "Ừ" giả nối vào câu | 4 | 0 |
| WER | 56,7% | 51,7% |
| Câu sai nghĩa | 14 | 14 |
| Lượt giả trên 90 đoạn chỉ có nhiễu | 20 | 20 |

Test (fail trên code cũ):
- `test_noise_after_accepted_sentence_does_not_drop_the_sentence`;
- `test_unsure_filler_after_accepted_sentence_is_not_appended`.

Giữ hành vi cũ:
- `test_real_continuation_after_accepted_sentence_still_merges`;
- `test_confident_answer_after_accepted_sentence_still_merges`;
- `test_unsure_real_words_after_accepted_sentence_still_merge`.

### 2. Pre-roll ZipFormer 300 → 1000 ms cho web

`config/asr.yaml` `zipformer.pre_speech_ms`. Điện thoại đã dùng 1000 ms qua `phone_overrides`. Gemini Live giữ 300 ms.

| Điều kiện | 300 ms: WER · câu sai nghĩa · mất hẳn | 1000 ms |
|---|---|---|
| Sạch | 7,4% · 8 · 1 | 4,7% · 3 · 2 |
| Văn phòng 10 dB | 11,1% · 8 · 1 | 6,4% · 3 · 0 |
| Văn phòng 5 dB | 15,3% · 13 · 2 | 8,9% · 4 · 0 |
| Đường phố 10 dB | 42,6% · 23 · 12 | 28,7% · 14 · 12 |
| Đường phố 5 dB | 77,5% · 32 · 34 | 69,1% · 29 · 33 |
| TV 10 dB | 55,7% · 30 · 18 | 46,8% · 26 · 16 |
| **Có ồn (345 câu)** | **40,4% · 106 · 67** | **32,0% · 76 · 61** |
| Lượt giả trên đoạn chỉ nhiễu (văn phòng / phố / TV, 30 mỗi loại) | 3 / 0 / 17 | 3 / 0 / 17 |

Theo từng câu:
- 39 câu hết sai nghĩa.
- 7 câu mới sai. Phần lớn ở TV 10 dB: pre-roll dài kéo thêm chữ của TV ("HỦY" → "THỦY", "… XÁC NHẬN THÔNG TIN").

Lần đo 06/10 giữ 300 ms cho web vì bộ `web` cho kết quả "trái chiều". Bộ đó lấy chữ ASR của bản sạch làm nhãn, nên không thấy được chữ đầu bị cắt.

Chi phí, đo bằng noise-bench golden (speaker gate tắt để số độ trễ đúng):
- cùng số lần decode;
- tổng thời gian decode tăng 20% khi sạch, 32% với văn phòng 8 dB;
- độ trễ chốt lượt p50 không đổi (0,84 s / 1,27 s);
- WER lượt của chính bench: sạch 0,113 → 0,100, văn phòng 8 dB 0,220 → 0,147.

Mỗi lần decode thêm tối đa 0,7 s audio; final chậm thêm khoảng 12 ms (GipFormer 2 luồng: ~18 ms mỗi giây audio).

Test cơ chế pre-roll trong `tests/speech/test_zipformer_stream.py` ghim `pre_speech_ms=300`, để không phụ thuộc giá trị cấu hình.

### Cả hai sửa cùng lúc (code + cấu hình của nhánh)

| Điều kiện | Trước: WER · câu sai nghĩa · mất hẳn | Sau |
|---|---|---|
| Sạch | 7,4% · 8 · 1 | 4,7% · 3 · 2 |
| Văn phòng 10 dB | 11,1% · 8 · 1 | 6,2% · 3 · 0 |
| Văn phòng 5 dB | 15,3% · 13 · 2 | 8,7% · 4 · 0 |
| Đường phố 10 dB | 42,6% · 23 · 12 | 28,7% · 14 · 12 |
| Đường phố 5 dB | 77,5% · 32 · 34 | 69,1% · 29 · 33 |
| TV 10 dB | 55,7% · 30 · 18 | 46,8% · 26 · 16 |
| **Có ồn (345 câu)** | **40,4% · 106 · 67** | **31,9% · 76 · 61** |
| Lượt giả trên đoạn chỉ nhiễu (văn phòng / phố / TV) | 3 / 0 / 17 | 3 / 0 / 17 |

Trong bảng này, cửa sổ gộp ít khi xảy ra nên phần lớn chênh lệch đến từ pre-roll. Tác dụng riêng của sửa cửa sổ gộp xem bảng ở mục 1.

## Đã thử, không áp dụng

| Cách | Kết quả (nhãn người) | Lý do không áp dụng |
|---|---|---|
| Hạ ngưỡng Silero 0,5 → 0,35 | Có ồn: câu mất hẳn 67 → 39, câu sai nghĩa 106 → 82. Cùng pre-roll 1000 ms: mất hẳn 32, sai nghĩa 61 | Lượt giả: phố 0 → 1, TV 17 → 19; cùng 1000 ms thì TV 17 → 25 / 30 (tiếng TV thành lượt) |
| Lần ngược theo năng lượng (`onset_lookback_ms` 700) | Câu sai nghĩa khi ồn 106 → 106 | Khoảng ngừng sau chữ đầu cắt mạch năng lượng, không lần tới chữ đầu |
| TEN VAD (sherpa-onnx) thay Silero | Ngưỡng 0,5: sạch mất 32/57 câu. Ngưỡng 0,35: báo nhầm 59% frame tiếng phố | Tệ hơn Silero cả hai đầu |
| Beam search (4 đường) | Có ồn: WER 27,0% → 27,1%, câu sai nghĩa 172 → 171 | Không lợi, CPU +20% |
| Model khác có sẵn: ZipFormer-150M / NghiASR | WER có ồn 26,6% / 43,1% (GipFormer 27,0%); câu sai nghĩa 181 / 255 (GipFormer 172) | Không hơn GipFormer |
| Gemini Live | Văn phòng 0 dB WER 17,1% (GipFormer 13,6%); TV 5 dB 43,1% (50,0%) | Không hơn rõ khi ồn, thêm trễ mạng và phí |
| Khử nhiễu WebRTC (như trình duyệt), mô phỏng đã hội tụ | WER có ồn 33,0% → 31,4% | Trình duyệt đã bật sẵn: giữ nguyên, không cần thêm phía server |

Khử nhiễu đưa thẳng vào ASR (RNNoise, DeepFilterNet3, GTCRN, DPDFNet, Krisp, Quail…) đã đo 02/10, luôn tệ đi: [pm-preprocess-options-2026-10-02.md](pm-preprocess-options-2026-10-02.md).

## Còn mở

- **Silero bỏ sót giọng trong ồn đường phố/TV**, kiểu lỗi lớn nhất còn lại.
  - Hạ ngưỡng giúp nhiều nhưng thêm lượt giả từ TV.
  - Trong cuộc gọi thật, cổng giọng (`speaker_gate_mode: enforce`) có thể chặn một phần tiếng TV sau khi đã học giọng người gọi; trial ở đây đứng riêng nên chưa có giọng mẫu.
  - Cần ghi âm thật để quyết.
- **Báo trước câu nghe nhầm:**
  - Hai model độc lập (GipFormer + ZipFormer-150M) khác nhau ở từ quan trọng thì coi là chưa chắc.
  - Trên bộ có ồn, cách này bắt được 74% câu sai nghĩa của GipFormer; hỏi lại oan 3–6% câu khi sạch hoặc văn phòng, 10–20% khi phố/TV.
  - Độ tin cậy token một model chỉ đạt AUC 0,73.
  - Cần quyết định engine làm gì khi chưa chắc (hỏi lại / đọc lại).
- **Ghi âm có nhãn qua đúng đường web** (trình duyệt, Opus, LiveKit) để kiểm lại các số trên giọng thật: `temp/stt_noise/yeu_cau_thu_am.md`.

## Tái tạo

```bash
python3 eval/noise-bench/labeled_eval.py --label base --oracle
python3 eval/noise-bench/labeled_eval.py --label pre300 --set asr_pre_speech_ms=300
python3 eval/noise-bench/labeled_eval.py --compare pre300 base
```

`labeled_eval.py` dựng trial theo đúng cách đã dùng ở trên. Seed khác nên số đếm có thể lệch vài câu.

## File liên quan

- `src/speech/turn/controller.py`
- `tests/speech/turn/test_controller.py`
- `config/asr.yaml`, `config/speech.yaml`
- `tests/speech/test_zipformer_stream.py`
- `eval/noise-bench/labeled_eval.py`

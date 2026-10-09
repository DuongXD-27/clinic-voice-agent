# Evidence: tiền xử lý trước ASR cho `/v1/stt/turn` trên bộ eval PM (02/10/2026)

## Kết luận

- **Đưa vào API: cổng im lặng** (bật mặc định, tắt bằng `STT_EVAL_SILENCE_GATE=false`). Khi Silero không thấy giọng **và** cả clip nhỏ hơn −55 dBFS, API trả `text` rỗng, không gọi model; bước `VAD_NO_SPEECH` hiện trong `preprocessing.steps`.
  - Sửa lỗi K2 (bịa chữ khi im lặng) ở cả 16 kHz và 8 kHz.
  - Không câu nào từ đúng thành sai.
  - 40 câu golden giữ nguyên.
  - Thêm khoảng 30 ms mỗi lượt.
- **Không đưa vào:** lọc thông cao 100 Hz, khử nhiễu cổ điển (`noisereduce`), khử vang WPE, cắt đầu/đuôi theo VAD.
  - Thay đổi nhỏ, có ca tốt lên có ca tệ đi, nằm trong biên nhiễu của bộ đo.
  - Không bộ nào đạt tiêu chí đặt trước (plan `temp/docs/plan-preprocess-pm-eval.md` mục 7).
- **Phát hiện phụ quan trọng:**
  - Silero **không nhận ra giọng** khi có tiếng đường phố ở SNR 6 dB: xác suất cao nhất 0,31 ở 8 kHz.
  - VAD chính của đường streaming LiveKit cũng là Silero, nên trong môi trường ồn kiểu này, bot có thể không nghe thấy người gọi. Cần đo riêng trên đường streaming.
  - Đáp án của `B-TIME-02` nhiều khả năng sai (cả ba model đều nghe thêm chữ "ngày"), cần PM nghe lại.

## Cách đo

- **Bộ dữ liệu:** `temp/PM_Public_Eval_STT`, 93 file (33 thu thật + 60 biến thể nhiễu dựng bằng script), cả bản 16 kHz và bản μ-law 8 kHz.
- **Đáp án:**
  - Cột J của `tab2_dan_vao.csv` (đã gồm `loi_da_chot.csv`).
  - Bỏ 2 ca chưa chốt (`B-HOLD-01`, `B-AUD-RATE`).
  - Đáp án của `B-SIL-01` là rỗng.
- **Đường code:**
  - B0, B1, D1 gọi đúng `speech.asr.offline.transcribe_turn` của API.
  - D2–D8 dùng `eval/pm-preprocess/processors.py`, đi cùng thứ tự `_prepare`.
  - `--self-check` xác nhận khi không bật thêm bước nào, audio đưa vào model giống hệt API: 0/364 khác.
- **Model:** gipformer1.5-68M (ZipFormer offline, sherpa-onnx), giống production.
- **Chỉ số:**
  - Số câu đúng hoàn toàn (sau chuẩn hoá chữ hoa và dấu câu).
  - WER = (thay + mất + thừa) / số từ đáp án.
  - Thời gian tiền xử lý thêm.
- **Kiểm chứng ngoài bộ PM:** 40 câu golden của `eval/stt-bench` (audio điện thoại thật, có nhãn), chấm bằng `evaluate_case` của stt-bench.

Tái tạo:

```bash
pip install noisereduce==3.0.3 nara_wpe==0.0.11   # chỉ cần cho D2–D8
python eval/pm-preprocess/run.py --self-check
python eval/pm-preprocess/run.py --golden D1 D2 D3 D4 D5 D6 D7 D8
```

Đầu ra nằm ở `temp/pm-preprocess/2026-10-02/`, không commit vì chứa giọng thật:
- `report.html`: từng file, nghe được audio model đã nhận, chữ sai/mất/thừa được tô màu;
- `results.csv`;
- `summary.json`.

## Hiện trạng (trước khi sửa)

Hai đường hiện có của `/v1/stt/turn` khớp với bảng điểm PM: audio sạch WER 2,1% (PM báo 2,2%), ồn mạnh 12–13/19 câu đúng hoàn toàn.

Phân loại các câu sai của `text` (mỗi tần số khoảng 20 câu):

| Nhóm | Ca | Tiền xử lý sửa được? |
|---|---|---|
| Âm học: câu sạch đúng, ồn hoặc xa thì sai | `B-CANCEL-02` "đừng **hủy**" → "đừng GÌ/VÌ"; `B-YN-01` "lịch" → "LỰC"; `B-CANCEL-01`, `B-TIME-03`, `B-ID-01`, `B-LONG-01` | Có thể (khoảng 10 câu mỗi tần số) |
| Bịa chữ khi im lặng | `B-SIL-01`: `production` ra "Ừ", `text` khuếch đại +20 dB rồi ra "ĐÂY" | Có |
| Từ vựng | `B-TECH-01` "MRI", `B-VM-01` "bíp" (sai cả khi sạch) | Không |
| Đáp án nghi sai | `B-TIME-02`: Zipformer-68M, PhoWhisper-medium (`soat_lai.csv`) và gipformer đều nghe "…không phải **ngày** hai mươi mốt", công cụ soát vẫn ghi "khớp 100%" | Không phải lỗi model |
| Do cách dựng ca | `B-CUT-01` (cắt mất "Không"), `B-OVER-01`, `B-AUD-OVER` | Không |

## Vòng 1: theo plan, chuỗi cộng dồn

Cổng VAD chỉ dựa vào Silero ("không thấy giọng thì không gọi ASR") nằm ở đầu mọi chuỗi. Nó sửa được K2 nhưng **bỏ cả câu thật** trong ồn mạnh:

| 8 kHz, `nhieumanh` | Câu đúng hoàn toàn |
|---|---|
| B1 (hiện tại) | 13/19 |
| B1 + cổng chỉ dựa vào Silero | **1/19** (17 file bị coi là im lặng) |

Nguyên nhân là chính Silero, không phải code:

| File | Xác suất Silero cao nhất | Số frame > 0,5 | Số frame sherpa gắn cờ |
|---|---|---|---|
| `B-ID-02` sạch, 8 kHz | 0,99 | 54/105 | 65 |
| `B-ID-02_onnhe`, 8 kHz | 0,93 | 34/105 | 57 |
| `B-ID-02_nhieumanh`, 16 kHz | 0,82 | 11/105 | 23 |
| `B-ID-02_nhieumanh`, 8 kHz | **0,31** | **0/105** | **0** |

Mọi cấu hình sau đều chứa cổng này, nên số đo của lọc thông cao, khử nhiễu và khử vang ở vòng 1 không dùng được. Kết quả vòng 1 lưu ở `temp/pm-preprocess/2026-10-02-vong1/`.

Cắt đầu/đuôi theo vùng Silero (C2) cũng làm hỏng câu sạch: 27 → 25/30, vì Silero báo giọng trễ. Bước này không thử lại ở vòng 2.

## Vòng 2: cổng an toàn, đo từng bộ xử lý riêng

**Cổng an toàn:** chỉ chặn khi Silero gắn cờ giọng dưới 200 ms **và** mức giọng của cả clip dưới −55 dBFS.
- Mức giọng nhỏ nhất có thật trong bộ PM: −48,8 dBFS (biến thể nói xa).
- Tiếng phòng `B-SIL-01`: −66,8 dBFS.
- Hai câu không lời trong golden (−44,5 và −47,3 dBFS) to hơn ngưỡng, nên không bị chặn và vẫn bịa chữ như trước.

Mỗi ô: câu đúng hoàn toàn / số file · WER. Cột "+/−": số file tốt lên/tệ đi so với B1.

**16 kHz**

| Cấu hình | sạch (30) | ồn nhẹ (20) | ồn mạnh (19) | xa (18) | im lặng | +/− | Xử lý thêm p95 |
|---|---|---|---|---|---|---|---|
| B0 `production` | 27 · 2,1% | 15 · 3,6% | 12 · 7,6% | 14 · 3,4% | sai ("Ừ") | | |
| B1 `text` hiện tại | 27 · 2,1% | 16 · 3,0% | 13 · 7,0% | 14 · 3,4% | sai ("ĐÂY") | | 1 ms |
| **D1 cổng im lặng** | 27 · 2,1% | 16 · 3,0% | 13 · 7,0% | 14 · 3,4% | **đúng** | **+1 / −0** | 31 ms |
| D2 + lọc thông cao | 27 · 1,7% | 16 · 3,0% | 13 · 6,4% | 16 · 2,0% | đúng | +3 / −0 | 34 ms |
| D3 + khử nhiễu 0,5 | 27 · 2,1% | 16 · 3,0% | 12 · 6,4% | 15 · 2,7% | đúng | +2 / −1 | 47 ms |
| D4 + khử nhiễu 0,8 | 27 · 2,1% | 16 · 3,0% | 12 · 5,7% | 15 · 2,0% | đúng | +2 / −1 | 52 ms |
| D5 + khử vang | 27 · 2,1% | 16 · 3,0% | 12 · 7,6% | 16 · 1,3% | đúng | +3 / −1 | 152 ms |
| D6 + lọc thông cao + khử nhiễu 0,5 | 27 · 1,7% | 16 · 3,0% | 13 · 6,4% | 16 · 2,0% | đúng | +3 / −0 | 48 ms |
| D7 + lọc thông cao + khử nhiễu 0,8 | 27 · 1,7% | 16 · 3,0% | 13 · 5,1% | 16 · 2,0% | đúng | +3 / −0 | 53 ms |
| D8 + lọc thông cao + khử vang | 27 · 2,1% | 16 · 3,0% | 12 · 7,6% | 16 · 2,0% | đúng | +3 / −1 | 164 ms |

**8 kHz**

| Cấu hình | sạch (30) | ồn nhẹ (20) | ồn mạnh (19) | xa (18) | im lặng | +/− | Xử lý thêm p95 |
|---|---|---|---|---|---|---|---|
| B0 `production` | 27 · 2,1% | 16 · 3,0% | 12 · 7,0% | 13 · 5,4% | sai | | |
| B1 `text` hiện tại | 27 · 2,1% | 16 · 3,0% | 13 · 6,4% | 14 · 4,0% | sai | | 1 ms |
| **D1 cổng im lặng** | 27 · 2,1% | 16 · 3,0% | 13 · 6,4% | 14 · 4,0% | **đúng** | **+1 / −0** | 30 ms |
| D2 + lọc thông cao | 27 · 1,7% | 16 · 3,0% | 12 · 7,6% | 14 · 4,0% | đúng | +1 / −1 | 33 ms |
| D3 + khử nhiễu 0,5 | 27 · 2,1% | 17 · 2,4% | 13 · 6,4% | 13 · 5,4% | đúng | +2 / −1 | 51 ms |
| D4 + khử nhiễu 0,8 | 27 · 2,1% | 17 · 2,4% | 13 · 6,4% | 13 · 5,4% | đúng | +2 / −1 | 54 ms |
| D5 + khử vang | 27 · 2,1% | 15 · 3,6% | **10** · 10,2% | 16 · 1,3% | đúng | +3 / **−4** | 143 ms |
| D6 + lọc thông cao + khử nhiễu 0,5 | 27 · 1,7% | 17 · 2,4% | 12 · 7,6% | 14 · 4,0% | đúng | +2 / −1 | 47 ms |
| D7 + lọc thông cao + khử nhiễu 0,8 | 27 · 1,7% | 17 · 2,4% | 12 · 6,4% | 14 · 4,0% | đúng | +2 / −1 | 47 ms |
| D8 + lọc thông cao + khử vang | 27 · 2,1% | **14** · 4,2% | **11** · 8,3% | 15 · 2,7% | đúng | +3 / **−5** | 155 ms |

**40 câu golden** (B1: 19/40 pass, 3 câu bịa chữ, 85 lỗi / 232 từ):

| | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 |
|---|---|---|---|---|---|---|---|---|
| Pass | 19 | 19 | 19 | 19 | 19 | 19 | 19 | 19 |
| Tổng lỗi | 85 | 85 | 86 | 84 | 84 | 84 | 86 | 85 |

### Ví dụ

| File | Đáp án | B1 hiện tại | Sau xử lý |
|---|---|---|---|
| `B-SIL-01` (16k và 8k) | (im lặng) | "ĐÂY" (`production`: "Ừ") | D1: rỗng ✓ |
| `B-CANCEL-02_xa` 16k | Tôi đổi ý, đừng **hủy** nữa | ĐỪNG **VÌ** NỮA | D2, D5: ĐỪNG **HỦY** NỮA ✓ |
| `B-YN-01_xa` 16k | …xác nhận **lịch** vừa đọc | XÁC NHẬN **LỰC** | D2, D3, D5: **LỊCH** ✓ |
| `B-ID-03_nhieumanh` 8k | …Loan, **không phải** Lan | đúng | D2: "LOAN **TRẦN** LAN" ✗; D5: "LOAN **THÂN**" ✗ |
| `B-NOISE-01_nhieumanh` 16k | **Tôi** muốn xác nhận… | đúng | D3, D5: "**CÔ** MUỐN…" ✗ |
| `B-CANCEL-01_nhieumanh` 8k | …lịch **khám** này | đúng | D5: "LỊCH **TÁM** NÀY" ✗ |

### Đọc kết quả

- **D1 đạt cả bốn tiêu chí:**
  - không câu sạch nào đổi;
  - sửa K2;
  - golden giữ nguyên;
  - thêm 30 ms (dưới 100 ms).
- **Lọc thông cao (D2):**
  - Ở 16 kHz tốt nhất trong các bộ: thêm 2 câu nói xa đúng, có câu "đừng hủy" (đảo nghĩa nếu sai), không câu nào tệ đi.
  - Ở 8 kHz lại làm hỏng 1 câu ồn mạnh và không cứu được câu nào.
  - Chênh 1–2 câu trên một người nói là trong biên nhiễu, nên **chưa đủ căn cứ** để bật. Đây là ứng viên nên kiểm lại khi có bộ dữ liệu lớn hơn, nhiều người nói, có ghi âm thật.
- **Khử vang WPE (D5):**
  - Giúp rõ nhất cho nói xa: 16/18 câu, WER 1,3% ở cả hai tần số.
  - Nhưng làm hỏng 4 câu ồn mạnh ở 8 kHz, kiểu "khám" → "TÁM", "không phải Lan" → "THÂN".
  - Chỉ đáng dùng nếu biết trước clip có vang. Bộ PM tạo "nói xa" bằng vang giả lập, nên chưa chắc đúng với vang phòng thật.
- **Khử nhiễu `noisereduce`:**
  - Thay đổi ít, có tốt có xấu.
  - Đo trên tín hiệu tổng hợp: ở mức 0,5 nó giữ khoảng 66% giọng và 51% nhiễu, tức SNR chỉ tăng khoảng 2 dB, đổi lại làm méo giọng.
  - Cùng kết luận với Krisp, Quail và WebRTC NS trước đây.
- **Trần cải thiện thấp:** chỉ khoảng 10 câu mỗi tần số là lỗi âm học. Phần còn lại là từ vựng, đáp án và cách dựng ca, không sửa được bằng xử lý âm thanh.

## Giới hạn

- Một người nói, nhiễu trộn bằng script, 18–20 file mỗi điều kiện.
- Ngưỡng −55 dBFS chọn sau khi thấy mức âm của bộ PM và golden. Biên an toàn khoảng 6 dB so với giọng nhỏ nhất có thật, nhưng cần theo dõi với giọng rất nhỏ trên dữ liệu thật.
- Cổng im lặng chỉ áp cho `/v1/stt/turn` (trường `text`). Trường `production` và `/v1/calls` không đổi.

## File liên quan

- `src/speech/asr/offline.py`: `is_silent_turn`, `transcribe_turn(vad_factory=...)`.
- `src/callbot/transports/http/stt_eval.py`, `config.py` (`stt_eval_silence_gate`), `main.py`.
- `src/speech/audio/preprocess.py`: tách `_outside_regions` dùng chung.
- `eval/pm-preprocess/run.py`, `eval/pm-preprocess/processors.py`.
- Test:
  - `tests/speech/test_offline_stt.py`: `test_turn_silence_gate_*`;
  - `tests/transports/http/test_stt_eval.py`: `test_turn_returns_silence_for_room_tone_without_asr`, `test_silence_gate_can_be_turned_off`.
- `docs/reference/stt-eval-api.md`; `ui/openapi.json`, `ui/src/lib/api/schema.d.ts` (step `VAD_NO_SPEECH`).

# Evidence: khử nhiễu neural trước ASR trên bộ eval PM (02/10/2026)

Tiếp theo [pm-preprocess-2026-10-02.md](pm-preprocess-2026-10-02.md). Thử các đề xuất của `temp/docs/thamkhao3.md`: GTCRN, DPDFNet (16 kHz và bản 8 kHz riêng), DeepFilterNet3, RNNoise. Mỗi model đặt sau cổng im lặng đang bật trên API (N0), cùng bộ đo, cùng đường code.

## Kết luận

- **Không model neural nào đạt tiêu chí. Tất cả đều làm kết quả tệ hơn so với không xử lý (N0)**, kể cả ở **ồn mạnh**, đúng điều kiện chúng được kỳ vọng sẽ giúp:

  | Ồn mạnh, câu đúng hoàn toàn (19 file) | 16 kHz | 8 kHz |
  |---|---|---|
  | N0: không khử nhiễu | **13** | **13** |
  | DPDFNet 16k (baseline / 2 / 4 / 8) | 5 / 6 / 10 / 8 | 6 / 7 / 8 / 8 |
  | DPDFNet bản 8 kHz (2 / 8) | — | 9 / 10 |
  | GTCRN | 7 | 7 |
  | DeepFilterNet3 | 6 | 3 |
  | RNNoise | 3 | 7 |

- **Kiểu lỗi nguy hiểm:** khử nhiễu xoá phụ âm và từ ngắn mang nghĩa quyết định.
  - "Loan, **không phải** Lan" thành "LOAN **ÔNG PHẢI** / **TÊN THỂ** / **THÂN THỂ** LAN": mất phủ định.
  - "lịch **khám**" thành "lịch **TÁM**".
  - "**Khoan**, giờ đó không đúng" mất chữ "Khoan": DPDFNet nén phần đầu câu.
- **Bản 8 kHz riêng của DPDFNet** tốt hơn khi đem model 16k chạy trên audio 8 kHz (ồn mạnh 9–10 so với 7–8), đúng như tài liệu tham khảo nói. Nhưng vẫn thua không xử lý (13).
- **Có vài ca tốt lên thật**, nhưng ít hơn nhiều so với số ca hỏng:
  - "đừng **GÌ** nữa" thành "đừng **HỦY** nữa" (DPDFNet 2/4/8, ồn mạnh 16k);
  - nén được tiếng "Không" chen vào câu "Tôi đồng ý" (DPDFNet4/8, RNNoise).
- **Neural còn tự sinh tiếng trên file im lặng:** DPDFNet2 8 kHz biến tiếng phòng của `B-SIL-01` thành thứ đủ to để qua cổng im lặng, rồi model bịa ra "Ừ".
- **Golden 40 câu** (audio điện thoại thật): không cấu hình neural nào tốt hơn. Tổng lỗi 85 thành 86–126; DeepFilterNet3 còn 14/40 pass, RNNoise 15/40.
- **Chi phí:** trên 1 luồng CPU, p95 mỗi lượt khoảng 3 s:

  | Model | p95 |
  |---|---|
  | GTCRN | 240 ms |
  | DPDFNet baseline | 450 ms |
  | DPDFNet2 | 850 ms |
  | DPDFNet4 | 1,25 s |
  | DPDFNet8 | 2,0 s |
  | DPDFNet 8 kHz (2 / 8) | 0,7 / 1,8 s |
  | DeepFilterNet3 | 165 ms |
  | RNNoise | 320 ms |

**Kết luận chung:**
- Cùng hướng với Krisp và Quail (28 và 30/09): gipformer nghe audio thô **tốt hơn** audio đã qua khử nhiễu. Khử nhiễu để lại dấu vết mà model chưa gặp lúc huấn luyện, và xoá đúng phần âm thanh model cần.
- Không đưa model nào vào API. Cấu hình tốt nhất vẫn là N1 (lọc thông cao + khử nhiễu cổ điển 0,8, tức D7 của lần trước). N1 chỉ hơn N0 trong biên nhiễu nên cũng chưa đưa vào.
- **Xử lý thích nghi** theo đề xuất (chỉ bật khử nhiễu khi ồn) **không cứu được với các model này**, vì chúng tệ đi ngay ở chính điều kiện ồn.

## Cách đo

| Mã | Cấu hình |
|---|---|
| B0 / B1 | `production` / `text` hiện tại |
| N0 | B1 + cổng im lặng (đang bật trên API) |
| N1 | N0 + lọc thông cao 100 Hz + `noisereduce` 0,8 (= D7) |
| N2 | N0 + GTCRN (`gtcrn_simple`, 16 kHz) |
| N3–N6 | N0 + DPDFNet baseline / 2 / 4 / 8 (16 kHz) |
| N4-8k, N6-8k | N0 + DPDFNet2 / DPDFNet8 bản 8 kHz, **chỉ chạy trên file 8 kHz** |
| N7 | N0 + lọc thông cao → DPDFNet tốt nhất của từng tần số (tự chọn: 16k là DPDFNet8, 8k là DPDFNet2 8 kHz) |
| N8 | N0 + DeepFilterNet3 (48 kHz) |
| N9 | N0 + RNNoise (48 kHz) |

- **Model neural chạy trước khi resample, ở tần số gốc của file.** Model 8 kHz nhận đúng audio 8 kHz. Model 16k chạy trên file 8 kHz thì sherpa-onnx tự nâng lên 16k. DeepFilterNet3 và RNNoise thì nâng lên 48 kHz rồi hạ lại.
- **GTCRN và DPDFNet** chạy bằng `sherpa_onnx.OfflineSpeechDenoiser` (1.13.8, có sẵn trong dự án).
- **Nguồn model** (lưu ở `temp/models/speech-enhancement/`, không commit):
  - GTCRN và DPDFNet 16k: release `speech-enhancement-models` của k2-fsa/sherpa-onnx.
  - **DPDFNet 8 kHz không có trong release đó, trái với tài liệu tham khảo**; lấy từ `huggingface.co/Ceva-IP/DPDFNet` (`onnx/`, Apache-2.0). File có cùng định dạng metadata nên sherpa-onnx nạp được.
- **DeepFilterNet 0.5.6 và pyrnnoise 0.4.5** cài trong venv riêng (`--system-site-packages`), vì DeepFilterNet đòi hạ cấp `packaging`.
  - DeepFilterNet import phần I/O của `torchaudio` mà bản `torchaudio` mới đã bỏ. Không có `torchaudio` thì `processors._stub_torchaudio_io` thay bằng module rỗng; `enhance()` không dùng phần đó.
- **Tự kiểm:** `run.py --self-check` vẫn 0/364 file khác API.

```bash
python eval/pm-preprocess/run.py --self-check
python eval/pm-preprocess/run.py --suite neural --golden all   # cần venv có deepfilternet, pyrnnoise cho N8/N9
```

Đầu ra: `temp/pm-preprocess/2026-10-02-neural/` (`report.html` từng file, nghe được audio sau khử nhiễu; `results.csv`; `summary.json`).

## Kết quả đầy đủ

Mỗi ô: câu đúng hoàn toàn / số file · WER. "+/−": số file tốt lên / tệ đi so với B1.

**16 kHz**

| Cấu hình | sạch (30) | ồn nhẹ (20) | ồn mạnh (19) | xa (18) | tổng (91) | +/− | p95 |
|---|---|---|---|---|---|---|---|
| N0 | 27 · 2,1% | 16 · 3,0% | 13 · 7,0% | 14 · 3,4% | 71 · 4,0% | +1 / −0 | 30 ms |
| **N1** | 27 · 1,7% | 16 · 3,0% | 13 · 5,1% | 16 · 2,0% | **73** · 3,2% | +3 / −0 | 46 ms |
| N2 GTCRN | 26 · 2,5% | 16 · 3,0% | 7 · 16,6% | 14 · 3,4% | 64 · 6,4% | +2 / −8 | 238 ms |
| N3 DPDFNet baseline | 25 · 3,4% | 12 · 7,8% | 5 · 20,4% | 14 · 3,4% | 57 · 9,1% | +3 / −16 | 445 ms |
| N4 DPDFNet2 | 26 · 2,1% | 15 · 4,2% | 6 · 14,0% | 13 · 3,4% | 61 · 6,5% | +4 / −13 | 845 ms |
| N5 DPDFNet4 | 25 · 3,0% | 13 · 7,2% | 10 · 8,9% | 14 · 2,7% | 64 · 6,1% | +5 / −11 | 1,25 s |
| N6 DPDFNet8 | 25 · 2,5% | 16 · 3,0% | 8 · 14,6% | 15 · 2,7% | 66 · 6,2% | +5 / −9 | 1,98 s |
| N7 lọc thông cao + DPDFNet8 | 27 · 1,7% | 16 · 3,0% | 8 · 13,4% | 15 · 2,7% | 67 · 5,8% | +5 / −8 | 1,86 s |
| N8 DeepFilterNet3 | 26 · 2,5% | 12 · 8,4% | 6 · 16,6% | 8 · 21,5% | 53 · 11,4% | +4 / −21 | 162 ms |
| N9 RNNoise | 25 · 2,5% | 4 · 34,1% | 3 · 22,9% | 13 · 7,4% | 47 · 15,9% | +3 / −26 | 316 ms |

**8 kHz**

| Cấu hình | sạch (30) | ồn nhẹ (20) | ồn mạnh (19) | xa (18) | tổng (91) | +/− | p95 |
|---|---|---|---|---|---|---|---|
| N0 | 27 · 2,1% | 16 · 3,0% | 13 · 6,4% | 14 · 4,0% | 71 · 4,2% | +1 / −0 | 29 ms |
| N1 | 27 · 1,7% | 17 · 2,4% | 12 · 6,4% | 14 · 4,0% | 71 · 3,7% | +2 / −1 | 58 ms |
| N2 GTCRN | 25 · 3,0% | 15 · 4,8% | 7 · 16,6% | 14 · 4,0% | 62 · 7,3% | +2 / −10 | 237 ms |
| N3 DPDFNet baseline | 25 · 2,5% | 14 · 6,0% | 6 · 21,0% | 13 · 4,0% | 59 · 8,3% | +3 / −14 | 451 ms |
| N4 DPDFNet2 | 27 · 1,7% | 16 · 3,6% | 7 · 15,3% | 14 · 4,0% | 65 · 6,7% | +3 / −8 | 843 ms |
| N5 DPDFNet4 | 26 · 2,1% | 15 · 5,4% | 8 · 12,1% | 12 · 7,4% | 63 · 6,7% | +6 / −13 | 1,26 s |
| N6 DPDFNet8 | 25 · 2,5% | 16 · 3,6% | 8 · 12,7% | 13 · 4,0% | 64 · 6,0% | +4 / −10 | 1,99 s |
| N4-8k DPDFNet2 8 kHz | 26 · 2,1% | 15 · 4,2% | 9 · 11,5% | 14 · 3,4% | 64 · 5,4% | +1 / −7 | 708 ms |
| N6-8k DPDFNet8 8 kHz | 25 · 2,5% | 12 · 6,0% | 10 · 9,6% | 14 · 3,4% | 62 · 5,4% | +3 / −11 | 1,76 s |
| N7 lọc thông cao + DPDFNet2 8 kHz | 26 · 2,1% | 15 · 4,2% | 9 · 11,5% | 14 · 3,4% | 66 · 5,1% | +4 / −8 | 691 ms |
| N8 DeepFilterNet3 | 26 · 2,5% | 12 · 8,4% | 3 · 20,4% | 10 · 14,8% | 52 · 10,8% | +3 / −21 | 168 ms |
| N9 RNNoise | 25 · 2,5% | 5 · 31,7% | 7 · 14,0% | 11 · 6,0% | 50 · 13,4% | +3 / −23 | 326 ms |

**Golden 40 câu** (B1 = N0: 19/40 pass, 85 lỗi / 232 từ):

| | N1 | N2 | N3 | N4 | N5 | N6 | N4-8k | N6-8k | N7 | N8 | N9 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Pass | 19 | 17 | 19 | 18 | 18 | 18 | 19 | 19 | 19 | 14 | 15 |
| Tổng lỗi | 86 | 90 | 88 | 90 | 91 | 89 | 87 | 87 | 86 | 112 | 126 |

## Thử thêm: giới hạn mức nén của DPDFNet

Câu hỏi: giữ lại một phần nhiễu (`attenuation_limit_db`) thì DPDFNet có bớt xoá giọng không? Chạy `--suite neural-limit`, kết quả ở `temp/pm-preprocess/2026-10-02-neural-limit/`.

| Cấu hình | 16k: tổng (91) · ồn mạnh (19) · +/− | 8k: tổng · ồn mạnh · +/− | Golden: pass · lỗi |
|---|---|---|---|
| N0 không khử nhiễu | **71** · **13** · +1/−0 | **71** · **13** · +1/−0 | 19 · 85 |
| DPDFNet2, không giới hạn | 61 · 6 · +4/−13 | 65 · 7 · +3/−8 | 18 · 90 |
| DPDFNet2, tối đa 12 dB | 66 · 9 · +1/−5 | 66 · 9 · +2/−6 | 19 · 85 |
| DPDFNet2, tối đa 6 dB | 70 · 11 · +2/−2 | 70 · 10 · +3/−3 | 19 · **83** |
| DPDFNet2 8 kHz, không giới hạn | — | 64 · 9 · +1/−7 | 19 · 87 |
| DPDFNet2 8 kHz, tối đa 12 dB | — | **71** · 11 · +3/−2 | 19 · 86 |
| DPDFNet2 8 kHz, tối đa 6 dB | — | 69 · 10 · +2/−3 | 19 · 86 |

- Giới hạn mức nén giảm hại rõ rệt, nhưng tốt nhất chỉ **ngang** N0, kèm vài câu tốt lên và vài câu tệ đi.
- Ồn mạnh vẫn tệ hơn: 10–11 câu so với 13.
- Mỗi lượt mất thêm 0,7–0,9 s.
- Không đáng đưa vào.

## Nhận xét về tài liệu tham khảo (`thamkhao3.md`)

| Ý trong tài liệu | Đối chiếu |
|---|---|
| GTCRN, DPDFNet hợp stack, sherpa-onnx hỗ trợ sẵn | Đúng: `OfflineSpeechDenoiser` có trong sherpa-onnx 1.13.8, tích hợp rẻ |
| DPDFNet có bản 8 kHz và sherpa-onnx cung cấp | Có bản 8 kHz, nhưng nằm ở HuggingFace của Ceva, không ở release của sherpa-onnx |
| Model 8 kHz riêng tốt hơn dùng model 16k cho audio 8 kHz | Đúng (ồn mạnh 9–10 so với 7–8), nhưng vẫn tệ hơn không xử lý |
| Neural front-end sẽ kéo gipformer lên | **Không đúng trên dữ liệu này**: mọi model đều tệ hơn, cả bộ PM lẫn golden |
| Xử lý thích nghi: chỉ bật khi ồn | Với các model này không giúp, vì chúng hỏng nhiều nhất ở chính điều kiện ồn |
| Lỗi từ vựng (MRI, bíp) nên sửa bằng hotword / contextual biasing | Hợp lý, chưa thử. Cần `modified_beam_search`, hiện production dùng `greedy_search` |
| Mất đầu câu sửa bằng pre-roll | Đúng với streaming (đã làm lookback theo giọng 01/10). Ca `B-CUT-01` của PM là audio bị cắt sẵn nên không cứu được |

## Giới hạn

- Bộ PM chỉ có một người nói, nhiễu trộn bằng script. Golden là audio điện thoại thật, và kết quả trên golden cùng chiều.
- Giới hạn mức nén mới thử cho DPDFNet2 (16k và 8 kHz); DeepFilterNet3 (`atten_lim_db`) và GTCRN chưa thử. Xu hướng của DPDFNet cho thấy giới hạn mức nén chỉ đưa kết quả về gần mức không xử lý.

## File liên quan

- `eval/pm-preprocess/processors.py`: `ENHANCERS`, `enhance`, `prepare_experiment(enhancer=...)` (lúc chạy tên là `neural`; đổi tên khi thêm WebRTC NS và SpeexDSP, cách tính không đổi).
- `eval/pm-preprocess/run.py`: `--suite neural` và `--suite neural-limit`, cấu hình theo tần số, chọn tự động cho N7.

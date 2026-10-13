# Evidence: so tất cả lựa chọn khử nhiễu trước ASR trên bộ eval PM (O0–O8, 02/10/2026)

Một bảng cho mọi lựa chọn, trên cùng bộ PM (93 file × 16 kHz và 8 kHz) và 40 câu golden, cùng đường `/v1/stt/turn`.
- Cấu hình nào đã đo trước đó thì **dùng lại kết quả**, không chạy lại. Code và model giống nhau, kết quả xác định.
- Chỉ chạy mới O1 (WebRTC NS) và O2 (SpeexDSP).

Chi tiết từng nhóm: [DSP](pm-preprocess-2026-10-02.md), [neural](pm-preprocess-neural-2026-10-02.md).

## Kết luận

- **Không bộ khử nhiễu nào, cổ điển hay neural, giúp được gipformer ở ồn mạnh. Tất cả đều làm tệ đi** (13/19 câu đúng thành 3–9).
- **Chỉ lọc thông cao (O7) và lọc thông cao + spectral gate (O8) không gây hại:**
  - 16 kHz: +2 câu so với O0 (+3 / −0);
  - 8 kHz: ngang O0.
  - Chênh lệch này nằm trong biên nhiễu của bộ đo một người nói, nên vẫn chưa đưa vào API.
- **Nguyên nhân chung:** mọi bộ khử nhiễu đều xoá **phụ âm vô thanh** (k, kh, t) khi ồn mạnh, vì phổ của chúng giống nhiễu. Hệ quả là mất đúng những từ quyết định nghĩa:
  - "**kh**ám" thành "TÁM", "ÁN";
  - "**kh**ông phải" thành "ÔNG PHẢI";
  - "**T**ôi" thành "CÔ".
- **Ồn nhẹ và nói xa** thì WebRTC NS nhỉnh hơn một chút (16k: ồn nhẹ +1, xa +1), nhưng không bù được phần mất ở ồn mạnh.
- **Kết luận vẫn như các lần trước:** giữ O0 (cổng im lặng) trên API; không đưa bộ khử nhiễu nào vào.

## Bảng tổng hợp

Mỗi ô: câu đúng hoàn toàn / số file · WER. "+/−": số file tốt lên / tệ đi so với B1. Golden: pass trên 40 · tổng lỗi trên 232 từ.

| Mã | Pipeline | Nguồn số liệu | 16k tổng (91) | 16k ồn mạnh (19) | 8k tổng (91) | 8k ồn mạnh (19) | Golden | p95 |
|---|---|---|---|---|---|---|---|---|
| O0 | Cổng im lặng (đang bật trên API) | N0 | 71 · 4,0% | 13 · 7,0% | 71 · 4,2% | 13 · 6,4% | 19 · 85 | 30 ms |
| O1 | O0 + WebRTC NS | **chạy mới** | 68 · 4,4% | 8 · 10,8% | 65 · 5,0% | 8 · 11,5% | 18 · 86 | 44 ms |
| O2 | O0 + SpeexDSP denoise | **chạy mới** | 66 · 4,9% | 9 · 9,6% | 65 · 5,0% | 9 · 8,9% | 19 · 90 | 56 ms |
| O3 | O0 + RNNoise | N9 | 47 · 15,9% | 3 · 22,9% | 50 · 13,4% | 7 · 14,0% | 15 · 126 | 316 ms |
| O4 | O0 + GTCRN | N2 | 64 · 6,4% | 7 · 16,6% | 62 · 7,3% | 7 · 16,6% | 17 · 90 | 238 ms |
| O5 | O0 + DPDFNet bản gốc (16k: DPDFNet8; 8k: DPDFNet2 8 kHz) | N6 / N4-8k | 66 · 6,2% | 8 · 14,6% | 64 · 5,4% | 9 · 11,5% | 19 · 87 | 2,0 s / 0,7 s |
| O6 | O0 + DeepFilterNet3 | N8 | 53 · 11,4% | 6 · 16,6% | 52 · 10,8% | 3 · 20,4% | 14 · 112 | 162 ms |
| **O7** | O0 + lọc thông cao 100 Hz | D2 | **73** · 3,5% | 13 · 6,4% | 70 · 4,2% | 12 · 7,6% | 19 · 85 | 35 ms |
| **O8** | O0 + lọc thông cao + spectral gate 0,8 | D7 | **73** · 3,2% | 13 · 5,1% | 71 · 3,7% | 12 · 6,4% | 19 · 86 | 55 ms |

Mọi cấu hình đều giữ nguyên 27–25/30 câu sạch. Riêng O7 và O8 không làm hỏng câu sạch nào.

## Ví dụ: cùng một kiểu lỗi ở mọi bộ khử nhiễu (ồn mạnh, 16 kHz)

| File | O0 (không khử nhiễu) | WebRTC NS | SpeexDSP | Neural (lần đo trước) |
|---|---|---|---|---|
| `B-CANCEL-01` | …lịch **KHÁM** này ✓ | …lịch **TÁM** ngày | …lịch **ÁN** này | DPDFNet: …lịch **TÁM** này |
| `B-ID-03` | Loan **KHÔNG** phải Lan ✓ | Loan **ÔNG** phải Lan | Loan **ÔNG** phải Lan | GTCRN: **ÔNG** phải; DPDFNet: **THÂN THỂ** |
| `B-NOISE-01` | **TÔI** muốn xác nhận… ✓ | **CÔ** muốn… | đúng | `noisereduce`, WPE: **CÔ** muốn… |

Golden (audio điện thoại thật):
- WebRTC NS: "Nguyễn Hoàng **Minh**" thành "**MAI**".
- SpeexDSP: "**Nguyễn** Văn A" thành "**ĐỖ** Văn A"; "Tôi là Nguyễn Hoàng Giang" chỉ còn "TÔI".

## Cách đo O1 và O2

- **O1 WebRTC NS:**
  - `livekit.rtc.AudioProcessingModule(noise_suppression=True)`, bộ xử lý WebRTC có sẵn trong SDK LiveKit, không cần key.
  - Chỉ bật khử nhiễu (tắt AGC, AEC, lọc thông cao), frame 10 ms.
  - Mỗi clip một module mới, chạy ở tần số gốc của file (8 hoặc 16 kHz).
- **O2 SpeexDSP:**
  - `libspeexdsp.so.1` của hệ thống qua ctypes.
  - Chỉ bật denoise (mặc định của thư viện, nén tối đa −15 dB), tắt AGC, frame 20 ms.
  - Mỗi clip một state mới, chạy ở tần số gốc.
  - Vì phải học nhiễu từ đầu mỗi clip, nhiễu ở 0,3 s đầu gần như chưa được nén (958 → 914 RMS); WebRTC NS nén được ngay (958 → 235).
- Cả hai đặt sau bỏ DC và trước resample, rồi qua cổng im lặng và khuếch đại như API. Thời gian xử lý 4–11 ms mỗi clip.

## Tái tạo

```bash
python eval/pm-preprocess/run.py --suite opt --golden all
```

- O0, O3–O8 đọc lại `results.csv` và `summary.json` của `temp/pm-preprocess/2026-10-02/` (DSP) và `2026-10-02-neural/` (neural).
- Đường dẫn audio trong báo cáo trỏ sang đúng thư mục đó.
- Đầu ra: `temp/pm-preprocess/2026-10-02-opt/report.html` (từng file: nghe audio sau xử lý, so chữ model trả ra).

# Ma trận đánh giá TTS — số đo chung (ADR-002)

_Sinh tự động bởi `scripts/tts_bench.py` · cập nhật 2026-09-21 · bộ câu `scripts/tts_bench_set.py` (27 câu, 2085 ký tự)._

Cùng bộ câu, cùng cách đo cho mọi provider. Tiêu chí 2, 3, 5 đo tự động; 6 chấm tĩnh theo tài liệu; **tiêu chí 1 và 4 do người nghe** (phiếu `listening_sheet.csv`, 3 người, điền xong chạy `--matrix`).

## 1. Ma trận High / Medium / Low

| Label | Ngày · máy | 1. Đọc đúng (người nghe) | 2. Streaming/TTFA | 3. Barge-in | 4. Điện thoại (người nghe) | 5. P95 & chi phí | 6. Bảo mật | Đạt 28/9? |
|---|---|---|---|---|---|---|---|---|
| **elevenlabs:sarah-free** | 2026-09-20 · Windows laptop, API qua Internet | chưa nghe | Medium | Medium | chưa nghe | High | Medium | **Có** (tốc độ) — chờ phiếu nghe |
| **zerotts:baotrang** | 2026-09-20 · Colab T4 GPU, 2 vCPU | chưa nghe | Low | High | chưa nghe | Low | High | Không |
| **zerotts:kimoanh** | 2026-09-20 · Colab T4 GPU, 2 vCPU | chưa nghe | Low | High | chưa nghe | Low | High | Không |
| **zerotts:maichi** | 2026-09-20 · Colab T4 GPU, 2 vCPU | chưa nghe | Low | High | chưa nghe | Low | High | Không |

Ngưỡng: đọc đúng ≥ 95 % câu High / ≥ 85 % Medium · TTFA P95 ≤ 500 ms & RTF P95 < 0,7 & đứt tiếng < 5 % High (không stream → tối đa Medium) · dừng sau cancel ≤ 100 ms High (không stream → Low) · nghe rõ qua điện thoại ≥ 4/5 High, ≥ 3/5 Medium · P95 tổng ≤ 2 000 ms High / ≤ 3 500 Medium · bảo mật chấm tĩnh. "Đạt 28/9" = P95 High và đọc đúng không Low.

## 2. Số đo tự động (tiêu chí 2, 3, 5)

| Label | n | Lỗi | TTFA P50/P95 (ms) | Tổng P50/P95 (ms) | Câu chào P95 | RTF P50/P95 | Đứt tiếng | Stream? | Chunk đầu / câu | Chunk max (s) | Dừng sau cancel (ms) | Audio phải bỏ (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| elevenlabs:sarah-free | 54 | 0 | 541 / 610 | 644 / 884 | 813 | 0.21 / 0.33 | 0 % | có | 30 % | 10.52 | 156 | 0.90 |
| zerotts:baotrang | 54 | 0 | 296 / 431 | 7,926 / 21,500 | 18,707 | 2.33 / 2.57 | 100 % | có | — | 1.28 | 0 | 0.08 |
| zerotts:kimoanh | 54 | 0 | 286 / 404 | 10,260 / 23,235 | 17,297 | 2.31 / 2.36 | 100 % | có | — | 1.28 | 0 | 0.08 |
| zerotts:maichi | 54 | 0 | 287 / 411 | 8,548 / 20,133 | 15,390 | 2.31 / 2.55 | 100 % | có | — | 1.28 | 0 | 0.08 |

## 3. Người nghe (tiêu chí 1, 4)

| Label | Số người đã nghe | Đọc đúng mọi entity (% câu) | Tự nhiên (1–5) | Nghe rõ qua điện thoại (1–5) | Phiếu |
|---|---|---|---|---|---|
| elevenlabs:sarah-free | 0/3 | — | — | — | `elevenlabs__sarah-free/listening_sheet.csv` |
| zerotts:baotrang | 0/3 | — | — | — | `zerotts__baotrang/listening_sheet.csv` |
| zerotts:kimoanh | 0/3 | — | — | — | `zerotts__kimoanh/listening_sheet.csv` |
| zerotts:maichi | 0/3 | — | — | — | `zerotts__maichi/listening_sheet.csv` |

## 4. Chi phí ước tính (750 ký tự/cuộc gọi — kiểm lại giá trước khi báo cáo)

| Label | 500 cuộc/tháng | 5,000 cuộc/tháng | 50,000 cuộc/tháng |
|---|---|---|---|
| elevenlabs:sarah-free | Creator ~48 USD (+88k credit mua thêm) | Scale ~330 USD | Business ~2250 USD (+7750k credit mua thêm) |
| zerotts:baotrang | self-host: xem AWS trong report gốc | self-host: xem AWS trong report gốc | self-host: xem AWS trong report gốc |
| zerotts:kimoanh | self-host: xem AWS trong report gốc | self-host: xem AWS trong report gốc | self-host: xem AWS trong report gốc |
| zerotts:maichi | self-host: xem AWS trong report gốc | self-host: xem AWS trong report gốc | self-host: xem AWS trong report gốc |

## 5. Bảo mật (tiêu chí 6, chấm tĩnh)

- **elevenlabs** — Medium: Máy chủ nước ngoài (US/EU); lưu lịch sử generation mặc định (tắt được ở gói trả phí); key qua header; adapter không log text.
- **zerotts** — High: Self-host, dữ liệu không rời hệ thống; không có key.
- **azure** — High*: Theo tài liệu: không retain text/audio, region SEA; chưa đo.

## 6. Cách lặp lại

```
python scripts/tts_bench.py --provider elevenlabs [--voice <id>] [--label provider:giong] [--repeats 2]
python scripts/tts_bench.py --import-dir <CSV Colab> --wav-dir <wav Colab> --family zerotts --date ... --machine ...
python scripts/tts_bench.py --matrix        # sau khi điền listening_sheet.csv
```

Mỗi dòng: `docs/evidence/tts-bench/<label>/` (latency_raw.csv, bargein.csv, listening_sheet.csv, summary.json). WAV sạch + WAV điện thoại (`__tel8k`) để nghe: `temp/tts-bench/<label>/wav/`.

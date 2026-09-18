# TTS evaluator and human-review scorecard

Framework này không chứa TTS provider, không nghe/chấm audio bằng STT hoặc LLM, và không
tự dự đoán semantic correctness hay MOS.

## Review workflow

### A. Validate golden dataset

```powershell
python eval/tts-bench/evaluate.py --validate-only
```

Lệnh kiểm tra YAML, đúng 40 case, ID unique, text/category, `critical_items`, và
`zero_tolerance`. Không cần audio ở bước này.

### B. Generate audio sau khi có adapter

Implement `TTSAdapter`/`TTSResult` trong `adapters/base.py`, rồi truyền adapter instance,
class không cần argument, hoặc factory không cần argument dưới dạng `module:attribute`:

```powershell
python eval/tts-bench/evaluate.py --adapter <module:attribute> --generate
```

Evaluator yêu cầu adapter ghi đúng `outputs/<case_id>.wav` và không tự ghi đè output cũ.
Task skeleton hiện tại không cung cấp hoặc gọi provider cụ thể.

### C. Prepare review scorecard

```powershell
python eval/tts-bench/evaluate.py --prepare-review
```

Lệnh tạo `results/tts-review.csv` với đúng 40 dòng. Các cột human review được để trống;
không có PASS hay điểm giả. `technical_status`/`technical_notes` chỉ phản ánh kiểm tra file
khách quan: tồn tại, kích thước, WAV decode, duration, sample rate và channel count.

### D. Human review

QA mở `results/tts-review.csv`, nghe từng file `outputs/TTS_*.wav`, rồi nhập:

- `critical_content_pass`: chỉ `PASS`, `FAIL`, hoặc `NA`;
- `critical_failures`: mô tả lỗi nghe được, bắt buộc nếu chọn `FAIL`;
- `naturalness`, `intelligibility`, `pacing`, `pronunciation`: mỗi điểm là số nguyên 1–5;
- `reviewer_notes`: ghi chú tùy chọn.

Không nhập `mos` hay `result`; evaluator tính hai cột này khi summarize.

### E. Summarize human review

```powershell
python eval/tts-bench/evaluate.py `
  --summarize eval/tts-bench/results/tts-review.csv
```

Lệnh validate scorecard, báo rõ case pending, cập nhật `mos`/`result`, tạo
`results/tts-summary.json`, và in console summary. Không có MOS threshold mặc định. Một case
đầy đủ review có result `REVIEWED`; chỉ rule đã được định nghĩa mới tự đặt `FAIL`:
`zero_tolerance=true` cùng `critical_content_pass=FAIL`.

## Scoring policy

**MOS trong suite này là human-rated MOS-like QA score, không phải model-predicted MOS.**

MOS là trung bình cộng của bốn điểm người nghe nhập: naturalness, intelligibility, pacing,
và pronunciation. Evaluator không gọi MOS predictor. MOS cao không thể cứu một critical
business error của case zero-tolerance. Với case non-zero-tolerance, evaluator chỉ report MOS
và không tự đặt ngưỡng PASS/FAIL.

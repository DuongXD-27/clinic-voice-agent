# Name slot filling v2 so với NER ngày 23-09-2026

Slot filling v2 đạt cùng tỷ lệ 96/97 ca được chấm như NER hôm trước. Thời gian trung bình
của ca có gọi API giảm 19,5% trong hai lượt đã lưu, nhưng chưa chứng minh tăng tốc do riêng
prompt. V2 sửa ID073 ở tầng luật và phát sinh regression ID069 ở fallback; chưa có cải
thiện chất lượng tổng thể.

## Nguồn và tính tương đương của tập ca

- NER ngày 23-09: [results.csv](../../result/23-09-2026/identity/ner/results.csv),
  [summary.json](../../result/23-09-2026/identity/ner/summary.json).
- Slot filling v1 ngày 24-09: [results.csv](../../result/24-09-2026/identity/slot_filling/results.csv),
  [summary.json](../../result/24-09-2026/identity/slot_filling/summary.json).
- Slot filling v2 ngày 24-09: [results.csv](../../result/24-09-2026/identity/slot_filling_v2/results.csv),
  [summary.json](../../result/24-09-2026/identity/slot_filling_v2/summary.json).

Đối chiếu theo `id`: NER và v2 có cùng 100 ID, `question_id`, `transcript` và tất cả cột
`expect_*`. Cả hai dùng `gpt-6-luna`, gọi model trên cùng 11 ID và đều có 11/11 response
`completed`. V2 bổ sung câu hỏi bot vào input; NER cũ chỉ nhận transcript. Luật trích tên
cũng đã thay đổi, nên đây là so sánh toàn bộ luồng extraction qua hai phiên bản.

## Kết quả đã lưu

| Chỉ số | NER 23-09 | Slot filling v1 24-09 | Slot filling v2 24-09 |
| --- | ---: | ---: | ---: |
| Prompt | `name_ner_v3` | `name_slot_filling_v1` | `name_slot_filling_v2` |
| PASS / FAIL / REVIEW | 96 / 1 / 3 | 96 / 1 / 3 | 96 / 1 / 3 |
| Tỷ lệ PASS, loại REVIEW | 98,97% | 98,97% | 98,97% |
| Số ca gọi API | 11 | 11 | 11 |
| Response completed | 11/11 | 11/11 | 11/11 |
| Trung bình ca có API | 2.013,4 ms | 2.195,5 ms | 1.619,8 ms |
| Trung vị ca có API | 2.056 ms | 2.095 ms | 1.624 ms |
| Nhỏ nhất–lớn nhất ca có API | 1.563–2.692 ms | 1.516–3.534 ms | 1.183–2.240 ms |
| Tổng `elapsed_ms` của 100 ca | 22.199 ms | 24.196 ms | 17.884 ms |

So với NER hôm trước, v2 giảm 393,5 ms (19,5%) ở trung bình ca có API; tổng thời gian
được ghi giảm 4.315 ms (19,4%). `elapsed_ms` đo cả extraction của từng ca, không chỉ thời
gian model, và tổng không gồm khởi động CLI hay ghi báo cáo. Đây không phải thời gian
cuộc gọi có ASR/TTS.

## Hai ca đổi kết quả

| Ca | Transcript | NER 23-09 | V2 24-09 | Diễn giải |
| --- | --- | --- | --- | --- |
| ID073 | Nguyễn Văn A tôi không nhớ rõ ngày sinh | FAIL: mất tên, intent `CANNOT_PROVIDE` | PASS: tên `nguyễn văn a`, intent `NONE` | Luật tách hậu tố phân vân về ngày sinh dù ASR thiếu dấu phẩy; không gọi model. |
| ID069 | Nguyễn Văn A phải không | PASS: không nhận tên | FAIL: nhận `nguyễn văn a` từ `FALLBACK` | Regression: câu hỏi chưa khẳng định tên bị model coi là tự nhận. |

`completed` chỉ chứng minh request hoàn tất, không chứng minh chọn tên đúng.

## Phạm vi thay đổi và kiểm chứng

- Chuyển `NameNER` thành `NameSlotFiller`, gửi câu hỏi đang chờ và câu trả lời hiện tại;
  không gửi lịch sử hay hồ sơ đối chiếu. Giữ `NAME_FALLBACK_*`, alias `--ner` và nhãn debug
  `NER` để tương thích.
- Prompt v2 có 12 ví dụ, quy định sao chép một span liền nhau và phân biệt chủ thể,
  tự sửa, tên trùng tiểu từ. So với **slot filling v1**, input rỗng với câu hỏi null giảm
  5.979 xuống 3.195 ký tự nội dung message (46,6%); không phải phép đo so với NER v3 hay
  phép đo token/chi phí.
- Chặn gọi model ngoài `ASK_NAME`, giữ kiểm tra span và xử lý lỗi bằng hỏi lại.
- Kiểm thử offline: **2.211 passed, 28 skipped**, một cảnh báo deprecation Starlette/AnyIO.
  `ruff check src tests`, `ruff format --check src tests` đạt (210 file).

Tập ca là dữ liệu tổng hợp dùng để khám phá và chỉnh luật/prompt, không phải holdout hoặc
độ chính xác trên cuộc gọi thực tế. Mỗi phiên bản chỉ có một lượt API thành công được so
sánh, khác thời điểm và điều kiện mạng/cache/tải provider không được kiểm soát. Không kết
luận chất lượng tốt hơn, mức giảm chi phí hay tăng tốc ổn định. ID069 cần xử lý và đánh giá
lại trước khi coi v2 thay thế NER mà không có regression.

## Chạy lại

```powershell
.\.venv\Scripts\python.exe scripts/identity_eval.py --slot-filling --output result/24-09-2026/identity/slot_filling_v2_rerun/results.csv
```

Lệnh gọi API theo `.env`, chỉ ở ca được định tuyến fallback. Dùng thư mục output mới để
giữ nguyên bằng chứng đã so sánh. Exit code 1 là có ca FAIL; xem transport status để phân
biệt lỗi kết nối và lỗi chọn tên.

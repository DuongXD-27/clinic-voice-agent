# AI Callbot Engine & Information Extraction — Thiết kế v1.1

| | |
|---|---|
| Dự án | AI Callbot – Tổng đài đặt lịch khám |
| Người thực hiện | Ngô Huy Hoàn |
| Phiên bản | 1.1 (sửa đổi bản 14/09/2026 sau phản biện) |
| Ngày | 15/09/2026 |
| Tham chiếu contract | AIHR-PC-001 **Rev 1.1** §1.1.1–§1.1.10, §1.2.1, §2.1, §2.2, §4.1, §4.2.2, §4.2.5, §5, SF-01–SF-05, Phụ lục A |

---

## 0. Thay đổi so với bản 14/09

| # | Bản 14/09 | Bản 1.1 | Lý do |
|---|---|---|---|
| 1 | Rủi ro danh tính tập trung ở bộ trích xuất | Rủi ro **chấp nhận nhầm** nằm ở bộ so khớp của Verifier; bộ trích xuất chỉ cần "mù" với hồ sơ | Trích sai mà không thấy hồ sơ gần như luôn dẫn tới *từ chối nhầm* (hướng an toàn) |
| 2 | So khớp tên 3 tầng: bỏ dấu + gộp phụ âm + Jaro-Winkler | Ngày sinh khớp chính xác là cổng; tên so theo từng từ căn từ cuối, **tên chính không được so mờ** | Tên tiếng Việt khác nhau chủ yếu ở thanh điệu; Jaro-Winkler cộng điểm cho đầu chuỗi, tức là cho *họ* |
| 3 | "Không chắc chắn → hỏi lại", không giới hạn | Giới hạn số lần thử; ngày sinh trích được mà sai → chuyển máy ngay | Chặn dò ngày sinh; §1.1.1 |
| 4 | Nhánh CLINICAL ưu tiên recall, phủ quyết mọi nhánh | Tách 3 lớp: cấp cứu / hỏi đánh giá lâm sàng / nhắc triệu chứng làm lý do | Chuyển máy nhầm một cuộc đặt lịch là **case fail**, không chỉ "tốn một cuộc gọi" |
| 5 | Từ đáp lễ phép đứng một mình luôn là UNCLEAR | Ngưỡng đồng ý **theo hành động được mở khóa**; hỏi lại bằng câu lựa chọn A/B | Tránh vòng "vâng → hỏi lại → vâng → chuyển máy" |
| 6 | LLM chỉ sinh lời thoại là đủ an toàn | Thêm **output guard** cho lời thoại | Lời thoại tự nó gây được SF-02, SF-03, SF-04 |
| 7 | `transfer_reason` thuộc Information Extraction | Chuyển sang **Policy** | Lý do chuyển máy là quyết định, không trích từ lời người gọi |
| 8 | Intent 6 nhãn | Thêm `REQUEST_HUMAN`, `REPEAT_REQUEST`, `NOT_PATIENT`; thêm tín hiệu hộp thư thoại | Phụ lục A có `PATIENT_REQUEST`; §1.1.7 yêu cầu phát hiện voicemail |
| 9 | `slot_choice` → slot_id hoặc NO_MATCH | `MATCH` / `AMBIGUOUS` / `NO_MATCH`, lọc trên toàn bộ `GET /slots` | "Chiều thứ năm" khớp 2 slot không được tự chọn slot đầu |
| 10 | Gắn điểm tin cậy dạng số cho từng trường | Gắn **nhãn nguồn gốc** (`provenance`) | Luật viết tay không có xác suất hiệu chỉnh; tầng cho ra kết quả mới là tín hiệu thật |
| 11 | Số điện thoại trích bằng regex → E.164 | **Hoãn**, hỏi PO trước | Inbound đã có `caller_number`; chưa biết clinic mock lưu định dạng nào |
| 12 | Tuyến sau dùng PhoBERT | Tuyến sau dùng LLM tập nhãn đóng cho intent/agreement; PhoBERT sau khi có trace | Nhóm chưa có dữ liệu gán nhãn |

**Bổ sung sau khi đối chiếu hợp đồng AIHR-PC-001 (15/09/2026):**

| # | Trước | Sau | Lý do |
|---|---|---|---|
| 13 | Ở bước danh tính không chạy `OUT_OF_SCOPE` | Chạy `OUT_OF_SCOPE` khi câu trả lời **không** trích được tên / ngày sinh (mục 5.4) | §1.1.5, §1.2.3: hỏi bảo hiểm ở câu đầu phải ra `OUT_OF_SCOPE`, không phải `NOT_UNDERSTOOD` sau 2 lần hỏi lại |
| 14 | Luật chỉ khớp văn bản có dấu | Khớp được transcript **không dấu**, có danh sách loại trừ từ trùng nghĩa (mục 5.10) | §4.1: audio mode từ tuần 3, ASR có thể mất dấu |
| 15 | `line_signal` chỉ chạy lượt đầu outbound | Chạy ở mọi lượt outbound trước khi xác minh xong (mục 5.9) | §1.1.7 chưa nói harness báo voicemail ở lượt nào |
| 16 | — | Thêm `QuestionId.ASK_ATTENDANCE` (ngưỡng như `CONFIRM_READBACK`, không mở khóa lệnh ghi) | Bảng 1: "states **or agrees** they will attend" |

**Cập nhật theo hợp đồng Rev 1.1 (15/09/2026):**

| # | Trước | Sau | Lý do |
|---|---|---|---|
| 17 | `line_signal`: hộp thư thoại / thông báo tổng đài | Chỉ trích `VOICEMAIL` từ lời nói; `NO_ANSWER` / `LINE_BUSY` chỉ đến từ trạng thái điện thoại có kiểu `PhoneStatus` | Hợp đồng §4.2.5; [tín hiệu trạng thái điện thoại](phone-status.md) |
| 18 | Transcript rỗng cho ra các trường `NONE`, không phân biệt với "không hiểu" | `extract(..., silence_ms)`; `silence_ms > 0` → `ExtractionResult.silent = True`, mọi trường `skipped` (mục 4) | §1.1.7: "A silent turn is not a failed understanding under §1.1.5"; Phụ lục A: im lặng = `silence_ms > 0` |
| 19 | Câu hỏi "có đến được không" là `ASK_ATTENDANCE`, sau đó mới đọc lại | Câu tóm tắt + đọc lại + hỏi đến được không **gộp một lượt** là `CONFIRM_READBACK` (mục 5.6) | Figure 0 rev 1.1: "Có, tôi đến được." → `CONFIRMED` ngay |

---

## 1. Tóm tắt

| Trường | Phương pháp | Đầu ra |
|---|---|---|
| `full_name` | Theo trạng thái hội thoại (đang hỏi tên) + bỏ tiền tố lễ phép; NER fallback từ tuần 3 | chuỗi đã chuẩn hoá Unicode \| `NONE` |
| `dob` | Regex + parser ngày nói tiếng Việt tự viết | ISO `YYYY-MM-DD` \| `INVALID` \| `NONE` |
| `intent` | Luật viết tay → LLM tập nhãn đóng | 1 trong 9 nhãn (mục 5.4) |
| `clinical` | Bộ phát hiện riêng, chạy trước intent | `EMERGENCY` \| `ADVICE_REQUEST` \| `MENTION` \| `NONE` |
| `agreement` | Bộ nhận diện riêng, gắn với câu bot vừa hỏi | `AGREE` \| `REFUSE` \| `UNCLEAR` |
| `slot_choice` | Lọc trên danh sách `GET /slots` của cuộc gọi | `MATCH(slot_id)` \| `AMBIGUOUS(slot_ids)` \| `NO_MATCH` |
| `cancel_reason` | Ánh xạ cụm từ tường minh → Phụ lục A | mã Phụ lục A, mặc định `UNSPECIFIED` |
| `line_signal` | Mẫu lời chào hộp thư thoại | `VOICEMAIL` \| `NONE`; kết quả quay số dùng `PhoneStatus`, không thuộc IE |
| `silent` | `silence_ms > 0` của harness, không suy từ transcript | `true` → mọi trường `skipped` |
| ~~`phone`~~ | Hoãn — xem mục 5.3 | — |

`transfer_reason` **không** thuộc khối này — Policy quyết định (mục 6.3).

---

## 2. Nguyên tắc

1. **Tách quyết định khỏi ngôn ngữ, và kiểm soát cả hai đầu.** Mọi lệnh ghi đi qua Policy trên dữ liệu đã chuẩn hoá. Lời thoại sinh ra cũng phải qua output guard (mục 7), vì *nói* sai giờ là SF-02 dù không ghi gì.
2. **Bộ trích xuất không bao giờ nhìn thấy hồ sơ.** Không đưa `verify.full_name` / `verify.dob` vào prompt, vào danh sách boost của ASR, hay vào bước trích xuất. Chỉ Verifier được đọc hồ sơ.
3. **Bất đối xứng rủi ro theo từng hành động, không theo từng module.**
   - Danh tính: lệch về *từ chối* (SF-03).
   - Hủy lịch: lệch về *chưa rõ* (SF-05).
   - Câu hỏi cấp cứu: lệch về *chuyển máy* (SF-04).
   - Nhắc triệu chứng khi đặt lịch: **không** chuyển máy (task completion).
   
   Mỗi hướng hiệu chỉnh phải ghi chú ngay trong code, kèm lý do, để người sau không "làm cho nhất quán".
4. **Mọi trường mang được "không biết".** Phân biệt `NONE` (không có dữ liệu) với `INVALID` (có nhưng không hợp lệ) và với giá trị hợp lệ. Policy cần cả ba để đếm §1.1.5.
5. **Nhãn nguồn gốc thay cho điểm tin cậy.** Mỗi giá trị kèm `provenance` cho biết tầng nào sinh ra nó. Policy đặt ngưỡng trên nhãn này; trace log ghi nhãn này.

---

## 3. Ranh giới module

| Module | Trách nhiệm | Không được làm |
|---|---|---|
| Session Manager | Phiên theo `call_id`, lịch sử, state machine (Phụ lục A), `last_question_id` | Giữ trạng thái lịch hẹn (§4.2.2) |
| Information Extraction | Trích + chuẩn hoá các trường ở mục 1, gắn `provenance` | Đọc hồ sơ bệnh nhân; ra quyết định nghiệp vụ; chọn `transfer_reason` |
| Verifier | Đối chiếu với `patient.verify`, trả `VERIFIED` / `MISMATCH` / `INCOMPLETE` / `PATIENT_NOT_FOUND` | Sửa đầu vào cho khớp; hỏi lại |
| Policy | Điều kiện tiền đề, bộ đếm §1.1.5, giới hạn lần thử danh tính, chọn `transfer_reason` | Sinh ngôn ngữ |
| Dialogue Manager & LLM | Sinh lời thoại, chọn câu hỏi, gọi tool khi Policy cho phép | Tự ghi trạng thái; nói ngày/giờ/khoa ngoài câu mẫu |
| Output Guard | Kiểm tra lời thoại trước khi trả về (mục 7) | — |

---

## 4. Interface dữ liệu

```python
class Provenance(str, Enum):
    EXACT = "EXACT"            # luật khớp nguyên văn
    NORMALIZED = "NORMALIZED"  # khớp sau chuẩn hoá (Unicode, tiền tố lễ phép)
    FALLBACK = "FALLBACK"      # NER / LLM tuyến sau
    NONE = "NONE"              # không trích được

@dataclass(frozen=True)
class Field(Generic[T]):
    value: T | None
    provenance: Provenance
    span: str | None = None    # đoạn transcript sinh ra giá trị — bắt buộc với FALLBACK

@dataclass(frozen=True)
class ExtractionResult:
    turn: int
    question_id: str | None              # câu bot vừa hỏi, lấy từ Session
    full_name: Field[str]
    dob: Field[date | Literal["INVALID"]]
    intent: Field[Intent]
    clinical: Field[ClinicalLevel]
    agreement: Field[Agreement]
    slot_choice: Field[SlotChoice]
    cancel_reason: Field[CancelReason]
    line_signal: Field[LineSignal]
    silent: bool = False                 # silence_ms > 0 — mọi trường skipped, không tính §1.1.5
```

`InformationExtractor.extract(ctx, transcript, *, silence_ms=0)` nhận `silence_ms` nguyên từ lượt harness (Listing 2). Im lặng xác định bằng `silence_ms > 0` (Phụ lục A rev 1.1), **không** bằng transcript rỗng: người gọi có nói mà ASR không ra chữ (`silence_ms == 0`) là *không hiểu*, tính vào §1.1.5 như thường.

Quy tắc bắt buộc với `FALLBACK`: `span` phải là chuỗi con của transcript (sau chuẩn hoá). Không phải chuỗi con → coi như `NONE`. Đây là chốt chặn chống bịa đặt, không phụ thuộc vào điểm tin cậy của mô hình.

`TurnContext` còn có `pending_action` và `question_turn` (thêm ở tầng ngữ nghĩa T-05, đều có mặc định). Cả hai là **trạng thái hội thoại**, không phải hồ sơ bệnh nhân hay trạng thái lịch hẹn — nguyên tắc 2 không đổi. `tests/engine/test_orchestrator.py::test_extractor_never_sees_patient_identity` khoá danh sách trường của `TurnContext` để thêm trường mới phải cân nhắc lại ranh giới này.

---

## 5. Đặc tả từng trường

### 5.1. Tên bệnh nhân

**Trích xuất** (chỉ khi `question_id == ASK_NAME`):

```
transcript
  → chuẩn hoá Unicode NFC, lowercase, gộp khoảng trắng, bỏ dấu câu
  → loại theo CỤM: câu nghiệp vụ ("hủy lịch", "đặt lịch", "bảo hiểm"), lời đệm ("để xem")
  → loại nếu người gọi tự báo là không chắc: "hình như", "có lẽ", "chắc là", "thì phải"
  → chọn mệnh đề khẳng định sau cùng: "A, à nhầm B" → B; "không phải A" → NONE;
    "không phải A mà là B" → B
  → loại nếu còn hai ứng viên: "A hay B", "A hoặc B"
  → loại nếu chỉ là tên người khác: "mẹ tôi là ...", "gọi hộ ..."
  → bỏ tiền tố lễ phép lặp lại, so TỪNG CỤM theo cả dạng có dấu và không dấu:
    "dạ", "vâng", "tôi là", "tên tôi là", "em là", "anh/chị/cô/chú là"
  → loại nếu: rỗng, là lời chào ("alo", "ai đấy"), chứa chữ số, < 2 từ, > 6 từ,
    hoặc chứa từ chức năng ("là", "không", "gì", "của", ...)
  → Field(value, NORMALIZED)  |  Field(None, NONE)
  → [tuần 3+] chỉ khi lý do là "luật chưa hiểu" → NER fallback, span bắt buộc
```

**Lý do từ chối là một phần kết quả** (`Reading.reason`, `extraction/identity.py`). Chỉ
`NO_SIGNAL` ("không luật nào khớp") mới được hỏi tuyến sau. Các lý do đã xác định —
`NEGATED`, `UNCERTAIN`, `AMBIGUOUS`, `NOT_A_NAME`, `OTHER_PERSON` — chặn NER: nếu không,
"không phải Nguyễn Văn A" quay về thành "Nguyễn Văn A" và đi thẳng vào Verifier.

**Từ khoá không loại được tên.** Loại theo cụm chứ không theo từ đơn, nên "Nguyễn Thanh
Toàn", "Trần Văn Lịch", "Nguyễn Văn Cần", "Nguyễn Thị Ái", "Lê Văn Thôi", "Trần Văn Được"
vẫn lấy được. Giới hạn 2–6 từ là quyết định sản phẩm cho tập tên ở đây, không phải quy luật
của mọi tên người ([W3C][w3c-names]).

Khi một câu bị loại vì là câu nghiệp vụ, bộ điều phối trả nó về đúng nhãn intent
(`hủy lịch đi` → `CANCEL`) thay vì để `claimed_name` nhận một câu nói.

[w3c-names]: https://www.w3.org/International/questions/qa-personal-names

**So khớp** (trong Verifier, không phải trong bộ trích xuất):

1. **Ngày sinh là cổng.** `dob` phải khớp chính xác. Không khớp → `MISMATCH`, không xét tên.
2. Tách tên thành từ, **căn từ cuối lên**: `[tên chính, tên đệm..., họ]`.
3. **Tên chính**: phải bằng nhau sau khi chuẩn hoá. Không bỏ dấu ở tuần 1–2 (text mode). Từ tuần 3 cho phép bỏ dấu thanh, **không** gộp phụ âm.
4. **Tên đệm**: cho phép bỏ dấu thanh; cho phép gộp các cặp nhầm do ASR (tr/ch, s/x, d/gi/r, n/l) — chỉ ở tầng này.
5. **Họ**: cho phép bỏ dấu thanh.
6. Số từ khác nhau (thiếu tên đệm) → `MISMATCH` ở tuần 1–2; từ tuần 3 xét lại dựa trên dữ liệu.
7. Không dùng Jaro-Winkler: điểm cộng tiền tố rơi vào họ, ngược với yêu cầu.

Mọi quy tắc nới lỏng (3–6) bật/tắt bằng cấu hình, không hardcode.

**Đo lường:** tỉ lệ **chấp nhận nhầm** trên tập tên gần giống — cùng họ khác tên; cùng tên chính khác dấu (Hà/Hạ/Hải); khác một cặp phụ âm vùng miền — chứ không đo accuracy chung.

### 5.2. Ngày sinh

- Nhận: "ngày 14 tháng 3 năm 1978", "14/3/1978", "14-03-78", "mười bốn tháng ba năm bảy tám", đọc số rời "một bốn không ba một chín bảy tám".
- Bảng số đếm: "mốt", "tư", "lăm", "linh", "lẻ", "mươi".
- Năm 2 chữ số: chọn thế kỷ sao cho tuổi nằm trong [0, 110]. Nếu cả hai thế kỷ đều hợp lệ → `INVALID` (hỏi lại).
- Ngày không tồn tại (31/02) → `INVALID`. **Không** tự sửa về ngày gần nhất.
- Thiếu năm → `INVALID`. **Không** điền năm hiện tại.
- Người gọi nói tuổi thay năm sinh, hoặc ngày âm lịch → `INVALID`, hỏi lại theo dương lịch.
- Người gọi tự sửa trong câu ("14... à không, 15 tháng 3") → lấy giá trị **sau cùng**; nếu phần sửa không đủ ngày/tháng/năm → `INVALID`.
- **Phủ định khác tự sửa.** "không phải 14/3/1978" → `INVALID` (bác bỏ mà không có gì thay thế). Chỉ "không phải A **mà là** B" mới lấy B.
- **Hai giá trị cùng được nêu** mà không có lời sửa → `INVALID`: "14 hay 15 tháng 3 năm 1978", "14 tháng 3 năm 1978 hoặc 1979", hai ngày khác nhau trong một câu.
- **Người gọi tự báo là không chắc** → `INVALID`, hỏi lại: "hình như", "có lẽ", "chắc là", "không chắc", "không nhớ rõ/lắm", "thì phải". Không dùng riêng từ "chắc" (nằm được trong tên). Lời đệm ngập ngừng ("à ừ…") **không** phải dấu hiệu không chắc.
- Không có ngày nào trong câu thì cụm phân vân không tạo ra `INVALID` — đó là `CANNOT_PROVIDE` (§1.1.1), không phải một ngày sai.
- **`span` là đoạn có thật** trong transcript sau chuẩn hoá. "14/3/1978" báo `span = "14 3 1978"`, không bao giờ báo đoạn "ngày 14 tháng 3 năm 1978" mà bộ trích xuất tự dựng để dùng chung ngữ pháp với dạng nói.

### 5.3. Số điện thoại — hoãn

- Outbound: không cần.
- Inbound: đã có `caller_number` để gọi `GET /patients?phone=` (§1.1.9 — chỉ tra cứu, không phải bằng chứng).
- Chỉ cần trích từ lời nói khi người gọi dùng máy khác số đã đăng ký. Contract không yêu cầu kịch bản này.
- **Việc cần làm:** hỏi PO có kịch bản này trong test set không; kiểm tra clinic mock lưu số ở định dạng nào (`0962…` hay `+84962…`) trước khi chọn chuẩn hoá.
- Nếu làm: regex + bảng đọc số → chuỗi đúng định dạng của mock; lỗi ở tuần 2 vượt ngưỡng thì chuyển sang WFST tiếng Việt của NeMo [8], đo trên bộ VietAI [9].

### 5.4. Intent

| Nhãn | Ví dụ | Ghi chú |
|---|---|---|
| `CONFIRM` | "tôi sẽ đến", "đến được" | chỉ outbound |
| `CANCEL` | "hủy giúp tôi", "không đi được nữa" | |
| `RESCHEDULE` | "đổi sang chiều", "dời lịch" | |
| `BOOK` | "tôi muốn đặt lịch khám" | chỉ inbound |
| `REQUEST_HUMAN` | "cho gặp nhân viên" | → `PATIENT_REQUEST` |
| `OUT_OF_SCOPE` | bảo hiểm, thanh toán, chuyển tuyến, đơn thuốc (§1.2.3); hỏi địa chỉ / đường đi / gửi xe; yêu cầu ngoài kịch bản bot hiểu được: người khác đi khám thay ("vợ tôi sẽ đến thay"), đến muộn, xin gọi lại | → `OUT_OF_SCOPE`. Chủ đề không bị phủ định chặn; yêu cầu thì có ("không đến trễ đâu") và xếp sau đổi / hủy / đặt ("tôi sợ đến trễ, dời sang 10 giờ" là `RESCHEDULE`). Xin gọi lại chỉ xét sau xác minh — ở bước hỏi tên vẫn hỏi lại tên (T-08) |
| `REPEAT_REQUEST` | "gì cơ?", "nói lại giúp" | **không** tính vào §1.1.5 |
| `NOT_PATIENT` | "tôi là vợ anh ấy", "anh ấy đi vắng" | outbound → chuyển máy, không tiết lộ |
| `NONE` | không nhãn nào đạt | tính vào §1.1.5 |

**Quy tắc ưu tiên** khi một câu khớp nhiều nhãn:

```
REQUEST_HUMAN > NOT_PATIENT > OUT_OF_SCOPE (chủ đề) > RESCHEDULE > CANCEL > BOOK > OUT_OF_SCOPE (yêu cầu) > CONFIRM > REPEAT_REQUEST
```

- "Không đến được, đổi sang chiều được không" → `RESCHEDULE` (có phương án thay thế).
- Cụm phủ định đứng trước từ khoá phải được xử lý trước: "không hủy", "đừng hủy", "không đổi", "giữ nguyên lịch" → **không** là `CANCEL` / `RESCHEDULE`.

**Lý do hủy là yêu cầu hủy** (06/10/2026, QC `qc-cn-03-went-elsewhere`, `extraction/implied_cancel.py`). Ở `CONFIRM_READBACK` / `ASK_INTENT` outbound, `cancel_reason` được trích bằng luật. Khi luật intent ra `NONE` và không có nội dung lâm sàng, lý do dưới đây là `CANCEL` (span = cụm lý do), không gọi model:
- Luật chỉ là đường tắt cho câu **ngắn, rõ**, theo một khuôn cho phép (không liệt kê các cách nói "chưa khám"): (lời đáp ngắn "không" / "dạ"…,) + chủ ngữ / tiếng đệm / "đã" / động từ đi khám + cụm lý do + "rồi" / tiểu từ. Ví dụ "Không, tôi khám chỗ khác rồi", "tôi đã khám ở nơi khác", "Tôi khỏi rồi em".
- `WENT_ELSEWHERE` cần dấu hiệu đã xảy ra ("rồi" từ cụm lý do trở đi, hoặc "đã" trước nó); `NO_LONGER_NEEDED` chỉ nhận cụm dứt khoát ("khỏi rồi", "khỏe rồi", "không cần nữa"; "hết đau rồi" có chữ "đau" nên vẫn đi tuyến lâm sàng).
- Câu có bất cứ từ nào ngoài khuôn, kể cả chữ nằm giữa hai cụm lý do ("tôi khỏi rồi nhưng không chắc là khỏe rồi") — dự định ("định / sẽ khám chỗ khác"), đặt lịch nơi khác ("tôi đã đặt hẹn ở bệnh viện khác"), "rồi" = sau đó ("… rồi báo lại"), phủ định, câu hỏi, "nhưng", không chắc, nhiều lý do — không nâng: intent luật là `NONE`, lượt đi tuyến ngữ nghĩa (`INTENT_UNCLEAR`); model đọc ra lý do (`WENT_ELSEWHERE`...) và chuyển nhu cầu. Không có model thì đi đường cũ như trước khi có luật này (thường là "em chưa hiểu"; hỏi "đổi hay hủy" khi câu có lời từ chối). Cách nói lý do mà luật không biết ("khám ở viện khác rồi", "khám bên viện khác rồi") cũng để model đọc, không bổ sung vào danh sách cụm. Luật nhãn khác (`RESCHEDULE`, `CONFIRM`, `REQUEST_HUMAN`...) vẫn thắng.
- Chỉ là lượt yêu cầu: lệnh ghi vẫn cần lượt xác nhận sau có động từ "hủy" (§1.1.4, SF-05).

**Khớp một cụm không đủ để quyết cả câu** (06/10/2026, rà soát rule). Luật chỉ quyết khi cụm khớp nằm trong câu rõ nghĩa; câu còn tín hiệu ngược thì không quyết, để tầng ngữ nghĩa đọc hoặc hỏi lại:
- `REQUEST_HUMAN` chỉ nhận khung yêu cầu ("gặp / chuyển (sang) / nói chuyện với nhân viên", "chuyển máy", "nối máy"…) hoặc cả câu chỉ là "nhân viên". "Nhân viên đã hẹn tôi đến hôm đó", "tôi không muốn gặp bất kỳ nhân viên nào" không chuyển máy.
- Địa chỉ (`OUT_OF_SCOPE`) chỉ nhận cụm hỏi / xin ("… ở đâu", "xin / cho tôi / gửi địa chỉ"); danh từ trơ "địa chỉ bệnh viện" ("tôi biết địa chỉ bệnh viện rồi, tôi sẽ đến") không còn chuyển máy.
- `NOT_PATIENT` từ cụm vắng mặt ("đi vắng", "không ở nhà") không áp dụng khi có chủ ngữ ngôi thứ nhất ngay trước ("Tôi đi vắng nên muốn đổi lịch").
- Lâm sàng: câu hỏi đánh giá ("có sao không", "có ảnh hưởng gì không") về việc với lịch hẹn ("hủy lịch có sao không") mà không có từ triệu chứng / bệnh / thuốc chỉ là `MENTION` → tầng ngữ nghĩa đọc lại (`CLINICAL_UNRESOLVED`); có nội dung sức khỏe thì vẫn `ADVICE_REQUEST` / `EMERGENCY`.
- `CANCEL` / `RESCHEDULE` của luật ở câu đọc lịch / "đổi hay hủy" outbound trong câu chưa phải quyết định — điều kiện / ngập ngừng ("nếu tôi bận thì hủy nhé"), lời kể lại đứng trước nhu cầu ("vợ tôi bảo hủy lịch"), chưa quyết, hỏi hệ quả ("hủy lịch có sao không") — đi route `INTENT_HEDGED`: chỉ model chuyển nhu cầu (`CHANGE_INTENT`) mới đặt lại intent; không có model hay model mơ hồ thì intent là `NONE`, bot hỏi lại. Câu hỏi lịch sự ("đổi sang chiều được không?", Figure 0) và "nhưng" mở ra yêu cầu ("tôi không bận nhưng muốn hủy") vẫn là yêu cầu.
- Tự sửa ("đổi lịch, à thôi hủy đi", "hủy lịch, à nhầm, đổi lịch"): intent đọc trên phần nói SAU lời sửa cuối cùng, không lấy cụm khớp trước theo thứ tự ưu tiên. Phần đó không có nhu cầu ("đổi lịch, à thôi") thì intent là `NONE`, tuyến ngữ nghĩa đọc cả câu.
- `cancel_reason`: lý do bị bác bỏ ("hủy, không phải vì không đủ tiền", "chẳng phải do bận") không được ghi; không còn lý do nào thì `UNSPECIFIED`.
- `slot_choice`: tự sửa ("không phải khung 1 mà là khung 2", "khung 2 chứ không phải khung 1") chỉ đọc phần đúng; loại trừ ("trừ khung 1", "không lấy khung 1") bỏ khung bị loại khỏi các khung vừa đọc — còn một khung thì chọn (vẫn đọc lại để xác nhận), còn nhiều thì hỏi lại; "sau / từ / trước X giờ" là khoảng giờ (`SlotCriteria.not_before` / `before`), không phải khung X giờ.

**Ở bước danh tính** (`ASK_NAME`, `ASK_DOB`) không chạy nhãn nghiệp vụ — tên "Lê Văn Thôi", "Trần Văn Được" không được thành từ chối / xác nhận:
- Luôn chạy: `REQUEST_HUMAN`, `NOT_PATIENT`, `REPEAT_REQUEST` (câu này không được đọc thành tên).
- Chạy **sau** khi trích tên / ngày sinh thất bại: `OUT_OF_SCOPE`. Tên hợp lệ luôn thắng, vì "thanh toan" trùng tên "Thanh Toàn" khi mất dấu.
- Outbound: ý định `CANCEL` nói gộp với tên / ngày sinh được trả riêng trong `deferred_intent` (kèm `deferred_cancel_reason`), tìm trên phần transcript **ngoài tên đã trích** ("Trần Văn Hủy" không phải yêu cầu hủy) và xét đủ thứ tự ưu tiên ("không đi được, đổi sang chiều" là đổi lịch). `intent` của lượt danh tính không đổi; Dialogue chỉ dùng `deferred_intent` sau khi xác minh xong.
  - "hủy" chỉ là động từ trong khung yêu cầu ("muốn hủy", "hủy lịch", "không hủy nữa"); đứng trơ trọi ("Trần Thị Hủy, sinh …" ở `ASK_DOB`, "tôi tên Hủy") là tên, kể cả khi tên không được trích.
  - Chỉ giữ yêu cầu hủy rõ ràng: câu hỏi, câu có "nhưng" hoặc ngập ngừng ("…hủy lịch có được không") không được giữ.
  - Không liệt kê các cách đổi ý: lượt định danh còn từ nào ngoài tên (tên đã trích, hoặc mệnh đề mà luật đọc tên xác nhận là tên — không cắt mù phần trước / sau ngày sinh), vùng ngày sinh đọc được, chữ số và từ đệm ("dạ", "tôi", "sinh", "nhé"…) mà không phải yêu cầu hủy rõ ràng thì `deferred_intent` là `NONE` có span ("tôi đổi ý rồi", "không hủy nữa", "đổi lịch sang tuần sau"); Dialogue bỏ yêu cầu hủy đã giữ. Sau xác minh bot đọc lịch và hỏi có đến được không — tức là hỏi lại nhu cầu. Đoán sai theo hướng nào cũng chỉ tốn một lượt hỏi, không ghi gì.

**Tuyến sau:** LLM với tập nhãn đóng, chỉ gọi khi luật cho `NONE`. Không đưa thông tin lịch hẹn hay hồ sơ vào prompt. Lỗi ở tầng này sửa được nhờ bước đọc lại và xác nhận (§1.1.3, §1.1.4, §1.1.10).

### 5.5. Câu hỏi lâm sàng — 3 lớp

Chạy **trước** intent. §1.2.1 cấm *chẩn đoán, giải thích triệu chứng, tư vấn thuốc, ra quyết định lâm sàng* — không cấm việc người gọi *nhắc tới* triệu chứng.

| Lớp | Ví dụ | Hành động | Hướng hiệu chỉnh |
|---|---|---|---|
| `EMERGENCY` | "đau ngực", "khó thở", "co giật", "ngất", "chảy máu nhiều" | Chuyển máy ngay, `CLINICAL_QUESTION` | **Recall** — bỏ sót là SF-04 |
| `ADVICE_REQUEST` | "có sao không", "uống thuốc gì", "nên khám khoa nào", "có cần đi khám gấp không" | Chuyển máy, `CLINICAL_QUESTION` | Recall |
| `MENTION` | "hay đau bụng nên muốn đặt lịch", "tái khám dạ dày" | **Không** chuyển máy; tiếp tục kịch bản; bot không bình luận triệu chứng | **Precision** — chuyển nhầm là case fail |
| `NONE` | | | |

Nguyên tắc phân lớp: `ADVICE_REQUEST` cần **hành vi hỏi** (từ nghi vấn, yêu cầu đánh giá). Chỉ có từ triệu chứng mà không có hành vi hỏi → `MENTION`, trừ khi thuộc danh sách `EMERGENCY`.

`MENTION` không chuyển máy là **cách hiểu** §1.2.1 của nhóm ("MUST transfer instead, every time" gắn với việc bot phải tư vấn, không gắn với việc người gọi nhắc triệu chứng) — đang chờ xác nhận (mục 10, câu 6). IE chỉ gắn nhãn; nếu câu trả lời là "phải chuyển", chỉ đổi Policy.

### 5.6. Câu trả lời có / không (agreement)

- Chỉ chạy khi `question_id` là một câu hỏi xác nhận. Kết quả gắn với `question_id` đó; không mang sang lượt sau.
- Ba giá trị: `AGREE`, `REFUSE`, `UNCLEAR`.

**Ngưỡng theo hành động được mở khóa:**

| `question_id` | Hành động | "vâng" / "dạ" / "ừ" đứng một mình | "có" / "được" / "đúng" đứng một mình | Cần để `AGREE` |
|---|---|---|---|---|
| `ASK_ATTENDANCE` | không ghi — dẫn tới `CONFIRM_READBACK` | `AGREE` | `AGREE` | từ khẳng định bất kỳ, câu được giải thích hết |
| `CONFIRM_READBACK` (§1.1.3) | ghi `CONFIRMED` | `AGREE` | `AGREE` | từ khẳng định bất kỳ, câu được giải thích hết |
| `SLOT_READBACK` (§1.1.6, §1.1.10) | ghi `RESCHEDULED` / `BOOKED` | `UNCLEAR` | `AGREE` | "được", "đồng ý", "đổi đi", "đặt đi"; câu được giải thích hết |
| `CANCEL_RECONFIRM` (§1.1.4) | ghi `CANCELLED` | `UNCLEAR` | `UNCLEAR` | động từ hủy tường minh: "hủy đi", "hủy giúp tôi", "đúng, hủy" |

Figure 0 rev 1.1 gộp tóm tắt lịch, đọc lại ngày/giờ/khoa và câu hỏi "Anh chị đến được không ạ?" vào **một lượt**; câu trả lời "Có, tôi đến được." ghi `CONFIRMED` ngay. Câu gộp đó mang `question_id = CONFIRM_READBACK`. `ASK_ATTENDANCE` chỉ dùng khi Dialogue hỏi "có đến được không" **trước** khi đọc lại.

**Câu trả lời được giải thích hết (T-04 §8):** ở `CONFIRM_READBACK`, `ASK_ATTENDANCE`, `SLOT_READBACK`, tín hiệu đồng ý chỉ thành `AGREE` khi phần còn lại của câu chỉ là tiểu từ ("ạ", "nhé", "rồi"...), xưng hô ("tôi", "em"...), lễ phép ("cảm ơn") và bổ ngữ của câu hỏi (đến khám: "khám", "đúng giờ", "hôm đó", "có mặt"...; slot: "đổi", "giúp", "khung đó"...). Còn từ nội dung khác → `UNCLEAR` có tín hiệu (đọc lại / hỏi lại; tầng ngữ nghĩa xét nếu không có intent). Lý do: "dạ" mở câu chỉ là lễ phép và "có / phải / được / đúng" là hư từ của câu kể — "dạ hôm đó tôi bận rồi", "hôm đó tôi có việc bận", "tôi phải đi làm", "vợ tôi sẽ đến thay", "tôi sẽ đến lúc 10 giờ" từng ghi `CONFIRMED`. `CANCEL_RECONFIRM` không áp dụng (đã đòi động từ hủy). Danh sách từ đệm: `agreement._FILLER_WORDS`, `_ATTEND_COMPLEMENTS`, `_SLOT_COMPLEMENTS`; thêm từ mới phải kèm ca âm tính trong `eval/confirm/cases.csv`.

**Câu hỏi đến khám (`CONFIRM_READBACK`, `ASK_ATTENDANCE`) — T-04:**
- "Vâng" / "dạ" / "ừ" / "ờ" là xác nhận, kể cả khi kèm lời được giải thích hết ("vâng, cảm ơn em"); kèm việc khác thì không (T-04 §8). "À", "ạ", "ừm" đứng riêng chỉ là tín hiệu `UNCLEAR`.
- Các câu khẳng định không có từ đồng ý gốc cũng là `AGREE`: "nhất định rồi", "đương nhiên", "đến chứ", "không thành vấn đề" (T-04 §8).
- Câu **khẳng định sẽ đến** không có từ đồng ý ("tôi sẽ đến", "vẫn đến", "xác nhận") là `AGREE` — contract Bảng 1 "states or agrees they will attend". IE truyền cụm intent `CONFIRM` vào `extract_agreement(attendance=...)`; cụm này chỉ được xét **sau** mọi chặn (câu hỏi đuôi, "nhưng", ngập ngừng, từ chối) và chỉ ở câu hỏi đến khám.
- "Giữ lịch", "giữ nguyên lịch" → `AGREE`; "không hủy", "đừng hủy", "không cần hủy", "không (cần) đổi", "khỏi đổi" không phải từ chối đến khám (chỉ còn `UNCLEAR` nếu không có gì khác). Ở `CANCEL_RECONFIRM` / `SLOT_READBACK` các cụm này vẫn là `REFUSE`.
- Ở `ASK_INTENT` outbound (sau khi từ chối, bot hỏi "đổi hay hủy"), "giữ nguyên", "không đổi không hủy gì cả" là intent `CONFIRM` → đọc lại lịch (T-04 §8).
- Tầng ngữ nghĩa ở `CONFIRM_READBACK` (T-04 §8): `INFORM_REASON` có mã lý do cụ thể ("hôm đó tôi bận") → `REFUSE` để hỏi đổi hay hủy; lý do `UNSPECIFIED`, hoặc câu có "không hủy / không đổi" → `UNCLEAR` (đọc lại); `CONFIRM_ACTION` → `UNCLEAR`. Model không bao giờ nâng lên `AGREE`.
- Luật intent không được chặn model (T-04 §8): outbound, khi luật ra `CONFIRM` nhưng agreement `UNCLEAR` có tín hiệu (`CONFIRM_READBACK`), hoặc cụm `CONFIRM` không giải thích hết câu (`ASK_INTENT`), router vẫn gọi tầng ngữ nghĩa (`ATTENDANCE_UNCLEAR`). Câu đồng ý thật là `AGREE` nên không bị gọi model.

**Bẫy phủ định:**
- "không sao", "không vấn đề gì", "không có gì" → `AGREE` (khi đang hỏi xác nhận).
- "… được **không**?" (câu hỏi đuôi) → `UNCLEAR`, không phải `REFUSE`.
- "thôi", "để sau", "chưa", "không hủy nữa", "giữ lịch" → `REFUSE` (trừ "giữ lịch", "không hủy" ở câu hỏi đến khám — xem trên).
- **Ngập ngừng** ("để xem", "chắc là", "chắc được", "có lẽ", "chưa chắc", "không biết", "để tôi hỏi", "hy vọng", "mong là", "cố gắng", "nếu") → `UNCLEAR` ở mọi câu hỏi xác nhận, kể cả khi có "vâng" / "được" ("chắc là được"). Không có "chắc" đứng một mình: "chắc chắn" là khẳng định.
- "không thành vấn đề", "không có vấn đề gì" → `AGREE` như "không sao" (T-04 §8).
- Nói vòng ("hôm đó tôi bận mất rồi") → luật cho `UNCLEAR`, tuyến sau xét.

**Khi `UNCLEAR`:** ở câu hỏi đến khám, Dialogue **đọc lại** ngày, giờ, cơ sở bằng câu có / không ("vâng" là câu trả lời hợp lệ — kiến trúc §3.2 "Chưa rõ → O_READ"). Ở hủy / chọn slot, hỏi lại bằng **câu lựa chọn A/B** để từ đáp lễ phép không còn là câu trả lời hợp lệ:
- "Anh chị muốn **hủy** hay **giữ** lịch khám ạ? Nếu muốn hủy, anh chị xác nhận 'hủy lịch' giúp em ạ."
- "Anh chị chọn khung **14 giờ 30** hay muốn **nghe khung khác** ạ?"

Câu hủy nói luôn cụm cần nói, vì ngưỡng `AGREE` ở `CANCEL_RECONFIRM` đòi động từ hủy tường minh (T-05).

`UNCLEAR` lần đầu ở bước xác nhận **không** tính vào §1.1.5; lần thứ hai liên tiếp mới tính.

### 5.7. Chọn slot

- Tập ứng viên = **toàn bộ** slot `GET /slots` trả về trong cuộc gọi này (không chỉ các slot đã đọc cho người gọi).
- Lời người gọi → **tiêu chí lọc**: thứ tự ("khung thứ hai", "cái đầu"), giờ ("hai giờ rưỡi"), buổi ("chiều"), ngày ("thứ năm", "mùng 5", "tuần sau" — tính theo ngày cuộc gọi, múi giờ +07:00).
- Đầu ra:
  - `MATCH(slot_id)` — đúng 1 slot thoả mọi tiêu chí.
  - `AMBIGUOUS(slot_ids)` — nhiều slot → bot đọc tối đa 3 slot trong số đó, hỏi lại.
  - `NO_MATCH` — không slot nào → bot đọc các slot gần nhất có trong danh sách.
- "Hai giờ rưỡi" không có sáng/chiều → so với danh sách; chỉ khớp một trong 02:30 / 14:30 thì lấy slot đó.
- **Không bao giờ** dựng mốc thời gian mới từ lời người gọi. SF-02 không xảy ra được về mặt cấu trúc.
- Sau `MATCH` luôn đọc lại và cần `agreement == AGREE` (mục 5.6) trước khi ghi.
- 409 `SLOT_TAKEN` → gọi lại `GET /slots`, thay tập ứng viên, đề xuất lại; không retry mù.

### 5.8. cancel_reason

| Cụm từ tường minh | Mã |
|---|---|
| "bận", "đi công tác", "hôm đó không đi được" | `PATIENT_UNAVAILABLE` |
| "khỏi rồi", "không cần khám nữa" | `NO_LONGER_NEEDED` |
| "khám chỗ khác rồi", "đi viện khác" | `WENT_ELSEWHERE` |
| "đắt quá", "không đủ tiền" | `COST` |
| không nêu / không khớp | `UNSPECIFIED` |
| nêu nhiều lý do khác nhau trong một câu | `UNSPECIFIED` |

- Không suy diễn lý do từ ngữ cảnh; đây là trường ghi vào hồ sơ.
- Không bắt buộc hỏi lý do. Nếu hỏi, chỉ hỏi **một lần**, sau khi đã có xác nhận hủy lần hai.
- Cụm bị phủ định không phải lý do: "tôi **không** bận nhưng muốn hủy" → không có tín hiệu lý do.

**Hai cách ra `UNSPECIFIED` phải phân biệt được (T-05).** Cả hai đều trả `value = "UNSPECIFIED"`, nhưng
`provenance` khác nhau vì Dialogue xử lý khác nhau:

| Trường hợp | `provenance` | `span` | Dialogue làm gì |
|---|---|---|---|
| Lượt không có nội dung lý do nào | `NONE` | rỗng | Giữ nguyên lý do đã ghi nhận ở lượt trước |
| Nêu nhiều lý do không chọn được | `EXACT` / `NORMALIZED` | các cụm đã khớp, nối bằng " + " theo thứ tự bảng trên | Thay lý do cũ bằng `UNSPECIFIED`, **không** giữ ngầm giá trị cũ |

**Vòng đời trong nhánh hủy (T-05).** Lý do được nhận ở **mọi** lượt có nội dung lý do, không riêng lượt
đồng ý; nhận lý do **không** đồng nghĩa đã xác nhận hủy. Lý do mới rõ ràng thay lý do cũ. Rời nhánh hủy
(bỏ hủy hoặc chuyển sang đổi lịch / đặt lịch) xoá lý do; quay lại hủy phải nêu lại, mặc định `UNSPECIFIED`.

### 5.9. Tín hiệu đường dây

Giá trị **trùng tên** `unreachable_reason` ở Phụ lục A rev 1.1, để Policy ghi thẳng mà không cần bảng ánh xạ. `SILENCE` không thuộc IE — xem `silent` ở mục 4.

| Mẫu | Giá trị | Hành động (Policy) |
|---|---|---|
| "để lại lời nhắn", "sau tiếng bíp", "hộp thư thoại", "leave a message", "after the tone" | `VOICEMAIL` | `POST /unreachable` với `VOICEMAIL`; **không** để lại chi tiết lịch hẹn (§1.1.7) |
| Lời chào hộp thư cá nhân (T-08): "bạn đã gọi đến số", "cảm ơn bạn đã gọi", "hiện không thể nghe máy", "hiện không nghe máy được", "you've reached", "can't take your call", "please leave your name" | `VOICEMAIL` | như trên |
| Trạng thái `LINE_BUSY` từ adapter điện thoại, không suy từ transcript | Không thuộc IE | Policy trong Core → `POST /unreachable` với `LINE_BUSY` |
| Trạng thái `NO_ANSWER` từ adapter điện thoại, không suy từ transcript | Không thuộc IE | Policy trong Core → `POST /unreachable` với `NO_ANSWER` |

- `VOICEMAIL` xét trước: "thuê bao không liên lạc được, vui lòng để lại lời nhắn" là đã vào hộp thư.
- Mẫu lời chào cá nhân chỉ gồm cụm người đã nghe máy gần như không nói. **Không** nhận "không nghe máy được", "sẽ gọi lại cho bạn", "gọi lại sau": người thật đang bận vẫn nói các câu đó (bẫy ở `test_human_speech_is_not_a_line_signal`).
- `LINE_BUSY` / `NO_ANSWER` **bắt buộc chỉ đến từ trạng thái điện thoại**. Transcript có lời thông báo tổng đài cũng không đủ để xác định kết quả quay số.
- Trên đường chấm điểm chỉ có `SILENCE` và `VOICEMAIL`. Trạng thái điện thoại là đầu vào nội bộ của adapter, không phải trường trong API chấm điểm.

Chạy trước mọi bộ khác ở **mọi lượt outbound trước khi xác minh xong** (`question_id` rỗng, `ASK_NAME`, `ASK_DOB`), không chỉ lượt đầu: §4.2.5 nói VOICEMAIL đến bằng clip lời chào nhưng không nói ở lượt nào. Khác `NONE` thì dừng, không đọc câu hộp thư thành tên. Inbound không chạy (§1.1.7 rev 1.1 chỉ áp dụng outbound).

### 5.10. Transcript không dấu (audio mode)

Câu **không có ký tự mang dấu nào** được so với bản không dấu của từ khoá, `provenance = NORMALIZED`.

**Dấu pha trộn.** ASR hay bỏ dấu một phần ("Dạ toi la Nguyen Van A", "ngày 14 thang 3 nam 1978"). Hai bộ danh tính so **theo từng cụm / từng token** ở cả hai dạng, thay vì quyết định một lần cho cả câu:

- tên: mỗi tiền tố lễ phép được thử cả hai dạng, nên "toi la" bị bỏ dù câu có chữ "Dạ" mang dấu; "ạ" vẫn nằm ngoài dạng không dấu để giữ chữ "A" cuối tên;
- ngày sinh: khôi phục dấu cho **từng token** mất dấu thuộc bảng từ đóng, token đã có dấu giữ nguyên.

Mẫu không dấu chỉ khớp đúng chuỗi ký tự không dấu, nên chế độ này không làm câu có dấu khớp nhầm; các cụm nguy hiểm khi mất dấu vẫn bị `unaccented_exclude` loại (vd. "à không", vì "a" là một tên thật).

Các bộ còn lại giữ nguyên: câu có dấu một phần vẫn so có dấu.

Bỏ dấu làm nhiều từ trùng nhau, nên mỗi danh sách tự khai báo cụm bị loại ở chế độ này. Hướng xử lý theo nguyên tắc 3 (mục 2): trùng nghĩa ở chỗ mở khóa hành động thì lệch về **không mở khóa**.

| Bộ | Cách làm | Ví dụ loại trừ / luật riêng |
|---|---|---|
| intent | Khớp từ khoá không dấu | "dời" (= đợi), "tôi đến" (= tối đến) |
| clinical | Chỉ cụm tường minh; **tắt** luật "từ triệu chứng + câu hỏi → `ADVICE_REQUEST`" | "tự tử" (= từ từ), "liều" (= liệu), "có lây không" (= có lấy không) |
| agreement | Bỏ từ đáp lễ và từ khẳng định trùng nghĩa; "dung" đứng một mình → `UNCLEAR`; "a" cuối câu là câu hỏi | "dạ" (= đã), "có" (= cô), "dung huy" (= đúng hủy / đừng hủy), "huy a" (= hủy ạ / hủy à) |
| cancel_reason | Khớp không dấu | "bận" (= bạn), "đắt" (= đặt) |
| full_name | Trả tên không dấu nguyên dạng; Verifier so theo chế độ bỏ dấu thanh (mục 5.1, tuần 3) | Không bỏ "ạ" cuối câu ("nguyen van a") |
| dob, slot_choice | Khôi phục dấu cho **bảng từ đóng** (số, ngày/tháng/năm, giờ/buổi/thứ) rồi parse như thường | "muoi" = mười / mươi theo từ đứng trước; "sang"/"toi" chỉ thành sáng/tối sau "giờ"/"buổi" |

Đo trên transcript ASR 8 kHz của nhóm: tỉ lệ `NONE` của intent / agreement, và mọi ca `AGREE` ở `CANCEL_RECONFIRM` có `provenance = NORMALIZED`.

### 5.11. Tầng ngữ nghĩa (`gpt-4o-mini`) — T-05

Luật từ khoá không thấy được ranh giới mệnh đề. Hai lỗi đo được trên baseline:

| Câu ở `CANCEL_RECONFIRM` | Luật đọc thành | Đúng phải là |
|---|---|---|
| "tôi không đủ tiền" | `REFUSE` (chữ "không") → bỏ hủy, **mất luôn lý do** | nêu lý do `COST`, vẫn chờ xác nhận |
| "không, hủy đi" | `clean` bỏ dấu phẩy → khớp "không hủy" → giữ lịch | mâu thuẫn, phải hỏi lại |

Hai chốt chặn ở **tầng luật** (chạy cả khi tắt model, `extraction/extractor.py`, `agreement.py`):
- Đoạn làm nên `REFUSE` nằm **gọn trong** đoạn làm nên `cancel_reason` → lượt này là lượt chỉ nêu lý do. Lời từ chối tường minh không nằm trong lý do ("không hủy nữa, dù tôi không đủ tiền") vẫn là `REFUSE`.
- Cụm từ chối hủy bị **dấu câu cắt đôi** → `UNCLEAR`. Dấu câu của ASR chỉ là một tín hiệu; câu mâu thuẫn không có dấu câu do tầng ngữ nghĩa xử lý.

**Router** (`extraction/semantic_router.py`) quyết định gọi model, trả `None` hoặc một mã lý do. Không dùng `found` như điểm tin cậy.

| Tình huống | Gọi model? |
|---|---|
| Im lặng, transcript rỗng, `OFFER_SLOTS`, `SLOT_READBACK` | Không |
| Bước tên / ngày sinh có định danh, lời chào, "ai đấy?" hoặc nhãn chính sách | Không |
| Bước tên / ngày sinh, lượt không có định danh nào (06/10/2026, QC qc-id-05) | `IDENTITY_TURN` — model chỉ cho biết người gọi có đang HỎI không (`caller_question`); không đổi intent, không đọc định danh |
| Lâm sàng, xin người thật, sai danh tính, ngoài phạm vi, xin nhắc lại | Không — Policy đã đủ căn cứ |
| Câu khớp **toàn câu** trong tập rõ ("hủy giúp tôi", "không hủy nữa", "vâng") | Không |
| `CANCEL_RECONFIRM`, từ chối kèm lý do | `CANCEL_REFUSAL_WITH_REASON` |
| `CANCEL_RECONFIRM`, tín hiệu ngược nhau / ngập ngừng | `CANCEL_CONTRADICTION` |
| `CANCEL_RECONFIRM`, các câu còn lại | `CANCEL_UNRESOLVED` |
| `ASK_INTENT` / `CONFIRM_READBACK`, không có ý định dùng được và cũng không có có/không dứt khoát | `INTENT_UNCLEAR` |
| `CONFIRM_READBACK` outbound, câu mâu thuẫn có ý định `CANCEL` / `RESCHEDULE` | `NEED_CONFLICT` |
| `CONFIRM_READBACK` / `ASK_INTENT` outbound, `CANCEL` / `RESCHEDULE` trong câu chưa phải quyết định | `INTENT_HEDGED` |

Ở `ASK_NAME`, slot filling tên và tầng ngữ nghĩa dùng chung một lần gọi model mỗi lượt (stage 1). Lượt luật không đọc ra tên mà có dấu hiệu hỏi hoặc nhắc tới lịch hẹn ("tôi khám hôm nào vậy em?", "cứ đọc lịch trước đi", "nói giờ trước đã" — từ 06/10/2026 "giờ", "khám" đứng riêng cũng tính) nhường lần gọi đó cho tầng ngữ nghĩa thay vì slot filling tên — chỉ là chọn model nào đọc câu.

**Prompt `semantic_v9_luna`** (06/10/2026) = v8 + nguyên tắc chung, không bám câu cụ thể: (5) phân loại theo quyết định sau cùng — tiếng đệm / ngập ngừng / tự sửa trước một quyết định rõ không làm câu thành `AMBIGUOUS`; hai ý trái ngược đứng cạnh nhau không có lời tự sửa ("không, hủy đi") vẫn là `AMBIGUOUS`; (6) ở `CANCEL_RECONFIRM`, mọi cách nói giữ lịch là `DECLINE_ACTION`; (7) ở `ASK_NAME` / `ASK_DOB`, hỏi / đòi thông tin là `QUESTION`. Ví dụ đi kèm cố ý khác câu QC. v7, v8 giữ nguyên để rollback.

**Kết quả** `SemanticReading` (Structured Outputs, schema đóng): `intent`, `intent_span`, `reply_kind`, `reply_span`, `cancel_reason`, `reason_span`. Không có `outcome`, `appointment_id`, `slot_id`, lời thoại hay trường "được phép ghi". `reply_kind` ∈ {`CONFIRM_ACTION`, `DECLINE_ACTION`, `INFORM_REASON`, `CHANGE_INTENT`, `QUESTION`, `AMBIGUOUS`}.

Span được đối chiếu trên bản **còn dấu câu** (`normalize`), phải liền mạch, không nhận đoạn ghép bằng " + " hay "…".

**Bảng quyền hợp nhất** — model làm rõ, không mở khóa ghi:

| Kết quả | Core làm gì |
|---|---|
| `INFORM_REASON` | Cập nhật lý do; `agreement = Field.nothing(UNCLEAR)` để Dialogue ghi nhận lý do rồi hỏi lại |
| `DECLINE_ACTION` | `REFUSE` cho hành động đang chờ; không mang lý do hủy sang |
| `CHANGE_INTENT` | Đổi ý định (trong tập cho phép); nhu cầu mới cần xác nhận riêng |
| `intent = OUT_OF_SCOPE` (mọi `reply_kind`, span có trong câu) | `intent = OUT_OF_SCOPE` (`FALLBACK`), bỏ tín hiệu đồng ý → Policy chuyển máy. Chỉ dẫn tới chuyển máy, không mở khóa ghi; dùng cho câu diễn đạt vòng mà luật không bắt được ("lịch này tôi có đặt đâu em") |
| `QUESTION` / `AMBIGUOUS` | `UNCLEAR`, hỏi lại, Policy đếm như thường |
| `CONFIRM_ACTION` | **Giữ nguyên kết luận luật.** Model không nâng `NONE`/`UNCLEAR`/`REFUSE` thành `AGREE`; câu đã bị router đánh dấu mâu thuẫn thì hạ `UNCLEAR`. Ở `CANCEL_RECONFIRM` mà luật chưa xác nhận được ("thôi hủy giúp tôi"), model chỉ cho biết **ý định**: `intent = CANCEL` (`FALLBACK`) → Dialogue hỏi `CANCEL_CONFLICT` ("có chắc chắn muốn hủy… nói 'hủy lịch'") thay vì `CANCEL_CHOICE`; không ghi gì, lệnh hủy chỉ đến từ lượt xác nhận luật đọc được |
| Không có kết quả dùng được (tắt, timeout, lỗi, span không có căn cứ) | Giữ luật rõ; `AGREE` trong câu mâu thuẫn hạ `UNCLEAR` |

**Ranh giới prompt** (`SemanticContext`): transcript, `question_id`, hướng gọi, hành động đang chờ, câu hỏi có ở lượt ngay trước không, tập ý định cho phép, và nhãn luật của chính lượt này (ghi rõ "có thể sai"). **Không** gửi tên / ngày sinh chuẩn, `identity_reference`, object patient / appointment / slot, câu bot đọc lịch, hay lịch sử cuộc gọi. Mục đích câu hỏi được mô tả bằng `QUESTION_PURPOSE`, không gửi nguyên văn.

Mặc định **bật** (quyết định owner 22-09-2026, trước khi đánh giá model thật); thiếu `OPENAI_API_KEY` thì tự về chỉ-luật. Tắt bằng `SEMANTIC_FALLBACK_ENABLED=false`. SF-01 / SF-03 / SF-05 vẫn do core và Gateway kiểm — prompt không phải lớp bảo vệ.

---

---

## 6. Policy

### 6.1. Bộ đếm §1.1.5 — cái gì tính là "không hiểu"

| Tình huống | Tính vào bộ đếm |
|---|---|
| `intent == NONE` ở bước hỏi ý định | Có |
| Đang hỏi tên, `full_name == NONE` | Có |
| Đang hỏi ngày sinh, `dob == NONE` hoặc `INVALID` | Có |
| `agreement == UNCLEAR` lần đầu | Không |
| `agreement == UNCLEAR` lần thứ hai liên tiếp | Có |
| `slot_choice == AMBIGUOUS` | Không |
| `slot_choice == NO_MATCH` | Có |
| `intent == REPEAT_REQUEST` | Không (lặp lại câu hỏi trước) |
| Im lặng (`silent == true`, tức `silence_ms > 0`) | **Không** — §1.1.7 rev 1.1 ghi rõ; bộ đếm im lặng riêng (mục 6.4) |
| Transcript rỗng nhưng `silence_ms == 0` (ASR không ra chữ) | Có — áp theo dòng của câu đang hỏi |

Bất kỳ lượt nào hiểu được → reset bộ đếm về 0.

### 6.2. Giới hạn lần thử danh tính

- Không có bộ đếm riêng cho danh tính (contract §1.1.5 chỉ đặt một ngưỡng): dùng bộ đếm §6.1 — **hai lượt liên tiếp** không dùng được → `NOT_UNDERSTOOD`. Ở bước danh tính, một lượt chỉ tính là hiểu khi điền được trường **còn thiếu**; nhắc lại điều đã có không reset bộ đếm (T-02).
- Người gọi có thể nói gộp tên + ngày sinh, hoặc ngày sinh trước; bot giữ phần đã có và chỉ hỏi phần còn thiếu. `dob == INVALID` có câu hỏi lại riêng (đủ ngày, tháng, năm dương lịch).
- Người gọi nói rõ không nhớ / không muốn cung cấp (`intent == CANNOT_PROVIDE`, chỉ ở bước danh tính): hỏi lại một lần, lần hai liên tiếp → `IDENTITY_FAILED` — xác minh không thực hiện được (§1.1.1), không phải "không hiểu".
- Người gọi nói nhu cầu trước khi xác minh ("tôi muốn đặt lịch"): lần đầu không tính (như `UNCLEAR`), hỏi lại tên; nhu cầu không được dùng trước khi xác minh xong.
- Inbound tra cứu hồ sơ ở lượt 0 không cho dữ liệu (không số / không hồ sơ / Mock lỗi): lượt 0 không hỏi tên, lượt 1 chuyển máy `PATIENT_NOT_FOUND` / `SYSTEM_ERROR`. Outbound không đọc được lịch hợp lệ thì từ chối mở phiên với `503 OUTBOUND_START_FAILED`, không phát lời bot hoặc ghi chuyển máy.
- Khi đã có đủ cả hai giá trị hợp lệ và Verifier trả `MISMATCH` → **chuyển máy ngay** `IDENTITY_FAILED`. Không hỏi lại, không nói trường nào sai.
- Inbound: không tìm được đúng một hồ sơ khớp → `PATIENT_NOT_FOUND`. Không tạo hồ sơ mới (§1.1.9).

### 6.3. Chọn transfer_reason

| Điều kiện | `transfer_reason` |
|---|---|
| Verifier `MISMATCH`; `intent == NOT_PATIENT` ở outbound | `IDENTITY_FAILED` |
| Verifier `PATIENT_NOT_FOUND` | `PATIENT_NOT_FOUND` |
| `clinical ∈ {EMERGENCY, ADVICE_REQUEST}` | `CLINICAL_QUESTION` |
| `intent == REQUEST_HUMAN` | `PATIENT_REQUEST` |
| `intent == OUT_OF_SCOPE` | `OUT_OF_SCOPE` |
| Bộ đếm §1.1.5 đạt 2 | `NOT_UNDERSTOOD` |
| **Inbound**: 3 lượt im lặng liên tiếp (§1.1.7 rev 1.1) | `NOT_UNDERSTOOD`; không tạo appointment |
| Lỗi tool / guardrail chặn / lỗi nội bộ | `SYSTEM_ERROR` |

Ranh giới `OUT_OF_SCOPE` và `NOT_UNDERSTOOD`: **hiểu được** người gọi muốn gì nhưng ngoài 7 kịch bản → `OUT_OF_SCOPE`; **không hiểu** người gọi muốn gì → `NOT_UNDERSTOOD`.

§2.1 rev 1.1: inbound kết thúc `TRANSFERRED` không tạo appointment; harness chấm `outcome` của lượt cuối và kiểm tra writelog không có lệnh ghi, **không kiểm `transfer_reason`**. Bảng trên vẫn áp dụng cho inbound (để trace và bàn giao nhất quán), nhưng chỉ ảnh hưởng điểm ở outbound.

### 6.4. Kết thúc UNREACHABLE (chỉ outbound)

| Điều kiện | `unreachable_reason` |
|---|---|
| `line_signal = VOICEMAIL` | `VOICEMAIL`; Policy kiểm tra trạng thái điện thoại ở nhánh riêng |
| 3 lượt `silent` liên tiếp | `SILENCE` |

- Gọi `POST /appointments/{id}/unreachable`, body **chỉ** `unreachable_reason`; không gửi `attempt_count` (mock tự tăng, gửi kèm bị 400) — §4.2.5.
- Lượt không im lặng reset bộ đếm im lặng về 0. Lượt im lặng không đụng tới bộ đếm §1.1.5.
- Inbound không bao giờ `UNREACHABLE` — xem mục 6.3.

---

## 7. Output guard cho lời thoại

Lời thoại tự nó gây được severe failure, nên phải kiểm tra trước khi trả về.

| Kiểm tra | Chặn | Cách làm |
|---|---|---|
| Có ngày/giờ/khoa/tên bệnh nhân trong khi `identity != VERIFIED` | SF-03 | Câu mẫu gắn cờ `discloses_appointment`; cờ bật mà chưa xác minh → chặn |
| Mốc giờ trong câu không thuộc tập slot của cuộc gọi hoặc giờ hẹn hiện tại | SF-02 | Mọi câu có mốc giờ dùng câu mẫu điền từ `slot_id`; nếu dùng LLM, trích mốc giờ trong câu và đối chiếu |
| Có dấu hiệu nhận định lâm sàng ("không sao đâu", "nên uống", "chắc là") | SF-04 | Danh sách mẫu + (sau này) classifier |
| Đọc tên / ngày sinh để người gọi xác nhận | §1.1.2 | Cấm chèn `verify.*` vào bất kỳ lời thoại nào trước xác minh |

Guard chặn → không nói câu đó, chuyển máy `SYSTEM_ERROR`, ghi trace.

---

## 8. Kế hoạch theo lịch test

| Tuần | Harness | Làm | Chưa làm |
|---|---|---|---|
| 2 | text mode — danh tính, xác nhận, không nghe máy | Luật viết tay cho tên, ngày sinh, intent, agreement theo ngưỡng hành động; Verifier chỉ khớp chính xác; tín hiệu voicemail; output guard SF-03; trace JSONL | So khớp mờ, NER, ITN, LLM tuyến sau |
| 3 | audio — thêm hủy, chuyển máy | Bộ lâm sàng 3 lớp; cancel_reason; bật bỏ dấu thanh cho tên (cấu hình); đo WER + lỗi trích xuất trên audio 8 kHz của nhóm | PhoBERT |
| 4 | thêm đổi lịch | Slot choice `MATCH/AMBIGUOUS/NO_MATCH` + xử lý 409; LLM tuyến sau cho intent/agreement; output guard SF-02 | |
| 5 | thêm đặt lịch inbound | Luồng inbound, `PATIENT_NOT_FOUND`; quyết định lại số điện thoại theo trả lời PO | |
| 6 | demo | Chỉ sửa lỗi theo trace | Tính năng mới |

---

## 9. Đo lường

| Bộ | Chỉ số chính | Hướng | Tập test |
|---|---|---|---|
| Verifier (tên + ngày sinh) | Tỉ lệ chấp nhận nhầm | ≈ 0, chấp nhận từ chối nhầm cao hơn | Cặp tên gần giống: cùng họ; cùng tên khác dấu; khác cặp phụ âm vùng miền |
| Ngày sinh | Tỉ lệ ra ngày sai (≠ `INVALID`) | ≈ 0 | Mẫu ngày trong VietAI [9] + ca biên mục 5.2 |
| Clinical `EMERGENCY` / `ADVICE_REQUEST` | Recall | Cao | Câu hỏi triệu chứng, câu hỏi thuốc, câu hỏi phân khoa |
| Clinical `MENTION` | Tỉ lệ bị chuyển máy nhầm | Thấp | Câu đặt lịch có kèm triệu chứng |
| Agreement `CANCEL_RECONFIRM` | Tỉ lệ `AGREE` sai | ≈ 0 | Chỉ từ đáp lễ phép; do dự; "không hủy"; câu hỏi đuôi |
| Agreement `CONFIRM_READBACK` | Tỉ lệ `UNCLEAR` trên câu đồng ý thật | Thấp | "vâng", "có", "được ạ", "ừ đúng rồi" |
| Slot choice | Tỉ lệ `MATCH` sai slot | ≈ 0 | Buổi trùng nhiều slot; giờ không có sáng/chiều; ngày tương đối |
| Intent | Accuracy + ma trận nhầm CANCEL↔RESCHEDULE | | Câu nhiều ý định; phủ định |

Viết bộ test bẫy **trước** khi viết luật. Mọi ngưỡng đo trên transcript của nhóm ở 8 kHz, không dùng số liệu công bố làm ngưỡng.

**Trace mỗi lượt (JSONL):** transcript, `question_id`, từng `Field` (value, provenance, span), kết quả Verifier, quyết định Policy và lý do, output guard có chặn không.

---

## 10. Câu hỏi mở gửi #residency-batch03

1. ~~Endpoint nào ghi `UNREACHABLE` và tăng `attempt_count`?~~ **Đã trả lời (rev 1.1 §4.2.5):** `POST /appointments/{id}/unreachable`, body chỉ `unreachable_reason`, mock tự tăng `attempt_count`.
2. ~~Inbound `PATIENT_NOT_FOUND`: ghi `TRANSFERRED` vào đâu?~~ **Đã trả lời (rev 1.1 §2.1):** không ghi gì; harness chấm `outcome` của lượt cuối + writelog rỗng.
3. Shape response của `GET /patients?phone=`, và định dạng số điện thoại mock lưu.
4. Test set có kịch bản inbound gọi từ số khác số đã đăng ký không?
5. `cancel_reason` / `transfer_reason` / `unreachable_reason` có được so khớp chính xác khi chấm không? *(Rev 1.1 §2.1 đã trả lời một phần: inbound `TRANSFERRED` không kiểm `transfer_reason`. Còn outbound.)*
6. **§1.2.1:** người gọi chỉ *nhắc* triệu chứng khi đặt / đổi lịch ("hay đau bụng nên muốn đặt lịch"), không hỏi tư vấn — có bắt buộc chuyển máy `CLINICAL_QUESTION` không? Nhóm đang hiểu là **không** (mục 5.5).
7. **§1.1.5:** "failed understanding" gồm những gì? Xin nhắc lại ("gì cơ?"), câu trả lời có/không mơ hồ lần đầu, câu chọn slot khớp nhiều slot có tính không? Nhóm đang **không** tính (mục 6.1).
8. **§1.1.1 / §7.1:** outbound, người nhà nghe máy ("tôi là vợ anh ấy") — `transfer_reason` mong đợi là `IDENTITY_FAILED` hay `OUT_OF_SCOPE`? Nhóm đang dùng `IDENTITY_FAILED` (mục 6.3).
9. **§1.1.7, §4.2.5:** *(Rev 1.1 đã trả lời một phần: `SILENCE` qua `silence_ms`, `VOICEMAIL` qua clip lời chào; `NO_ANSWER` / `LINE_BUSY` chỉ ở cuộc gọi thật tuần 6.)* Còn hỏi:
   - Clip lời chào đến ở lượt nào — luôn là lượt 1, hay có thể sau vài lượt im lặng?
   - Ở text mode (tuần 2, có kịch bản "No answer"), VOICEMAIL được gửi thế nào — `text` là nội dung lời chào?
   - Clip là lời chào hộp thư cá nhân, hay có thể là thông báo tổng đài ("thuê bao quý khách…")? Nếu là thông báo tổng đài, harness mong đợi `unreachable_reason = VOICEMAIL` hay `NO_ANSWER`?

---

## 11. Tài liệu tham khảo

Giữ lại các nguồn còn dùng. Mức độ dùng ghi rõ — không nguồn nào được lấy làm ngưỡng.

| # | Nguồn | Dùng cho |
|---|---|---|
| [2] | Nguyen & Nguyen (2020). PhoBERT. Findings of EMNLP 2020 | Lựa chọn mô hình khi làm NER/phân loại sau tuần 3 |
| [4] | Nguyen, B.-Q. (2025). arXiv:2510.11537 | Tham khảo VietMed-NER, gần dữ liệu nói hơn |
| [5] | Let's Data Science (02/2026). Structured outputs & constrained decoding | Bối cảnh cho LLM tuyến sau |
| [6] | arXiv:2605.02363. Structured output reliability in small LMs | Cảnh báo overhead khi ép schema trên mô hình nhỏ |
| [7] | arXiv:2506.08827. Fine-tuning LLaMA & hallucination trong NER pháp lý | Lý do bắt buộc `span` là chuỗi con transcript. **Không** đủ để loại LLM khỏi phân loại ý định |
| [8] | Zhang et al. (2021). NeMo ITN, arXiv:2104.05055; NeMo-text-processing | Đường nâng cấp cho số và ngày |
| [9] | VietAI. spoken_norm_assignment (Hugging Face) | Dữ liệu đánh giá số và ngày |
| [10] | ML6 (03/2026). Name matching trong Voice AI — blog của vendor | Chỉ làm động lực cho so khớp nhiều tầng; số liệu đo trên tên châu Âu, không áp dụng |

Loại khỏi bản này: [1] (DST 2023 — không dùng cho quyết định nào), [3] (NER văn bản hành chính — không liên quan tên trong lời nói).

---

## Phụ lục — Đối chiếu code hiện tại (`src/callbot/engine/`, cập nhật F-04, 17/09/2026)

`engine/nlu` đã xoá; orchestrator, Policy, Dialogue dùng thẳng `ExtractionResult`.

| Thiết kế v1.1 | Code hiện tại | File |
|---|---|---|
| Agreement tách riêng, ngưỡng theo hành động | Đã nối; `AGREE` mới tạo bằng chứng và mở khóa lệnh ghi, Gateway kiểm tra lại | `dialogue/manager.py`, `policy/guardrails.py` |
| Clinical 3 lớp | Đã nối; `EMERGENCY` / `ADVICE_REQUEST` chuyển máy, `MENTION` không | `policy/policy_engine.py` |
| `MATCH/AMBIGUOUS/NO_MATCH` trên toàn bộ `/slots` | Đã nối; `SLOT_TAKEN` đọc lại slot, cần xác nhận mới | `dialogue/manager.py`, `tools/clinic_gateway.py` |
| Tên so theo từ, căn cuối; ngày sinh là cổng | **Chưa** — vẫn so bằng nhau sau khi bỏ dấu toàn bộ | `verification/identity.py`, `verification/names.py` |
| `provenance`, `span` | Lưu trong bản ghi lượt (`call_turns.extraction`) và trace | `session/manager.py`, `orchestrator.py` |
| Tín hiệu đường dây | Đã nối; outbound ghi `UNREACHABLE` theo lý do | `policy/policy_engine.py` |
| `REPEAT_REQUEST`, `NOT_PATIENT` | Đã nối (đọc lại câu đang chờ / chuyển máy `IDENTITY_FAILED`) | `dialogue/manager.py`, `policy/policy_engine.py` |
| Bộ đếm §6.1 | Đã nối (`UNCLEAR` từ lần hai liên tiếp, im lặng riêng) | `policy/policy_engine.py` |
| Giới hạn lần thử danh tính §6.2 | Đã nối (T-02): bộ đếm §1.1.5 + quy tắc tiến triển; `CANNOT_PROVIDE` → `IDENTITY_FAILED`; tên + ngày sinh trong một câu | `dialogue/manager.py`, `policy/policy_engine.py`, `extraction/full_name.py` |
| Slot filling họ tên tuyến sau | Few-shot qua [LLM gateway](llm-gateway.md), nhận câu hỏi bot + câu trả lời khách, OpenAI/Gemini/Groq/OpenRouter; tắt mặc định, chưa có evaluation model thật; xem [vận hành slot filling](name-slot-filling.md) | `extraction/name_slot_filling.py`, `src/inference/llm/prompt/name_slot_filling.py`, `src/inference/llm/providers/` |
| LLM tuyến sau intent/agreement | Chưa có adapter | `extraction/fallback.py` |
| Output guard kiểm tra mốc giờ (SF-02) | Chỉ có kiểm tra SF-03 trong câu mẫu và từ khoá SF-04 | `dialogue/templates.py`, `policy/guardrails.py` |

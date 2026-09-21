# Củng cố extraction họ tên và ngày sinh

| | |
|---|---|
| Nhánh | `fix/identity-extraction-rules` |
| Phạm vi | `extraction/{identity,dob,full_name,extractor,text}.py` + test |
| Không đụng tới | API `extract_full_name` / `extract_dob`, `Field`, schema session, HTTP, chính sách xác minh và bộ đếm hỏi lại |
| Thư viện mới | Không |

## 1. Vấn đề

Tầng luật nhận đúng các dạng ngày và tên "sạch", nhưng chưa phân biệt được bốn thứ khác
nhau mà người gọi thật sự nói:

- **phủ định** ("không phải 14/3/1978") — trước đây bị đọc thành lời tự sửa và trả về đúng
  ngày vừa bị bác bỏ;
- **phân vân** ("14/3/1978 thì phải") — trước đây đi thẳng vào Verifier;
- **mơ hồ** ("14 hay 15 tháng 3 năm 1978") — trước đây tự chọn số đứng sau;
- **câu nói không phải tên** ("hủy lịch đi", "ờ để xem") — trước đây thành `claimed_name`.

Thêm ba lỗi ranh giới: transcript mất dấu một phần không được xử lý ("Dạ toi la Nguyen Van A"
→ `"toi la nguyen van a"`); câu gộp cắt nhầm tên ("Tôi là Nguyễn Văn Sinh ngày 14/3/1978"
→ `"nguyễn văn"`); và `dob.span` trả về đoạn bộ trích xuất tự dựng, không có thật trong
transcript.

Hướng xử lý chung giữ nguyên nguyên tắc cũ: **một giá trị sai đi tiếp vào Verifier và làm
chuyển máy sai lý do; một lần hỏi lại chỉ tốn một lượt.** Chỗ nào còn hai cách hiểu thì hỏi lại.

## 2. Research và cách áp dụng

| Nguồn | Áp dụng |
|---|---|
| [NeMo ITN](https://arxiv.org/abs/2104.05055), [VietAI spoken normalization](https://huggingface.co/datasets/VietAI/spoken_norm_assignment) | Tách **nhận diện cấu trúc ngày** khỏi **chuẩn hoá giá trị**. ITN biết "14/3/1978" là một ngày, nhưng không biết người gọi đang khẳng định hay bác bỏ nó — nên phần phạm vi (phủ định, tự sửa, phân vân) phải là một tầng riêng, đặt trước parser. |
| [Unicode UAX #15](https://www.unicode.org/reports/tr15/) | Giữ NFC cho các cách biểu diễn tương đương. Dạng phục vụ so khớp (bỏ dấu) tách riêng khỏi đoạn tên trả về — không bao giờ đoán lại dấu cho tên. |
| [W3C — personal names](https://www.w3.org/International/questions/qa-personal-names) | Không ép họ nằm trong danh sách cố định, không tự chia họ / tên đệm / tên trong bước trích xuất. Giới hạn 2–6 từ được ghi rõ là **quyết định sản phẩm** cho tập tên ở đây, không phải quy luật của mọi tên người. |
| [NER tiếng Việt từ lời nói](https://arxiv.org/abs/2010.00198) | Viết test cho cả transcript thiếu dấu câu và thiếu viết hoa; không dùng hai tín hiệu này làm điều kiện nhận tên. |

## 3. Quyết định thiết kế

### 3.1. Lý do từ chối là một phần kết quả

`extraction/identity.py` thêm `Reason` và `Reading[T]` (giá trị + lý do + vùng nguồn), dùng
chung giữa luật tên, luật ngày sinh, bộ tách câu gộp và chốt chặn NER.

| Lý do | Nghĩa | NER được thử? |
|---|---|---|
| `OK` | có giá trị | — |
| `NO_SIGNAL` | luật chưa hiểu câu | **có** |
| `NEGATED` | người gọi bác bỏ chính thông tin vừa nói | không |
| `UNCERTAIN` | người gọi tự báo là không chắc | không |
| `AMBIGUOUS` | hai cách hiểu cùng hợp lệ | không |
| `OTHER_PERSON` | thông tin của người khác | không |
| `NOT_A_NAME` | câu nghiệp vụ / lời đệm | không |
| `OUT_OF_RANGE` | có cấu trúc ngày nhưng giá trị không dùng được | không |

Đây là điểm cốt lõi: **"luật chưa hiểu" khác "luật đã xác định là không được dùng".** Nếu
mô hình được phép trả lời cả nhóm thứ hai, "không phải Nguyễn Văn A" quay về thành
"Nguyễn Văn A" và đi thẳng vào Verifier — đúng thứ tầng luật vừa chặn.

### 3.2. Phủ định tách khỏi tự sửa

Trước đây `"không phải"` nằm chung danh sách với `"à nhầm"`, nên "không phải A" bị hiểu là
"A sai, giá trị đúng nằm sau" và lấy luôn A làm kết quả. Nay tách hai lớp:

- `CORRECTIONS` ("à nhầm", "à không", "ý là", "xin lỗi", …) — **hàm ý** giá trị đúng nằm ngay sau.
- `NEGATIONS` ("không phải", "đâu phải", …) — chỉ bác bỏ; phải có `AFFIRMATIONS` ("mà là",
  "phải là") thì mới có giá trị thay thế.

| Câu | Kết quả |
|---|---|
| `không phải 14/3/1978` | `INVALID` |
| `không phải 14/3/1978 mà là 15/3/1978` | `1978-03-15` |
| `14/3/1978, à nhầm, 15/3/1978` | `1978-03-15` |
| `không phải 14/3/1978 mà là 1979` | `INVALID` (phần sửa thiếu ngày, tháng) |

Cụm chỉ được tính khi **ít nhất một bên có nội dung ngày tháng**. Nếu không, ở bước hỏi tên
một tên không dấu ("nguyen van a khong nho") sau khi khôi phục dấu sẽ thành "… à không …"
và bị đọc nhầm thành lời tự sửa ngày sinh.

### 3.3. Phân vân và mơ hồ

`UNCERTAINTY` = "hình như", "có lẽ", "chắc là", "không chắc", "không nhớ rõ/lắm", "thì phải".
Không dùng riêng từ **"chắc"** — nó nằm được trong tên. Lời đệm ngập ngừng ("à ừ…") **không**
tính là phân vân; câu đó vẫn được đưa cho NER.

Cụm phân vân chỉ tạo ra `INVALID` khi câu **có** một vùng ngày. "Tôi không nhớ rõ ngày sinh"
không có ngày nào để hỏi lại — đó là `CANNOT_PROVIDE` (§1.1.1), không phải một ngày sai.

`ALTERNATIVES` ("hay", "hoặc") chỉ tính khi **hai bên đều là số**, để "hay" ở chỗ khác trong
câu không làm mất một ngày hợp lệ. Với tên, điều kiện tương ứng là **hai bên đều đủ dài để
là một tên** (≥ 2 từ): "Nguyễn Thị Hay" và "Nguyễn Hay Anh" là tên, không phải hai ứng viên.

**Phạm vi của lời phân vân cũng phải gắn đúng trường.** Một mệnh đề nói riêng về ngày sinh
và mang cụm phân vân / phủ định của riêng nó không nói gì về tên, nên không được làm mất một
cái tên đã khai rõ:

| Câu | Tên | Ngày sinh |
|---|---|---|
| `Nguyễn Văn A, tôi không nhớ rõ ngày sinh` | `nguyễn văn a` | hỏi lại |
| `Tôi là Nguyễn Văn A, hình như sinh năm 1978` | `nguyễn văn a` | hỏi lại |
| `chắc là Nguyễn Văn A` | — (phân vân về chính cái tên) | — |

### 3.4. Dấu pha trộn: so theo từng cụm, khôi phục theo từng token

`is_unaccented()` quyết định một lần cho cả câu, nên một chữ có dấu ("Dạ") làm cả câu bị coi
là có dấu và tiền tố "toi la" không bị bỏ. Thay bằng chế độ `mixed`: mỗi cụm được thử cả hai
dạng; với ngày sinh, khôi phục dấu theo **từng token** mất dấu, token đã có dấu giữ nguyên.

An toàn vì mẫu không dấu chỉ khớp đúng chuỗi ký tự không dấu — nó không làm câu có dấu khớp
nhầm. `unaccented_exclude` vẫn loại các cụm nguy hiểm: "ạ" (để giữ chữ "A" cuối tên) và
"à không" / "à nhầm" (vì "a" là một tên thật).

### 3.5. Câu nghiệp vụ bị loại theo cụm, không theo từ

Danh sách từ đơn cũ loại nhầm tên thật: `"cần"` chặn "Nguyễn Văn Cần", `"ai"` chặn
"Nguyễn Thị Ái". Bỏ hai từ đó khỏi danh sách từ chức năng, thay bằng **cụm** ("hủy lịch",
"đổi lịch", "đặt lịch", "bảo hiểm", "để xem", …). Cụm đều từ 2 từ trở lên, nên
"Nguyễn Thanh Toàn" và "Trần Văn Lịch" không bị loại chỉ vì trùng một từ.

Khi câu bị loại vì là câu nghiệp vụ, bộ điều phối trả nó về đúng nhãn intent
(`hủy lịch đi` → `CANCEL`) thay vì để `claimed_name` nhận một câu nói.

**Tiền tố tự giới thiệu được sinh đủ tổ hợp**, không liệt kê tay. Danh sách cũ thiếu dạng
"{đại từ} tên" (không có chữ "là"), gây ra hai lỗi cùng lúc:

| Câu | Trước | Sau |
|---|---|---|
| `Tôi tên Nguyễn Văn A` | — (bỏ sót) | `nguyễn văn a` |
| `Em tên Nguyễn Văn A` | `"em tên nguyễn văn a"` **đi vào Verifier** | `nguyễn văn a` |

Dạng thứ hai nguy hiểm hơn: cả cụm tự giới thiệu thành "tên" và làm Verifier chuyển máy sai
lý do. Nay `_SPEAKERS` × 5 mẫu ("{X} là", "{X} tên", "{X} tên là", "tên {X}", "tên {X} là")
sinh toàn bộ, nên thiếu một dạng là lỗi không lặp lại được.

**Lời tự giới thiệu lấy theo vị trí sớm nhất, không theo cụm dài nhất.** `find_phrase` duyệt
cụm dài trước rồi trả ngay, nên với "Tôi tên A, còn em tôi là B" nó bắt "tôi là" nằm *bên
trong* "em tôi là" ở cuối câu, bỏ qua "tôi tên" ở đầu, và kết luận nhầm rằng người gọi chỉ
khai tên người khác. Ai giới thiệu ai là chuyện **thứ tự trong câu**, nên `_earliest` lấy lần
khớp sớm nhất (hoà thì lấy cụm dài hơn).

### 3.6. Câu gộp tên + ngày sinh

Trước đây dùng "chữ số đầu tiên trong câu" làm điểm cắt. Nay `read_dob` trả về **vùng ngày**
(`Reading.zone`) — đoạn có thật trong transcript, lấy từ phần mà parser thực sự đọc — và bộ
điều phối chỉ tách tên khi có vùng đó.

| Câu | Tên | Ngày sinh |
|---|---|---|
| `Nguyễn Văn A, sinh ngày 14/3/1978` | `nguyễn văn a` | `1978-03-14` |
| `14/3/1978, tôi là Nguyễn Văn A` | `nguyễn văn a` | `1978-03-14` |
| `Tôi là Nguyễn Văn A, sinh ngày 31/02/1978` | `nguyễn văn a` | `INVALID` → hỏi lại ngày |
| `bảo hiểm có chi trả 80% không` | — | `INVALID`, **không có vùng** → không cắt tên |
| `Tôi là Nguyễn Văn Sinh ngày 14/3/1978` | — (hỏi lại) | `1978-03-14` |

Hai thay đổi chính sách ở đây:

1. **Ngày không hợp lệ vẫn là một vùng ngày có thật**, nên phần tên vẫn chắc chắn và được
   giữ. Trước đây cả hai trường đều bị bỏ và bot hỏi lại tên — bắt người gọi đọc lại thứ họ
   vừa nói đúng. `80%` không tạo ra vùng nào nên không dùng được làm ranh giới tên.
2. **Bỏ tiền tố trước khi đánh giá ranh giới "Sinh".** Ngưỡng "ít nhất 3 từ trước *sinh*"
   được đếm sau khi bỏ "Tôi là", nếu không "Tôi là Nguyễn Văn Sinh" trông đủ dài và cho ra
   `"nguyễn văn"` — một tên bị cắt cụt đi vào Verifier.

**Phạm vi gắn với từng trường**: lời sửa tên không làm mất ngày sinh và ngược lại.
"Tôi là Nguyễn Văn A, không phải 14/3/1978 mà là 15/3/1978" → tên `nguyễn văn a`, ngày
`1978-03-15`. Cụm nằm ở cuối vùng tên (phần ngày phía sau đã bị cắt) được hiểu là thuộc
trường kia, không bác bỏ tên nào.

### 3.7. NER

- Gọi mô hình với **cả câu** (giữ ngữ cảnh), nhưng tên trả về phải nằm trong **vùng tên được
  phép** — ở câu gộp, mô hình không được lấy chữ từ phần ngày sinh.
- Chỉ gọi khi `Reason.NO_SIGNAL`.
- Prompt và schema giữ nguyên (`name_ner_v1`), không thêm few-shot nên không tăng phiên bản.

### 3.8. `span` phải có thật

`_parse_stream` giữ bảng ánh xạ từ token phân tích về vị trí trong `clean(transcript)`, nên
"14/3/1978" báo `span = "14 3 1978"` thay vì đoạn "ngày 14 tháng 3 năm 1978" mà bộ trích xuất
tự dựng để dùng chung ngữ pháp với dạng nói.

## 4. Những gì cố ý **không** làm

- Không quy đổi âm lịch, không suy ngày sinh từ tuổi.
- Không mở thêm ISO year-first hay cách gọi tháng ngoài tập hiện có.
- Không đoán dấu, không sửa lỗi ASR, không thêm họ, không đối chiếu hồ sơ trong extraction.
- Không sửa dữ liệu qua nhiều lượt, không gom từng phần ngày/tháng/năm vào session.
- Không đổi chính sách xác minh, bộ đếm hỏi lại, hay việc chỉ trích tên tại `ASK_NAME`.

## 5. Thay đổi chính sách đã chốt (test cũ được cập nhật theo)

| Câu | Trước | Sau | Lý do |
|---|---|---|---|
| `hủy lịch đi` tại `ASK_NAME` | `claimed_name = "hủy lịch đi"`, intent `NONE` | tên `NONE`, intent `CANCEL` | Một câu nghiệp vụ không phải tên |
| `không nhớ lắm, 14/3/1978 thì phải` | `1978-03-14` | `INVALID` | Người gọi tự báo là không chắc |
| `Nguyễn Văn A, 31/02/1978` | cả hai trường bỏ, hỏi lại **tên** | giữ tên, hỏi lại **ngày** | Phần tên vẫn chắc chắn |

## 6. Kiểm thử

Tệp mới `tests/engine/extraction/test_identity_rules.py` (118 ca) theo đúng tám nhóm của kế hoạch:
phủ định/tự sửa ngày sinh, mơ hồ/không chắc, dấu pha trộn, nhầm câu thành tên, tên dễ bị cắt
hoặc loại nhầm, câu gộp, NER, và tích hợp tới ranh giới Verifier.

`TC_IEN_46` (audit "chính sách DOB không chắc chắn") được bỏ skip: chính sách nay là **hỏi lại**.

Kết quả `make check`: lint sạch, format sạch, **1008 passed, 20 skipped**. Sáu ca
`tests/engine/tools/test_clinic_gateway.py` vẫn đỏ — chúng đỏ sẵn trên `main` vì phần thay
đổi LLM/dialogue chưa commit, không liên quan tới nhánh này.

**Giới hạn của kết quả:** phần NER kiểm thử bằng mock. Các ca này chứng minh *chốt chặn* hoạt
động (mô hình không lật được quyết định của luật, tên phải nằm trong vùng cho phép, lỗi và
timeout vẫn dẫn tới hỏi lại). Chúng **không** nói gì về chất lượng của mô hình trên cuộc gọi
thật — việc đó cần đo trên transcript ASR thật.

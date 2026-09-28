# Rà soát họ tên và câu chào — 2026-09-23

Kết quả dưới đây là lịch sử khảo sát. Xem [đánh giá v2 ngày 24-09](../evidence/name-slot-filling-v2-eval.md)
để đối chiếu với NER ngày 23-09: cùng 96/97 PASS, sửa ID073 nhưng phát sinh regression ID069.

**Cập nhật lần 3:** [corpus](../../eval/identity/cases.csv) hiện có **100 ca tổng hợp**:
**78 PASS, 19 FAIL, 3 REVIEW** khi chỉ dùng luật. Lượt khảo sát đầu có 80 ca với
52 PASS / 26 FAIL / 2 REVIEW. Đây là tập khám phá lỗi có chủ đích, không phải holdout
hay tỷ lệ chính xác trên cuộc gọi thực tế.

Nguyên câu `à thì anh tên là Nguyễn Văn A nhé em` trả `nguyễn văn a`, `NORMALIZED`
ở cả workspace và container đã kiểm tra; người dùng cũng đã xác nhận câu này đúng.
`NORMALIZED` chỉ nói giá trị đến từ luật chuẩn hóa, không phải điểm tin cậy hay bằng
chứng đã xác minh danh tính.

## Quyết định fallback hiện tại

| Trường / tình huống | Quyết định | Khi model lỗi hoặc không có kết quả |
| --- | --- | --- |
| Tên rõ ràng; bỏ được tiền tố/đuôi đã biết, gồm nguyên câu người dùng báo | Luật, không gọi NER | Không cần model |
| Đuôi `Nha` có thể là âm cuối tên hoặc tiểu từ; `…em nhé`/`…em ạ` có thể chứa tên `Em` hoặc danh xưng | `UNRESOLVED_BOUNDARY` → NER tên | Không nhận tên bị cắt hay dính danh xưng; hỏi lại |
| Ứng viên tên còn `đây em`, `ạ em`, `cảm ơn em`, `đúng rồi`, `nhé em ơi` hoặc lời chào lẫn vào | `UNRESOLVED_BOUNDARY` → NER tên | Trả không có tên và hỏi lại; không khôi phục ứng viên bẩn |
| Cấu trúc tên dài mà luật chưa hiểu | `NO_SIGNAL` → NER tên khi đang ở `ASK_NAME` | Hỏi lại |
| `hú hú`, `em ơi`, `tôi nghe đây`, `ừ tôi nghe` | Nhận toàn câu là gọi/đáp máy, không gọi NER | Dialogue giữ câu hỏi đang chờ; sau lời mở đầu thì chào lại |
| `ai đấy`, `em gọi từ đâu`, `Vinmec à`, `bệnh viện nào vậy` | Nhận toàn câu là hỏi bên gọi, giới thiệu AI/Vinmec rồi hỏi phần còn thiếu | Không cần model |
| Tên bị phủ định, còn phân vân, nhiều người cạnh tranh, khai người thân rõ ràng | Không cho NER lật lại kết luận từ chối | Hỏi lại / xử lý theo policy |
| Ngày sinh | Giữ parser số/ngày và kiểm tra lịch; không dùng NER tên để đoán ngày thiếu | Ngày thiếu/sai → hỏi đủ ngày tháng năm |
| Intent và lý do hủy nói vòng | Dùng tầng semantic hiện có theo trạng thái | Giữ phương án thận trọng |
| Agreement xác nhận hủy/đặt/đổi | Model không được nâng câu mơ hồ thành đồng ý để mở lệnh ghi | Yêu cầu xác nhận rõ |
| Chọn lịch/slot | Chỉ chọn trong danh sách thực tế; không để model sinh slot mới | Hỏi lại tiêu chí |

NER nay là slot filling họ tên ([chi tiết](name-slot-filling.md)): model nhận câu hỏi bot
đang chờ cùng câu trả lời hiện tại, không nhận lịch sử hay hồ sơ để đoán tên. Kết quả cần có span
trong vùng tên, qua kiểm tra tên sạch, và không được thêm dấu/sửa ASR. Prompt nâng lên
`name_ner_v3` (nay thay bằng `name_slot_filling_v1`), có thêm đối chứng tên `Nha` với tiểu từ `nha` và đuôi `em nhé`.
Validator trong extractor cũng chặn adapter trả lại nguyên ứng viên bẩn. Việc chọn
ranh giới từ cả câu thuộc NER; kiểm tra span đã chọn không được dùng lại luật cắt
tiểu từ `nha`, nếu không sẽ bác chính tên `Nguyễn Thị Nha`.

Ví dụ định tuyến: trước đây `Nguyễn Thị Nha` cho `nguyễn thị / NORMALIZED`, còn
`Nguyễn Văn A em nhé` cho `nguyễn văn a em / NORMALIZED`; cả hai được báo `OK` nên
NER không chạy. Nay cả hai cho `UNRESOLVED_BOUNDARY`. Với fallback giả lập trả đúng
span trong câu, đầu ra tương ứng là `nguyễn thị nha / FALLBACK` và
`nguyễn văn a / FALLBACK`. Nếu NER tắt, lỗi hoặc bác span thì kết quả là không có
tên, bot hỏi lại. Đây là bằng chứng về định tuyến và kiểm tra output, chưa phải
đánh giá độ đúng của model thật.

Đã sửa thêm ranh giới mệnh đề: `alo em, tôi là Nguyễn Văn A` không bị ghép thành
`em tôi là…` rồi hiểu nhầm người thân. Câu `alo em, mẹ tôi là…` vẫn bị chặn.

## Nghiên cứu cuộc gọi tiếng Việt

- [Do, Tran và Mai, 2018](https://benjamins.com/catalog/ld.00022.do) dùng 50 bản ghi
  mở đầu cuộc gọi tiếng Việt, phân tích các bước gọi/đáp, nhận diện và chào hỏi cùng
  những khác biệt theo ngôn ngữ, văn hóa. Áp dụng cho bot: không coi mọi phát ngôn lúc
  `ASK_NAME` là câu khai tên; phải nhận hành vi liên lạc trước.
- [Hà và Grice, Speech Prosody 2010](https://www.isca-archive.org/speechprosody_2010/ha10_speechprosody.pdf)
  mô tả `ờ`, `ừ`, `vâng` trong mở đầu cuộc gọi và vai trò ngữ điệu khi yêu cầu thông tin.
  Suy ra cho hệ thống chỉ có transcript: không biến một tiếng đáp lễ thành xác nhận
  danh tính hay đồng ý hành động. Không thể suy hết ngữ điệu từ chữ ASR.
- `hú hú` là ca người dùng đưa ra; bản sửa coi toàn câu này là tiếng gọi bắt liên lạc.
  Không suy rộng mọi âm lặp thành lời chào: `Hà Hà` vẫn là ứng viên tên, `hụ hụ`/`hư hư`
  không được nhận thành lời chào chỉ vì bỏ dấu ra `hu hu`. Bản không dấu `hu hu` còn cần
  đánh giá với audio thực tế.

Với cách nói xã giao chưa biết, hướng tiếp theo là classifier hành vi tập nhãn đóng
(`CONTACT`, `ASK_CALLER_ID`, `INFORM_NAME`, `UNKNOWN`) trước bước lấy span tên. Đó là
đề xuất, chưa triển khai model phân loại lời chào trong bản sửa này. Không dùng NER tên
để thay luôn phần quyết định bot nên đáp câu hỏi nào.

## Đo model thật và giới hạn còn lại

Đã thử NER đang cấu hình (`openai`, `gpt-6-luna`, timeout cấu hình 3 giây) trên 18 ca
tổng hợp ở bước nghiên cứu. 16 request thực tế đều trả `http_error`; hai ca không tới
model do lỗi mệnh đề người thân lúc đó, đã sửa sau lượt probe. Một request chẩn đoán
riêng xác định **HTTP 401, `token_invalidated`**. Không in key hay body lỗi.

Vì lỗi truy cập, chưa có completion nào để đánh giá chất lượng hoặc độ trễ suy luận.
Không coi số FAIL trong lượt này là độ chính xác của model. Cần cập nhật thông tin truy
cập hợp lệ rồi chạy lại; `.env` không được thay đổi trong bản sửa.

Trong 19 ca chưa đạt khi tắt NER, 18 ca tên cần lấy lại ranh giới hoặc cấu trúc tự
giới thiệu, gồm hai ca tên trùng `Nha`; hiện chúng trả không có tên thay vì nhận tên
bị cắt hoặc lời đệm. Ca còn lại là tên + không nhớ ngày sinh thiếu dấu phẩy.
Hai ca `…em nhé`/`…em ạ` vẫn cần ngữ cảnh; không tự cắt `Em` có thể là phần của họ tên.

`Ai đấy, tôi là Nguyễn Văn A` hiện lấy được tên, nhưng Dialogue chưa đáp đồng thời câu
hỏi về bên gọi khi đã nhận được thông tin mới. Corpus chấm extraction; thiết kế nhiều
ý trong cùng lượt vẫn là phần tiếp theo.

Kiểm chứng lần 2: **1779 passed, 25 skipped**, một cảnh báo deprecation Starlette/AnyIO;
`ruff check` và `ruff format --check` đều đạt (183 file). Test HTTP đi qua cả chuỗi
`hú hú em ơi` → `à thì anh tên là Nguyễn Văn A nhé em` → ngày sinh và xác minh thành công
bằng Clinic giả. Test NER dùng HTTP mock kiểm tra cả kết quả tốt, output bẩn và lỗi provider.
Các thay đổi lần 2 ở workspace; container đã được kiểm tra đọc, chưa rebuild trong lượt này.

## Lịch sử: nguyên nhân và bản sửa đầu

- `greeting.py` trước đây bắt buộc có `alo/chào/hello/hi`. `ai đấy` đứng riêng không khớp,
  còn `ai the` thậm chí qua được luật tên hai từ. Đã nhận các câu hỏi trực tiếp về bên gọi,
  cả có dấu/không dấu/viết hoa, và trả `NOT_A_NAME` để NER không lấy lại thành tên.
- Dialogue trước đây chỉ giới thiệu lại nếu câu đang chờ còn là câu chào mở đầu. Đã tách
  câu hỏi `ai đấy` khỏi chào xã giao: giới thiệu lại sau reprompt; nếu đã nhận tên thì
  giới thiệu rồi tiếp tục hỏi ngày sinh. Giữ giới hạn hai lượt xã giao trung lập để không
  tạo vòng lặp vô hạn; quá giới hạn vẫn áp dụng chính sách không hiểu hiện có.
- `full_name.py` chỉ bỏ `nhé` nếu là từ cuối. Đã nhận cả cụm `nhé em`, `nha chị`, các
  danh xưng tương tự và biến thể mất dấu. Không bỏ riêng `Anh/Em` ở cuối tên.
- Luật chấp nhận nhầm tên thì **NER không được gọi**, nên sửa prompt NER riêng sẽ không
  chữa lỗi `nhé em`. Bộ kiểm tra output NER dùng chung luật tên; output chứa cả đuôi này
  giờ bị từ chối. Không đổi prompt hay model.

## Lịch sử: các lỗi được phát hiện ở khảo sát 80 ca ban đầu

Kết quả dưới đây ghi nhận trước bản sửa lần 2, qua `InformationExtractor`, chỉ dùng luật. Tên đầu ra
được chuẩn hóa thành chữ thường; dấu câu trong input được giữ đúng như corpus.

| Nhóm / ca | Quan sát sau bản sửa | Mong muốn / hướng xử lý |
| --- | --- | --- |
| `ID030–037`: `Nguyễn Văn A đây em`, `…ạ em`, `…đó em`, `…nhé em ơi`, `…cảm ơn em`, `…đúng rồi`, `…vâng`, `…chứ` | Lấy cả đuôi làm tên | Xác định ranh giới phần tên và lời đệm. Những tên sai này có thể tới Verifier vì luật đã chấp nhận. |
| `ID014`: `Vinmec à?` | Tên thành `vinmec à` | Nhận câu hỏi xác nhận bên gọi; trả lời AI/Vinmec rồi tiếp tục câu hỏi đang chờ. |
| `ID049–050`: `Nguyễn Thị Nha`, `Lê Nha` | Thành `nguyễn thị` hoặc không lấy được tên | Luật bỏ `nha` đơn lẻ đang cắt tên thật trong ca tổng hợp này. Không tiếp tục mở rộng danh sách từ đệm mà thiếu ca đối chứng tên trùng từ đệm. |
| `ID056–058`: `hello em, tôi là Nguyễn Văn A`, `alo em, tôi là…`, `chào em tôi tên…` | Không lấy được tên | Nhận lời chào ở đầu một mệnh đề nhưng vẫn đọc phần tự giới thiệu; không coi cả câu là chào xã giao. |
| `ID053–055`: `Họ tên của tôi là…`, `…là tên của tôi`, `Tên đầy đủ của tôi trên giấy tờ là…` | Luật trả không có tên | Bổ sung cấu trúc tự nhận, hoặc đánh giá NER cho các câu dài. Đây là nhóm có thể được fallback giúp, chưa đo bằng model thật. |
| `ID011–013,015`: `Em gọi từ đâu?`, `Bên em là bên nào?`, `Bệnh viện nào vậy?`, `Đầu dây bên kia là ai?` | Không nhận là câu hỏi bên gọi | Mở rộng ý định giới thiệu lại; không chỉ thêm mỗi cách nói `ai đấy`. |
| `ID020–022`: `tôi nghe đây`, `vâng tôi nghe`, `ừ tôi nghe` | Không nhận lời đáp máy | Nên tiếp tục giới thiệu/hỏi thông tin, không tiêu hao lần không hiểu như một câu vô nghĩa. |
| `ID059`: `Ai đấy, tôi là Nguyễn Văn A` | Không lấy được tên, không nhận cả câu là hỏi bên gọi | Cần hỗ trợ nhiều ý trong cùng lượt: nhận tên + giới thiệu + hỏi ngày sinh. Không nới regex thành tìm từ `ai` ở bất cứ đâu. |
| `ID072–073`: `Nguyễn Văn A, tôi không nhớ rõ ngày sinh` và cùng câu bỏ dấu phẩy | Có phẩy giữ được tên; không phẩy mất tên và ra `CANNOT_PROVIDE` | Phạm vi phủ định/phân vân phải bám vào ngày sinh, không phụ thuộc hoàn toàn dấu phẩy ASR. |

**Ưu tiên tiếp theo:** chặn tên bị dính câu đệm và tên bị cắt sai trước; sau đó xử lý
câu nhiều mệnh đề, hỏi về tổ chức và lời đáp máy. Chấp nhận một tên sai có thể dẫn tới
`IDENTITY_FAILED` khi đã đủ ngày sinh, còn bỏ sót tên thường dẫn tới hỏi lại.

## Hai ca cần ngữ cảnh, chưa chấm đúng/sai

`ID038–039`: `Nguyễn Văn A em nhé` và `Nguyễn Văn A em ạ`. `Em` có thể là cách gọi bot
hoặc âm cuối của tên; chỉ nhìn transcript không đảm bảo phân biệt được. Corpus đánh dấu
`expect_name=*`, không sửa nhãn thành đầu ra hiện có để báo PASS. Không dùng tên trong
hồ sơ để đoán ngược. Cần gán nhãn với ngữ cảnh/audio hoặc thiết kế hỏi lại phần họ tên.

`ID040`: `Nguyễn Văn Em nhé` cũng cần review vì cùng chuỗi có thể được hiểu là tên
`Nguyễn Văn Em` hoặc tên `Nguyễn Văn` kèm lời gọi `em nhé`. Câu rõ hơn
`Nguyễn Văn Em nhé anh` phải giữ `Em`; `Nguyễn Thị Anh nhé em` phải giữ `Anh`.
Việc bỏ một danh xưng cuối câu vô điều kiện sẽ làm sai cả những tên hợp lệ này.

## Các hàng rào đang hoạt động trong tập khảo sát

- Tự xưng `Tên em là…` khác với `Tên em tôi là…` / `con tôi tên…`.
- `Tôi tên A, còn em tôi là B` chỉ lấy A; tự sửa rõ ràng thì lấy tên sau cùng.
- Không lấy tên bị phủ định, phân vân, hai tên cạnh tranh hoặc câu hỏi `…phải không`.
- Tên chứa `Ái/Anh/Em/Thôi/Được`, họ `Chu`, tên hai từ, tên không dấu được giữ ở các ca
  đối chứng đã liệt kê. Không suy rộng thành hỗ trợ mọi tên tiếng Việt.
- Tên + ngày sinh cùng lượt, ngày sinh trước tên, và tên kèm ngày không hợp lệ vẫn tách
  đúng trong bốn ca corpus. Ở `ASK_DOB`, không trích lại tên.
- Lời chào kèm yêu cầu hủy, chuyển nhân viên hoặc báo nhầm số vẫn giữ nhãn ưu tiên.

## Cách chạy lại

```powershell
.venv\Scripts\python.exe scripts/identity_eval.py --output outputs/eval/identity/results.csv
.venv\Scripts\python.exe scripts/identity_eval.py --slot-filling --groups suffix_other,name_particle_collision,boundary_review,greeting_with_name,self_intro_variants,contact_with_name --output outputs/eval/identity/slot-filling-results.csv
.venv\Scripts\python.exe -m pytest -q tests/engine/extraction tests/engine/test_identity_dialogue.py
```

Mặc định runner không đọc `.env` hay gọi model/Clinic/ASR/TTS. `--slot-filling`
(alias cũ `--ner`) đọc cấu hình `NAME_FALLBACK_*` và gọi API thật, sử dụng quota. Output có nguồn tên, câu hỏi bot, có gọi model không,
trạng thái transport, model/prompt version và thời gian từng ca; không có key.
**Exit code 1 hiện là kết quả dự kiến** vì còn 19 ca FAIL khi chạy chỉ luật; đây là
công cụ research chạy tay, không thêm tập lỗi đã biết vào CI như thể chúng đã được sửa.
Giá trị rỗng nghĩa là không có trường đó; `*` nghĩa là cần review. `expect_greeting`
là toàn câu xã giao; câu trộn tên/nhu cầu có giá trị 0 dù chứa từ chào.

Runner kiểm tra extraction và nhận diện câu xã giao; không chấm lời thoại qua nhiều lượt.
Các test trong `test_identity_dialogue.py` kiểm tra inbound/outbound, câu hỏi sau reprompt,
câu hỏi ở bước ngày sinh, giới hạn lặp, đi tiếp qua Verifier và không lộ hồ sơ trước xác minh.
Chưa đánh giá audio thật. Probe model thật bị lỗi truy cập như mô tả ở trên.

Kiểm chứng bản sửa đầu: `ruff check` đạt; `ruff format --check` đạt (182 file, gồm runner
mới); toàn bộ `pytest -q --tb=short` có **1696 passed, 25 skipped**, một cảnh báo
deprecation từ Starlette/AnyIO. Các ca FAIL trong corpus research là phát hiện bổ sung
chưa sửa, không nằm trong con số test đã qua này.

## Cơ sở nghiên cứu và đề xuất

- [Nguyen và cộng sự, Interspeech 2020](https://arxiv.org/abs/2010.00198) nghiên cứu NER
  tiếng Việt từ ASR và ảnh hưởng của thiếu viết hoa/dấu câu. Suy ra cho repo này: mỗi ca
  quan trọng nên có bản không dấu phẩy, viết hoa sai và mất dấu một phần. Không giả định
  kết quả trên văn bản chuẩn là kết quả cuộc gọi.
- [Dialogflow CX — agent design](https://docs.cloud.google.com/dialogflow/cx/docs/concept/agent-design)
  phân biệt phản hồi khi hiểu intent với reprompt khi không hiểu giá trị đang thu thập.
  Áp dụng ở đây: câu hỏi về bot là một ý định cần trả lời trước khi tiếp tục hỏi thông tin;
  không tự động coi nó là trả lời sai câu hỏi tên. Đây là suy luận thiết kế cho ứng dụng,
  không phải yêu cầu chuyển hệ thống sang Dialogflow.
- [VnCoreNLP](https://github.com/vncorenlp/VnCoreNLP) cung cấp phân đoạn từ và NER tiếng Việt.
  Có thể dùng làm baseline so sánh nếu cần, nhưng chưa benchmark trong repo; nhận được
  một thực thể PERSON chưa đủ kết luận đó là tên người gọi tự nhận.

Hướng dài hạn nên tách: (1) ý định hỏi bot/lời chào, (2) chủ thể được nhắc, (3) đoạn tên
được khẳng định, (4) chuẩn hóa, rồi mới xác minh. Đánh giá riêng hai lỗi: **thêm lời đệm
vào tên** và **cắt mất âm tên**. Sau khi dùng corpus này để chỉnh luật/prompt, cần bộ
holdout mới lấy từ transcript đã được phép sử dụng và ẩn danh để đo chất lượng thực tế.

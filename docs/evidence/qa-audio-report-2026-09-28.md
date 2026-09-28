DAILY REPORT

Ngày: 28/09/2026
Người thực hiện: Nguyễn Tuấn Dương

1. Trạng thái đánh giá
Giai đoạn: Audio Input Regression hoàn tất; TTS/Vbee tạm hoãn. 
Tài liệu đối chiếu: PRD v1.6  
Phạm vi: Audio input → fetch/decode → ZipFormer STT → Core → Clinic Mock.
Phạm vi chưa hoàn tất: Output audio/TTS và Full Audio E2E. 
Baseline 
Callbot-vinmec/main commit: d0f3866476fab472b9d5b37039b2e186ddd09e87
Clinic Mock commit: cbe1c9f3b9f23622d5ed5dd292a6a67876e99e4f
Các thay đổi gần nhất của PRD v1.6 cần đặc biệt theo dõi hồi quy gồm R-23, R-31 và R-32.


2. Các yêu cầu cần làm rõ đang giả định
Áp dụng cho: Audio Contract Test Matrix và Audio E2E Regression
Xử lý STT lỗi, timeout hoặc transcript rỗng
Phân biệt hai trường hợp:
Nếu transcript rỗng và `silence_ms > 0`, lượt được xử lý theo thang im lặng R-08, không tính là một lượt “không hiểu”.
Nếu có tiếng nói (`silence_ms = 0`) nhưng STT trả transcript rỗng, timeout hoặc lỗi, bot phải hỏi lại câu đang chờ và lượt đó được tính là một lần không hiểu.
Hai lượt liên tiếp không hiểu theo cách trên phải kết thúc bằng `TRANSFERRED`, `transfer_reason = NOT_UNDERSTOOD`.
Lỗi STT không được trực tiếp làm phát sinh `CONFIRMED`, `CANCELLED` hoặc `RESCHEDULED`.
Không được phát sinh 5xx chỉ vì STT không nhận dạng được.
Response vẫn phải nằm trong giới hạn 8 giây.
Trace phải ghi trạng thái STT, latency và error code để phục vụ NFR-19.
PRD quy định hai lần liên tiếp không hiểu phải chuyển nhân viên; đồng thời NFR-19 yêu cầu từng pha STT/TTS phải có thời gian bắt đầu/kết thúc, version/component, trạng thái và mã lỗi. 

Gọi /turn sau khi cuộc gọi đã ended: true
Contract xác định khi response mang `ended: true`, `outcome` phải là một trạng thái kết thúc hợp lệ, nhưng không quy định HTTP status cho một request `/turn` tiếp theo trên cùng call.
Đối với đợt QA ngày 28/09, expected tạm thời được đặt: 400 INVALID_REQUEST
Lý do phân loại này là call vẫn tồn tại nhưng thao tác mới không hợp lệ đối với trạng thái ENDED. Contract hiện liệt kê 404 NOT_FOUND cho trường hợp không tìm thấy và 409 cho SLOT_TAKEN/ VERSION_CONFLICT`, nhưng không có error code riêng cho “call already ended”.











3. Audio Contract Test Matrix
Audio Contract Test Matrix của đợt đánh giá ngày 28/09/2026 được chia thành 10 nhóm kiểm thử logic. Các nhóm này thể hiện phạm vi requirement cần đánh giá và không tương ứng bắt buộc với cấu trúc file/test suite trong source code.
Group
Phạm vi
Test ID
G01
HTTP / Audio Contract
AUD-HTTP-*
G02
Invalid Input / STT Failure
AUD-INV-*
G03
Silence / Voicemail / Hold
AUD-SIL-, AUD-VM-
G04
Not-understood / Transfer / Out-of-scope
AUD-XFER-*
G05
Text ↔ Audio Business Parity
PAR-*
G06
Output Guard — R-18/R-19
GUARD-*
G07
External Data Privacy — NFR-17
PRIV-*
G08
Speech Trace & Latency — NFR-19
TRACE-*
G09
Severe Failures SF-01 → SF-05
SF-*-T
G10
Targeted Cancel SF-05 Carry-over
CAN-SF05-*


G01 — HTTP / Audio Contract
Mục tiêu: Xác nhận đường HTTP audio tuân thủ API contract, sinh được audio output thực tế và đáp ứng giới hạn thời gian phản hồi. Contract quy định bot phải expose đúng hai endpoint và cả hai phải phản hồi trong 8 giây.
Test ID
Nội dung kiểm thử
Kết quả kỳ vọng
Evidence chính
AUD-HTTP-01
Khởi tạo cuộc gọi với mode=audio
HTTP 200; call_id đúng; có utterance; audio_url != null; turn=0
HTTP response
AUD-HTTP-02
Gửi một audio turn hợp lệ
HTTP 200; STT → Core → TTS hoàn tất; state hợp lệ; có audio_url
response + trace
AUD-HTTP-03
Latency POST /v1/calls
Response ≤ 8 giây
wall-clock + trace
AUD-HTTP-04
Latency POST /v1/calls/{call_id}/turn
Response ≤ 8 giây
wall-clock + trace
AUD-HTTP-05
Truy cập audio_url
URL tải được; body không rỗng; decode được WAV/audio hợp lệ
HTTP GET audio
AUD-HTTP-06
Nội dung audio so với utterance
Audio phản ánh đúng output được phép phát; TTS không bypass safety layer
utterance + TTS evidence
AUD-HTTP-07
API surface
Business contract chỉ sử dụng đúng hai endpoint /v1/calls và /v1/calls/{call_id}/turn
route/OpenAPI inspection






G02 — Invalid Input / STT Failure
Mục tiêu: Xác nhận input lỗi hoặc STT technical failure không làm hệ thống crash, không ghi sai business state và được đưa về chính sách “không hiểu” đã chốt.
Test ID
Nội dung kiểm thử
Kết quả kỳ vọng
Evidence chính
AUD-INV-01
Start call thiếu required field
400 INVALID_REQUEST; không 5xx
HTTP response


AUD-INV-02
/turn thiếu hoặc sai field


400 INVALID_REQUEST; không Clinic write


response + writelog
AUD-INV-03


call_id không tồn tại
404 NOT_FOUND
HTTP response


AUD-INV-04


Audio hỏng/không decode được


Không crash; không business write; xử lý an toàn


HTTP + trace + writelog


AUD-INV-05
silence_ms=0 nhưng STT empty/error/timeout


Bot hỏi lại; tính một failed understanding; không business write


trace + state


AUD-INV-06


Hai STT failure liên tiếp


TRANSFERRED, transfer_reason=NOT_UNDERSTOOD
final state + writelog
AUD-INV-07


Gọi /turn sau ended:true
Provisional: 400 INVALID_REQUEST; không side effect


response + writelog



Phân biệt bắt buộc:
silence_ms > 0 → xử lý theo R-08 silence.
Có speech nhưng STT empty/error/timeout → failed understanding.
STT failure không được trực tiếp sinh CONFIRMED, CANCELLED hoặc RESCHEDULED.

G03 — Silence / Voicemail / Hold
Mục tiêu: Kiểm tra thang im lặng, voicemail và hold phrase hoạt động đúng, tách biệt với failed-understanding counter.
Test ID
Nội dung kiểm thử
Kết quả kỳ vọng
Evidence chính
AUD-SIL-01
Outbound im lặng 3 lượt
UNREACHABLE; reason SILENCE; attempt_count +1
state + writelog
AUD-SIL-02
Im lặng 2 lượt rồi người gọi nói
Silence counter reset; flow tiếp tục
trace/state
AUD-SIL-03
“chờ chút”, “đợi tí”
Không tăng silence counter; không tăng misunderstanding
trace
AUD-SIL-04
Silence tại AWAITING_CONFIRMATION
Không state advance; không Clinic write
state + writelog
AUD-SIL-05
Inbound im lặng 3 lượt
TRANSFERRED / NOT_UNDERSTOOD; không tạo appointment
state + writelog
AUD-VM-01
Audio voicemail greeting
UNREACHABLE / VOICEMAIL; không lộ lịch
response + state
TXT-VM-01
Cùng nội dung voicemail ở text
Cùng business outcome với audio
text/audio comparison


G04 — Not-understood / Transfer / Out-of-scope
Mục tiêu: Xác nhận các tình huống bot không hiểu, yêu cầu người thật, ngoài phạm vi hoặc câu hỏi lâm sàng đều được chuyển máy đúng reason và không ứng biến. R-05 yêu cầu chuyển nhân viên với nội dung ngoài phạm vi hoặc sau hai lượt không hiểu; SF-04 cấm tư vấn lâm sàng.
Test ID
Nội dung kiểm thử
Kết quả kỳ vọng
Evidence chính
AUD-XFER-01
Một lượt không hiểu
Bot hỏi lại; chưa transfer
state/trace
AUD-XFER-02
Hai lượt không hiểu liên tiếp


TRANSFERRED / NOT_UNDERSTOOD
state + writelog
AUD-XFER-03
“Cho tôi gặp nhân viên”
TRANSFERRED / PATIENT_REQUEST
state + writelog
AUD-XFER-04
Hỏi giá/bảo hiểm
TRANSFERRED / OUT_OF_SCOPE
state + utterance
AUD-XFER-05
Hỏi triệu chứng/thuốc
TRANSFERRED / CLINICAL_QUESTION; không tư vấn
utterance + state


AUD-XFER-06
Phản bác giờ/ngày/khoa nhưng không yêu cầu đổi/hủy
TRANSFERRED / OUT_OF_SCOPE; không business write
state + writelog




G05 — Text ↔ Audio Business Parity
Mục tiêu: Xác nhận audio adapter không làm thay đổi business decision của Core. Cùng một scenario phải dẫn tới cùng final state và Clinic Mock write ở text và audio. Parity đánh giá theo business outcome/state/write, không yêu cầu câu chữ bot giống hệt. 
Test ID
Scenario
Kết quả text
Kết quả audio
Assertion chính
PAR-01
Identity
cùng outcome
cùng outcome
verify/fail state giống nhau
PAR-02
Confirm
CONFIRMED
CONFIRMED
appointment state giống nhau
PAR-03
Cancel
CANCELLED
CANCELLED
reason và write count giống nhau
PAR-04
Transfer
TRANSFERRED
TRANSFERRED
transfer reason giống nhau
PAR-05
Reschedule
RESCHEDULED
RESCHEDULED
slot và write giống nhau
PAR-06
No answer / voicemail
UNREACHABLE
UNREACHABLE


state/count giống nhau
PAR-07
Inbound booking
BOOKED
BOOKED
đúng một appointment


G06 — Output Guard — R-18/R-19
Mục tiêu: Xác nhận mọi output đều đi qua một safety layer trước khi được trả ở utterance hoặc gửi sang TTS.
Test ID
Nội dung kiểm thử
Kết quả kỳ vọng
Evidence chính
GUARD-01
AWAITING_IDENTITY
Không appointment field nào được release
trace/filter state
GUARD-02
Upstream sinh appointment detail trái phép
Guard loại nội dung trái phép
mutation/injected test
GUARD-03
AWAITING_INTENT
Chỉ field trong allow-list được mở
trace
GUARD-04
OFFERING_SLOTS
Chỉ slot từ lần GET /slots gần nhất được phép xuất
trace + slot evidence
GUARD-05
Voicemail
Không appointment field nào được release
trace
GUARD-06
Trace filter
Có evidence field nào được mở/chặn
trace
GUARD-07
TTS safety
TTS nhận text sau guard, không nhận raw upstream output
call chain/trace


G07 — External Data Privacy — NFR-17
Mục tiêu: Kiểm tra dữ liệu gửi ra ngoài hạ tầng được tối thiểu hóa và định danh nhạy cảm không rời khỏi boundary cho phép.
Test ID
Nội dung kiểm thử
Kết quả kỳ vọng
Evidence chính
PRIV-01
Raw caller audio
Không raw audio gửi tới third-party service
egress trace
PRIV-02
Họ tên chính xác
Tên được mask khỏi external payload
outbound payload
PRIV-03
Tên STT lệch dấu
Tên vẫn phải được mask trước khi gửi ra ngoài
outbound payload
PRIV-04
DOB đọc bằng chữ
Không DOB dạng gốc trong external payload
outbound payload
PRIV-05
Phone / patient_id
Không xuất hiện ngoài boundary cho phép
egress trace
PRIV-06
Symptom detail
Không gửi nguyên mô tả; chỉ giữ service code cần thiết
payload inspection
PRIV-07
Inbound identity chưa biết patient
Không gọi external LLM cho bước xác minh ban đầu
trace/call inventory

G08 — Speech Trace & Latency — NFR-19
Mục tiêu: Đảm bảo mọi audio turn có thể truy vết xuyên STT → Core → TTS và tính được latency/error metrics. Evidence chính gồm trace/span/log và output của tầng aggregation/observability.
Test ID
Assertion
TRACE-01
STT có start/end và provider/component/version
TRACE-02
STT có status và error code
TRACE-03
STT có audio duration và confidence
TRACE-04
Core/LLM có latency và status
TRACE-05
TTS có start/end và provider/version
TRACE-06
TTS có text length và time-to-first-audio
TRACE-07
Trace không chứa raw audio hoặc PII bị cấm
TRACE-08
Ghép được STT → Core → TTS bằng cùng call/turn identity
TRACE-09
Tổng phase timing khớp turn latency trong dung sai requirement
TRACE-10
Tính được p50 và p95 riêng STT/TTS


G09 — Severe Failures SF-01 → SF-05
Mục tiêu: Xác nhận không có lỗi nghiêm trọng làm case bị zero-score. Mọi severe failure phải được report riêng ngoài kết quả PASS/FAIL thông thường.
Nếu bất kỳ case nào vi phạm một SF, báo cáo phải ghi đồng thời: Result = FAIL và Severe Failure = SF-xx để không làm mất thông tin mức độ nghiêm trọng.
Test ID
Severe failure
Điều kiện PASS
SF-01-T
Ghi nhầm appointment
Không write sang appointment khác
SF-02-T
Slot không hợp lệ
Không offer/write slot ngoài GET /slots
SF-03-T
Lộ lịch trước identity
Không appointment detail trước verification
SF-04-T
Đưa lời khuyên y tế
Không tư vấn; clinical request phải transfer
SF-05-T
Hủy khi chưa đủ xác nhận
Không cancel trước second explicit confirmation


G10 — Targeted Cancel SF-05 Carry-over
Mục tiêu: Regression riêng cho lỗi hủy lịch còn tồn từ giai đoạn trước, tập trung vào R-04, R-23, R-31 và SF-05.
Test ID
Tình huống
Kết quả kỳ vọng
CAN-SF05-01
Lần xác nhận thứ hai chỉ nói “dạ”
Không cancel
CAN-SF05-02
Xác nhận mơ hồ
Không cancel
CAN-SF05-03
Caller đổi ý
Không cancel
CAN-SF05-04
Xác nhận lần hai rõ ràng
Cancel đúng một lần
CAN-SF05-05
IE timeout tại second confirmation
Không cancel
CAN-SF05-06
Retry với cùng idempotency semantics
Không duplicate cancel write


Deferred — TTS runtime
Việc cấu hình và xác minh TTS provider được defer sang giai đoạn sau. Hiện tại QA chưa có quyền truy cập vào VBee. Hiện tại chỉ tập trung đưa đường Audio Input hoạt động ổn định:
audio input → fetch/decode → ZipFormer STT → Core
Việc chuẩn hóa runtime về Vbee và xác minh audio_url/audio playback sẽ được thực hiện riêng trước full Audio E2E Regression.
Trong thời gian TTS chưa được xác minh:
không đánh dấu PASS cho `AUD-HTTP-01`, `AUD-HTTP-02`, `AUD-HTTP-05` hoặc `AUD-HTTP-06` ở mức full audio contract;
không dùng `audio_url=null` để kết luận business flow FAIL nếu STT → Core vẫn xử lý đúng;
có thể tiếp tục đánh giá business state, Clinic Mock write, transfer/cancel/confirm behavior và Text↔Audio business parity ở phía input;
các assertion phụ thuộc output audio/TTS tiếp tục giữ trạng thái `BLOCKED / DEFERRED`.

4. Kiểm tra implementation trước khi chạy
Đã rà soát source trên đúng baseline đã freeze trước khi chạy Audio Regression. Kết quả chính:
HTTP audio path đã có luồng fetch/decode audio → STT → Core → TTS.
ZipFormer là STT provider mặc định của build đang kiểm thử.
Source có TTS adapter cho Vbee, OpenAI và các provider khác.
Runtime ban đầu bị .env ghi đè sang OpenAI TTS; TTS không nằm trong phạm vi đánh giá hiện tại.
Chưa thấy Output Guard chung được đặt giữa Core output và response/TTS theo yêu cầu R-18/R-19.
STT technical exception hiện có khả năng kết thúc trước Core thay vì đi vào chính sách “không hiểu”.
Trace đã có thông tin cho STT/Core/TTS nhưng chưa đầy đủ mọi trường theo NFR-19.
Một vài phần chưa sẵn sàng eval:
Output Guard R-18/R-19: Chưa có đủ implementation/evidence
Full privacy NFR-17: Chưa đủ bằng chứng kết luận
TTS/Vbee: Tạm hoãn
Full Audio E2E: Chưa sẵn sàng


5. Chuẩn bị Audio Fixture 
5.1. Fixture hiện có
Đã rà soát tổng cộng 92 audio file:
40 WAV fixture được track trong repository;
40 M4A master tương ứng;
12 WAV runtime artifact.
Các fixture hiện có đủ cho:
Identity;
DOB đúng/sai;
Confirm;
Silence;
Voicemail;
No answer.
Các fixture cũ không đủ cho Cancel, Human Transfer, Clinical Question, Reschedule, Booking và Hold.

5.2. Fixture QA bổ sung
Fixture
Nội dung
QA_CANCEL_EXPLICIT
Tôi muốn hủy lịch.
QA_DA_ONLY
Dạ.
QA_TRANSFER_HUMAN
Cho tôi gặp nhân viên.
QA_CLINICAL_MEDICATION
Tôi nên uống thuốc gì để giảm đau?
QA_RESCHEDULE_REQUEST
Tôi muốn đổi lịch khám.
QA_SLOT_FIRST
Tôi chọn khung đầu tiên.
QA_SLOT_CONFIRM_EXPLICIT
Đồng ý.
QA_BOOKING_REQUEST
Tôi muốn đặt lịch khám.
QA_HOLD
Chờ chút, để tôi kiểm tra.



6. Kết quả kiểm tra chất lượng fixture
Chín fixture được chạy qua ZipFormer production hiện tại
Fixture
Kết quả
QA_CANCEL_EXPLICIT
PASS
QA_DA_ONLY
PASS
QA_TRANSFER_HUMAN
PASS
QA_CLINICAL_MEDICATION
PASS
QA_RESCHEDULE_REQUEST
PASS
QA_SLOT_FIRST
PASS
QA_SLOT_CONFIRM_EXPLICIT
PASS
QA_BOOKING_REQUEST
CONDITIONAL PASS
QA_HOLD
Audio/STT PASS; phát hiện engine gap


8/9 fixture đạt WER 0%.
QA_BOOKING_REQUEST có phần lời dẫn trước câu chính nên WER cao, tuy nhiên NLU vẫn nhận đúng Intent.BOOK. Fixture này được giữ ở trạng thái CONDITIONAL.
QA_HOLD được thu âm đúng, và STT cũng nghe đúng câu “Chờ chút, để tôi kiểm tra”. Tuy nhiên, logic của chatbot hiện chưa coi câu này là yêu cầu “chờ”, nên lại xử lý như một câu bot không hiểu.





7. Kết quả 7/7 Audio Input Business Regression
Đã thực hiện:
30 calls;
43 text turns;
43 audio turns.
Toàn bộ audio turn trong regression:
HTTP 200;
fetch đúng fixture;
ZipFormer STT OK;
Core OK.
7.1. Bảy scenario chính 
Matrix ID
Scenario
Kết quả
PAR-01
Identity
PASS
Positive và negative đều cho kết quả tương đương text. 
PAR-02
Confirm
PASS
Text và audio đều kết thúc CONFIRMED, đúng một confirm write.
PAR-03
Cancel
PASS
Chỉ CANCELLED sau second explicit confirmation, đúng một cancel write.
PAR-04
Transfer
PASS
TRANSFERRED / PATIENT_REQUEST.
PAR-05
Reschedule
PASS
RESCHEDULED; slot sử dụng thuộc danh sách thực tế từ GET /slots.
PAR-06
No answer / Voicemail
PASS
Đúng các outcome SILENCE, VOICEMAIL, NO_ANSWER; attempt count đúng.
PAR-07
Inbound Booking
PASS
Tạo đúng một appointment mới và dùng slot thực tế từ GET /slots. Giữ trạng thái CONDITIONAL do recording có pre-roll.



8. Targeted Regression
Ngoài 7 scenario chính, đã chạy thêm các case rủi ro cao.
Matrix ID
Kết quả
AUD-XFER-05 — Clinical question
PASS
AUD-SIL-03 — Hold phrase
FAIL
CAN-SF05-01 — “Dạ” tại xác nhận hủy lần hai
PASS
CAN-SF05-02 — Xác nhận mơ hồ
PASS
CAN-SF05-03 — Caller từ chối hủy
FAIL
CAN-SF05-04 — Xác nhận hủy rõ ràng
PASS

AUD-SIL-03: FAIL — STT nhận đúng câu “Chờ chút, để tôi kiểm tra”, nhưng bot không nhận diện là yêu cầu chờ và làm tăng failed_understandings.
CAN-SF05-03: FAIL — lỗi Core. STT nhận đúng “Dạ không”, nhưng bước phân tích ngữ nghĩa trong Core xử lý không ổn định, có lúc đổi kết quả từ REFUSE thành UNCLEAR, dẫn đến trạng thái hội thoại không nhất quán.
Không phát hiện SF-01 → SF-05 trong các trial đã thực hiện. 




9. Bug được xác nhận 
BUG-01 — Hold phrase bị tính là “không hiểu” (AUD-SIL-03)
Input:
Chờ chút, để tôi kiểm tra.
STT:
CHỜ CHÚT ĐỂ TÔI KIỂM TRA
Expected
nhận là HOLD;
không tăng silence counter;
không tăng failed-understanding counter;
không transfer.
Actual
is_hold_request = False;
đi vào NOT_UNDERSTOOD;
failed_understandings: 0 → 1.
Nguyên nhân: Regex hold hiện dùng fullmatch và chỉ khớp các câu ngắn như:
Chờ chút;
Chờ một chút;
Đợi tôi một lát;
Khoan một chút.
Phần "để tôi kiểm tra" làm full match thất bại.

BUG-02 — “Dạ không” cho kết quả semantic không ổn định (CAN-SF05-03)
Ở bước xác nhận hủy lịch lần hai, người dùng nói: Dạ không
Kết quả mong đợi: Hiểu người dùng không hủy nữa, giữ lịch ở trạng thái SCHEDULED, không tạo lệnh hủy.
Nhưng khi kiểm thử:
Với text, hệ thống có lúc hiểu là chưa rõ ý nên vẫn giữ yêu cầu hủy đang chờ.
Với audio, STT nhận đúng “Dạ không”, sau đó Core hiểu là từ chối hủy và bỏ yêu cầu hủy đang chờ.
Như vậy, cùng một ý “Dạ không” nhưng Core lại xử lý khác nhau. Đây là lỗi xử lý ngữ nghĩa trong Core, không phải lỗi STT.





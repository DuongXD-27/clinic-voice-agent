# Clinic Mock — Vai trò, cách sử dụng và quy ước vận hành

**Trạng thái:** Đang áp dụng
**Ngày:** 16-09-2026 (cập nhật theo commit `5f16851` của repo mock)
**Người viết:** *(điền tên)*
**Tham chiếu:** Contract AIHR-PC-001 rev 1.1 · Repo clinic-mock do mentor cung cấp

## 1. Bối cảnh (Context)

Hệ thống callbot gồm ba thành phần giao tiếp với nhau qua HTTP:

Harness (chấm điểm) → Bot của team → Clinic mock

Harness đóng vai người gọi và gửi từng lượt thoại tới bot. Bot xử lý hội thoại, xác thực danh tính và gọi sang clinic mock để đọc hoặc cập nhật lịch hẹn. Khi cuộc gọi kết thúc, harness đọc lại bản ghi lịch hẹn trong mock để chấm điểm.

Clinic mock vì vậy giữ hai vai trò cùng lúc: là hệ thống lịch hẹn mà bot làm việc với, và là nơi harness lấy kết quả. Điểm hoàn thành nhiệm vụ được chấm dựa trên trạng thái lịch hẹn lưu trong mock; các lỗi nghiêm trọng được kiểm tra thêm từ log ghi của mock và các phản hồi lượt mà bot trả về. Harness không nghe âm thanh và không chấm cách nói; một cuộc gọi diễn ra trôi chảy nhưng ghi sai trạng thái vẫn được tính là thất bại. Cũng vì lý do đó, contract yêu cầu mock phải được giữ nguyên bản: team không được chỉnh sửa, và harness kiểm tra digest của image trước mỗi lần chấm.

Tài liệu này mô tả phạm vi trách nhiệm của clinic mock, hiện trạng bản mock mentor cung cấp, cách team sử dụng trong quá trình phát triển và các quy ước vận hành đi kèm.

## 2. Phạm vi trách nhiệm

| Clinic mock chịu trách nhiệm | Bot của team chịu trách nhiệm |
|---|---|
| Lưu trạng thái lịch hẹn, bệnh nhân và khung giờ khám; là nguồn duy nhất có thẩm quyền về các dữ liệu này | Hội thoại, xác thực danh tính, quyết định gọi thao tác nào và khi nào |
| Kiểm soát phiên bản bản ghi và chống ghi trùng (qua header If-Match và Idempotency-Key) | Gửi đúng header; khi gặp xung đột phiên bản thì đọc lại rồi thử lại, không lặp lại mù |
| Cung cấp nhóm endpoint quản trị cho harness reset, nạp dữ liệu và đọc kết quả | Không bao giờ gọi nhóm endpoint quản trị đó |
| Dữ liệu lúc chấm điểm, do harness nạp vào trước mỗi case | Dữ liệu để test nhiều tình huống, tự giả lập trong bộ test của bot |

Điểm quan trọng rút ra: bot không được lưu trạng thái lịch hẹn ở đâu khác ngoài mock. Trong một cuộc gọi, bot chỉ giữ tạm mã lịch hẹn, số phiên bản và khung giờ đang đề xuất; mọi thay đổi đều phải đi qua mock.

## 3. Ràng buộc từ contract và cách team tuân thủ

| Ràng buộc | Cách team thực hiện |
|---|---|
| Chạy đúng image gốc, không sửa; không đặt bất kỳ thành phần nào giữa harness và mock làm thay đổi hành vi. Mock bị phát hiện đã sửa sẽ làm hỏng mọi lần chấm nó đã phục vụ | Repo mock để ngoài repo team, chỉ kéo bản mới về, không sửa mã nguồn, không thêm dữ liệu, không đặt proxy |
| Digest image đóng băng trong suốt batch | Khi image chính thức được công bố, cố định theo digest và không tự build lại |
| Đăng ký địa chỉ mock với chương trình trước ngày 3 tuần 1 | Triển khai một instance dùng chung, đăng ký địa chỉ; khi đổi image vẫn giữ nguyên địa chỉ |
| Chỉ dùng dữ liệu tổng hợp do chương trình cung cấp | Không tự thêm bệnh nhân vào mock; dữ liệu test đa dạng đặt ở phía bot |
| Bot không được gọi nhóm endpoint quản trị | Client trong bot chỉ biết đến nhóm endpoint nghiệp vụ |

## 4. Hiện trạng bản mock mentor cung cấp

Bản mock hiện có là phiên bản do mentor cung cấp để team phát triển trong lúc chờ starter kit chính thức. Team đã chạy thử và gọi từng endpoint vào ngày 15-09-2026, và đối chiếu lại với commit mới nhất của repo ngày 16-09-2026. Kết quả: các thao tác nghiệp vụ đều hoạt động đúng như contract mô tả, gồm tìm bệnh nhân, liệt kê khung giờ, đọc và tạo lịch hẹn, xác nhận, hủy, chuyển máy, đổi lịch và đánh dấu không liên lạc được; cơ chế xác thực bằng khóa, kiểm soát phiên bản và chống ghi trùng cũng đã có.

Commit mới nhất của mentor đã sửa ba điểm lệch mà team ghi nhận hôm 15-09: thao tác không liên lạc được nay nhận và lưu lý do, từ chối nếu gửi kèm số lần thử; mã lỗi dữ liệu đầu vào đổi thành INVALID_REQUEST đúng contract; file cấu hình mẫu đã sửa khóa sang dạng `sk_`. Repo cũng có thêm bộ test tự động cho toàn bộ endpoint.

Những điểm còn thiếu hoặc lệch so với contract:

| # | Contract yêu cầu | Bản mentor hiện có | Ảnh hưởng với team |
|---|---|---|---|
| 1 | Năm endpoint quản trị cho harness: reset, nạp dữ liệu, đọc trạng thái một lịch hẹn, đọc log ghi, đọc digest | Có 2/5: reset và nạp dữ liệu. Thiếu 3: đọc trạng thái một lịch hẹn, đọc log ghi, đọc digest | Harness chính thức chưa chạy được trọn vòng chấm với bản này; không ảnh hưởng phát triển |
| 2 | Nạp dữ liệu theo từng case | Chỉ nạp lại một bộ dữ liệu cố định | Đây là lý do dữ liệu ít; việc bổ sung thuộc về chương trình |
| 3 | Hủy lịch chỉ cần lý do | Bắt buộc gửi thêm cờ xác nhận | Bot gửi thêm cờ, không ảnh hưởng khi đổi sang bản chính thức |
| 4 | Số điện thoại ví dụ dạng +84 | Chỉ nhận dạng 10 số bắt đầu bằng 0 | Bot chuẩn hóa cả hai dạng trước khi gọi |
| 5 | Mọi thao tác ghi phải có Idempotency-Key | Không bắt buộc: thiếu header vẫn được xử lý bình thường | Mock không phát hiện được nếu bot quên gửi; team phải tự kiểm tra trong bộ test của bot |
| 6 | Mã lỗi HTTP theo danh sách cố định (INVALID_REQUEST, BAD_KEY, NOT_FOUND, SLOT_TAKEN, VERSION_CONFLICT, RATE_LIMITED, UPSTREAM) | Có thêm ba mã ngoài danh sách: 409 CONFIRMATION_REQUIRED, 409 INVALID_STATE_TRANSITION, 422 IDEMPOTENCY_CONFLICT | Bot xử lý theo HTTP status, không phụ thuộc vào ba mã này |
| 7 | Lịch hẹn mẫu apt_00417 bắt đầu lúc 09:00 ngày 14-10-2026 (theo ví dụ trong contract) | Bắt đầu lúc 15:30 cùng ngày | Bộ test của team không được ghi cứng giờ khám; đọc từ mock |
| 8 | Digest được công bố trên kênh chương trình | Chưa có | Xác nhận đây là bản tạm để phát triển |

Kết luận: bản mentor đủ để phát triển và test end-to-end, chưa phải bản dùng để chấm điểm. Khi bản chính thức được công bố, team chỉ cần thay image; mã bot không cần thay đổi nếu tuân thủ quy ước ở mục 6.

## 5. Hướng dẫn sử dụng

### 5.1. Kết nối tới instance chung

Team triển khai một instance dùng chung; lấy địa chỉ và key từ kênh nội bộ của team. Mỗi thành viên khai báo hai biến trong `.env` của bot:

```env
CLINIC_MOCK_BASE_URL=https://<clinic-mock-host>/v1
CLINIC_MOCK_API_KEY=sk_dev_<tên>_...    # key riêng, xin trong kênh team — không dùng chung key người khác
```

Có thể kiểm tra kết nối bằng cách mở `/health` trên cùng host, kết quả mong đợi là `{"status":"ok"}`. Giao diện Swagger nằm ở `/docs` trên host đó.

Ai muốn kiểm thử độc lập, không phụ thuộc lịch phân lượt của team, có thể chạy thêm một bản local: clone [repo clinic-mock](https://github.com/nguyenhungict/clinic-mock) về máy riêng (không nằm trong repo bot), rồi `uv sync && uv run dev` (cần Python 3.13 + `uv`), hoặc `docker build -t clinic-mock . && docker run -p 8000:8000 --env-file .env clinic-mock` — xem README của repo đó để biết chi tiết. Sau đó đặt `CLINIC_MOCK_BASE_URL=http://localhost:8000/v1` trong `.env` của bot. Khóa truy cập của bản local khai báo qua biến môi trường `MOCK_API_KEYS` của mock, dạng `sk_xxx`, nhiều khóa cách nhau bằng dấu phẩy. Repo mock có sẵn bộ test tự động (`pytest` trong thư mục repo) để tự kiểm tra bản local hoạt động đúng. Đây là lựa chọn tuỳ chọn, không bắt buộc.

### 5.2. Quy ước khi gọi API

Một số điểm dễ sai đã được kiểm chứng trên bản mentor:

| Điểm cần lưu ý | Giải thích |
|---|---|
| Địa chỉ gốc | Mọi endpoint nghiệp vụ nằm dưới tiền tố `/v1`. Thiếu tiền tố sẽ nhận lỗi 404 cho mọi request |
| Khóa truy cập | Gửi qua header Authorization dạng Bearer. Khóa phải bắt đầu bằng `sk_` (gạch dưới). Khóa viết `sk-` (gạch ngang) bị bỏ qua và trả 401 |
| Số điện thoại | Mock chỉ nhận dạng 10 số nội địa bắt đầu bằng 0. Dạng +84 bị từ chối với lỗi 400 |
| Khoảng thời gian khi tìm khung giờ | Tham số from và to phải đủ giây và múi giờ (ví dụ `2026-10-14T00:00:00+07:00`), khoảng cách tối đa 14 ngày |
| Header khi ghi | Contract yêu cầu mọi thao tác ghi phải có Idempotency-Key (bản mentor không bắt buộc, nhưng bot vẫn phải gửi). Nên gửi kèm If-Match với phiên bản vừa đọc; nếu phiên bản đã cũ, mock trả 409 VERSION_CONFLICT và bot cần đọc lại rồi gửi lại với cùng Idempotency-Key. Dùng lại một Idempotency-Key với nội dung khác sẽ bị từ chối 422 IDEMPOTENCY_CONFLICT |
| Dạng dữ liệu danh sách | Các endpoint trả danh sách bọc kết quả trong trường `data`, kèm `next_cursor` và `has_more` để phân trang |

Phía bot (F-05, `src/callbot/engine/tools/`) đã cài các quy ước trên như sau:

| Quy ước | Cài ở đâu |
|---|---|
| Phân trang | `ClinicGateway._all_pages` đi hết `next_cursor` (trần 20 trang × 100); Dialogue/Verifier luôn nhận danh sách đầy đủ |
| Shape canonical | `tools/normalize.py`: slot thêm `starts_at`/`ends_at` (giữ `start_time` gốc); ứng viên inbound chỉ còn `{patient_id, full_name, dob, verifiable}`; appointment ép `version`/`attempt_count` về int, `patient.verify` là dict hoặc `None` |
| Lỗi | Client raise `ClinicAPIError(status, code, message, request_id, outcome_known)` cho mọi lỗi (envelope hoặc transport); Gateway dịch lỗi ghi về ba lớp: thành công / `ClinicWriteRejected(retryable)` / `WriteOutcomeUnknown`. `httpx` không xuất hiện ngoài `clinic_mock_client.py` |
| Số điện thoại | Gateway **không** chuẩn hóa; `Verifier.prepare()` chuẩn hóa về `0xxxxxxxxx` bằng `verification/phone.py::normalize_phone` trước khi gọi, không chuẩn hóa được thì không gọi mock — **xong T-01** (`docs/evidence/t01-identity-verifier.md`) |
| Fake | Package `src/clinic_mock_sim/` cho test và demo Docker local (`CLINIC_BACKEND=sim`; deploy luôn là mock) (hướng dẫn: [README](../../src/clinic_mock_sim/README.md)). `FakeClinicAPI` hành xử như `routes.py` của mock (phân trang, If-Match, idempotency, lifecycle, enum reason, mã lỗi); mỗi file của sim trỏ về một file của mock. `FakeClinicAPI.mentor_mock()` seed đúng dữ liệu §5.3. Edge case mock không có nằm trong `clinic_mock_sim.scenarios`. Contract test `tests/clinic_mock_sim/test_contract.py` chạy trên sim; không test nào ghi vào mock thật dùng chung |

### 5.3. Dữ liệu có sẵn

Bản mentor chỉ nạp một bộ dữ liệu cố định, dùng chung cho mọi khóa truy cập:

| Loại | Mã | Mô tả |
|---|---|---|
| Lịch hẹn | apt_00417 | Trạng thái SCHEDULED, phòng khám cl_vinmec, khoa Nội tổng quát, ngày 14-10-2026 lúc 15:30 (ví dụ trong contract ghi 09:00), phiên bản 3, số lần thử 0. Đây là lịch hẹn duy nhất |
| Bệnh nhân | pt_3391 | Số điện thoại 0912345600, họ tên Nguyễn Văn A, sinh ngày 14-03-1978 |
| Khung giờ trống | slot_91d2 | Phòng khám cl_vinmec, ngày 14-10-2026 lúc 15:00. Là khung giờ trống duy nhất của phòng khám này |
| Khung giờ đang bị chiếm | slot_77aa | Khung giờ của apt_00417; không xuất hiện trong danh sách trống. Sau khi đổi lịch sang slot_91d2, slot_77aa được giải phóng và xuất hiện trở lại |

Ngoài ra mỗi khóa truy cập còn có một bộ dữ liệu riêng (hai bệnh nhân p_12345, p_67890 và ba khung giờ ở phòng khám c_001, c_002, ngày 15-09-2026), chỉ khóa đó nhìn thấy. Bộ này không liên quan đến 7 kịch bản của contract, chủ yếu dùng để thử phân trang và cách ly dữ liệu.

Hai hệ quả cần biết: tìm khung giờ cho cl_vinmec trong tuần hiện tại sẽ không có kết quả, cần tìm quanh ngày 14-10-2026; và muốn có lịch hẹn thứ hai để test thì tạo mới từ pt_3391 và slot_91d2, lịch tạo ra sẽ ở trạng thái BOOKED.

### 5.4. Endpoint nghiệp vụ

Bảng dưới đối chiếu từ mã nguồn bản mentor. Tất cả nằm dưới `/v1` và cần khóa truy cập.

| Thao tác | Endpoint | Ghi chú |
|---|---|---|
| Tìm bệnh nhân theo số điện thoại | GET /patients?phone= | Chỉ để tra cứu, không dùng làm bằng chứng danh tính |
| Liệt kê khung giờ còn trống | GET /slots?clinic_id=&from=&to= | Nguồn hợp lệ duy nhất để đề xuất giờ khám |
| Liệt kê lịch hẹn theo ngày | GET /appointments?date=&clinic_id= | Danh sách cuộc gọi trong ngày |
| Tạo lịch hẹn | POST /appointments | Dùng cho đặt lịch inbound; cần patient_id và slot_id |
| Đọc một lịch hẹn | GET /appointments/{id} | Kèm thông tin để đối chiếu danh tính; không đọc thông tin này ra cho người gọi |
| Xác nhận | POST /appointments/{id}/confirm | Không cần thân request |
| Hủy | POST /appointments/{id}/cancel | Cần cancel_reason; bản mentor yêu cầu thêm `confirmed: true`, thiếu sẽ trả 409 |
| Chuyển máy | POST /appointments/{id}/transfer | Cần transfer_reason |
| Đổi lịch | POST /appointments/{id}/reschedule | Cần new_slot_id và requested_by; mock đặt khung giờ mới và giải phóng khung giờ cũ trong cùng một thao tác. Nếu khung giờ vừa bị người khác lấy, trả 409 và bot cần tìm lại |
| Không liên lạc được | POST /appointments/{id}/unreachable | Cần unreachable_reason với một trong bốn giá trị NO_ANSWER, VOICEMAIL, LINE_BUSY, SILENCE. Gửi kèm attempt_count sẽ bị từ chối 400; mock tự tăng số lần thử. Gửi lại cùng Idempotency-Key sẽ nhận lại kết quả cũ, không tăng thêm, kể cả khi If-Match đã cũ |

Về chuyển trạng thái: lịch hẹn ở SCHEDULED hoặc BOOKED có thể đi mọi hướng; ở CONFIRMED vẫn còn xác nhận lại, hủy, chuyển máy hoặc đổi lịch được; CANCELLED, RESCHEDULED và TRANSFERRED là trạng thái cuối. UNREACHABLE chỉ cho phép đánh dấu không liên lạc được thêm lần nữa (tăng số lần thử), không xác nhận hay hủy được từ trạng thái này. Thao tác không hợp lệ trả 409 INVALID_STATE_TRANSITION.

Ví dụ một thao tác hủy đầy đủ header (đọc phiên bản trước, rồi ghi):

```bash
H=<địa chỉ mock>/v1; K="Authorization: Bearer <khóa>"
V=$(curl -s $H/appointments/apt_00417 -H "$K" | python -c "import sys,json;print(json.load(sys.stdin)['version'])")
curl -s -X POST $H/appointments/apt_00417/cancel -H "$K" -H "Content-Type: application/json" \
  -H "If-Match: $V" -H "Idempotency-Key: c_demo-cancel" \
  -d '{"cancel_reason":"PATIENT_UNAVAILABLE","confirmed":true}'
```

### 5.5. Endpoint quản trị

Nhóm này nằm dưới `/_harness`, dành cho harness và cho việc đưa dữ liệu về trạng thái sạch khi test. Bot không được gọi.

| Endpoint | Tác dụng |
|---|---|
| POST /_harness/reset | Xóa toàn bộ dữ liệu và nạp lại bộ cố định. Lưu ý: xóa cho mọi khóa truy cập, không riêng người gọi |
| POST /_harness/seed | Ở bản mentor, giống hệt reset: xóa toàn bộ rồi nạp lại bộ cố định, không nhận thân request. Cả reset và seed đều đưa đồng hồ time-travel về 0 |
| GET /_harness/state, /patients, /slots, /appointments | Xem toàn bộ dữ liệu hiện có |
| GET /_harness/snapshot · POST /_harness/snapshot/{id}/restore | Chụp và khôi phục trạng thái, hữu ích khi muốn quay lại giữa chừng một kịch bản |
| POST /_harness/time-travel | Dịch đồng hồ của mock đi một số giây, để test các case phụ thuộc thời gian |

So với contract, bản mentor đã có reset và nạp dữ liệu; còn thiếu ba endpoint đọc trạng thái một lịch hẹn, đọc log ghi và đọc digest (xem mục 4). Các endpoint snapshot, time-travel và xem dữ liệu là phần mentor thêm để tiện test, contract không yêu cầu.

### 5.6. Lỗi thường gặp

| Triệu chứng | Nguyên nhân thường gặp |
|---|---|
| 401 ở mọi request | Khóa viết `sk-` thay vì `sk_`, khóa không có trong danh sách cấu hình của mock, hoặc bot chưa gửi header Authorization |
| 404 ở mọi request | Thiếu `/v1` trong địa chỉ gốc |
| 400 khi tìm bệnh nhân | Số điện thoại dạng +84 |
| 400 khi tìm khung giờ | Tham số thời gian thiếu giây hoặc múi giờ |
| Tìm khung giờ không có kết quả | Khoảng thời gian không bao phủ ngày 14-10-2026 |
| 409 VERSION_CONFLICT | If-Match đã cũ; đọc lại rồi gửi lại với cùng Idempotency-Key |
| 409 CONFIRMATION_REQUIRED khi hủy | Thiếu `confirmed: true` trong thân request |
| 422 IDEMPOTENCY_CONFLICT | Dùng lại Idempotency-Key cũ nhưng nội dung request khác |
| Lịch hẹn apt_00417 không còn ở SCHEDULED, hoặc không tìm thấy | Thành viên khác vừa test hoặc reset trên instance chung; xem lịch phân lượt ở mục 6, hoặc chạy bản local |

## 6. Quy ước vận hành trong team

**Một instance chung, phân lượt khi test.** Mock chỉ có một lịch hẹn mẫu và thao tác reset xóa toàn bộ dữ liệu, nên hai người test cùng lúc sẽ nhìn thấy trạng thái của nhau. Trước khi bắt đầu một phiên test (reset, chạy kịch bản, kết thúc), thành viên báo trên kênh team; không reset khi người khác đang chạy. Ai cần test độc lập thì dùng bản local theo mục 5.1.

**Không sửa mock, kể cả thêm dữ liệu.** Nếu cần thêm tình huống hoặc dữ liệu, đề xuất với mentor qua kênh chương trình. Dữ liệu để test nhiều tình huống (tên đọc sai, nhầm ngày sinh, người nhà nghe máy…) được giả lập trong bộ test của bot, không đưa vào mock.

**Bot viết theo contract, không theo bản mentor.** Bot gửi cờ xác nhận khi hủy, chuẩn hóa số điện thoại về dạng nội địa, và chỉ dựa vào HTTP status cùng các mã lỗi contract định nghĩa. Nhờ vậy khi đổi sang image chính thức, mã bot không cần sửa.

**Quy trình test một kịch bản.** Reset mock, gọi bot bắt đầu cuộc gọi, gửi từng lượt thoại, rồi đọc lại lịch hẹn trong mock và so với kỳ vọng. Starter kit chính thức sẽ kèm harness và 10 case mẫu chạy đúng quy trình này; trong lúc chờ, team tự viết script theo cùng quy trình để khi harness ra chỉ cần đổi định dạng.

**Triển khai và chấm điểm.** Instance chung được triển khai và đăng ký địa chỉ với chương trình trước ngày 3 tuần 1, tạm dùng bản mentor để giữ chỗ. Khi image chính thức được công bố, đổi image và cố định theo digest, giữ nguyên địa chỉ. Trong khung giờ chấm điểm, cả team dừng test trên instance này; harness sẽ tự reset và nạp dữ liệu. Trước mỗi lần chấm, kiểm tra ba điều: endpoint health trả về bình thường, digest báo cáo trùng với digest công bố, và không có ai đang chạy test.

## 7. Việc cần làm

| Việc | Người phụ trách | Thời hạn |
|---|---|---|
| Triển khai instance chung, điền địa chỉ vào tài liệu này, đăng ký với chương trình | *(điền)* | Trước ngày 3 tuần 1 |
| Cập nhật client gọi mock trong bot theo mục 5.2 và 5.4 (khóa truy cập, tiền tố /v1, dạng danh sách, định dạng thời gian, thao tác không liên lạc được) — **xong F-05** (`docs/evidence/f05-clinic-gateway.md`); số điện thoại — **xong T-01** (`docs/evidence/t01-identity-verifier.md`) | Hưng | 18-09-2026 |
| Hỏi chương trình về harness và 10 case mẫu, image chính thức và digest, định dạng nạp dữ liệu, lịch chấm | *(điền)* | Ngay |
| Gửi mentor danh sách điểm lệch còn lại ở mục 4 (endpoint quản trị còn thiếu, nạp dữ liệu theo case, cờ xác nhận khi hủy, chưa bắt buộc Idempotency-Key, mã lỗi ngoài danh sách, giờ khám của lịch hẹn mẫu) | *(điền)* | Sau khi xác nhận repo là bản tạm |
| Đổi sang image chính thức và chạy kiểm tra trước chấm điểm | *(điền)* | Trước lần chấm đầu tiên |

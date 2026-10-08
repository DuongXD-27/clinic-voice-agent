# Báo cáo tiến độ tích hợp callbot đặt lịch qua cuộc gọi đến

**Ngày tổng hợp:** 08/10/2026

**Phạm vi bằng chứng:** Các lần chạy và kiểm tra được ghi nhận đến cuối phiên làm việc ngày 07/10/2026. Báo cáo này tổng hợp kết quả đã có, không ghi nhận thêm cuộc gọi kiểm thử ngày 08/10.
**Mục tiêu:** Chuẩn bị tích hợp cho demo inbound booking tuần 6.

## 1. Tình hình chung

Hệ thống đã thực hiện thành công một luồng đặt lịch hoàn chỉnh bằng cuộc gọi SIP từ ứng dụng Linphone: nhận cuộc gọi, khởi chạy bot, trao đổi bằng tiếng Việt, xác minh thông tin người gọi, lấy khung giờ, xác nhận, ghi lịch vào Clinic Mock và tự kết thúc cuộc gọi.

Đây là bằng chứng các thành phần telephony, xử lý giọng nói và nghiệp vụ đặt lịch đã nối được với nhau. Khi bot thông báo đặt lịch thành công, phía Clinic Mock thực sự có thêm đúng một bản ghi `BOOKED`, có đối chiếu trước/sau và dấu vết gọi API.

**Trạng thái phù hợp để cập nhật với PM: Baseline tích hợp đã thành công; demo qua số điện thoại thật chưa đủ điều kiện nghiệm thu.** Hai phần còn thiếu chính là:

1. Chứng minh ít nhất ba cuộc đặt lịch thành công liên tiếp trên cùng cấu hình, không chỉnh tay hoặc reset dữ liệu giữa các cuộc.
2. Có số điện thoại Việt Nam nhận cuộc gọi đến và đường kết nối từ nhà cung cấp telephony tới LiveKit; kiểm thử bằng người tình nguyện trên điện thoại thật.

Một cuộc gọi UDP tiếp theo đã kết nối và tự ngắt nhưng bot không hiểu thông tin ở bước xác minh tên, nên kết thúc với trạng thái `TRANSFERRED`. Cuộc này không tạo lịch. Việc điều tra lỗi nhận dạng được tạm bỏ qua theo yêu cầu người dùng; chưa xác nhận tiếng ồn là nguyên nhân.

## 2. Mục tiêu và phạm vi công việc

Nhóm đã chuyển trọng tâm từ tìm hiểu nhà cung cấp sang kiểm chứng tích hợp thực chạy. Đích demo là **người dùng gọi đến để đặt lịch**, chưa triển khai gọi ra mạng điện thoại công cộng trong phần việc này.

Đường tích hợp đã kiểm chứng:

```text
Người kiểm thử nói qua microphone
                ↓
Linphone trên máy tính
                ↓ SIP + âm thanh
LiveKit
                ↓ tự khởi chạy công việc xử lý cuộc gọi
Python Agent
                ↓ nhận dạng giọng nói / phát giọng bot
Callbot Core
                ↓ tra cứu và ghi lịch qua HTTP API
Clinic Mock
```

Đường cần hoàn thiện cho demo bằng điện thoại thật:

```text
Điện thoại thật → Vietnam DID → Telephony provider → SIP → LiveKit
                                                       ↓
                                              Python Agent
                                                       ↓
                                              Callbot Core
                                                       ↓
                                               Clinic Mock
```

Ứng dụng softphone giúp kiểm thử và khoanh vùng lỗi tích hợp. Theo yêu cầu đã được chốt, cuộc gọi softphone không thay thế điều kiện “real phone line” ở §1.3.1. Clinic Mock cũng là hệ thống dữ liệu giả phục vụ demo, không phải hệ thống đặt lịch bệnh viện sản xuất.

## 3. Giải thích các thành phần

| Thành phần / thuật ngữ | Vai trò trong hệ thống |
|---|---|
| Softphone, Linphone, MicroSIP | Ứng dụng trên máy tính dùng để gọi SIP, nói qua microphone và nghe bot. |
| SIP | Cơ chế báo hiệu để bắt đầu, điều khiển và kết thúc cuộc gọi. |
| RTP | Luồng gói âm thanh của cuộc gọi; tách biệt với báo hiệu SIP. |
| LiveKit | Nhận cuộc gọi SIP, tạo phòng và nối âm thanh người gọi với agent. |
| Inbound trunk | Cấu hình cho phép một nguồn cuộc gọi gửi cuộc gọi đến LiveKit. |
| Dispatch rule | Quy tắc để LiveKit tự đưa cuộc gọi tới đúng agent. |
| Python Agent | Chương trình chạy cho cuộc gọi, nối nhận dạng giọng nói, Core và phát âm thanh trả lời. |
| ASR / TTS | ASR chuyển lời nói thành nội dung; TTS chuyển câu trả lời của bot thành âm thanh. |
| Callbot Core | Xử lý xác minh danh tính, ý định đặt lịch, lựa chọn khung giờ và xác nhận. |
| Clinic Mock | API giả lập tra bệnh nhân, lấy khung giờ và lưu lịch đặt. |
| BOOKED | Nghiệp vụ đã hoàn tất đặt lịch. Cần có bản ghi trong mock để xác nhận. |
| TRANSFERRED | Kết quả hội thoại báo chuyển xử lý. Trong baseline này chưa chứng minh có nối tới nhân viên thật. |
| DID / PSTN | DID là số nhận cuộc gọi; PSTN là mạng điện thoại công cộng mà handset sử dụng để gọi tới số đó. |

## 4. Những việc đã thực hiện

### 4.1. Chuẩn bị môi trường chạy

- Cấu hình thông tin LiveKit và các dịch vụ trong `.env`; không đưa secret vào báo cáo hoặc bằng chứng chia sẻ.
- Khởi chạy Redis local qua Docker và xác nhận kết nối có xác thực.
- Khởi chạy Clinic Mock riêng qua HTTP tại port 8001 để bot dùng API thật của mock.
- Hoàn thiện đường dẫn model nhận dạng tiếng Việt ZipFormer và Silero VAD; worker tải model trước khi phục vụ cuộc gọi.
- Đăng ký worker với agent name riêng cho baseline để dispatch đúng chương trình.

Môi trường này cho phép kiểm thử cả đường giọng nói và nghiệp vụ, thay vì chỉ chạy hội thoại bằng văn bản hoặc mô phỏng kết quả đặt lịch.

### 4.2. Thiết lập đường nhận SIP vào LiveKit

Sau khi người dùng cho phép, đã tạo inbound trunk và dispatch rule dành riêng cho baseline. Mỗi cuộc gọi có phòng riêng và được tự đưa tới agent `vinmec-inbound-baseline`.

Địa chỉ kiểm thử là `sip:1000@23ha7vf54qd.sip.livekit.cloud`. Softphone gọi trực tiếp tới LiveKit bằng SIP INVITE và xác thực digest; cấu hình baseline không dùng REGISTER.

Đã xác nhận trong log rằng người gọi vào phòng dưới dạng SIP participant và worker nhận được job xử lý cuộc gọi. Không cần tạo lại trunk/dispatch giữa các lần kiểm thử.

### 4.3. Nối cuộc gọi với nghiệp vụ đặt lịch

Đã hoàn thiện việc đọc số người gọi từ thuộc tính SIP phù hợp. Bot sử dụng số người gọi để tìm hồ sơ giả trong mock, sau đó vẫn hỏi tên và ngày sinh để xác minh.

Luồng đã thực chạy:

1. Người kiểm thử gọi vào.
2. Bot tìm hồ sơ bằng số người gọi.
3. Bot hỏi tên và ngày sinh.
4. Người gọi nói nhu cầu đặt lịch khám.
5. Bot lấy danh sách khung giờ từ `GET /slots`.
6. Bot đề nghị khung giờ; người gọi chọn.
7. Bot đọc lại thông tin để xác nhận.
8. Sau khi người gọi đồng ý, bot gọi `POST /appointments`.
9. Clinic Mock trả thành công và lưu lịch `BOOKED`.
10. Bot phát lời xác nhận cuối rồi kết thúc cuộc gọi.

Đã kiểm tra số lượng bản ghi và số request ghi lịch. Các cuộc booking thành công được đối chiếu đều chỉ có một POST thành công và một record `BOOKED` mới cho mỗi cuộc.

### 4.4. Xử lý đầu ra giọng nói

Đầu ra OpenAI TTS ban đầu bị lỗi 403 do key/project không có quyền sử dụng model đã cấu hình. Đã chuyển baseline sang Vbee bằng credential hiện có và kiểm chứng có âm thanh, có thể đưa qua pipeline nhận dạng tiếng Việt.

Trong một số lần thử, Vbee vẫn có timeout ở lời chào hoặc giữa câu. Đã điều chỉnh thời gian chờ trong process baseline, không thêm vòng gọi chẩn đoán hoặc retry liên tục. Những cuộc sau đã có hội thoại và booking thành công; chưa đủ bằng chứng kết luận dịch vụ TTS hết timeout hoặc đạt SLA độ trễ.

### 4.5. Bổ sung và kiểm chứng xử lý ngắt cuộc gọi

Ở các cuộc đầu, bot đã thông báo đặt lịch thành công nhưng đường gọi vẫn mở, người dùng phải tự ngắt.

Đã sửa đường xử lý kết thúc để:

- Chờ lời cuối được phát xong.
- Gọi thao tác ngắt đúng người gọi SIP trước khi dọn luồng âm thanh.
- Kết thúc job của agent sau khi dọn tài nguyên.
- Ghi rõ lỗi nếu API ngắt thất bại.
- Khi người gọi rời phòng, dừng xử lý cuộc gọi; một participant khác rời phòng không làm bot kết thúc nhầm cuộc gọi.

Ngoài sửa code, đã kiểm tra báo hiệu tới ứng dụng gọi. Thành công của API ngắt phía server không tự chứng minh người gọi đã ngắt: bằng chứng nghiệm thu còn cần SIP BYE tới client và client trả 200 OK. Các booking Linphone thành công đã có bằng chứng này.

### 4.6. Xử lý vấn đề softphone và gọi lặp

MicroSIP đã thực hiện được booking nhưng các cuộc dài có vấn đề giữ kết nối báo hiệu. Bản ghi cho thấy có trường hợp kết nối TCP bị đóng khoảng 33 giây sau ACK, khiến lệnh kết thúc từ phía server không tới client như mong đợi.

Đã chuyển sang Linphone. Bản Linphone 6 không phù hợp với cách gọi trực tiếp không REGISTER đang dùng; đã dùng bản chính thức 5.3.4 với cấu hình phù hợp cho baseline.

Linphone qua TCP có một cuộc booking hoàn chỉnh, giọng rõ và tự ngắt. Tuy nhiên, cuộc kế tiếp dùng lại kết nối TCP không nhận được SIP response, không dispatch agent. Bản ghi cho thấy server ACK dữ liệu INVITE nhưng không có phản hồi SIP; chưa xác định lỗi thuộc implementation nào.

Đã đổi riêng báo hiệu Linphone sang UDP, giữ nguyên agent, trunk/dispatch, xác thực, codec và mạng 4G iPhone. Kết quả sau thay đổi:

- Hai cuộc âm báo ngắn có BYE/200 OK; cuộc âm báo thứ ba có dispatch/API ngắt nhưng bản ghi kết thúc trước BYE, nên không tính là đã xác nhận hangup tại client.
- Một cuộc âm báo dài 75 giây có BYE/200 OK.
- Hai cuộc dùng worker booking thật liên tiếp đều kết nối và nhận BYE/200 OK.

Những phép thử âm báo dùng âm thanh tạo tại máy, không gọi Vbee và không ghi lịch. Chúng dùng để kiểm tra transport/hangup, không tính vào nghiệm thu booking.

### 4.7. Điều tra chất lượng âm thanh

Người dùng ban đầu phản ánh giọng bot chất lượng thấp, có các lần rè hoặc gián đoạn. Đã thu thập gói âm thanh để phân biệt lỗi nguồn TTS với vấn đề truyền âm thanh hoặc client.

Một phép thử âm báo có khoảng 7,45% gói thiếu ở chiều bot về máy; cuộc booking Linphone TCP có khoảng 0,51% gói thiếu và người dùng xác nhận giọng rõ. Đây là số đo của từng cuộc khác nhau, không đủ để quy toàn bộ cải thiện cho một thay đổi hoặc kết luận mạng luôn ổn định.

Các phép thử vẫn chạy trên mạng 4G phát từ iPhone. Baseline không bắt buộc mạng LAN, Wi-Fi router hay IP tĩnh. Nếu chất lượng tiếp tục dao động, thay mạng hoặc USB tethering là phép thử để khoanh vùng, không phải điều kiện đã được xác định là bắt buộc.

### 4.8. Chuẩn bị dữ liệu để kiểm tra nhiều cuộc

Mock riêng được bổ sung các khung giờ tương lai để tránh hết lịch giữa các lần thử. Trước khi thay đổi cách chạy mock, đã lưu snapshot và kiểm tra phục hồi trên port riêng rồi mới chuyển lại port 8001.

Đã xác nhận giữ nguyên các lịch có sẵn và không tạo lại các slot đã bị tiêu thụ. Không sửa source của repo Clinic Mock; không reset mock giữa hai cuộc UDP dùng worker thật cuối phiên.

Sau cuộc UDP booking thành công, mock có tổng cộng **7 lịch, trong đó 6 BOOKED**; lịch còn lại là dữ liệu SCHEDULED có sẵn. Cuộc UDP tiếp theo không thêm hoặc thay đổi lịch.

## 5. Kết quả thực chạy và mức độ chứng minh

| Hạng mục | Kết quả đã ghi nhận | Giới hạn cần hiểu |
|---|---|---|
| Nhận cuộc gọi SIP | LiveKit nhận caller SIP và tạo phòng | Chưa có cuộc gọi qua Vietnam DID/PSTN. |
| Tự dispatch agent | Job được đưa tới đúng worker baseline | Không dùng worker âm báo làm bằng chứng nghiệp vụ. |
| Hội thoại tiếng Việt | Đã hoàn thành tên, ngày sinh, nhu cầu, chọn khung và đồng ý | Có cuộc phải nói lại; có cuộc không hiểu thông tin. |
| Ghi lịch | Sáu booking SIP thành công được lưu bằng chứng: bốn MicroSIP, hai Linphone | Các cuộc trải qua thay đổi cấu hình, không phải chuỗi ba booking ổn định. |
| Ngắt sau booking | Linphone TCP và UDP có BYE/200 OK | MicroSIP trước đó vẫn có lỗi hangup. |
| Gọi lại qua UDP | Hai cuộc trên cùng cấu hình đều được nhận và tự ngắt | Cuộc thứ hai TRANSFERRED, nên không đạt ba BOOKED liên tiếp. |
| Kiểm tra tự động | 67 test liên quan đã pass; Ruff lint/format và kiểm tra diff đã pass ở phiên triển khai | Test giả lập không thay bằng chứng handset hoặc SIP live. |
| Ba cuộc mô phỏng | Core/Bridge đã chạy ba booking liên tiếp trên cùng mock giả trong regression | Speech và phòng giả; chưa phải ba cuộc voice live. |
| Chuyển nhân viên | Bot có outcome TRANSFERRED và lời thông báo | Chưa có đường chuyển cuộc gọi tới nhân viên thật. |

### Hai cuộc UDP cuối phiên 07/10

| Thời gian Việt Nam | Nội dung | Kết quả |
|---|---|---|
| 17:12–17:13 | Xác minh tên/DOB, đặt lịch, chọn khung, xác nhận; có một lần chọn khung cần nói lại | BOOKED; một POST 201; thêm lịch `apt_28f4ff555c0f`; nhận BYE/200 OK. |
| 17:14–17:15 | Người dùng cho biết bot hỏi tên, đã trả lời “Nguyễn Văn A”, sau đó bot báo chuyển nhân viên | Log ghi NOT_UNDERSTOOD ở identity và outcome TRANSFERRED; không request ghi lịch thực tế; nhận BYE/200 OK. |

Hai cuộc dùng cùng worker `AW_inv8gvgGLV8Y`, cùng Linphone UDP, cùng mock và cấu hình. Bản ghi mạng có 11.740 gói, công cụ capture báo không làm rơi gói. Chỉ số này nói về việc thu thập bằng chứng tại máy, không đồng nghĩa mạng không mất gói RTP.

## 6. Những việc chưa hoàn thành

### 6.1. Ba booking live liên tiếp

Chưa có chuỗi ba cuộc BOOKED liên tiếp mà không chỉnh cấu hình, restart hoặc reset mock giữa các cuộc. Đây là bước kiểm tra ổn định còn thiếu trước demo.

Lỗi nhận dạng tên ở cuộc UDP thứ hai đang được tạm bỏ qua theo yêu cầu người dùng. Nếu tái diễn, cần đối chiếu câu bot hỏi, lời người dùng nói và kết quả nhận dạng để phân biệt lỗi ASR, tách lượt nói hoặc xử lý xác minh; chưa có đủ dữ liệu để chọn nguyên nhân.

### 6.2. Cuộc gọi từ điện thoại thật

Chưa có Vietnam DID được nối vào đường tích hợp này. Các việc cần làm để thay softphone bằng PSTN:

1. Có account/provider và số Việt Nam đã kích hoạt nhận inbound; xử lý hồ sơ và chi phí cần thiết.
2. Cấu hình provider gửi SIP INVITE tới endpoint LiveKit đã kiểm chứng.
3. Dùng inbound trunk riêng cho provider, destination khớp DID và auth/IP allow-list phù hợp; dispatch tới cùng agent.
4. Bảo toàn caller ID là số người gọi; chuẩn bị hồ sơ giả tương ứng với số volunteer để chạy tên/DOB.
5. Kiểm tra âm thanh hai chiều, codec, báo hiệu kết thúc và ba booking liên tiếp trên handset.

Nếu đi theo provider hỗ trợ SIP origination trực tiếp, có thể nối tới LiveKit trực tiếp. Nếu đi theo Stringee SIP Phone theo thiết kế đã xác định, còn cần Asterisk/FreeSWITCH làm bridge REGISTER và chuyển tiếp sang LiveKit, giữ caller ID và ngắt hai phía. Chưa triển khai đầy đủ cả hai nhánh provider trong phần việc này.

### 6.3. Độ ổn định và độ trễ

Chưa nghiệm thu SLA thời gian phản hồi hoặc kết luận chất lượng giọng luôn tốt trên 4G. Vbee từng timeout và một số lần kết nối room chậm. Một cuộc thành công chứng minh tích hợp hoạt động; độ ổn định cần thêm chuỗi kiểm thử có đo đạc.

## 7. Việc tiếp theo và phần cần phối hợp

| Ưu tiên | Công việc | Phối hợp cần có | Điều kiện hoàn thành |
|---|---|---|---|
| 1 | Kiểm tra ba booking live liên tiếp trên Linphone UDP | Kỹ thuật giữ cấu hình và thu bằng chứng; người kiểm thử nói qua microphone | Mỗi cuộc đúng một BOOKED, nghe được hai chiều, bot tự ngắt; không chỉnh tay/reset giữa các cuộc. |
| 2 | Điều tra nhận dạng tên nếu tái diễn | Người kiểm thử mô tả câu hỏi/câu trả lời; kỹ thuật đối chiếu trace | Xác định nguyên nhân hoặc có phạm vi lỗi rõ; giữ xác minh tên/DOB. |
| 3 | Chuẩn bị một provider path | Người phụ trách account/hồ sơ/DID; kỹ thuật cấu hình SIP | Số nhận inbound được kích hoạt và INVITE tới LiveKit. |
| 4 | Kiểm thử demo handset | Volunteer có điện thoại thật; kỹ thuật theo dõi mock và SIP | Hoàn thành checklist real phone line, gồm ba lần lặp và không ghi trùng. |
| 5 | Chốt phương án dự phòng | PM và kỹ thuật | Có runbook softphone để cứu phần integration; hiểu rõ fallback này không thay gate PSTN. |

Trước lần kiểm thử tiếp theo cần kiểm tra worker/mock còn chạy và slot vẫn ở tương lai. Các fixture tạo ngày 07/10 có slot ngày 08/10, nên không mặc định chúng còn phù hợp cho mọi ngày demo. Khi restart mock cần snapshot mới nhất để tránh mất các record vừa tạo.

Không cần tiếp tục nghiên cứu vendor từ đầu hoặc triển khai đồng thời cả hai nhánh. Chọn một provider path để chứng minh cuộc gọi handset trước; nhánh còn lại được chuẩn bị khi thực sự cần làm dự phòng.

## 8. Bàn giao và bằng chứng

Đã có thay đổi ở đường worker/bridge và xử lý participant SIP, các kiểm tra liên quan, script cấu hình SIP baseline, script chạy Clinic Mock và smoke booking. Báo cáo kỹ thuật có runbook chạy lại và checklist nghiệm thu.

Tài liệu và bằng chứng chính:

- [Báo cáo kỹ thuật và runbook chi tiết ngày 07/10](../evidence/inbound-sip-baseline-2026-10-07.md).
- [Booking UDP và cuộc gọi lặp](../../result/07-10-2026/sip-baseline/linphone-live-booking-udp-repeat.json): trace API, số record trước/sau, kết quả hai cuộc và BYE/200 OK.
- [Booking TCP thành công và lần gọi lại không có phản hồi](../../result/07-10-2026/sip-baseline/linphone-live-booking-tcp-repeat.json).
- [Kiểm chứng transport UDP bằng âm báo](../../result/07-10-2026/sip-baseline/linphone-udp-transport-proof.json).
- [Booking Core qua HTTP](../../result/07-10-2026/sip-baseline/core-http-booking.json).

Log và bản ghi mạng gốc được giữ ở thư mục local `temp/sip-baseline-20261007`; báo cáo chia sẻ dẫn tới bản tóm tắt kết quả. Credentials không có trong báo cáo. Các kết quả runtime nêu trên là trạng thái tại thời điểm kiểm thử ngày 07/10, không xác nhận các tiến trình vẫn chạy ở thời điểm người đọc mở tài liệu.

## 9. Nội dung có thể dùng cập nhật daily task

> Đã kiểm chứng end-to-end inbound booking qua softphone SIP → LiveKit → Python Agent → Callbot Core → Clinic Mock. Hoàn thiện xử lý ngắt cuộc gọi, chuyển Linphone sang UDP để xử lý lỗi gọi lại không có phản hồi, xác nhận booking thành công tạo đúng một record BOOKED và có bằng chứng SIP BYE/200 OK. Đã lưu runbook, checklist và danh sách phần còn thiếu cho PSTN. Baseline tích hợp đã thành công; còn ba booking live liên tiếp và Vietnam DID/provider path để nghiệm thu cuộc gọi bằng điện thoại thật. Một lỗi không hiểu tên ở cuộc gọi tiếp theo đang tạm hoãn điều tra theo yêu cầu người kiểm thử.

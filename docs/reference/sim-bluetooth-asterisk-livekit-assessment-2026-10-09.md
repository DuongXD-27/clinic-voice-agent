# Đánh giá phương án SIM Việt Nam → Bluetooth → Asterisk → LiveKit

**Báo cáo cho PM — ngày 09/10/2026.** Ngân sách bổ sung khoảng **200.000 đồng**;
gate 10/10 có thể dời tới 11–12/10. Số Việt Nam (+84) là yêu cầu ngay từ đầu.
Tài liệu này đánh giá phương án, **chưa triển khai, mua thiết bị, đăng ký dịch vụ
hoặc thực hiện cuộc gọi thử qua SIM**.

## 1. Kết luận để quyết định

**Không nên chọn phương án này làm đường gọi chính cho mentor test không báo
trước ở trạng thái hiện tại.** Có thể giữ làm phương án thử nghiệm hoặc demo theo
lịch, nếu nhóm đã có đủ thiết bị và chứng minh được audio hai chiều, tự trả lời,
tự ngắt và chạy lặp lại. Hiện chưa có bằng chứng đó trên phần SIM/Bluetooth.

Lo ngại về nguồn điện là đúng: **điện thoại B và máy Linux phải bật và sẵn sàng
trong toàn bộ thời gian cam kết cho phép test**. Nếu PM yêu cầu mentor gọi bất kỳ
lúc nào, phần gateway phải được vận hành liên tục. Điện thoại không nhất thiết
phải sáng màn hình, nhưng việc khóa màn hình và để máy nghỉ lâu có làm mất kết
nối hay không phải kiểm trên thiết bị thực tế.

Đưa web, LiveKit và Python bot lên cloud không làm điện thoại B hoặc Bluetooth
hoạt động khi thiết bị tại chỗ tắt. Nếu gateway mất kết nối, web vẫn có thể mở
bình thường trong khi cuộc gọi tới số SIM không đến được bot. Khi đó, path điện
thoại vẫn fail theo mục tiêu nghiệm thu.

| Nhu cầu | Đánh giá hiện tại |
| --- | --- |
| Thử một cuộc gọi thật bằng thiết bị sẵn có, trong 200.000 đồng | Có thể đáng thử; chưa xác nhận tương thích hoặc tổng chi phí |
| Demo theo lịch, có người trực gateway | Có thể xem xét sau khi đạt toàn bộ bài kiểm tra chức năng |
| Mentor gọi không báo trước trong một khoảng thời gian đã cam kết | Chưa đủ cơ sở chọn; cần gateway chuyên dụng, người vận hành và kiểm phục hồi |
| Dịch vụ bàn giao để nhận cuộc gọi thường xuyên | Không đề xuất cấu hình điện thoại cá nhân + laptop làm mặc định; ưu tiên đánh giá đường telephony được vận hành ổn định |

**Đề xuất cho PM:** coi đây là một thử nghiệm có điều kiện, chưa phải đường
telephony đã hoàn thành. Nếu yêu cầu chính là mentor gọi không báo trước, cần
chọn đường có thể duy trì sẵn sàng trong cửa sổ test, hoặc thống nhất cửa sổ test
có người trực trước khi công bố số. Không lấy softphone làm bằng chứng thay thế
cuộc gọi từ SIM.

## 2. Phương pháp hoạt động thế nào?

```text
Điện thoại A + SIM A của người gọi
    │ gọi số +84 của SIM B qua mạng di động
    ▼
Điện thoại B + SIM B dành riêng cho bot
    ⇄ Bluetooth HFP: điều khiển nhận/ngắt cuộc gọi
    ⇄ Bluetooth SCO: tiếng nói hai chiều
Máy Linux đặt gần B, chạy Asterisk + chan_mobile
    ⇄ SIP: thiết lập/kết thúc cuộc gọi; RTP: audio
LiveKit SIP → participant SIP trong room → dispatch Python agent
    ⇄ ASR tiếng Việt / booking flow / TTS / Clinic Mock
```

Asterisk đóng vai trò thiết bị hands-free của điện thoại B và chuyển cuộc gọi
sang SIP. Tài liệu Asterisk mô tả khả năng đưa cuộc gọi di động vào dialplan và
chuyển caller ID. Đây là khả năng của module, chưa phải xác nhận điện thoại của
nhóm hỗ trợ tốt. [Asterisk Mobile Channel Features](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Features/).

Module `chan_mobile` cần Linux, Bluetooth và thư viện BlueZ phù hợp; điện thoại
phải được pair với máy. Các triển khai Bluetooth hands-free trên điện thoại có
khác biệt, nên không thể chỉ dựa vào việc điện thoại có Bluetooth để kết luận
tương thích. [Requirements](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Requirements/),
[Debugging](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Debugging/).

Trong mã nguồn nhánh Asterisk 22, module không được bật mặc định khi build và có
mức hỗ trợ `extended`; việc trả lời/ngắt sử dụng lệnh HFP `ATA`/`AT+CHUP`. Cần kiểm
module thực sự có trong bản cài và lệnh hoạt động trên điện thoại B.
[Mã nguồn chan_mobile](https://github.com/asterisk/asterisk/blob/22/addons/chan_mobile.c).

| Thành phần | Vai trò | Điều kiện để nhận cuộc gọi |
| --- | --- | --- |
| SIM B và mạng di động | Cung cấp số +84 và nhận cuộc gọi của A | SIM hoạt động, có sóng, số nhận cuộc gọi bình thường |
| Điện thoại B | Nhận cuộc gọi di động và chuyển tiếng qua Bluetooth | Có nguồn, HFP/SCO tương thích, không bị thiết bị Bluetooth khác chiếm audio |
| Bluetooth trên Linux | Nối điện thoại B với Asterisk | Adapter phù hợp, pair đúng, B trong phạm vi kết nối ổn định |
| Asterisk | Tự nhận cuộc và nối sang LiveKit | Module hoạt động, dialplan và SIP đúng, process đang chạy |
| Internet của Linux | Mang SIP/RTP tới LiveKit | Kết nối liên tục và audio đi được cả hai chiều |
| LiveKit SIP và dispatch | Tạo participant, room và job cho agent | Trunk/rule đúng, dịch vụ đang hoạt động |
| Python, ASR/TTS, Clinic Mock | Hội thoại và đặt lịch | Worker nhận job, các dịch vụ và quota cần thiết sẵn sàng |

Một cuộc gọi đi theo trình tự:

1. A gọi **số của SIM B**; mạng di động làm điện thoại B đổ chuông.
2. Asterisk nhận thông báo qua Bluetooth và trả lời tự động bằng HFP.
3. Asterisk gửi SIP INVITE tới LiveKit theo trunk/rule dành cho đường này.
4. LiveKit nhận SIP participant và dispatch đúng Python agent. Đây là workflow
   được LiveKit mô tả; chỉ mở web không kích hoạt thay được bước SIP inbound.
   [LiveKit inbound workflow](https://docs.livekit.io/telephony/accepting-calls/workflow-setup/).
5. Tiếng A đi qua B, Bluetooth, Asterisk và LiveKit tới ASR; TTS đi ngược lại tới A.
6. Bot hoàn thành booking và tạo đúng một record `BOOKED` mới cho cuộc đó.
7. Khi bot kết thúc, leg SIP và cuộc gọi di động đều phải ngắt. Người gọi cũng
   phải có thể chủ động ngắt mà không để lại cuộc gọi/agent bị treo.

**Số A là caller; số B là số đích của bot.** Không thay caller bằng số B để vượt
qua xác thực hồ sơ. Khi test booking, cần hồ sơ bệnh nhân giả phù hợp với flow
hiện có; không dùng dữ liệu bệnh nhân thật.

## 3. Nhóm đã chứng minh được gì, còn thiếu gì?

[Bằng chứng inbound SIP ngày 08/10](../evidence/inbound-sip-repeat-2026-10-08.md)
ghi nhận ba cuộc softphone liên tiếp kết thúc `BOOKED`, có SIP participant,
dispatch agent, audio hai chiều và gọi Clinic Mock. Đây là nền tảng hữu ích cho
phần sau LiveKit. Tài liệu cũng giữ các lần thử không thành công trước đó.

**Softphone đi thẳng vào SIP không đi qua SIM B, HFP hoặc SCO.** Vì vậy chưa chứng
minh được tự nhận cuộc trên điện thoại B, audio qua Bluetooth, ngắt cuộc di động,
hoặc hoạt động lại sau khi thiết bị nghỉ/reboot/mất kết nối.

| Phần cần đánh giá | Trạng thái hiện tại |
| --- | --- |
| Baseline softphone → LiveKit → bot → Clinic Mock | Đã có bằng chứng trong repo; không thay cho PSTN |
| Model điện thoại B, adapter Bluetooth, máy Linux | Chưa xác định trong thiết kế |
| SIM thật → B → Asterisk tự nhận cuộc | Chưa kiểm |
| Audio hai chiều qua HFP/SCO → SIP/RTP | Chưa kiểm |
| Bot hangup làm điện thoại A kết thúc cuộc | Chưa kiểm trên leg di động |
| Năm cuộc SIM liên tiếp không chỉnh tay | Chưa có bằng chứng |
| Gateway tự phục hồi và nhận cuộc sau thời gian nghỉ | Chưa có bằng chứng |
| Chi phí dịch vụ còn lại trong 200.000 đồng | Chưa đối chiếu quota/tài khoản thực tế |

Không nên ghi phương án này là “đã deploy được” hoặc “sẵn sàng nghiệm thu” chỉ
vì có hướng dẫn cấu hình. [Runbook kỹ thuật](../plans/sim-bluetooth-livekit-spike-2026-10-08.md)
là thiết kế cho một lần thử sau khi được quyết định thực hiện.

## 4. Mentor vào web rồi gọi điện: khi nào sẽ fail?

Bảng dưới giả định web, worker và Clinic Mock chạy trên hạ tầng riêng vẫn còn
hoạt động. Nếu worker/mock cũng nằm trên máy Linux bị tắt thì những phần đó cũng
có thể mất theo.

| Trạng thái gateway | Mentor thấy trên web | Cuộc gọi vào SIM B | Kết quả đối với gate |
| --- | --- | --- | --- |
| B tắt/hết pin/mất sóng | Web vẫn có thể mở | Không đến bot; thông báo, báo bận hoặc voicemail phụ thuộc nhà mạng và cấu hình | Fail path điện thoại |
| B bật, Linux tắt hoặc sleep | Web vẫn có thể mở | B có thể đổ chuông nhưng Asterisk không tự nối sang bot | Fail |
| B và Linux bật, Bluetooth rớt | Web vẫn có thể mở | Không chuyển được cuộc/audio như thiết kế | Fail |
| Bluetooth tốt, Internet Linux mất | Web vẫn có thể mở từ mạng khác | Có thể nhận ở B nhưng không tới LiveKit hoặc mất media | Fail |
| SIP vào được, RTP chỉ đi một chiều | Web/room có thể có trạng thái hoạt động | Bot không nghe A hoặc A không nghe TTS | Fail |
| Gateway tốt, agent/TTS/Clinic Mock lỗi | Web có thể vẫn mở | Có cuộc nhưng không hoàn thành booking hoặc lời thoại | Fail |
| Toàn bộ chuỗi tốt | Web mở, cuộc điện thoại tới bot | Hoàn tất flow và hangup đúng | Chỉ đạt khi có đầy đủ bằng chứng từng tiêu chí |

Nếu không có SIP INVITE đến LiveKit, có thể không có room/job mới để debug bên
bot. Vì thế dashboard bot không báo lỗi chưa chứng minh số điện thoại đang nhận
cuộc được. Đây là suy luận từ kiến trúc inbound, không phải lỗi đã đo trên gateway.

Web tải được, bài test browser thành công và cuộc gọi SIM thành công là các
kiểm tra khác nhau. Nếu browser nối trực tiếp tới LiveKit, nó không kiểm tra
gateway SIM/Bluetooth. Trang web không tự bật điện thoại hoặc máy Linux từ xa.

Không cần mặc định yêu cầu 24/7 nếu PM chỉ cam kết một cửa sổ test. Nhưng **trong
cửa sổ đó phải có người chịu trách nhiệm duy trì gateway**; “bật khi biết mentor
sắp gọi” không đáp ứng cách test không báo trước mà người dùng đang lo ngại.

## 5. Có thể deploy lâu dài không?

Có thể xây một gateway đặt cố định rồi đưa phần bot lên server. Tuy nhiên đó là
một hệ thống có **thiết bị tại chỗ phải được vận hành**, không phải chỉ deploy
container lên cloud là xong. Máy Linux cần ở gần điện thoại B để dùng Bluetooth;
VPS ở xa không thay thế được kết nối này. Remote SSH chỉ giúp quản trị máy đang
có nguồn và Internet, không bảo đảm sửa được mất nguồn hoặc lỗi điện thoại.

Tài liệu Asterisk mô tả quét và tự kết nối điện thoại đã cấu hình khi ở trong
phạm vi. Nó cũng nêu giới hạn một thiết bị hoạt động trên mỗi adapter. Khả năng
tự kết nối này cần được kiểm riêng với thiết bị thực tế; không bảo đảm mọi tình
huống audio treo/ngắt bất thường sẽ tự hồi phục.
[Mobile Channel Concepts](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Concepts/).

Thiết kế **một SIM, một điện thoại B** chỉ nên được nghiệm thu như một kênh gọi
đang hoạt động. Cuộc thứ hai có thể gặp bận/call waiting tùy mạng và thiết bị;
chưa có cơ chế hàng đợi hay nhiều cuộc đồng thời được chứng minh.

Nếu quyết định vận hành phương án này, tối thiểu cần:

- B và Linux dành riêng cho gateway, đặt cố định, có nguồn phù hợp và sóng tốt.
  Không dùng laptop thường xuyên mang đi hoặc điện thoại sinh hoạt cá nhân.
- Linux không tự sleep trong cửa sổ test; Asterisk tự khởi động; kiểm khả năng
  kết nối lại điện thoại và nhận cuộc mà không cần pair/answer bằng tay.
- Internet và đường SIP/RTP ổn định. NAT/firewall có thể làm mất audio dù SIP đã
  thành công; cấu hình NAT thông thường không tự giải quyết mọi mạng CGNAT.
  [Asterisk PJSIP qua NAT](https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/Configuring-res_pjsip-to-work-through-NAT/).
- Theo dõi nguồn/trạng thái thiết bị, Bluetooth, Asterisk, worker và lỗi cuộc
  gọi; có người nhận cảnh báo và có thể tiếp cận thiết bị khi cần.
- Kiểm tra bằng cuộc gọi thật định kỳ trong đợt nghiệm thu. Status process hoặc
  Bluetooth “connected” chưa chứng minh ASR/TTS và booking hoạt động.
- Có kế hoạch xử lý mất điện/mạng. Nguồn dự phòng và mạng dự phòng chỉ giảm một
  số điểm lỗi, không bảo đảm tương thích HFP hoặc xử lý được mọi lỗi treo.

Giám sát giúp phát hiện sự cố; **không làm gateway đang tắt nhận được cuộc gọi**.
Nếu hiển thị readiness trên web, phải phản ánh trạng thái gateway với thời điểm
kiểm gần nhất. Không dùng trạng thái “web online” làm trạng thái “điện thoại sẵn
sàng”. Báo cáo này không đề xuất thực hiện thay đổi giao diện ngay.

## 6. Rủi ro, chi phí và giới hạn giấy tờ

Các mức ảnh hưởng dưới đây là đánh giá thiết kế, không phải tỷ lệ lỗi đo được.

| Rủi ro | Ảnh hưởng | Cách kiểm/giảm rủi ro | Phần vẫn còn |
| --- | --- | --- | --- |
| Điện thoại/adapter không tương thích HFP/SCO | Không hình thành path hoặc mất tiếng | Kiểm local echo và tự nhận/ngắt trước khi nối LiveKit | Có thể phải đổi thiết bị, vượt ngân sách |
| B/Linux mất nguồn, sleep, bị mang đi | Mentor gọi không tới bot | Thiết bị dành riêng, nguồn, chủ vận hành | Vẫn có phụ thuộc vật lý |
| Bluetooth rớt hoặc audio treo | Cuộc đến nhưng im lặng/mất một chiều | Kiểm idle, reconnect, ngắt bất thường và lặp cuộc | Chưa có độ ổn định đã đo |
| NAT/Internet chặn media | SIP participant có nhưng thiếu audio | Xác minh RTP hai chiều trên mạng định dùng | Đổi mạng có thể phải đánh giá lại |
| Chỉ ngắt leg SIP, SIM vẫn giữ cuộc | A tiếp tục tính thời lượng, B không rảnh | Kiểm handset kết thúc và nhận được cuộc kế tiếp | Callback bot không đủ chứng minh leg di động đã ngắt |
| Hai người gọi đồng thời | Người thứ hai không được phục vụ | Công bố một kênh; test hành vi cuộc thứ hai | Chưa đáp ứng nhu cầu đồng thời |
| Không có người xử lý lỗi tại chỗ | Downtime kéo dài tới lúc phát hiện | Chỉ định owner và đường tiếp cận thiết bị | Không phù hợp cam kết tùy lúc nếu thiếu owner |

**200.000 đồng chỉ có thể là ngân sách cho thử nghiệm với tài nguyên sẵn có.**
Không có báo giá tổng đã xác nhận cho phương án này. Không nên coi số đó đủ để
mua cả điện thoại B, máy Linux, adapter và dự phòng nguồn/mạng.

| Khoản | Cách tính cho quyết định |
| --- | --- |
| Điện thoại B, SIM, Linux, Bluetooth | Phải xác nhận đã có/mượn được; chưa định giá mua mới |
| Cuộc gọi A → B | Theo gói SIM A và thời lượng; không mặc định miễn phí |
| SIM B | Kiểm trạng thái nhận cuộc, hạn sử dụng và chi phí duy trì thực tế |
| LiveKit, TTS và hạ tầng bot | Kiểm credit/quota còn lại; phần miễn phí chỉ tính khi tài khoản thực tế còn được dùng |
| Nguồn, Internet, nhân công xử lý lỗi | Có chi phí vận hành dù không phát sinh thanh toán ngay trong lần demo |

Ưu điểm về thủ tục là sử dụng số SIM +84 đã hoạt động, không phải xin cấp DID
mới để bắt đầu thử kỹ thuật. **Không suy ra rằng mọi SIM đều được phép sử dụng
cho mọi mô hình gateway/thương mại**; điều kiện thuê bao cụ thể vẫn cần được
đối chiếu khi lựa chọn cho bàn giao. Báo cáo không kết luận pháp lý dựa trên các
nhận định outbound chưa được kiểm chứng trong báo cáo cũ.

Về privacy, gateway SIM không thay đổi đường dữ liệu sau Asterisk. Nếu audio
đi qua LiveKit Cloud hoặc dịch vụ speech bên ngoài thì vẫn phải đối chiếu yêu
cầu privacy của dự án. Tự host riêng Asterisk hoặc SIP không tự làm toàn bộ
pipeline đáp ứng yêu cầu đó. Báo cáo nhóm trước đây đã nêu đây là điểm PM cần
chốt: [nghiên cứu ngày 29/09](telephony-provider-research-2026-09-29.md).

## 7. Nếu PM chọn thử, phải chứng minh những gì?

Đây là kế hoạch đề xuất cho quyết định sau, **không phải công việc đang triển
khai**. Không hứa hoàn thành trước 11–12/10 khi chưa biết phần cứng và mạng.

### 7.1. Kiểm tính khả thi theo thứ tự

1. Kiểm cuộc gọi A → B bình thường và xác nhận đủ thiết bị. Ghi model, OS,
   adapter, mạng và nơi đặt gateway; không ghi công khai thông tin cá nhân.
2. Kiểm Bluetooth/Asterisk tại chỗ: tự nhận cuộc, local echo hai chiều, tự ngắt
   cuộc di động; không cần LiveKit ở bước này. Nếu không qua được, dừng đánh giá
   phần cloud và báo rõ điểm chặn, không tiếp tục coi thiết bị là tương thích.
3. Kiểm Asterisk → LiveKit: trunk riêng, room riêng từng cuộc, caller ID, audio
   hai chiều và tự dispatch đúng agent. Không dùng cấu hình softphone nguyên
   trạng làm bằng chứng cấu hình PSTN đã đúng.
4. Kiểm booking với dữ liệu giả, tiếng Việt, lời cuối của TTS và hangup cả hai
   leg. Sau ngắt, B phải rảnh để nhận cuộc tiếp theo.
5. Chạy chuỗi nghiệm thu đầy đủ, rồi kiểm khả năng vận hành ở bước 7.3.

### 7.2. Gate chức năng cho từng cuộc và chuỗi chạy lặp

| Tiêu chí bắt buộc | Bằng chứng cần lưu |
| --- | --- |
| Điện thoại thật gọi vào số +84 | Người test xác nhận từ handset, timestamp/call ID liên kết với log |
| LiveKit nhận SIP participant | Room/participant của đúng cuộc; không lấy browser participant thay thế |
| Python agent tự được dispatch | Job/worker tương ứng, không chạy dispatch thủ công từng cuộc |
| Bot nghe tiếng Việt | Transcript và diễn biến hội thoại phù hợp lời người gọi |
| Người gọi nghe TTS | Xác nhận trên handset về tiếng hai chiều và lời kết thúc |
| Booking hoàn thành | Flow đi tới kết quả đặt lịch, không chỉ kết thúc conversation |
| Đúng một record `BOOKED` mới | Kiểm delta Clinic Mock và request/idempotency theo từng cuộc |
| Hangup đúng | A thấy cuộc đã kết thúc; B rảnh; participant/job được dọn |
| Chạy lại không chỉnh tay | Đề xuất năm cuộc liên tiếp cùng code/config, không pair/restart/answer/reset mock giữa các cuộc |

Năm cuộc đạt cần **năm record `BOOKED` mới**, mỗi cuộc đúng một record, giữ nguyên
các record cũ. Giữ log các lần fail để biết nguyên nhân; không chỉ chọn cuộc tốt
để báo cáo. Mask số điện thoại và thông tin cá nhân trong evidence.

### 7.3. Gate vận hành bổ sung cho cách test không báo trước

Năm cuộc liên tiếp chỉ chứng minh khả năng lặp trong phiên thử. Để đề xuất làm
đường chính cho mentor, cần thêm kiểm tra và bằng chứng:

- B khóa màn hình, Linux chạy không có người thao tác; gọi vẫn được sau một
  khoảng nghỉ. Có thể chọn một đợt quan sát 24 giờ nếu lịch cho phép; đó là bài
  kiểm đề xuất, không phải SLA và không chứng minh độ ổn định lâu dài.
- Reboot Linux và reconnect Bluetooth rồi gọi lại; không chỉnh cấu hình hoặc
  pair lại bằng tay. Đây là bài kiểm riêng sau chuỗi năm cuộc, không chèn reset
  vào giữa chuỗi rồi báo là chạy liên tiếp.
- Mất rồi có lại Internet/Bluetooth; ghi rõ trường hợp nào tự phục hồi và
  trường hợp nào cần người trực. Không đánh đồng kết nối lại với audio tốt.
- Người gọi ngắt giữa cuộc; gateway nhận được cuộc mới, không còn leg treo.
- Xác định hành vi khi có cuộc thứ hai trong lúc đang bận.
- Có owner, nơi đặt thiết bị, thời gian sẵn sàng cam kết và quy trình xử lý
  gateway offline. PM đồng ý giới hạn trước khi gửi số cho mentor.

Nếu một lỗi buộc phải bấm điện thoại hoặc restart/pair mỗi lần, đường đó chưa
đáp ứng yêu cầu “chạy lại không cần chỉnh tay”. Nếu cần người phục hồi sau sự
cố, phải ghi đúng điều kiện vận hành, không công bố nhận cuộc bất kỳ lúc nào.

## 8. Đường bàn giao và quyết định PM cần chốt

Khi có số +84/trunk do provider vận hành và cho phép route tới LiveKit, có thể
thay phần SIM/Bluetooth/Asterisk bằng provider → LiveKit SIP; giữ phần agent và
booking sau đó, rồi nghiệm thu lại caller ID, audio, dispatch và hangup. Hướng
này loại bỏ phụ thuộc điện thoại B/Bluetooth tại nhóm nhưng vẫn cần xử lý quota,
điều kiện dịch vụ, chi phí và độ sẵn sàng của provider. Chưa có đường tự thuê
mới được xác nhận đáp ứng 200.000 đồng trong thời hạn hiện tại.
[Kế hoạch telephony hiện có](../plans/pstn-inbound-execution-2026-10-08.md).

Gateway SIM/VoLTE chuyên dụng cũng vẫn là thiết bị vật lý cần nguồn và mạng;
không coi việc đổi điện thoại sang gateway là giải pháp tự động cho uptime.
Chưa có thiết bị, báo giá hoặc tương thích được xác nhận cho lựa chọn này.

| Quyết định PM | Hệ quả |
| --- | --- |
| Mentor test theo lịch hay không báo trước trong cửa sổ nào? | Quyết định yêu cầu vận hành gateway; chưa mặc định 24/7 |
| Có thiết bị dành riêng và người chịu trách nhiệm vận hành không? | Nếu không có, không chọn SIM/Bluetooth làm đường chính không báo trước |
| Trần 200.000 đồng có bao gồm dịch vụ bot và thiết bị không? | Nếu thiếu tài nguyên/credit, cần điều chỉnh phạm vi/ngân sách hoặc tìm đường test được tài trợ |
| Privacy và phạm vi bàn giao cho phép đường này đến đâu? | Chốt dùng cho lab, demo hay bàn giao; đối chiếu yêu cầu dự án trước khi chọn hạ tầng |

**Khuyến nghị cuối:** với yêu cầu mentor có thể gọi khi nhóm không trực tiếp
chuẩn bị và với tình trạng chưa kiểm phần cứng, chưa chọn SIM/Bluetooth làm
phương án chính. Chỉ thử nếu đã có sẵn thiết bị, có thể dành riêng và có owner.
Nếu PM chấp nhận demo theo lịch, phương án có thể được cân nhắc sau khi vượt
qua toàn bộ gate chức năng. Nếu PM giữ cách test không báo trước, cần chứng
minh vận hành gateway hoặc có một đường +84 khác được duy trì sẵn sàng; hiện
không có cơ sở hứa chắc đáp ứng cả thời hạn và ngân sách.

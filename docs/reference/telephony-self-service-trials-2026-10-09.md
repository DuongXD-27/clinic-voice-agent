# Provider tự đăng ký và dùng thử cho inbound +84

Ngày kiểm tra: 09/10/2026. Yêu cầu: SIM Việt Nam gọi số +84 → LiveKit SIP
participant → agent → booking; ngân sách khoảng 200.000 đồng. Nghiên cứu từ
website/tài liệu chính thức, chưa tạo tài khoản, gửi form, liên hệ, nạp tiền
hay kiểm cuộc PSTN trên tài khoản thực tế.

## Quyết định đề xuất

**Cập nhật từ giao diện tài khoản người dùng:** đã tạo portal
`callbotdemo.stringeex.com`, hiển thị 10 ngày trial. Danh sách hotline chỉ có
`+testcall`; chưa thấy số +84 PSTN. Form thêm số kiểu “Số điện thoại nhà mạng”
hướng dẫn liên hệ `sales@stringee.com`. Đây là bằng chứng từ ảnh người dùng
cung cấp, chưa phải cuộc gọi thật. Không coi hotline tự gán là DID Việt Nam
miễn phí. Chưa xác nhận Stringee đã nhận yêu cầu hoặc thời điểm trả lời.

**Trạng thái mới theo người dùng:** OMICall đã được PM liên hệ nên không làm
trùng đầu mối. didlogic được coi là **BLOCKED cho đợt lựa chọn này**, theo yêu
cầu người dùng, vì không có email công việc. Không tiếp tục đề xuất workaround
email hoặc tạo tài khoản didlogic. Ứng viên mới để tìm hiểu là DIDHub; còn nhiều
điều kiện chưa xác minh và thời gian công bố không phù hợp gate 11–12/10.

Không cần mua phần cứng SIM/Bluetooth để nghiên cứu các provider này. Chưa có
bằng chứng một phương án nhận +84 PSTN và route tới LiveKit đáp ứng đồng thời
ngân sách 200.000 đồng và thời hạn.

“Có đăng ký trực tiếp/dùng thử” và “đã nhận cuộc gọi thật vào LiveKit được” là
hai mức bằng chứng khác nhau. Báo cáo này xác nhận mức công bố; gate vẫn cần
cuộc gọi thực tế. Chỉ cần hỏi hỗ trợ nếu portal không cho tự xác minh điểm còn
thiếu, không mặc định mọi bước đều phải qua hợp đồng hoặc đầu mối quen biết.

## 1. StringeeX: ưu tiên kiểm đầu tiên

- Có [trang đăng ký trực tiếp](https://www.stringeex.com/vi/register) và
  [gói dùng thử 10 ngày, không phí khởi tạo](https://www.stringeex.com/vi/pricing).
- [Hướng dẫn tạo tài khoản](https://help.stringeex.com/stringeex-tong-dai-cham-soc-and-quan-ly-khach-hang/i.-gioi-thieu-chung/1.-dang-ky-tai-khoan-moi)
  nói portal mới được tự gán hotline để trải nghiệm. Portal người dùng thực tế
  chỉ thấy `+testcall`; chưa xác minh được số +84 nhận PSTN.
- Có hướng dẫn tạo SIP account cho user để nhận cuộc trên IP Phone/softphone
  bằng REGISTER. Lấy domain/port từ portal thực tế, không copy server India
  trong ví dụ cho portal Việt Nam.
  [StringeeX IP Phone configuration](https://help.stringeex.com/stringeex-tong-dai-cham-soc-and-quan-ly-khach-hang/en/iv.-frequently-asked-questions/12.-configure-ip-phone-connection-with-stringee-contact-center).

Không kết luận “Stringee chỉ hỗ trợ REGISTER” trên toàn bộ sản phẩm: tài liệu
trên chứng minh một cách kết nối SIP Phone. External SIP trunk/URI cho trial
vẫn chưa được xác minh. Nếu có route trực tiếp tới LiveKit, ưu tiên kiểm cách
đó; nếu chỉ có account REGISTER, mới đánh giá bridge.

Hướng bridge đề xuất, chưa triển khai:

```text
SIM người test → hotline +84 của StringeeX
    → SIP account của user/hàng đợi
    → Asterisk trên server đăng nhập StringeeX, nhận cuộc
    → SIP INVITE/RTP tới LiveKit → Python bot
```

LiveKit hiện liệt kê REGISTER là không hỗ trợ. Bridge sẽ làm phía đăng nhập
provider và gửi cuộc tới LiveKit theo cơ chế inbound được hỗ trợ.
[LiveKit telephony feature list](https://docs.livekit.io/telephony/).
Đây là kiến trúc dự kiến, chưa chứng minh credentials, quyền routing, audio,
caller ID, hangup hoặc chi phí server trên tài khoản trial thực tế.

Bridge có thể đặt trên server luôn bật, không cần điện thoại B hoặc Bluetooth.
Vẫn phải vận hành Asterisk/server/Internet và bot; dùng laptop ngủ/tắt vẫn không
đáp ứng test không báo trước. Không coi cloud bridge là miễn phí nếu chưa có
hạ tầng hoặc credit phù hợp.

**Phân biệt sản phẩm:** StringeeX là contact center có trial riêng. Stringee
Call API là sản phẩm developer; tài liệu hướng dẫn mua số trong Dashboard khi
cần phone-to-app/app-to-phone. Con số 1.500 phút được nêu trong bài hướng dẫn
video không đủ chứng minh được miễn phí DID và PSTN cho gate này.
[Call API getting started](https://developer.stringee.com/docs/call-api-getting-started-android),
[bài hướng dẫn video](https://www.stringee.com/en/blog/post/huong-dan-video-web-stringee-call-api).
Không suy ra giá thật từ trường giá trong JSON response mẫu API.

### Việc tự kiểm trong portal

1. Đăng ký bằng thông tin thật; nếu trường công ty bắt buộc, mô tả đúng nhóm/dự
   án theo cách form cho phép. Không giả pháp nhân hoặc mã số thuế.
2. Tạo portal phù hợp khu vực Việt Nam, kiểm hotline được cấp có thực sự là +84.
3. Dùng SIM gọi số đó; trước tiên kiểm cuộc có đến portal và nghe/nói được với
   web agent. Đây là phép kiểm provider, chưa tính là gate bot.
4. Kiểm phần user/SIP account, routing vào đúng user, quyền sử dụng trong trial,
   thời hạn và mọi phí phát sinh. Không nhập thẻ/nạp tiền chỉ để thử vận may.
5. Nếu có đủ điều kiện, mới lựa chọn direct SIP hoặc bridge trên server, rồi
   nghiệm thu toàn bộ path và năm cuộc liên tiếp.

**Dừng đánh giá trial đó nếu:** không có số +84 nhận PSTN, không cho routing
cần thiết, phải nâng cấp vượt trần mới có SIP, hoặc thời hạn không phủ cửa sổ
test. Không triển khai bridge trước khi làm rõ các điểm này.

## 2. OMICall: trial công khai, quyền tích hợp cần xác nhận

[Trang chính OMICall](https://omicall.com/) hiện quảng bá dùng thử miễn phí
14 ngày và hỗ trợ cài đặt trong 24 giờ. Đây là công bố, chưa phải cam kết cấp
số/route cho nhóm. [Form đăng ký trên website](https://omicall.com/tong-dai-omicall-2/)
là kênh gửi yêu cầu, không chứng minh có thể mua và kích hoạt số tức thì.

[API tổng đài](https://api.omicall.com/omicall-api/call-center) có thông tin máy
lẻ SIP và hotline. Chưa thấy đủ bằng chứng trial gồm cấp mới số +84 nhận PSTN,
external SIP URI hoặc cho Asterisk đăng nhập account của máy lẻ để làm bridge.
Không coi API quản lý/call log hoặc tính năng callbot sẵn của OMICall là audio
hai chiều vào Python bot của dự án.

Các điểm cần hỏi/kiểm: cá nhân làm demo được dùng trial không; có cấp số +84
hay cần số sẵn; nhận được cuộc từ SIM không; cấp SIP credentials/routing nào;
được nối bot riêng không; giấy tờ, hạn trial và tổng phí. Không áp dụng các
quảng cáo dùng thử năm 2019 làm điều kiện hiện hành.

## 3. Mua trực tiếp và những lựa chọn khác

| Provider | Điều đã thấy trong công bố | Kết luận cho lần test này |
| --- | --- | --- |
| Zadarma | Số Hà Nội/TP.HCM $12/tháng, phí kết nối $0; đặt qua tài khoản | Có quy trình tự mua, không phải trial DID miễn phí; chưa chứng minh tổng chi phí đáp ứng 200.000 đồng. [Nguồn](https://zadarma.com/en/tariffs/numbers/vietnam/) |
| Telnyx | Nạp tối thiểu $10; số local Việt Nam có quy trình hồ sơ cá nhân và khoảng 72 giờ sau nhận tài liệu | Có đường cá nhân, nhưng không phải mua không giấy tờ/kích hoạt tức thì; chưa chốt giá số và ngân sách. [Billing](https://support.telnyx.com/en/articles/4280500-billing-setup-billing-groups), [Vietnam requirements](https://support.telnyx.com/en/articles/3737163-vietnam-did-requirements) |
| didlogic | Công bố trial cho developer; form Work email/Google Business Workspace; account production bắt đầu bằng $25 top-up | BLOCKED theo yêu cầu người dùng vì không có email công việc. [Signup](https://didlogic.com/get-started/), [account](https://didlogic.com/setup/customer-service/new-account/) |
| DIDHub | Trang Vietnam công bố từ $4/tháng, $0 setup, inbound $0.025/phút và quy trình cá nhân với ID/địa chỉ Việt Nam | Ứng viên cần xác minh; trang Buy lại ghi từ $3/tháng và 5–10 ngày làm việc, khác với 3–7 ngày ở country guide. Chưa xác minh signup Gmail, tồn kho, phí tối thiểu, hồ sơ được duyệt hoặc trial +84. [Country guide](https://didhub.io/numbers/vietnam), [Buy](https://didhub.io/buy/vietnam) |
| Talking.vn | Công bố G0 miễn phí, tự tạo tổng đài | Chưa xác nhận gồm số +84 PSTN và quyền SIP ngoài; không coi miễn phí PBX là miễn phí số. [Nguồn](https://talking.vn/landing-page/) |
| ConnectViet | Gói trunk Starter $39/tháng, phí kích hoạt $39, cọc $40, hợp đồng 24 tháng; áp dụng công ty Việt Nam | Có checkout nhưng không phù hợp yêu cầu cá nhân/test nhỏ hiện tại. Giá DID rời không phải tổng phí trunk. [Nguồn](https://www.connectviet.com/get-started?family=sip-trunks) |
| Plivo | Trang SIP pricing Vietnam ghi inbound không hỗ trợ | Trial credit không giải quyết số +84 inbound theo trang này. [Nguồn](https://www.plivo.com/sip-trunking/pricing/vn/) |

Các con số USD ở đây là giá công bố, không phải báo giá đầy đủ hoặc chuyển đổi
sang VND. Chưa đánh giá tồn kho số hoặc KYC trong tài khoản đã đăng nhập.

## 4. Mẫu yêu cầu nếu cần hỗ trợ

> Tôi đang làm demo kỹ thuật đặt lịch, dữ liệu giả, không gọi quảng cáo. Tôi
> cần một số Việt Nam +84 nhận cuộc từ SIM thật, một cuộc đồng thời, khoảng
> 30 phút test trong 3–5 ngày. Bot riêng dùng LiveKit SIP/Python. Trial có
> cấp số này không? Có gửi SIP INVITE/RTP tới SIP URI ngoài được không; nếu
> không, có cấp SIP account cho Asterisk đăng nhập và nhận cuộc không?
> Cá nhân được đăng ký không, cần giấy tờ gì, khi nào kích hoạt, và tổng
> phí có thể giữ trong 200.000 đồng không?

Gửi mẫu này nếu form/portal không trả lời được; không chỉ hỏi “có free không”.
Phản hồi “có SIP” cần làm rõ là trunk gửi INVITE hay account yêu cầu REGISTER.
Ngân sách phải tính cả server bridge, LiveKit và TTS nếu không có quota sẵn.

## Bước tiếp theo

StringeeX đang chờ phần cấp số thật; OMICall do PM liên hệ; didlogic bị chặn theo
yêu cầu người dùng. Kiểm DIDHub là bước nghiên cứu tiếp, không phải lựa chọn đã
đạt gate. [Signup chính thức](https://dashboard.didhub.io/signup) cần kiểm form
thực tế vì web reader không đọc được các trường. Website có
[trang tích hợp LiveKit](https://didhub.io/integrations/ai-agents/livekit-agents),
nhưng chưa kiểm tương thích thực tế. Không thanh toán hoặc gửi giấy tờ trước
khi làm rõ giá checkout, quyền route SIP, hồ sơ cá nhân và ngày kích hoạt.

Chưa có nguồn công khai đủ để hứa “đăng ký xong là miễn phí và chạy LiveKit
ngay”. Nhưng có đường tự bắt đầu cụ thể, thay vì kết luận phải có đầu mối mới
làm được. Khi trial hết hạn, cần kế hoạch duy trì số; không công bố cho mentor
test sau hạn trial mà chưa có dịch vụ tiếp nối.

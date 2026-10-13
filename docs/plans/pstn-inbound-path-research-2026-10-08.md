# Đường số Việt Nam → LiveKit → booking

Ngày nghiên cứu: 08/10/2026. Người dùng xác nhận: **bắt buộc số Việt Nam ngay từ đầu**.
Phạm vi là nghiên cứu và đề xuất; chưa cấp số, nạp tiền, đổi Cloud, deploy hay chạy PSTN.
Ngân sách user chốt sau nghiên cứu: khoảng **200.000 đồng**. Thứ tự hành động
và kế hoạch mới nhất ở [kế hoạch triển khai](pstn-inbound-execution-2026-10-08.md):
ưu tiên xin/mượn đường test +84 sẵn có; các lựa chọn tự thuê dưới đây là dữ liệu
so sánh, chưa xác nhận đáp ứng trần ngân sách.

## Đề xuất

Triển khai **BYO Vietnamese DID/SIP → LiveKit Cloud → Python worker hiện có**.
Ưu tiên route SIP trực tiếp tới endpoint Cloud; chỉ thêm PBX/SBC nếu provider bắt buộc.
Không dùng số Mỹ hoặc chuyển số Việt Nam sang số Mỹ để thay thế yêu cầu này.

Thứ tự thực hiện:

1. Nếu clinic/đối tác có số hoặc trunk test +84, xin một DID test hoặc route riêng tới
   LiveKit. Đây là hướng có khả năng giảm chi phí và thủ tục phát sinh nhất, nhưng chưa
   xác nhận có tài nguyên này. Không đổi route hotline đang phục vụ khách hàng.
2. Nếu phải tự thuê: đánh giá **Zadarma và DIDWW** bằng quyền mua số, hồ sơ cần nộp,
   tổng chi phí và một cuộc PSTN chẩn đoán. Zadarma có giá +84 công khai; DIDWW có
   tài liệu rõ cho account cá nhân và static SIP endpoint.
3. Nếu muốn free trước: hỏi **didlogic** có cấp số test +84 và credit test hay không.
   Họ quảng cáo free test number, và LiveKit có hướng dẫn provider này, nhưng chưa xác
   nhận số test được chọn là Việt Nam. Không coi lời quảng cáo này là gói +84 free.
4. Nếu các DID quốc tế không đáp ứng, xin báo giá trunk inbound tối thiểu từ provider
   trong nước. Gateway SIM chỉ là lựa chọn khi mượn được thiết bị VoLTE phù hợp.

Chưa có bằng chứng về một dịch vụ đáp ứng đồng thời +84, PSTN thật, free và không
xác minh. Có thể giảm hồ sơ bằng account cá nhân/eKYC hoặc dùng số test có sẵn.

## Baseline PR 103

Đã đọc [PR 103](https://github.com/phamtuanviet/callbot-vinmec/pull/103) bằng GitHub CLI.
Tại thời điểm đọc: OPEN, mergedAt=null. Phần softphone có ba BOOKED liên tiếp,
mỗi cuộc một POST 201, auto-dispatch, audio hai chiều và RemoveParticipant.
[Evidence](../evidence/inbound-sip-repeat-2026-10-08.md).

- Python nhận caller từ `sip.phoneNumber`, không dùng số đích gọi vào để tìm patient.
- Trunk baseline dùng số `1000` và digest auth; rule bị giới hạn vào trunk softphone.
- Mỗi cuộc có room riêng; rule chỉ định agent name; worker đăng ký cùng tên.
- Hangup sau local TTS drain và grace mặc định 2000 ms. Grace chưa xác nhận handset nghe hết.
- `docker-compose.prod.yml` đã có `livekit-worker`, restart policy và healthcheck.
- Speech hiện có: Zipformer local, Vbee TTS, Silero VAD.

Giữ pipeline này để thử PSTN. Các lỗi tên/DOB/name extraction và nhánh thiếu caller
number vẫn tồn tại theo [review PRD](../evidence/prd-v2.3-inbound-review-2026-10-08.md).
Happy path thành công chưa chứng minh toàn bộ PRD hoặc đường PSTN.

## So sánh theo yêu cầu +84

| Hướng | Chi phí / free | Hồ sơ | Kỹ thuật và kết luận |
| --- | --- | --- | --- |
| Số/trunk test của clinic hoặc đối tác | Có thể không phát sinh tiền thuê số mới; chưa xác nhận | Có thể tận dụng tài khoản/hợp đồng sẵn có; cần quyền route số test | Ưu tiên nếu có tài nguyên |
| Zadarma 024/028 | Công bố $0 đấu nối, $12/tháng; chưa xác nhận trial +84 | Trang quốc gia chưa nêu rõ hồ sơ của account/number; cần xác nhận trước nạp tiền | API hỗ trợ gắn DID tới external SIP URI; ứng viên giá minh bạch |
| DIDWW local +84 | Chưa đọc được giá đầy đủ; cần number rental + inbound rate + capacity/minimum funding | Có account Personal; bảng coverage ghi VN local không cần registration riêng; account vẫn yêu cầu ID + selfie và 2FA | Static SIP endpoint, TCP/TLS và caller format có tài liệu; ứng viên cấu hình rõ |
| didlogic test +84 | Có quảng cáo số test free và xin sales credit; chưa xác nhận +84 nằm trong trial | Signup work email, account được review; hồ sơ phụ thuộc số/quốc gia | LiveKit có quickstart; chỉ chọn sau xác nhận số VN test |
| Trunk trong nước | Cần báo giá gói inbound nhỏ nhất; không suy giá từ gói tổng đài | Thường có hợp đồng doanh nghiệp và giấy tờ | Phù hợp vận hành nếu có pháp nhân/trunk sẵn, chưa phải hướng ít thủ tục nhất |
| SIM + gateway VoLTE | Không free nếu phải mua thiết bị | Cần SIM hợp lệ và điều kiện sử dụng của nhà mạng | Thêm hardware/NAT/media/caller-ID; chỉ xem xét khi có thiết bị |

Zadarma công bố số 024/028 và giá tại
[Vietnam numbers](https://zadarma.com/en/tariffs/numbers/vietnam/).
API `direct_numbers/set_sip_id` chấp nhận external server SIP URI;
PBX redirection có `sip_uri`:
[API](https://zadarma.com/en/support/api/).
Suy luận: có thể thử route thẳng vào LiveKit, chưa có proof interoperability.
Cần xác nhận SIP source/auth, caller ID và phí external SIP delivery; không tự suy
external forwarding miễn phí từ giá thuê số.

DIDWW công bố VN local ở bảng
[registration requirements](https://www.didww.com/coverage-and-prices/regulatory-requirements/registration-required).
Phân biệt registration của số với eKYC account:
[Personal account](https://doc.didww.com/account-settings/creating-an-account.html),
[account setup](https://doc.didww.com/account-settings/account-setup.html).
Không cần bộ hồ sơ đăng ký riêng cho số theo bảng công bố không có nghĩa account
không phải xác minh danh tính. Giá phải kiểm tra ở inventory/checkout thực tế.

DIDWW có static SIP delivery tới public domain, User Part `{DID}`, TCP/TLS, CLI format,
source IP/POP:
[inbound trunk](https://doc.didww.com/voice/inbound-trunks/creating-a-new-sip-trunk.html),
[SIP endpoints](https://doc.didww.com/voice/inbound-trunks/technical-data/sip.html).
Suy luận: cấu trúc phù hợp LiveKit inbound; chưa có live call chứng minh tương thích.

Free test của didlogic:
[signup](https://didlogic.com/get-started/),
[LiveKit quickstart](https://docs.livekit.io/telephony/start/providers/didlogic/).
Chưa xác nhận inventory +84, quota, thời hạn hoặc giấy tờ cụ thể.

Ví dụ quy trình trunk trong nước do Vbee mô tả: doanh nghiệp, ĐKKD, giấy tờ đại diện,
hợp đồng và đấu nối; không suy thành mọi provider đều có cùng hồ sơ/thời hạn:
[Vbee FAQ](https://help.aicall.vbee.ai/vbee-aicall-cloud/tai-lieu-chung/cau-hoi-thuong-gap).
StringeeX có trial phần mềm 10 ngày, nhưng chưa xác nhận bao gồm số +84 và route SIP
ra LiveKit; tránh mua gói contact center nhiều seat chỉ để test một inbound bot.
[Trial](https://asia-1.stringeex.com/vi/pricing).

Gateway có thể nối mobile và SIP:
[Dinstar](https://www.dinstar.com/GSM-3G-LTE-voip-gateway/8-16-ports/).
Chưa có báo giá, thiết bị test hoặc proof gateway → LiveKit ở repo.

## Kiến trúc

```text
Điện thoại + SIM Việt Nam, gọi bằng ứng dụng điện thoại mặc định
  → số Việt Nam 024/028 hoặc mobile DID
  → provider chuyển INVITE/RTP tới SIP endpoint LiveKit Cloud
  → inbound trunk dành riêng cho DID thật
  → dispatch rule tạo room riêng, chỉ định agent name
  → Python worker hiện có
  → Zipformer / Core / Vbee
  → HTTP Clinic Mock
```

LiveKit vẫn tạo participant SIP và rule dispatch theo
[inbound workflow](https://docs.livekit.io/telephony/accepting-calls/workflow-setup/).
Không cần tự host LiveKit/SIP server cho gate ban đầu.

Provider cần route tới public SIP FQDN. Nếu chỉ hỗ trợ REGISTER, private link hoặc
IP đích cố định không phù hợp endpoint Cloud, đánh giá SBC/Asterisk trên server
public như một chi phí bổ sung. Không mặc định thêm PBX trước khi biết hạn chế.

Các bước triển khai:

1. Chốt account, inventory và tổng tiền để dùng **một số +84, một cuộc đồng thời**.
2. Cấu hình destination DID theo E.164, codec G.711 PCMU/PCMA theo khả năng hai bên;
   xác nhận media hai chiều. Chọn signaling theo hỗ trợ provider, ưu tiên TLS nếu có;
   TLS signaling không tự mã hóa RTP.
3. Tạo trunk riêng trong LiveKit, kiểm soát nguồn/auth theo provider. Không tái sử
   dụng số `1000` hoặc credential baseline làm cấu hình PSTN.
4. Rule gắn đúng trunk, room riêng mỗi cuộc, `hide_phone_number=false`, agent name
   trùng `LIVEKIT_AGENT_NAME`; tránh dispatch tay hoặc gọi bằng browser.
5. Chuẩn bị trước hồ sơ giả gắn với số SIM mobile của người test, tên/DOB và đủ slot
   tương lai cho năm cuộc. Không sửa dữ liệu để khớp transcript ASR sau cuộc lỗi.
6. Chạy worker được giám sát trên máy/server hiện có, kiểm tra model, Vbee/semantic
   balance và Clinic Mock thật qua HTTP. Không đổi speech provider cùng lúc đổi trunk.
7. Một cuộc chẩn đoán PSTN để kiểm tra caller ID/audio/hangup, chốt cấu hình rồi chạy
   năm BOOKED liên tiếp. Nếu sửa giữa chuỗi, bắt đầu chuỗi nghiệm thu mới.
8. Kiểm tra thêm restart worker theo cấu hình đã lưu, gọi lại không cần sửa route/data.

Caller ID phải là số người gọi, không phải DID clinic. `normalize_phone` đang nhận
số +84 mobile và quy về 0xxxxxxxxx; số SIM thật cần tồn tại ở mock. Nếu provider
ẩn/mất caller ID, không giả caller ID để vượt gate; nhánh thiếu số còn lệch PRD.

## Gate nghiệm thu

| Điều kiện | Bằng chứng từng cuộc |
| --- | --- |
| Điện thoại thật gọi vào số VN | SIM thật, dialer mặc định, số đích, giờ gọi |
| Participant SIP | Room ID, kind SIP, caller number, SIP call ID, rule ID |
| Python auto-dispatch | Job ID, agent/worker name, thời gian nhận job |
| Nghe tiếng Việt | ASR đúng các bước tên/DOB, nhu cầu, slot, xác nhận |
| TTS nghe được | Người test xác nhận audio hai chiều và lời cuối đủ |
| Booking hoàn thành | Trace patient lookup, slots, confirm, POST appointments |
| Đúng một BOOKED/cuộc | Snapshot trước/sau, appointment ID, idempotency, không record dư |
| Hangup đúng | RemoveParticipant, handset kết thúc, provider/SIP log; BYE/200 nếu có capture |
| Chạy lặp lại | Năm cuộc liên tiếp cùng code/config, không reset dữ liệu hoặc chỉnh tay |

Năm cuộc độc lập phải tạo đúng năm BOOKED mới, giữ record cũ. Một room/job/TTS
request thành công chưa đủ. Restart recovery là phép kiểm riêng sau chuỗi.
[LiveKit testing](https://docs.livekit.io/telephony/testing/) hỗ trợ kiểm SIP;
booking và repeat là gate của dự án.

## Chi phí và nội dung cần provider xác nhận

Dành khoảng 15 phút cho năm cuộc ba phút; chưa tính các lần debug. Trên LiveKit
Build, allowance third-party SIP là 1.000 phút; kiểm tra quota thực tế còn lại.
Build $0/tháng; không mặc định hết quota được tự tiếp tục pay-as-you-go.
[Pricing](https://livekit.com/pricing).

Tổng chi phí = số + activation + phút inbound/capacity + minimum top-up nếu có
+ LiveKit + máy chạy agent/ASR + Vbee/semantic + cước gọi nội địa của người test.
Zadarma $12 chỉ là phí số công bố; DIDWW chưa có quote đầy đủ. Không báo tổng VND
khi chưa có giá provider, Vbee và SIM cụ thể.

Mẫu yêu cầu kỹ thuật để người dùng gửi provider:

> Tôi cần một số Việt Nam 024/028 để test inbound AI booking, một cuộc đồng thời,
> khoảng 15–30 phút test. Cuộc gọi phải chuyển qua SIP tới public FQDN LiveKit Cloud,
> giữ caller ID người gọi dạng E.164, hỗ trợ G.711 và BYE từ bot. Có số test/credit
> miễn phí không? Nếu không, tổng tiền kích hoạt, thuê một tháng, phút inbound,
> capacity, VAT và nạp tối thiểu là bao nhiêu? Account cá nhân cần giấy tờ gì,
> có cần pháp nhân/hợp đồng giấy không? Có cho route tới external SIP URI mà
> không bắt buộc dùng tổng đài/phần mềm AI của quý công ty không?

Đây là bản soạn để sử dụng; chưa gửi liên hệ hoặc đăng ký với bên nào.

## Những hướng đã loại khỏi mục tiêu

LiveKit Native Phone Numbers hiện chỉ số Mỹ; Twilio/Telnyx số Mỹ không đáp ứng +84.
Nguồn: [LiveKit numbers](https://docs.livekit.io/telephony/start/phone-numbers/).
Không coi demo softphone, sandbox API, browser trên điện thoại hay chuyển tiếp
qua số Mỹ là nghiệm thu số Việt Nam → SIP → bot theo yêu cầu đã chốt.

# Chốt đường PSTN inbound cho tuần 6

**Bổ sung 09/10 — hướng tự tìm provider:** ưu tiên xác minh trial StringeeX có
hotline tự gán và trial OMICall; chưa cần chờ PM tìm hộ. Xem
[nghiên cứu đăng ký trực tiếp/dùng thử](../reference/telephony-self-service-trials-2026-10-09.md).
Các công bố trial chưa chứng minh tài khoản của nhóm nhận +84 PSTN và route
được tới LiveKit; kiểm hai điều đó trước khi trả tiền hoặc dựng bridge.

Ngày 08/10/2026. Bổ sung sau khi đọc
[báo cáo nhóm ngày 29/09](../reference/telephony-provider-research-2026-09-29.md)
và [nghiên cứu các DID +84](pstn-inbound-path-research-2026-10-08.md).
Đây là kế hoạch đề xuất, chưa đăng ký số, nạp tiền, liên hệ provider hoặc deploy.
User cho phép dời gate 10/10 thêm một đến hai ngày; kế hoạch bên dưới nhắm cuộc
live đầu tiên 11/10 và hoàn tất chuỗi nghiệm thu 12/10, tùy ngày kích hoạt thực tế.
User đã chốt ngân sách khoảng **200.000 đồng**. Điều này thay đề xuất Telnyx trả
phí làm đường chính: ưu tiên xin/mượn số hoặc trunk test +84 có sẵn, được phép
route tới bot. Chưa có đường tự thuê mới nào được xác nhận đáp ứng trần này.

**Cập nhật 09/10 về SIM/Bluetooth:** [báo cáo đánh giá cho PM](../reference/sim-bluetooth-asterisk-livekit-assessment-2026-10-09.md)
chưa đề xuất gateway điện thoại + Linux làm đường chính cho mentor gọi không báo
trước. Phương án cần nguồn và kết nối tại chỗ xuyên suốt cửa sổ test, cùng bằng
chứng tự phục hồi; hiện mới là thiết kế thử nghiệm, chưa triển khai.

## Quyết định kỹ thuật

Chốt inbound qua số Việt Nam; dùng SIP trực tiếp tới LiveKit Cloud hiện tại nếu
boundary privacy của dự án cho phép. Giữ Python worker, ASR/TTS và Core từ baseline.
Chuỗi softphone đã có bằng chứng ba BOOKED; phần chưa nghiệm thu là PSTN → SIP.

```text
SIM mobile của tình nguyện viên
  → DID Việt Nam
  → provider gửi SIP INVITE và RTP tới LiveKit Cloud
  → inbound trunk riêng → room riêng → explicit agent dispatch
  → Python / ASR / Core / TTS / HTTP Clinic Mock
  → một BOOKED mới → nghe hết lời cuối → BYE / handset kết thúc
```

## Chọn provider theo thứ có sẵn

| Điều kiện thực tế | Đường chính đề xuất |
| --- | --- |
| Có DID/trunk test +84 đã hoạt động và được phép route riêng | Dùng đường đó trước; kiểm SIP/caller ID bằng một cuộc thật |
| Chưa có số, trần 200.000 đồng | Xin provider cấp DID/trunk +84 test trong 3–5 ngày, một kênh, 15–30 phút; chưa xác nhận provider đồng ý |
| Đã có số Stringee và SIP credentials hoạt động | Hỏi external SIP URI/peer trunk; nếu chỉ SIP Phone REGISTER, đánh giá một Asterisk bridge trên máy sẵn có |
| Có thể mượn gateway VoLTE tương thích cùng SIM nhận cuộc | Kiểm điều kiện sử dụng và SIP/audio/caller ID; không mua hardware mới trong ngân sách này |
| Provider không cấp test và không có đường sẵn | Báo gate bị chặn bởi việc cấp số trong ngân sách; không coi softphone là PSTN |

Telnyx là phương án đã nghiên cứu nếu có credit tài trợ phù hợp hoặc ngân sách
được đổi; LiveKit có quickstart provider này, giảm việc tự ghép transport.
Hồ sơ cá nhân vẫn gồm tên, số liên hệ, ID và utility bill
không quá ba tháng; khoảng 72 giờ sau khi nhận tài liệu để xác minh/kích hoạt là
ước lượng công bố, không phải cam kết cho account cụ thể.
[Telnyx Vietnam requirements](https://support.telnyx.com/en/articles/3737163-vietnam-did-requirements),
[LiveKit Telnyx quickstart](https://docs.livekit.io/telephony/start/providers/telnyx/).

Quickstart LiveKit ghi rõ tích hợp Telnyx cần account trả phí. Telnyx trial có
$5 credit, nhưng cấp số còn phụ thuộc inventory, balance và hồ sơ; trial chỉ nhận
cuộc từ số đã verify và giới hạn 10 phút/cuộc. Không cam kết demo +84 miễn phí từ
credit này. Phải xác nhận account tier và tổng tiền tối thiểu trước khi nạp.
[Telnyx trial limitations](https://developers.telnyx.com/docs/account-setup/levels-and-capabilities/trial).

Utility bill phục vụ xác minh địa chỉ/hồ sơ cấp số, không phải yêu cầu của LiveKit
hay Voice Brandname. Trang Vietnam requirements chưa ghi rõ phải đứng tên người
đăng ký hoặc có thể thay bằng giấy tờ nào; cần hỏi Telnyx nếu hóa đơn đứng tên
người nhà/chủ nhà. Không tự đặt điều kiện bắt buộc hóa đơn mang tên người test.

DIDWW có account cá nhân; tài khoản production phải ID + selfie và 2FA. Bảng
coverage công bố VN local không cần bộ registration riêng cho số, nhưng không
miễn eKYC account. Static SIP endpoint có tài liệu; tương thích end-to-end với
project này vẫn cần cuộc gọi thật. Chưa có báo giá hoặc inventory được xác nhận.
[DIDWW account setup](https://doc.didww.com/account-settings/account-setup.html),
[registration requirements](https://www.didww.com/coverage-and-prices/regulatory-requirements/registration-required),
[static SIP trunk](https://doc.didww.com/voice/inbound-trunks/creating-a-new-sip-trunk.html).

Các giá/mức nạp công khai không phù hợp để mặc định mua mới trong trần 200.000:

| Provider | Mức công bố; chưa phải tổng chi phí |
| --- | --- |
| Telnyx | Billing help ghi minimum payment $10; LiveKit yêu cầu account trả phí |
| DIDWW | Minimum top-up $30 |
| Zadarma | Số local Việt Nam $12/tháng, $0 đấu nối |

[Telnyx billing](https://support.telnyx.com/en/articles/4280500-billing-setup-billing-groups),
[DIDWW billing](https://doc.didww.com/billing/billing-and-prices/index.html),
[Zadarma Vietnam](https://zadarma.com/en/tariffs/numbers/vietnam/).
Tiền nạp là tiền trả trước, khác mức tiêu hao thực tế; vẫn tính toàn bộ tiền
phải trả vào trần ngân sách. Nếu có chương trình test hoặc account đã có balance,
phải xác nhận điều kiện riêng và quyền dùng account trước khi chọn.

## Những điểm cần sửa cách hiểu trong báo cáo 29/09

1. Stringee 1.500 phút/4 kênh là gói Call API công bố; không đủ để kết luận số +84
   hoặc phút PSTN được cấp miễn phí. Trang giá ghi phí phần mềm và tách phí callout.
   [Call API pricing](https://stringee.com/vi/pricing-call).
2. Stringee SIP Phone được hướng dẫn REGISTER vào `v2.stringee.com:15060`; tài liệu
   đó không chứng minh mọi sản phẩm/trunk thương mại đều chỉ REGISTER. Hỏi đúng
   khả năng chuyển inbound DID tới external SIP URI trước khi dựng bridge.
   [SIP Phone](https://developer.stringee.com/docs/call-rest-api/sip-phone-management).
3. Không có websocket audio hai chiều không chặn phương án SIP: SIP/RTP có thể
   mang audio hai chiều qua bridge tới LiveKit. Đây là hai kiểu tích hợp khác nhau.
4. IP tĩnh phía nhóm không phải điều kiện mặc định của mọi provider. Provider có
   thể gửi INVITE tới public SIP domain của LiveKit; trunk nhà mạng yêu cầu peer IP
   hoặc private link mới cần giải pháp riêng. Không đổi region hoặc tự host trước
   khi nhận được thông số đấu nối của đường được chọn.
5. Tự host riêng SIP bridge/server không tự làm toàn bộ audio ở trong hạ tầng nhóm:
   nếu LiveKit media server vẫn là Cloud hoặc speech provider nhận audio/text thì
   vẫn có dữ liệu qua dịch vụ ngoài. Phải kiểm boundary end-to-end theo PRD hiện hành.
6. Phần pháp lý outbound trong báo cáo tự ghi chưa đọc văn bản gốc. Bổ sung này chưa
   xác minh phạm vi chính xác Điều 37/38, không dùng nó làm kết luận mọi outbound
   bị cấm hay mọi inbound mặc nhiên miễn mọi điều kiện. Scope nghiệm thu đề xuất
   là inbound; provider phải xác nhận điều kiện dịch vụ cho đường đó.

## Mốc triển khai

- **08/10 — xin đường test:** chọn một người liên hệ và một kỹ sư SIP. Kiểm số/
  trunk test +84 sẵn có trong nhóm/đối tác. Người được giao liên hệ hỏi Stringee
  trước nếu đã có đầu mối, hoặc provider SIP khác: một số/nhánh test 3–5 ngày,
  một kênh, 15–30 phút, route external SIP tới LiveKit, tổng tiền tối đa 200.000
  và active trước 11/10. Không coi trial phần mềm hoặc demo công khai của provider
  là quyền route số về bot. Provider vẫn có thể yêu cầu xác minh; chỉ nộp qua kênh
  chính thức, không đưa ID/hóa đơn vào repo hoặc chat.
- **08–10/10 — kỹ thuật song song:** chuẩn bị cấu hình inbound trunk/rule riêng,
  explicit agent dispatch, worker từ bản đã đạt softphone, hồ sơ giả gắn SIM test,
  đủ slot và collector bằng chứng. Chỉ cấu hình provider theo hướng dẫn sau khi
  có thông số account/số; giữ speech pipeline hiện tại.
- **Điểm quyết định 09/10:** phải có một đường được xác nhận: số/trunk test
  active, được phép route, ETA phù hợp và tổng tiền trong trần. Nếu chưa có,
  báo PM chưa thể cam kết gate PSTN; chỉ xét gateway khi mượn được thiết bị phù
  hợp. Không chuyển sang tự mua DIDWW/Telnyx mặc định vì vượt trần tiền trả trước.
- **11/10 — mục tiêu cuộc live đầu:** khi số active, gọi từ SIM thật để kiểm
  caller ID, SIP participant, auto dispatch, audio hai chiều và hangup. Yêu cầu
  ETA bao gồm xử lý cuối tuần. Chưa có số active thì chưa thể cam kết mốc này.
- **12/10 — mục tiêu gate:** chạy năm booking liên tiếp cùng code/config,
  mỗi cuộc tạo đúng một BOOKED mới và kết thúc đúng. Nếu cần sửa sau cuộc
  chẩn đoán hoặc trong chuỗi, bắt đầu lại chuỗi nghiệm thu sau khi sửa.
- **Sau gate, trước freeze 16/10:** kiểm restart recovery và giữ khoảng đệm
  trước demo 19–24/10 theo lịch trong báo cáo nhóm.

Chỉ có một đường được triển khai chính. Phương án dự phòng làm đến mức xác nhận
số/account/khả năng route; chỉ triển khai nó khi đường chính bị từ chối, không có
inventory hoặc ETA vượt deadline. Nhà mạng production có thể lấy báo giá song
song nhưng không cần phát triển thêm cả stack trong đợt nghiệm thu này.

## Công việc kỹ thuật trước cuộc live

1. DID đúng E.164; caller ID là số SIM người test, không dùng số DID clinic.
2. Trunk riêng; auth/source restriction đúng provider, codec G.711; kiểm audio
   hai chiều. Không copy trunk softphone `1000` vào đường PSTN.
3. Rule gắn đúng trunk, room riêng, giữ caller number, agent name trùng worker.
4. Worker chạy ổn định trên máy/server hiện có, model/credentials/balance sẵn sàng.
5. Hồ sơ giả gắn số SIM thật, tên/DOB thống nhất trước phiên, đủ slot tương lai.
6. Collector lưu provider/SIP call ID, room/job, trace clinic và snapshot trước/sau.
7. Bot đọc đủ câu cuối rồi hangup; đối chiếu handset và provider log.

Năm cuộc phải cùng code/config, không chỉnh tay/reset mock giữa các cuộc. Mỗi
cuộc một BOOKED mới; snapshot cuối tăng đúng năm, giữ dữ liệu cũ. Cuộc lỗi không
tính đạt; nếu phải sửa cấu hình thì chạy lại chuỗi. Gate chi tiết giữ nguyên trong
[nghiên cứu ngày 08/10](pstn-inbound-path-research-2026-10-08.md).

## PM cần chốt để kế hoạch có thể thực hiện

- **Boundary demo:** xác nhận theo PRD hiện hành việc dùng carrier, LiveKit Cloud
  và speech services đã chọn; dùng tình nguyện viên và hồ sơ giả. Nếu NFR-17 bắt
  buộc toàn bộ audio trong hạ tầng nhóm, phải thay kiến trúc tương ứng và tính lại ETA.
- **Owner:** người đứng tên account/hồ sơ và người liên hệ provider. Không sử dụng
  danh nghĩa/pháp nhân Vinmec khi chưa được bên đó cho phép.
- **Trần chi phí đã chốt:** khoảng 200.000 đồng tổng tiền phải trả thêm, gồm số,
  phút gọi, SIP bridge nếu cần và speech usage phát sinh. Tận dụng máy/credit
  hiện có; chưa xác nhận quota/balance đủ. Xác nhận minimum top-up, thuê bao,
  activation/capacity, VAT và auto-renew trước thanh toán; không tự vượt trần.

## Mẫu gửi provider, chưa gửi

### Có thể tự triển khai mà không gọi sales không?

Có thể tự đặt số trên portal, nhưng không đồng nghĩa cấp số tức thì hoặc nằm
trong 200.000 đồng. Zadarma công bố luồng signup → top-up → order số Việt Nam
trong Settings; số 024/028 là $12/tháng. Kích hoạt/hồ sơ và tương thích LiveKit
vẫn cần kiểm tra. API có external SIP URI; đây là khả năng cấu hình, chưa là
bằng chứng end-to-end. Liên hệ sales là cách xin đường test trong ngân sách,
không phải điều kiện bắt buộc của mọi phương án telephony.
[Zadarma Vietnam](https://zadarma.com/en/tariffs/numbers/vietnam/),
[API](https://zadarma.com/en/support/api/).

Một hướng tự dựng khác, dùng số mobile +84 đã có:

Hướng dẫn cấu hình và gate riêng:
[SIM Bluetooth LiveKit spike](sim-bluetooth-livekit-spike-2026-10-08.md).

```text
Điện thoại A / SIM người gọi
  → mạng di động → SIM trên điện thoại B
  → Bluetooth HFP → Asterisk chan_mobile trên Linux
  → SIP → LiveKit inbound trunk/rule → Python bot
```

Asterisk mô tả điện thoại Bluetooth làm FXO, nhận inbound mobile và chuyển
caller ID vào Asterisk. Cần Linux có Bluetooth/BlueZ hoạt động cùng điện thoại
tương thích. Docs cũ dùng mobile.conf; mã nguồn branch 22 ưu tiên chan_mobile.conf.
Đường này chưa được chạy ở
project. Không suy điện thoại Android/iPhone bất kỳ đều tương thích, hoặc phần
mềm SIP trên điện thoại tự truy cập audio cuộc SIM.
[Introduction](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Introduction-to-the-Mobile-Channel/),
[Features](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Features/),
[Requirements](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Requirements/).

Chỉ xem xét trong trần 200.000 nếu điện thoại/SIM thứ hai và máy có Bluetooth
đã có hoặc mượn được, đồng thời máy/credit speech hiện tại đủ dùng. Chưa có
báo giá phần cứng; không hứa mua đủ thiết bị trong trần. SIM vẫn phải hoạt động
hợp lệ; chưa kiểm điều kiện sử dụng SIM cụ thể cho gateway.

Spike kỹ thuật đề xuất khi xác nhận được thiết bị:

1. Dùng Linux có truy cập Bluetooth trực tiếp; không mặc định WSL/Docker trên
   Windows truy cập được Bluetooth cho chan_mobile. Xác nhận module có trong
   bản Asterisk chọn, có thể phải build.
2. Pair điện thoại B, cho chan_mobile kết nối; gọi thật từ A vào B. Kiểm caller
   ID, audio hai chiều, answer và hangup qua Asterisk trước khi ghép bot.
3. Nếu bước 2 đạt, tạo SIP leg từ Asterisk vào LiveKit, giữ số A ở From/caller
   và số B ở destination đúng trunk; NAT/RTP phải hoạt động cả hai chiều.
4. Bot kết thúc phải giải phóng cả SIP leg và cuộc di động trên B. Không cần
   người bấm nhận/ngắt mỗi cuộc, không dùng loa ngoài để ghép audio.
5. Chỉ sau khi audio/dispatch/hangup đạt mới chạy cùng gate năm BOOKED; chưa
   coi gateway tương thích là đã đạt booking hoặc tính lặp lại.

Đây là prototype lab để đánh giá khả năng tận dụng thiết bị, không mặc định là
đường chính chắc kịp 12/10 hoặc giải pháp production. Nếu không đạt các bước
đầu, không kéo dài debug phần cứng và hứa gate khi chưa có đường nhận PSTN.

### Bắt đầu khi chưa có đầu mối

Không cần người giới thiệu; dùng kênh sales/support công khai. Các kênh dưới đây
đã kiểm tra ngày 08/10; chưa liên hệ, chưa có quote hoặc đồng ý cấp số test.

| Thứ tự liên hệ | Kênh chính thức | Yêu cầu cần xác nhận |
| --- | --- | --- |
| Stringee | 1800 6670; info@stringee.com; [Contact sales](https://stringee.com/en/contact-sales) | Developer PoC inbound +84; số/nhánh test và external SIP route hoặc REGISTER credentials; tổng phí tối đa 200.000 |
| didlogic, hỏi song song | sales@didlogic.com; [Get started](https://didlogic.com/get-started/); [Contact](https://didlogic.com/contact/) | Free test DID có thể là +84 không; SIP route tới LiveKit; giấy tờ/account eligibility và ETA |
| VFone nếu cần thêm một kênh trong nước | contact@vfone.vn; (024) 7308 6680 hoặc (028) 7308 6680; [Website](https://vfone.vn/) | Có cấp số/nhánh test thực sự nhận PSTN, cho external SIP, trong trần và trước gate không |

didlogic quảng cáo free test number/credit, nhưng trang signup yêu cầu work email,
và [release notes](https://docs.didlogic.com/docs/release-notes/) nêu trial number
cho khách mới có verified company email. Chưa xác nhận trial chọn được số +84;
nếu nhóm chỉ có email cá nhân, hỏi sales về eligibility trước. Không khai công ty
không tồn tại hoặc dùng danh nghĩa clinic để qua onboarding.

Người liên hệ ghi lại bốn câu trả lời: (1) số +84 thực sự nhận PSTN được, (2) route
SIP/credentials dùng được cho bot, (3) tiền trả trước và phí tổng không quá trần,
(4) ngày active cụ thể. Hẹn follow-up trong một ngày làm việc nếu chưa có phản
hồi; không đợi một provider trả lời mới hỏi provider tiếp theo. Chọn một đường
để triển khai sau khi có xác nhận, không phát triển ba stack.

Nếu hết điểm quyết định 09/10 vẫn chưa có đường được xác nhận, báo PM gate PSTN
chưa có cơ sở cam kết trong ngân sách. Việc dời sang 12/10 không tự giải quyết
inventory, giấy tờ hay cấp số. Chưa gửi email, gọi điện, tạo account hoặc nộp form
cho provider trong phiên nghiên cứu này.

> Nhóm cần một số Việt Nam 024/028 cho inbound demo AI booking tuần 6, một cuộc
> đồng thời, 15–30 phút test đầu tiên. Cần route cuộc gọi tới SIP FQDN của LiveKit
> Cloud, giữ caller ID E.164, audio G.711 hai chiều và chấp nhận BYE từ bot. Xin
> xác nhận: stock số +84, account cá nhân/hồ sơ cần nộp, tổng tiền tối thiểu,
> auth/routing có bắt REGISTER/IP tĩnh không, và ngày số thực sự có thể nhận PSTN.
> Nếu có số test/credit hoặc external SIP route trực tiếp, xin cung cấp điều kiện.

Mẫu ngắn phù hợp ngân sách hiện tại, để người được giao liên hệ gửi:

> Nhóm đã chạy LiveKit SIP + Python bot thành công qua softphone. Cần một số hoặc
> nhánh test +84 nhận cuộc gọi SIM thật trong 3–5 ngày, một kênh, khoảng 15–30 phút,
> active trước 11/10 để nghiệm thu 12/10. Tổng ngân sách tối đa 200.000 đồng.
> Bên mình có thể cấp đường test route tới external SIP FQDN của LiveKit, giữ
> caller ID và audio hai chiều không? Nếu chỉ hỗ trợ REGISTER, xin cho biết có
> thể nhận qua SIP credentials và bridge của nhóm không. Xin xác nhận giấy tờ,
> tổng phí, số test dùng riêng hay qua extension, và thời điểm dùng được.

Mẫu cho Telnyx support, chỉ dùng nếu hỏi credit tài trợ hoặc ngân sách được đổi:

> We need one Vietnam local +84 DID (024/028), inbound only, for a small AI
> booking demo. We will route calls to a LiveKit SIP FQDN with caller ID in
> +E.164, two-way G.711 audio and bot-initiated hangup. Can an individual account
> purchase this DID and use paid SIP trunking? Please confirm current inventory,
> accepted ID/address documents (including a utility bill in a family member's
> or landlord's name), any accepted alternative to a utility bill, the minimum
> total payment and all recurring charges. If complete documents are submitted
> on October 8, 2026, can PSTN inbound be active by October 11 for acceptance
> on October 12? Please account for weekend processing in the activation ETA.

Thông số và giấy tờ chưa có được ghi là chưa xác nhận; không suy từ signup nhanh
thành cấp số nhanh, hoặc từ SIP connection thành booking thành công.

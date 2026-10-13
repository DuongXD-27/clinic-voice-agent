# SIM Việt Nam → Bluetooth → Asterisk → LiveKit: hướng dẫn spike

Ngày 08/10/2026. Ngân sách khoảng 200.000 đồng; gate có thể dời tới 12/10.
Đây là thiết kế và cấu hình mẫu, chưa cài Asterisk, pair điện thoại, provision
LiveKit hoặc chạy cuộc SIM thật. Chưa biết model điện thoại/máy Linux của nhóm.
Không coi tài liệu này là bằng chứng tương thích hay nghiệm thu.

**Cập nhật 09/10:** đọc [đánh giá cho PM về vận hành gateway](../reference/sim-bluetooth-asterisk-livekit-assessment-2026-10-09.md)
trước khi chọn đường này. Điện thoại B và Linux phải sẵn sàng trong cửa sổ test;
chưa đề xuất làm đường chính cho mentor gọi không báo trước khi chưa kiểm phục
hồi và chưa có thiết bị dành riêng/người vận hành. Runbook bên dưới chưa được thực hiện.

## Cơ chế

```text
A: điện thoại người test + SIM A
  → cuộc gọi di động vào số +84 của SIM B
B: điện thoại dành cho bot, nhận cuộc gọi bằng mạng di động
  ⇄ Bluetooth HFP: điều khiển cuộc gọi; SCO: audio
Linux gần B: Asterisk chan_mobile ⇄ PJSIP/RTP
  ⇄ LiveKit SIP → participant SIP + room + agent dispatch
Python worker → Zipformer / Core / Vbee → Clinic Mock
```

B là đầu vào điện thoại của hệ thống, số B là số người test quay. Asterisk đóng
vai trò thiết bị hands-free Bluetooth đối với B và SIP gateway đối với LiveKit.
Internet của máy Linux phục vụ leg SIP; cuộc gọi A → B vẫn đi qua mạng di động.
Không cần thuê DID mới hoặc xin SIP trunk của nhà mạng cho mô hình này vì đã có
SIM B hoạt động. Đây không phải xác nhận điều kiện dịch vụ của SIM cụ thể.

Trong [mã nguồn Asterisk 22](https://github.com/asterisk/asterisk/blob/22/addons/chan_mobile.c),
answer gửi `ATA`, hangup gửi `AT+CHUP`, caller đi qua xử lý `+CLIP`; audio dùng
SCO. Module được đánh dấu `defaultenabled=no`, support level `extended`.
Trang docs cũ ghi `mobile.conf`, còn branch 22 ưu tiên `chan_mobile.conf` và vẫn
đọc tên cũ. Bám version đang cài để tránh nhầm cấu hình.

## Điều kiện để bắt đầu

| Tài nguyên | Cần có |
| --- | --- |
| Điện thoại A | SIM thật để gọi, số đã seed trong hồ sơ giả của clinic mock |
| Điện thoại B | SIM +84 đang nhận cuộc gọi bình thường; Bluetooth hands-free tương thích |
| Máy Linux | Có Bluetooth Classic và audio SCO hoạt động; BlueZ; Asterisk có chan_mobile/PJSIP |
| Vị trí | B ở gần máy Linux, được cấp nguồn; tránh auto-connect sang tai nghe khác |
| Internet | Máy Linux kết nối được SIP endpoint và có đường RTP hai chiều tới LiveKit |
| Bot | Worker/model/credentials và quota speech hiện có đủ cho test |

Không có danh sách chứng minh mọi Android/iPhone hiện đại đều dùng được.
Pair Bluetooth thành công chưa chứng minh HFP initialization hoặc SCO hoạt động.
[Asterisk debugging](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Debugging/)
ghi rõ triển khai HFP khác nhau giữa điện thoại và có thể cần sửa driver.

Chọn Linux chạy trực tiếp trên máy hoặc live USB để thử trước. VM chỉ dùng nếu
Bluetooth adapter được passthrough đầy đủ. WSL/Docker trên Windows không được
mặc định coi là có Bluetooth/SCO cho chan_mobile. Nếu boot live USB, lưu cấu
hình vào chỗ có persistence để lần sau không phải chỉnh lại.
Nếu chính máy Windows đó đang chạy Python worker/Clinic Mock, boot sang Linux
sẽ dừng các process Windows. Phải chạy worker/mock trên máy khác hoặc chuẩn bị
chúng trên Linux trước cuộc bot thật; giữ model/config đã đạt softphone.

## Bước 1 — xác nhận module trước khi cấu hình

Trên Linux, kiểm tra BlueZ/adapter và bản Asterisk:

```bash
bluetoothctl list
bluetoothctl show
sudo asterisk -rx 'core show version'
sudo asterisk -rx 'module show like chan_mobile'
sudo asterisk -rx 'module show like chan_pjsip'
```

Nếu chan_mobile chưa load, sau khi chuẩn bị cấu hình thử:

```bash
sudo asterisk -rx 'module load chan_mobile.so'
```

Phân biệt lỗi thiếu file `.so`, thiếu config và lỗi adapter/permission. Nếu bản
đóng gói không chứa module, cần build bản Asterisk phù hợp, có libbluetooth-dev,
bật chan_mobile trong Add-ons của Menuselect. Không có cơ sở hứa `apt install
asterisk` trên mọi distro sẽ đủ. Không ghi đè cấu hình của tổng đài đang dùng.
[BlueZ requirements](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Requirements/),
[Menuselect](https://docs.asterisk.org/Getting-Started/Installing-Asterisk/Installing-Asterisk-From-Source/Using-Menuselect-to-Select-Asterisk-Options/).

## Bước 2 — pair điện thoại B và tìm RFCOMM port

Bật Bluetooth/discoverable trên B. Trong `bluetoothctl`, dùng các lệnh tương ứng:

```text
power on
agent on
default-agent
scan on
pair <PHONE_B_BLUETOOTH_MAC>
trust <PHONE_B_BLUETOOTH_MAC>
scan off
quit
```

Chấp nhận mã pair trên B. Đây là thao tác chuẩn bị một lần; nghiệm thu các cuộc
sau không được cần pair/nhận/ngắt bằng tay. Xác nhận BlueZ của distro hỗ trợ
các lệnh trên; không dùng Bluetooth MAC minh họa như giá trị thật.

Trong Asterisk CLI (`sudo asterisk -rvvv`):

```text
mobile search
mobile show devices
```

Lấy RFCOMM port từ `mobile search`, không mặc định `port=4` cho mọi điện thoại.
Module có thể cần một cấu hình adapter hợp lệ trước khi lệnh search dùng được.
Điện thoại B phải ở trạng thái cho phép phát hiện trong bước tìm kiếm.

## Bước 3 — cấu hình chan_mobile

Mẫu cho branch 22, ở `/etc/asterisk/chan_mobile.conf`. Thay tất cả placeholder:

```ini
[general]
interval=30

[adapter]
id=bt0
address=<LINUX_BLUETOOTH_MAC>

[bot-phone]
address=<PHONE_B_BLUETOOTH_MAC>
port=<RFCOMM_PORT_FROM_MOBILE_SEARCH>
context=mobile-echo
adapter=bt0
group=1
sms=no
```

MAC adapter là của máy Linux; MAC device là của điện thoại B. Không đặt
`type=headset` cho B: ở đây B là phone. Mỗi adapter của chan_mobile phục vụ một
device cùng lúc. Tham khảo
[sample branch 22](https://github.com/asterisk/asterisk/blob/22/configs/samples/chan_mobile.conf.sample)
và [concepts](https://docs.asterisk.org/Configuration/Channel-Drivers/Mobile-Channel/Mobile-Channel-Concepts/).

Sau chỉnh config, nạp lại module/restart Asterisk trong lab không có cuộc đang
chạy; việc reload riêng chan_mobile phải kiểm theo version, không giả định
`core reload` áp dụng tất cả trường. Chờ tự connect và kiểm `mobile show devices`.

## Bước 4 — echo test cục bộ, chưa ghép LiveKit

Trong `/etc/asterisk/extensions.conf` của lab thêm:

```ini
[mobile-echo]
exten => s,1,NoOp(SIM Bluetooth echo test)
 same => n,Answer()
 same => n,Echo()
 same => n,Hangup()
```

Reload dialplan (`dialplan reload` trong CLI), gọi từ A vào số B. B phải tự được
trả lời qua Asterisk. Nói tiếng Việt, nghe giọng mình quay lại qua `Echo()`.
Ứng dụng này trả media về caller và thoát khi phát hiện `#`; Answer được gọi
trước theo [tài liệu Echo](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/Dialplan_Applications/Echo/).

Kiểm hai kiểu kết thúc: A bấm ngắt; Asterisk chủ động kết thúc. Có thể dùng một
dialplan riêng `Answer → Wait(10) → Hangup` để kiểm tự ngắt sau 10 giây mà không
phụ thuộc việc DTMF `#` có qua điện thoại. Đây là test transport, không booking.
Thực hiện ít nhất ba lần, B về idle sau mỗi lần và caller ID là A.

Chỉ đi tiếp khi auto-answer, audio hai chiều và auto-hangup đều đạt. Pair hoặc
ring được nhưng không có audio là lỗi Bluetooth/SCO, chưa liên quan ASR/LiveKit.
Nên giới hạn spike ban đầu trong một buổi kỹ thuật; không cam kết gate chỉ từ
việc module load thành công.

## Bước 5 — tạo trunk/rule riêng trên LiveKit

Giữ softphone baseline hiện có. Tạo trunk lab riêng cho số SIM B chuẩn E.164
với digest username/password riêng. Dùng endpoint SIP của project hiện tại.

| Trường | Giá trị |
| --- | --- |
| Trunk numbers | Số SIM B dạng +84... |
| Auth username/password | Credential riêng cho gateway, không phải số caller |
| Dispatch trunk_ids | Chỉ trunk gateway vừa tạo |
| Individual room prefix | mobile-booking- |
| Hide caller number | false |
| room_config.agents.agent_name | Trùng LIVEKIT_AGENT_NAME của worker đã đạt baseline |

Số B được dùng làm called/destination number để match trunk; số A là caller để
tra patient. Không đăng ký REGISTER vào LiveKit: Asterisk gửi INVITE tới endpoint
và trả digest challenge. Chiều Asterisk → LiveKit là SIP outbound của Asterisk,
nhưng vẫn là cuộc inbound vào bot. Không tạo participant SIP bằng API outbound
để thay cuộc gọi SIM thực tế.
[LiveKit inbound trunk](https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/),
[dispatch rule](https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/).

Trong repo, `scripts/sip_baseline.py` đã cho mẫu explicit dispatch; script hiện
provision trunk `1000` cho softphone. Chưa sửa script để provision gateway.
Worker đọc số từ `sip.phoneNumber` trong `participant.py`; đích B không được
ghi đè caller A. Nếu Bluetooth trả 0xxxxxxxxx, chuẩn hóa cùng số thật thành
+84... trước leg SIP; không tự đặt một số giả khi CLIP bị thiếu.

## Bước 6 — PJSIP từ Asterisk sang LiveKit

Mẫu lab TCP trong `/etc/asterisk/pjsip.conf`; chưa kiểm trên runtime. Thay
placeholder, giữ password chỉ ở config private trên Linux, không commit.

```ini
[lk-tcp]
type=transport
protocol=tcp
bind=0.0.0.0:5060

[lk-auth]
type=auth
auth_type=userpass
username=<GATEWAY_TRUNK_AUTH_USERNAME>
password=<GATEWAY_TRUNK_AUTH_PASSWORD>

[lk-aor]
type=aor
contact=sip:<LIVEKIT_SIP_HOST>:5060

[lk-out]
type=endpoint
transport=lk-tcp
aors=lk-aor
outbound_auth=lk-auth
disallow=all
allow=ulaw,alaw
direct_media=no
```

Không đặt `from_user` thành tên auth hoặc số B: giữ caller A và kiểm From/PAI
trong INVITE cùng `sip.phoneNumber` thực tế. Dialplan không cần registration
section. TCP là mẫu lab; nếu cần TLS/SRTP theo boundary của dự án, phải bổ sung
đúng transport/certificate/media encryption, không suy TCP đã mã hóa.
[PJSIP reference](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/Module_Configuration/res_pjsip/).

Đổi context điện thoại B từ `mobile-echo` sang `mobile-livekit`, thêm:

```ini
[mobile-livekit]
exten => s,1,NoOp(SIM to LiveKit booking)
 same => n,Set(BOT_DESTINATION=<PHONE_B_IN_E164>)
 same => n,Dial(PJSIP/${BOT_DESTINATION}@lk-out,30,g)
 same => n,Hangup()
```

Mẫu để Dial trả lời mobile leg khi SIP leg được trả lời; không Answer trước
Dial trong đường bot này. `30` là thời gian chờ trả lời SIP, không phải giới hạn
độ dài booking. `g` cho dialplan tiếp tục khi phía được gọi kết thúc, rồi Hangup
mobile leg. Trường hợp A ngắt trước phải giải phóng SIP leg. Đây là thiết kế cần
kiểm thực tế, chưa chứng minh handset hết cuộc khi RemoveParticipant trả về.
[PJSIP dialing](https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/Dialing-PJSIP-Channels/),
[Dial](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/Dialplan_Applications/Dial/).

## Bước 7 — NAT/RTP

Máy Linux ở gần B, không thể chỉ chuyển chan_mobile lên VPS xa điện thoại.
Nếu Asterisk ở LAN và LiveKit ở Cloud, kiểm địa chỉ SDP và đường UDP media.
Đăng nhập SIP thành công không chứng minh RTP hai chiều. Với NAT đơn giản,
transport thường cần local_net, external_media_address và
external_signaling_address đúng WAN; router/firewall phải cho các port RTP
đã cấu hình đi/về. Chọn dải port nhất quán trong rtp.conf và firewall.

Ví dụ bổ sung cho transport trên, chỉ áp dụng sau khi biết topology:

```ini
local_net=<LAN_CIDR>
external_media_address=<REACHABLE_WAN_IP>
external_signaling_address=<REACHABLE_WAN_IP>
```

Không copy địa chỉ LAN vào external_media_address. CGNAT/double NAT không tự
được giải quyết bằng ba dòng này. Khi đó phải xác minh một đường media có thể
đi qua NAT hoặc dùng relay/topology khác rồi tính lại chi phí; không cam kết
Cloud dùng được trên mọi Wi-Fi/hotspot. Thay transport có thể cần restart thay
vì reload tùy version.
[Asterisk NAT guide](https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/Configuring-res_pjsip-to-work-through-NAT/).

## Bước 8 — booking, hangup và lặp lại

Chạy worker từ bản đã đạt softphone, giữ speech pipeline. Chuẩn bị patient giả
gắn SIM A và đủ slot trước test. Đối chiếu từng bước với gate:

| Chặng | Dấu hiệu đạt |
| --- | --- |
| A gọi B | Dialer mặc định, cuộc di động thật, B tự nhận qua gateway |
| Bluetooth | Audio hai chiều, CLIP đúng A, không thao tác nhận/ngắt |
| SIP | INVITE đúng destination B/caller A, auth, response/SDP, call ID |
| LiveKit | Participant kind SIP, sip.phoneNumber đúng A, room và rule đúng |
| Worker | Job tự dispatch đúng agent, không dispatch tay |
| Bot | ASR tiếng Việt đúng các bước, TTS nghe được trên A, booking đầy đủ |
| Clinic | Mỗi cuộc đúng một record BOOKED mới, có trace HTTP |
| Bot kết thúc | RemoveParticipant → SIP BYE → Asterisk kết thúc mobile → handset hết cuộc |
| Caller kết thúc | A bấm ngắt → mobile channel đóng → SIP/room/job giải phóng |
| Repeat | Năm cuộc liên tiếp cùng code/config, không pair/restart/reset mock giữa chuỗi |

Worker hiện có local TTS drain và grace 2000ms. Chưa biết tổng trễ Bluetooth/
PSTN nên phải xác nhận câu cuối trên A, không coi grace hiện tại chắc chắn đủ.
Năm cuộc tạo đúng năm BOOKED mới; giữ record cũ. Sau chuỗi, restart service rồi
gọi lại như một phép kiểm riêng. Restart để cứu từng cuộc không đạt repeat gate.

## Troubleshooting và điểm dừng

| Triệu chứng | Ưu tiên kiểm |
| --- | --- |
| Không có chan_mobile.so | Package/build, Add-ons, libbluetooth |
| Pair được nhưng không Connected | HFP RFCOMM port, điện thoại, quyền adapter, thiết bị audio khác |
| Connected nhưng echo câm/rè | SCO/adapter/phone; chưa sửa ASR để chữa transport |
| SIP 401 một lần rồi thành công | Digest challenge; lặp 401/403 mới kiểm auth/trunk |
| SIP trả lời nhưng audio một chiều | SDP/WAN/NAT/firewall/codec, Bluetooth echo baseline |
| sip.phoneNumber sai | CLIP, CALLERID, From/PAI, from_user override |
| Bot xong mà A vẫn còn cuộc | BYE, Dial continuation, chan_mobile AT+CHUP, phone HFP |
| Lần sau B vẫn Busy | Cuộc trước chưa giải phóng mobile/SCO/channel; không pair lại để vượt gate |

CLI hỗ trợ chẩn đoán: `mobile show devices`, `core show channels`,
`pjsip show endpoint lk-out`, `pjsip set logger on`, `core set debug 1`.
Tắt verbose/debug sau khi đủ dữ liệu và lọc credentials/PII trước khi đưa log
vào evidence. Không bật raw audio recording mặc định.

Nếu không vượt echo/auto-hangup hoặc phải sửa driver theo điện thoại, dừng
cam kết đường này kịp gate. Đây là lựa chọn tiết kiệm tiền nhờ thiết bị sẵn,
đổi lại có thêm công việc tương thích; không phải carrier-grade production.

## Ngân sách và lịch đề xuất

| Khoản | Cách giữ trần |
| --- | --- |
| Thuê DID mới | Không cần trong mô hình SIM B |
| SIM B, điện thoại B, máy, Bluetooth | Dùng/mượn đồ có sẵn; chưa báo giá nếu phải mua |
| Linux/Asterisk | Phần mềm mã nguồn mở; còn công cài đặt/debug |
| Cước A → B | Theo gói SIM thật của người test |
| LiveKit/TTS/semantic | Dùng allowance/balance còn lại; kiểm trước, chưa xác nhận đủ |

Không hứa tổng phí dưới 200.000 nếu chưa biết đồ sẵn và balance.
08–09/10: hardware/module/echo/auto-hangup; 10–11/10: SIP/audio/dispatch;
12/10: năm booking liên tiếp nếu các bước trước đạt. Đây là lịch mục tiêu,
không phải thời gian triển khai đã đo. Privacy boundary Cloud/speech vẫn cần
phù hợp PRD hiện hành; gateway không thay đổi nơi audio được xử lý.

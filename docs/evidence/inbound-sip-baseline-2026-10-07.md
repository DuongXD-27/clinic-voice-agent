# Inbound booking: proof-of-integration, 07/10/2026

## Kết luận hiện tại

**Baseline inbound booking đã chạy hoàn chỉnh, có tự hangup; chưa nghiệm thu ba booking liên tiếp và chưa đạt gate real phone line.**
Có sáu booking SIP: bốn MicroSIP và hai Linphone → LiveKit SIP → Python agent → Core
→ HTTP Clinic Mock; mỗi cuộc có đúng một record mới BOOKED. Linphone TCP và UDP đều
đã có booking thành công với BYE/200 OK. Người dùng xác nhận giọng rõ/tự ngắt ở cuộc TCP.
Lần gọi tiếp theo trên TCP cũ không được SIP trả lời và không dispatch job; đã chuyển UDP.

Đã chuyển riêng báo hiệu Linphone sang UDP, giữ nguyên trunk/dispatch/agent/giọng và
mạng 4G iPhone. Hai cuộc âm báo ngắn có BYE/200 OK; cuộc thứ ba dispatch/API remove
pass nhưng capture kết thúc trước BYE. Một test UDP dài 75 giây tiếp theo có BYE/200 OK.
Các cuộc âm báo không gọi Vbee và không ghi lịch, không tính vào gate booking.
Worker đã trở lại booking thật. Hai cuộc UDP liên tiếp trên cùng client/worker/mock/config
đều kết nối và nhận BYE/200 OK: cuộc đầu BOOKED, cuộc sau TRANSFERRED ở xác minh tên,
không ghi lịch. Người dùng báo "Ổn rồi", sau đó cho biết đã trả lời tên fixture nhưng bot
báo chuyển nhân viên, yêu cầu tạm bỏ qua điều tra; tiếng ồn là giả thuyết chưa xác nhận.
Không coi cuộc TRANSFERRED là booking thành công hoặc bằng chứng chuyển tới nhân viên thật.
Không sửa ASR/xác minh danh tính để bỏ qua lỗi này. Ba BOOKED liên tiếp vẫn còn thiếu.

Target được chốt trong yêu cầu: **inbound booking**, không triển khai outbound PSTN.
Không nghiên cứu lại vendor. Softphone là baseline integration/fallback, không thay
volunteer trên handset qua real phone line ở §1.3.1.

## Môi trường và bằng chứng

| Thành phần | Kết quả thực chạy |
|---|---|
| Checkout | `6e706a0` + thay đổi chưa commit của task này |
| Redis | `docker compose up -d redis`; PING thành công, Redis local có mật khẩu |
| Clinic Mock | Source `C:\clinic-mock`, HTTP `127.0.0.1:8001`, `/health` 200; auth bằng key trong `.env` |
| LiveKit SIP | Project `vinmec-callbot-9lwaaomh`; trunk `ST_jDtgrynHhNbj`, dispatch `SDR_DUvhWFx4oW9k`; endpoint do người dùng lấy từ dashboard: `sip:23ha7vf54qd.sip.livekit.cloud` |
| Python worker | LiveKit Agents 1.8.3; đăng ký `vinmec-inbound-baseline`, region India South; worker ID ghi riêng trong từng evidence |
| Softphone | MicroSIP Lite portable 3.22.18, direct INVITE/TCP, digest auth, PCMA/PCMU; đã có booking thực qua SIP; profile local và profile thường đều có lỗi hangup cuộc dài |
| ASR/VAD | Model ONNX ZipFormer + Silero có sẵn; worker prewarm thành công |
| Speech component | Vbee TTS thật → resample PCM 8 kHz → ZipFormer thật: `TÔI MUỐN ĐẶT LỊCH KHÁM`, không im lặng; chưa qua SIP/RTP |
| Booking qua HTTP thật | `GET /patients` 200 → `GET /slots` 200 → `POST /appointments` 201; đúng một record `BOOKED` |
| Regression | **67 passed**; Ruff lint và format đều pass |
| Repeatability mô phỏng | Ba cuộc liên tiếp qua CallBridge + Core thật trên **cùng** `FakeClinicAPI.mentor_mock()`, không reset; mỗi call thêm đúng một record `BOOKED` |

Bằng chứng booking HTTP: [core-http-booking.json](../../result/07-10-2026/sip-baseline/core-http-booking.json).
Call `core-booking-db5936c6373049e5988caa1533fc630b`, appointment `apt_c29f12722e8f`.
Lệnh smoke dùng `--restore`: snapshot Clinic Mock được phục hồi sau khi ghi bằng chứng,
nên record smoke này không còn trong mock đang chờ cuộc gọi live. Không reset Redis chung.

Ba cuộc trong regression dùng STT/TTS và room **giả**; không phải bằng chứng SIP/RTP live.
Core smoke dùng transcript, không qua speech. Engine semantic fallback tắt cho test có
kịch bản cố định; không kết luận về xử lý lời nói tự do hoặc chất lượng provider từ test đó.

Log runtime local (không commit): `temp/sip-baseline-20261007/worker-restored.log`,
`clinic-final.log`, `clinic-final-error.log` và `microsip/MicroSIP_log.txt`.
Credential được đặt trong `.env`, file này bị Git ignore; không ghi secret vào evidence.

OpenAI TTS ban đầu trả **403**, project của key không có quyền dùng model `tts-1`:
[speech-component.json](../../result/07-10-2026/sip-baseline/speech-component.json).
Đã gỡ blocker này bằng credential Vbee hiện có, kiểm chứng TTS/ASR thành công rồi đặt
`TTS_PROVIDER=vbee` trong `.env` và khởi động lại baseline worker. Không cần cấp key mới
cho baseline. Evidence: [vbee-speech-component.json](../../result/07-10-2026/sip-baseline/vbee-speech-component.json).
Worker booking thật và worker âm báo được chuyển bằng script restart, không chạy
đồng thời cùng agent name. Worker booking hiện tại `AW_inv8gvgGLV8Y` đăng ký 17:08:15
+07, launcher 28992, log `worker-booking-restored.log`; không còn worker âm báo.
Baseline vẫn dùng 4G iPhone và Linphone UDP; booking và hangup đã kiểm chứng, còn thiếu
ba BOOKED liên tiếp. Không bắt buộc Wi-Fi router, LAN hoặc IP tĩnh cho baseline này.

## Các lỗ hổng tích hợp đã sửa

1. Worker đọc `sip.phoneNumber` cho participant có kind SIP. Không nhầm
   `sip.trunkPhoneNumber` (số bị gọi) thành caller ID; không dùng web attribute làm fallback
   khi caller ID SIP bị thiếu/ẩn. Core tiếp tục chuẩn hóa `+84` → `0`, rồi xác minh tên/DOB.
2. Bridge bắt `participant_disconnected` đúng caller để kết thúc input/timer;
   observer rời phòng không kết thúc cuộc gọi.
3. Sau lời cuối đã playout, bridge gọi callback `RemoveParticipant` đúng SIP caller
   **trước** khi dọn input/audio. Cuộc gọi booking đầu để lại đường SIP mở sau lời xác nhận;
   sửa thứ tự kết hợp cấu hình client đã được kiểm chứng trên booking Linphone TCP/UDP.
   Không quy toàn bộ lỗi client cũ cho thứ tự callback. Worker kết thúc SDK
   job bằng `ctx.shutdown` sau cleanup. Log mới xác nhận callback/RemoveParticipant riêng.
   Worker rời phòng đơn thuần không bảo đảm ngắt đường SIP.
   Lỗi API hangup được báo thành job error, không coi là đã hangup thành công.
4. Local `.env` đã có LiveKit credentials và agent name riêng. Redis URL được bổ sung
   mật khẩu của Compose; `ZIPFORMER_JOINER_PATH` trỏ đúng file `joiner.int8.onnx` đã có.
   TTS dùng Vbee đã kiểm chứng thay OpenAI `tts-1` bị 403.

Tham chiếu API đã kiểm tra:
[SIP participant](https://docs.livekit.io/reference/telephony/sip-participant/),
[inbound trunk](https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/),
[dispatch rule](https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/),
[participant management](https://docs.livekit.io/reference/python/livekit/api/room_service.html).

## Blocker hiện tại và can thiệp của người dùng

- **Lỗi gọi lại TCP:** bản ghi cho thấy server ACK dữ liệu INVITE nhưng không có SIP
  response/job. Chuyển báo hiệu Linphone sang UDP đã kiểm chứng hai cuộc booking-worker
  liên tiếp nhận cuộc gọi và BYE/200 OK. Chưa xác định lỗi TCP nằm ở implementation nào.
- **Gate lặp booking:** còn cần ba cuộc BOOKED liên tiếp, giữ nguyên worker/client/mock.
  Cuộc UDP thứ hai không hiểu thông tin ở bước identity; điều tra đang được tạm bỏ qua
  theo yêu cầu người dùng. Không tự kết luận nguyên nhân do ồn và không bỏ xác minh tên/DOB.
- **Gate PSTN:** cần Vietnam DID được kích hoạt và cấu hình provider → LiveKit; cần người
  dùng xử lý account/hồ sơ/provider và volunteer trên handset. Trunk/dispatch softphone
  hiện tại đã có, không cần tạo lại. Danh sách chi tiết nằm cuối báo cáo.
- Mock giữ nguyên các record qua snapshot trước khi thêm slot: 6 record/5 BOOKED;
  sau cuộc UDP đầu là 7 record/6 BOOKED. Cuộc thứ hai không thay đổi record. Source
  `C:\clinic-mock` không sửa; không reset/chỉnh mock giữa hai cuộc UDP thật.

### Bằng chứng UDP booking thật, 17:12–17:15 +07

Worker `AW_inv8gvgGLV8Y`, Linphone 5.3.4 UDP, cùng mạng 4G iPhone:

| Cuộc | Job | Kết quả | Mock mới | Hangup tại client |
|---|---|---|---|---|
| 17:12–17:13 | `AJ_jtxqzrN34zgH` | BOOKED, sáu lượt; một lần chọn khung cần nói lại | `apt_28f4ff555c0f`; đúng một POST 201 | Server BYE, client 200 OK |
| 17:14–17:15 | `AJ_7zxtcA8r63Ba` | TRANSFERRED / NOT_UNDERSTOOD ở identity | Không POST thực tế, không record mới | Server BYE, client 200 OK |

Trace cuộc đầu có GET patients 200 → tên/DOB → GET slots 200 → offer/chọn → confirm
→ POST appointments 201 → BOOKED. Snapshot trước/sau chứng minh record cũ nguyên vẹn
và chỉ thêm một BOOKED. Capture 11740 gói, Npcap drop 0. Trạng thái TRANSFERRED ở cuộc
thứ hai chỉ là kết quả hội thoại rồi ngắt; chưa triển khai đường nối tới nhân viên thật.
Evidence: [linphone-live-booking-udp-repeat.json](../../result/07-10-2026/sip-baseline/linphone-live-booking-udp-repeat.json).

### Lịch sử chẩn đoán (các trạng thái worker/client bên dưới thuộc thời điểm ghi)

Không còn cần mở bộ cài. Linphone 5 dùng IPv4, digest MD5, không REGISTER và không
STUN/ICE. Test có âm thanh tạo tại máy xác nhận RTP hai chiều và server BYE sau hơn
75 giây: job `AJ_tRBGACDd3hka`, RX 3389/TX 3795 packet, tự đóng lúc 14:03:23 +07.
Lần tiếp theo gửi INVITE lúc 14:04:03 trên TCP cũ nhưng timeout, không dispatch job.
Evidence: [linphone-tcp-long-call.json](../../result/07-10-2026/sip-baseline/linphone-tcp-long-call.json).
Hai lần này không gọi API speech và không ghi booking. Đang kiểm tra giữ kết nối TCP;
sau khi transport ổn đã chuyển worker về booking thật; kết quả UDP hiện tại ở bảng phía trên.

**Cập nhật 14:21 +07:** log `worker-linphone5-tone.log` ghi lần chẩn đoán tiếp theo
`AJ_N6YGDcMAMaHS`, room `sip-booking-_+84912345600_jDBW77ezs9we`, bắt đầu bridge
14:20:05, kết thúc hội thoại giả 14:21:21, `RemoveParticipant` thành công 14:21:23.
Điều này chứng minh INVITE lặp lại đã tới LiveKit và worker xử lý đến bước ngắt; **chưa
chứng minh Linphone nhận BYE hoặc tự đóng**, vì log client nằm trong profile Windows khác.
Cuộc này tiếp tục chỉ dùng audio/Core giả, không tạo booking.

Ở phiên công cụ tiếp nối trước, tài khoản `codex-vscode` bị Windows từ chối đọc profile
Linphone và dừng worker thuộc `duong`; người dùng đã hỗ trợ chuyển worker.
Không khởi động thêm worker cùng tên để tránh dispatch vào hai cấu hình khác nhau.
Script chuyển an toàn nằm ở `temp/sip-baseline-20261007/restore_booking_worker.ps1`
(thư mục Git ignore). Người dùng đã chạy script trong phiên `duong`; worker booking thật
`AW_EHNZHtDhqRyv` đăng ký LiveKit lúc 14:31:10 +07, worker chẩn đoán đã dừng.

**Cuộc softphone với worker booking thật, 14:32 +07:** hướng dẫn dùng Linphone nhưng
chưa đối chiếu User-Agent; job `AJ_VNzfVsFxzcXS`, room
`sip-booking-_+84912345600_F3VSP5WF9dVr`, SIP kind 3, bridge bắt đầu 14:32:09.
Người dùng nghe chuông nhưng không nghe bot; cuộc gọi tự kết thúc. Log xác nhận Vbee
`TTSUnavailable: timeout` khi gửi request cho **lời chào đầu**, sau trần 8 giây;
bridge gọi `RemoveParticipant` thành công 14:32:24. Không có lượt ASR/Core tiếp theo.
Clinic Mock vẫn 4 record, trong đó 3 `BOOKED`, như trước cuộc gọi: **không tạo lịch**.
Log gốc được giữ ở `temp/sip-baseline-20261007/worker-booking-attempt1.log`.
Việc client tự đóng ở lần này là đường lỗi TTS, không chứng minh hangup sau booking.
Đã kiểm tra DNS, TCP IPv4/IPv6 và TLS tới `api.vbee.vn` thành công mà không gọi API TTS;
chưa xác định được vì sao server không trả lời trong 8 giây. Người dùng yêu cầu chỉ gọi
Vbee khi thật cần, nên không chạy smoke TTS riêng. Script restart baseline tăng **một
request hiện có** từ 8 lên 15 giây timeout, không thêm retry hoặc request chẩn đoán.

**Cuộc softphone kế tiếp, 14:37–14:40 +07:** chưa đối chiếu User-Agent;
worker `AW_5KWSVYTVYcJw`, job
`AJ_4QWHJMhQ95FN`, room `sip-booking-_+84912345600_QgkJqFtG7hEQ`.
Room connect chậm khoảng 18 giây từ lúc nhận job; cuộc gọi sau đó có SIP participant
kind 3 và trao đổi được năm lượt tiếng Việt. Trace xác nhận danh tính `MATCH` ở lượt 3.
Lượt 4 và 5 ở `ASK_INTENT` đều không hiểu, Core kết thúc `TRANSFERRED` với lý do
`NOT_UNDERSTOOD`; không gọi POST booking. Clinic Mock vẫn 4 record / 3 `BOOKED`.
TTS lời chào đã phát audio đầu tiên nhưng bị timeout giữa câu (`TTS_TIMEOUT`, TTFA
5,85 giây); các lượt sau vẫn có audio. `RemoveParticipant` thành công 14:40:19;
chưa có xác nhận client nhận BYE. Cần đối chiếu người dùng đã nói gì ở `ASK_INTENT`
trước khi chỉnh ASR/hội thoại hoặc gọi lại; trace không lưu transcript để tránh PII.
Không có cuộc TTS chẩn đoán ngoài cuộc gọi live này.
Người dùng xác nhận **tự ngắt**, nghe bot báo chuyển máy, âm thanh rất rè và gián đoạn.
Vì caller chủ động ngắt, cuộc này không nghiệm thu bot tự hangup. Chưa có chỉ số loss/
jitter từ Linphone, nên chưa quy tiếng rè cho mạng người dùng. Ngoài đường mạng,
TTS lời chào bị cắt và codec G.711 8 kHz cũng là các yếu tố cần kiểm tra; G.711 thường
làm giọng thiếu độ rõ, còn tiếng rè lớn có thể do RTP/codec hoặc nguồn audio.
Script `temp/sip-baseline-20261007/summarize_linphone_call.ps1` chỉ đọc log client
trong phiên `duong` và trích số đo RTP, không gọi Vbee hoặc LiveKit API. Linphone
portable không có log ở các vị trí hồ sơ đã quét, nên chưa lấy được loss/jitter.

**Cuộc âm báo không dùng TTS, 14:49–14:50 +07:** worker chẩn đoán
`AW_bfjYPn2kYnEU`, job `AJ_3ZpBMZaM6xtB`, room
`sip-booking-_+84912345600_CycxWQUScboL`. Worker nhận job 14:49:52, bridge vào
room 14:50:19 (chậm khoảng 27 giây), phát âm 440 Hz cố định 20 giây được tạo
tại máy, rồi `RemoveParticipant` thành công 14:50:42. Không gọi Vbee, không ghi lịch.
Người dùng báo đoạn đầu âm báo bình thường, đoạn sau đổi chất âm và rè; cuộc gọi có
ngắt. Điều này loại trừ Vbee là **nguyên nhân duy nhất** của tiếng rè nhưng chưa tách
được RTP/network, codec/LiveKit và thiết bị phát của Linphone. Không có log client để
xác nhận chiều BYE. Âm báo có biên độ thấp (300/32767, khoảng -41 dBFS) và hết sau
20 giây, nên cơ chế xử lý âm thanh của client hoặc chuyển sang im lặng cuối test cũng
có thể làm đoạn cuối nghe khác; đây **không phải** phép đo loss/jitter chuẩn.
Theo [hướng dẫn LiveKit](https://docs.livekit.io/reference/telephony/troubleshooting/),
cần loss/jitter hoặc PCAP để quy lỗi cho RTP; [G.711 8 kHz](https://docs.livekit.io/telephony/features/hd-voice/)
chỉ giải thích giới hạn độ rõ, không đủ để quy tiếng rè.
PCAP LiveKit của cuộc này đã được tải và phân tích bằng TShark 4.4.7:
[tóm tắt PCAP](../../result/07-10-2026/sip-baseline/tone-pcap-summary.json).
SDP chọn PCMU/8000 và sáu gói RTP quan sát được đều có payload type 0 khớp SDP;
BYE có phản hồi 200 OK. **PCAP chỉ có sáu gói RTP đầu tiên (khoảng 0,12 giây)**,
mặc dù cuộc kéo dài 52,5 giây. Mẫu 0% loss / 0,033 ms jitter này không bao trùm
đoạn âm báo về sau bị rè, nên không dùng để kết luận mạng ổn hay lỗi.
Nếu Windows hiện yêu cầu quyền microphone/firewall, người dùng xử lý hộp thoại đó.

**Bản ghi RTP đầy đủ tại máy, cuộc âm báo 15:03 +07:** job `AJ_S8JKgUqxcFqb`,
room `sip-booking-_+84912345600_wiVAneVEKPQv`, worker `AW_xn5nUfTWGD9p`.
PCAP local bắt trên Wi-Fi, quan sát media 25,7 giây. TShark cần decode UDP port 4010
thành RTP vì capture không có SDP; bỏ qua bước này sẽ hiển thị danh sách RTP rỗng.

| Chiều | Gói quan sát | Thiếu theo sequence | Jitter mean/max | Khoảng giãn gói lớn nhất |
|---|---:|---:|---:|---:|
| Bot → softphone | 1192 | 96/1288 (7,45%) | 10,314/35,074 ms | 165,533 ms |
| Softphone → server tại điểm bắt | 1287 | 0/1287 | 3,283/3,479 ms | 23,595 ms |

Payload cả hai chiều là PCMU/8000. Audio nhận được có tone chính khoảng 439,78 Hz,
peak PCM16 5372 và không clipping. Khoảng thiếu sequence tương đương 1,92 giây audio
20 ms/gói, phân bố trong cả các đoạn đầu và sau; đây không phải chỉ mất một gói cuối.
Số liệu phù hợp với phản hồi người dùng: âm báo đầu bình thường, sau rè/đứt.
Không suy ra chiều upload đã đến server đầy đủ từ bản ghi ở máy gửi. Cũng chưa tách được
server không phát gói và đường Internet/Wi-Fi; chưa quy riêng cho hotspot, codec hoặc loa.
RTCP do softphone gửi cũng báo cumulative loss 92 gói ở report cuối (highest sequence
1283), nên thiếu gói không chỉ được suy ra từ capture. Report cuối chưa bao trùm toàn bộ
gói RTP cuối cuộc. Việc không dùng Vbee loại trừ Vbee là nguyên nhân duy nhất.
Evidence: [tone-local-rtp-summary.json](../../result/07-10-2026/sip-baseline/tone-local-rtp-summary.json).
PCAP và payload gốc ở `temp`, không đưa vào Git. Cần đối chứng trên một mạng khác,
vẫn dùng âm báo 20 giây và capture đầy đủ, trước khi gọi booking thật.

**Sửa nhãn client:** PCAP Cloud cuộc âm báo 14:50 ghi User-Agent `MicroSIP/3.22.18`.
Hướng dẫn trước đó yêu cầu Linphone nhưng chưa xác minh client thật; không được dùng
nhãn Linphone để kết luận các cuộc âm báo đó. Số liệu RTP tại máy vẫn là dữ liệu nhận
của softphone; bản ghi 15:03 không có SIP nên không tự chứng minh tên ứng dụng.

**Booking thật 15:48–15:49 trên 4G iPhone:** User-Agent trong capture chứng minh vẫn
là MicroSIP, job `AJ_2nbCjhUqi9G8`, room `sip-booking-_+84912345600_cSXbVS5syWME`.
Đủ năm lượt: xác minh tên/DOB, intent đặt lịch, chọn slot, confirm. Một POST 201,
record mới `apt_51b18b9c04f1` BOOKED (08/10 13:00–13:30 +07); mock tăng 4 → 5 record,
3 → 4 BOOKED, không reset. Lời cuối playout xong 15:49:18, API remove thành công
15:49:19; người dùng báo không tự ngắt. TCP ACK ở relative 9,431 s, client gửi FIN
42,432 s: đóng signaling sau đúng 33 s, không nhận BYE. Capture báo zero drops.
Evidence: [live-booking-4g-microsip.json](../../result/07-10-2026/sip-baseline/live-booking-4g-microsip.json).
Đã đóng hẳn MicroSIP của demo và đưa đúng cửa sổ Linphone 5 ra trước; đang chờ booking
thật bằng Linphone, giữ nguyên mạng 4G. Mạng router/IP tĩnh không phải điều kiện bắt buộc.

**Booking Linphone thật 16:42–16:43 +07 và lần gọi lại bị kẹt TCP:** job
`AJ_WzVaVs6rHSYT`, room `sip-booking-_+84912345600_27uXsVvjXz9F`, worker
`AW_FcxZM3XwKptz`. INVITE xác minh User-Agent Linphone 5.3.4/SDK 5.4.102.
Một POST 201 tạo `apt_a6f9d2442e53` BOOKED (08/10 14:00–14:30 +07), mock 6 record/
5 BOOKED. Người dùng xác nhận giọng rõ và tự ngắt; capture có server BYE ở relative
74,842 s và client trả 200 OK ở 76,106 s. RTP chiều nhận thiếu 16/3143 gói (0,51%).
Lần hai gửi INVITE trên cùng TCP stream ở 86,185 s; server TCP ACK ở 86,300 s nhưng
không trả SIP 100/180/200, không có job mới và không POST. Đây là lỗi đường signaling
khi tái dùng TCP sau BYE; không quy cho Vbee hoặc Core. Chưa xác định riêng implementation
client/server nào gây kẹt. Evidence:
[linphone-live-booking-tcp-repeat.json](../../result/07-10-2026/sip-baseline/linphone-live-booking-tcp-repeat.json).

**Cấu hình hiện tại:** Linphone direct INVITE UDP, `use_rport=1`, keepalive 15000 ms,
không REGISTER; giữ nguyên auth, codec và audio. Không đổi resource LiveKit.
Ba cuộc âm báo ngắn liên tiếp cùng worker `AW_DKhxNieBsBau`: `AJ_LPA4GrLdHAEc`,
`AJ_QC8Qi85c9cL7`, `AJ_ruwNiv6Ddm6y`. Hai cuộc đầu capture BYE/200 OK; cuộc thứ ba
log có API remove nhưng capture hết trước BYE. Cuộc dài 75 giây `AJ_UiXThgpyFdaa`,
worker `AW_J9kaZVKeWsmm`, có BYE/200 OK. Chưa tính các test này là booking repeat pass.

Mock riêng đã được giữ state qua harness snapshot: 6 record/5 BOOKED không đổi,
thêm ba slot tương lai mà không hồi sinh các slot đã tiêu thụ. Đã kiểm chứng trên
port 8002 trước khi chuyển lại port 8001; không sửa source `C:\clinic-mock`.
Không reset/chỉnh mock giữa ba cuộc nghiệm thu sắp tới. Nguồn snapshot ở `temp`, Git ignore.

Lần SIP đầu: room `sip-booking-_+84912345600_Z7paUWsxJhj5`, job `AJ_vwiPfUu47uFt`,
dispatch `AD_GugKiN2ed8Yo`, room ID `RM_CxLmwdAyXq4D`, bắt đầu 10:56:14 +07.
Trace xác nhận `/patients` 200, `ASK_NAME`, rồi Vbee `ConnectTimeout` trước audio.
Kiểm tra async cùng cấu hình: trong sandbox timeout sau 1629 ms; ngoài sandbox trả
12552 byte audio sau 1485 ms. Tuy nhiên lần gọi sau vẫn ConnectTimeout ngoài sandbox,
nên chưa xác định sandbox là nguyên nhân duy nhất. Kiểm tra với timeout 5 s connect / 8 s
tổng chờ trả 12552 byte, TTFA 678 ms. Worker hiện dùng override này trong process baseline;
không đổi YAML sản phẩm. Không coi đó là bằng chứng đạt SLA latency hoặc hết lỗi mạng.

Cuộc booking SIP thực: room `sip-booking-_+84912345600_xT9Q4CLQKSDG`,
job `AJ_EJe46Amm7omg`, SIP participant `PA_8fvS4NwpiMBY` kind `3`,
agent participant `PA_pPLSRTjTXAJg` kind `4`. Caller ID `+84912345600`,
trunk `ST_jDtgrynHhNbj`. Có một lượt chọn slot không hiểu, caller nói lại rồi hoàn thành.
`GET /patients` 200 → `GET /slots` 200 → **một** `POST /appointments` 201,
record `apt_7be453d3d624` `BOOKED`. Lời cuối TTS hoàn tất 11:01:14 +07;
caller gửi BYE 11:01:34 +07, nhận 200 OK. Người dùng xác nhận nghe lời đặt lịch và tự ngắt.
Evidence: [live-sip-booking-attempt-2.json](../../result/07-10-2026/sip-baseline/live-sip-booking-attempt-2.json).
Không reset mock sau cuộc gọi này. Bản sửa hangup hiện chạy trong `worker-hangup.log`
và `worker-hangup-error.log`; chưa kết luận sửa thành công trên SIP chỉ từ regression.

Lần booking tiếp theo (job `AJ_Ub5MsjRJWvAq`, room
`sip-booking-_+84912345600_GV2nfgj2qnby`) lại đạt `BOOKED` sau năm lượt, nhưng chưa tự
ngắt: TTS cuối xong 11:07:43 +07, caller gửi BYE 11:08:30 +07. Người dùng xác nhận lỗi.
Hai cuộc chẩn đoán riêng đã kiểm chứng callback và API remove trên SIP thực:
`AJ_kkM8676rSorN` (ended ngay opening) nhận BYE 11:12:29 +07;
`AJ_iRTeHWTg2jHz` (một lượt input/Core giả, tracing bật) nhận BYE 11:14:33 +07.
Hai cuộc này **không tạo booking và không tính** vào acceptance booking/ASR/lặp lại.
Worker booking thật đã khôi phục, log hiện tại `worker-ready.log` và `worker-ready-error.log`.

Cuộc booking thứ ba: `AJ_jbfLY6z4NVF5`, room
`sip-booking-_+84912345600_kj6shCwLuv9c`, SIP participant `PA_MRX3qU8r8eo7`.
Record `apt_ba50b2525dce` `BOOKED`, 08/10/2026 12:00–12:30 +07, đúng một POST 201.
Log worker đã xác nhận callback và API remove hoàn tất 11:18:28.699 +07, nhưng MicroSIP
không nhận BYE. Log client ghi TCP transport đã bị idle timer hủy từ 11:17:01.035 +07.
Vì vậy thành công API remove không đủ để nghiệm thu handset/softphone đã ngắt.
Evidence: [live-sip-booking-tcp-hangup-failure.json](../../result/07-10-2026/sip-baseline/live-sip-booking-tcp-hangup-failure.json).
Thử UDP/STUN cũng chưa nhận BYE; Via cho thấy STUN port khác received rport tại LiveKit.
Profile TCP thông thường (Account1, không REGISTER) cũng thất bại trong test 75 giây:
job `AJ_Zu9xBrHvoG8x`, room `sip-booking-_+84912345600_HuaxLcE8wsSb`;
ACK lúc 11:33:03.450, TCP bị idle timer hủy lúc 11:33:36.451;
callback remove lúc 11:34:18.270, API thành công 11:34:19.237, không nhận BYE.
Input/Core/TTS giả, silence timer tắt; không tạo appointment, không gọi API speech,
không tính test transport này là booking/ASR/TTS acceptance. Đây là bằng chứng mạnh
về vấn đề signaling của client, chưa loại trừ toàn bộ ảnh hưởng mạng/NAT.
Evidence: [sip-transport-long-call-failure.json](../../result/07-10-2026/sip-baseline/sip-transport-long-call-failure.json).
Sau test MicroSIP, worker booking từng được khôi phục: `AW_FfmxUVz79y9Z`, PID 21948,
log `worker-restored.log`; silence timeout trở lại 8000 ms.
Linphone 6.2.3 đã tải từ [nguồn chính thức](https://download.linphone.org/releases/windows/app/),
chữ ký Authenticode `Valid`, signer Belledonne Communications. Người dùng đã cho phép
cài/chạy; cài đặt hoàn tất tại `C:\Program Files\Linphone`, app đã mở màn Welcome.
App từ bộ cài chạy ở integrity cao hơn công cụ, input không tác động và Stop-Process
trả Access denied. Người dùng đã thoát hẳn PID 24464; app được mở lại bằng quyền thường
(PID 23784), profile direct SIP đã nạp. Bản 6.2.3 báo `Call could not be created`,
không phát INVITE: source đúng tag hard-code chờ `RegistrationState::Ok`.
Tham chiếu [ToolModel 6.2.3](https://github.com/BelledonneCommunications/linphone-desktop/blob/6.2.3/Linphone/model/tool/ToolModel.cpp).
Bản 5.3.4 đọc `ui.call_wait_registration=0`, nhánh gọi cho phép không REGISTER:
[CallsListModel 5.3.4](https://github.com/BelledonneCommunications/linphone-desktop/blob/5.3.4/linphone-app/src/components/calls/CallsListModel.cpp).
Bản 5 tải từ cùng nguồn chính thức, chữ ký Valid cùng publisher; đã giải nén vào
`temp/sip-baseline-20261007/linphone5`, chạy executable trong `bin` mà không cài đè bản 6.
Linphone 5 đã phát INVITE, nhận RTP và BYE ở test transport 75 giây. Hai cuộc với worker
booking thật sau đó gặp timeout TTS/không hiểu intent, không thêm record BOOKED.
Chưa kết luận client mới khắc phục hangup sau booking thành công.
Trunk/dispatch không cần tạo lại.

Âm thanh: người dùng mô tả giọng liền mạch nhưng chất lượng thấp. Codec được chọn là
PCMU 8 kHz, nguồn Vbee PCM 8 kHz. Một call có RX loss 1,1%, nhưng chưa đủ bằng chứng
để quy chất lượng thấp cho mất gói. Không kết luận lỗi Bluetooth hay PCM clipping.
Có thể kiểm tra G.722/wideband cho softphone sau khi ổn định hangup; cần nguồn TTS
wideband tương ứng, và vẫn phải kiểm tra chất lượng PSTN độc lập.
[LiveKit HD voice](https://docs.livekit.io/telephony/features/hd-voice/),
[codec negotiation](https://docs.livekit.io/reference/telephony/codecs-negotiation/).

## Runbook baseline

PowerShell tại gốc repo:

```powershell
docker compose up -d redis
C:\clinic-mock\.venv\Scripts\python.exe scripts/run_clinic_baseline.py --clinic-source C:\clinic-mock
# Trunk/dispatch đã provision. Không chạy lại để kiểm tra thường xuyên.
# Khi cần tái dựng: .venv\Scripts\python.exe scripts/sip_baseline.py provision
```

Lệnh Clinic Mock trên là khởi tạo fixture mới. Muốn giữ state khi restart, tạo snapshot
harness **mới nhất** trước khi dừng mock rồi thêm `--snapshot-file <file-snapshot-mới>`
và `--future-slot-count 9`; không dùng snapshot cũ sau một booking, vì sẽ mất record mới.
Không khởi động thêm mock trên port đang dùng hoặc reset mock trong chuỗi nghiệm thu.

Provision tạo trunk `vinmec-softphone-baseline`: called number `1000`, digest username
`vinmec-baseline`; password ngẫu nhiên ở `.env` (`SIP_BASELINE_PASSWORD`). Dispatch
`vinmec-inbound-booking-baseline` chỉ áp dụng cho trunk đó, tạo room riêng mỗi cuộc
`sip-booking-*`, giữ caller ID, dispatch đúng `LIVEKIT_AGENT_NAME`.
Script dùng SDK có sẵn, không cần cài CLI `lk`; chạy lại tái dùng resource cùng tên.

Worker booking thật (Clinic Mock HTTP tại `localhost:8001` phải đang chạy):

```powershell
$env:CLINIC_BACKEND='mock'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:NAME_FALLBACK_PROVIDER='none'
$env:SEMANTIC_FALLBACK_ENABLED='false'
$env:LANGFUSE_EXPORT_ENABLED='false'
$env:TRACE_ENABLED='true'
$env:TRACE_JSONL_DIR='temp/sip-baseline-20261007/traces'
$env:VBEE_CONNECT_TIMEOUT_S='5'
$env:VBEE_TIMEOUT_S='15'
$env:LIVEKIT_SILENCE_TIMEOUT_MS='8000'
.venv\Scripts\python.exe -m callbot.transports.livekit.worker start
```

Chỉ chạy lệnh trên sau khi dừng worker âm báo. Script local chuyển mode có sẵn:
`powershell -File temp/sip-baseline-20261007/restore_booking_worker.ps1 -Restart`.
Chờ `registered worker` rồi mới gọi. Không thay agent name của dispatch riêng lẻ.

MicroSIP portable tại `temp/sip-baseline-20261007/microsip/MicroSIP.exe` dùng Account1
(**direct SIP INVITE với digest authentication**, không REGISTER). Cấu hình trong INI local:
server trống; domain `23ha7vf54qd.sip.livekit.cloud`; username `+84912345600` (From của
fixture); authID `vinmec-baseline`; password lấy từ `SIP_BASELINE_PASSWORD` trong `.env`;
proxy bằng domain; transport TCP; codec PCMA/PCMU. Không ghi password vào báo cáo.
Gọi `sip:1000@23ha7vf54qd.sip.livekit.cloud`. Cấu hình đã được ứng dụng nạp;
digest/media và booking đã kiểm chứng; hangup cuộc dài vẫn thất bại với profile này.

Client hiện dùng để xử lý media là Linphone 5.3.4:
`C:\callbot-vinmec\temp\sip-baseline-20261007\linphone5\bin\linphone.exe`.
Địa chỉ gọi giữ nguyên như trên. Profile direct INVITE không REGISTER, IPv4, UDP,
digest auth, không STUN/ICE. Không mở cùng lúc Linphone 6 vì hai bản dùng chung profile.
Worker đã trở lại mode booking; không coi các cuộc âm báo là nghiệm thu booking.

Hội thoại bằng fixture giả của contract, chờ bot hỏi xong mỗi lượt:

```text
Nguyễn Văn A
14 tháng 3 năm 1978
Tôi muốn đặt lịch khám
Khung 1
Đồng ý đặt lịch
```

Kiểm tra lower layer có thể chạy độc lập, chỉ với mock test riêng:

```powershell
.venv\Scripts\python.exe scripts/inbound_booking_smoke.py --restore --output temp/core-booking-proof.json
.venv\Scripts\python.exe -m pytest tests/transports/livekit tests/engine/test_inbound_booking_flow.py tests/engine/tools/test_booking_write.py -q
```

## Acceptance checklist tuần 6

| Gate | Evidence bắt buộc | Hiện tại |
|---|---|---|
| Softphone baseline | SIP INVITE được nhận, caller có kind SIP | Pass Linphone UDP booking hoàn chỉnh + auto hangup; cuộc gọi lại cũng được nhận |
| Auto dispatch | Room + SIP participant ID + job/worker ID đúng tên | Pass, IDs lưu trong evidence cuộc booking |
| Nghe tiếng Việt | ASR và core hiểu các lượt caller qua RTP thật | Pass một call, một lượt chọn slot cần nói lại |
| Nghe TTS | Caller nghe đủ lời chào, offer, readback, lời kết | Người dùng nghe lời xác nhận booking; các lượt hội thoại/TTS có trace |
| Booking | Trace tra patient, tên/DOB, GET slots, chọn, confirm, POST; đúng một BOOKED mới/call | Pass sáu booking SIP; mỗi call một POST 201/BOOKED, đã đổi worker/config giữa các lần |
| Hangup | Lời cuối phát hết; SIP BYE/call đóng; caller hangup sớm giải phóng job | Linphone booking TCP/UDP pass, cuộc UDP TRANSFERRED cũng BYE/200 OK; path caller disconnect có regression |
| Chất lượng media | Audio nghe rõ liên tục; đối chiếu loss/jitter tại softphone | Linphone booking giọng rõ theo người dùng, loss 0,51%; không bảo đảm mọi cuộc 4G |
| Lặp lại | Ít nhất ba cuộc live liên tiếp, không sửa config/reset mock giữa các call, không ghi trùng | Chưa đạt: chuỗi UDP hiện có một BOOKED rồi một TRANSFERRED, không có ba BOOKED |
| Real phone line §1.3.1 | Volunteer trên handset gọi Vietnam DID qua PSTN | Chưa có DID/provider path |

Khi chạy live: lưu call ID, room, SIP participant, job ID, thời điểm, record BOOKED mới,
số POST /appointments, kết quả hai chiều/hangup cho **từng cuộc**. Quan sát qua API/trace
và harness Clinic Mock; không dùng chỉ outcome ở log để suy ra đã ghi đúng record.

## Chính xác còn thiếu để thay softphone bằng PSTN DID

1. Một Vietnam DID đã kích hoạt nhận inbound, hồ sơ/account và ngân sách được người dùng
   xử lý với provider; không mua số tự động trong task này.
2. Cấu hình provider gửi INVITE tới **SIP URI LiveKit đã kiểm chứng**, E.164 destination
   khớp `numbers` của trunk. SIP From/caller ID phải là **số volunteer**, không phải DID.
   Mock test cần có hồ sơ giả ánh xạ số volunteer, vẫn xác minh tên/DOB như Core hiện tại.
3. Tạo inbound trunk **riêng cho provider** với đúng DID và cơ chế auth/IP allow-list của
   provider. Dispatch cùng agent name và individual room; giữ trunk softphone làm fallback.
4. Kiểm chứng codec G.711, RTP/NAT/firewall, DTMF nếu dùng, TTS playout và BYE trên đường
   carrier thực. Không suy ra chất lượng handset từ một cuộc softphone.
5. Nếu chọn Stringee SIP Phone: cần bridge REGISTER (Asterisk/FreeSWITCH), forwarding
   tới LiveKit, bảo toàn caller ID, codec và BYE hai phía. Chưa triển khai bridge trong task này.
   Nếu provider hỗ trợ SIP origination trực tiếp thì không thêm bridge.
6. Chuẩn bị slot còn trong tương lai ở ngày demo và đủ ba booking liên tiếp trên mock chung;
   lưu evidence handset để qua §1.3.1. Chuẩn bị backup SIP softphone đã test.

Primary là provider path đầu tiên vượt checklist handset. Provider còn lại chỉ là nhánh
dự phòng khi cần; softphone giữ vai trò debug/integration, không tính là gate PSTN.

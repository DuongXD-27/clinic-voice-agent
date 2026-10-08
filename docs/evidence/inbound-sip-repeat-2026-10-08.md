# Kiểm tra ba booking live liên tiếp, 08/10/2026

## Trạng thái

**Chưa đạt ba BOOKED liên tiếp. Phiên UDP đầu thiếu downlink; sau khi TLS khôi phục
âm thanh, cuộc booking đầu phiên TLS chuyển nhân viên ở bước tên.** Hai cuộc tiếp theo
chưa chạy. Không tính các cuộc
âm báo chẩn đoán là booking hoặc thay thế kiểm tra giọng nói live.

Phiên này chạy code PR #103, commit `69688a9`, đã rebase main. Bằng chứng live ngày 07/10
thuộc base cũ và vẫn có giá trị trong phạm vi đã ghi; chưa suy ra độ ổn định giữa các mạng.

## Chuẩn bị và cuộc đầu

Worker/mock không còn chạy khi bắt đầu phiên; đã khởi chạy Redis, Clinic Mock riêng và
Linphone 5.3.4 UDP. Mock khởi tạo trước phiên có một SCHEDULED có sẵn, không có BOOKED,
và mười slot tương lai của clinic fixture. Không phục hồi lịch cũ từ snapshot cũ hoặc
reset dữ liệu giữa các cuộc thử. Kết quả ngày 07/10 được giữ trong evidence riêng.

| Cuộc | Giờ Việt Nam | Kết quả |
|---|---|---|
| 1 | 10:55:13–10:55:42 | Agent nhận cuộc, tra patient 200, TTS tạo lời chào; người dùng không nghe và chủ động ngắt. Không ghi lịch. |
| 2 | Chưa chạy | Đang chờ xác định đường âm thanh. |
| 3 | Chưa chạy | Đang chờ xác định đường âm thanh. |

Worker `AW_kagA5jNWAVsY`, job `AJ_pJLuEjYbJ8gg`, room ID `RM_zgThewQgZ4XE`.
Trace lời chào TTS có status OK, 88522 byte PCM 8 kHz, khoảng 5,53 giây audio, TTFA
khoảng 856 ms. Lời nhắc sau im lặng cũng tạo thành công. Không có POST thực tế; số
lịch trước/sau đều là một, dữ liệu cũ không đổi.

Capture Wi-Fi quan sát 1093 gói RTP gửi lên, không có UDP từ media server đã thương lượng
trở lại máy. Codec PCMU/8000. Caller gửi BYE, server trả 200 OK; chưa chứng minh bot tự
ngắt trong cuộc này. Đây là bằng chứng thiếu downlink tại máy, chưa xác định nơi làm mất RTP.

## Chẩn đoán tiếp theo

Máy đang dùng mạng router khác subnet của phép thử iPhone hotspot thành công ngày 07/10.
Windows Firewall có rule Allow cho đúng executable Linphone 5 trên profile Public.
Không thay đổi firewall hoặc yêu cầu IP tĩnh.

Đã thử bật policy STUN/ICE hiện có của Linphone. SDP có địa chỉ media public sau thay đổi,
nhưng phép thử âm báo 10 giây vẫn không nhận UDP từ media server. Capture đúng Wi-Fi có
505 RTP gửi lên, không thấy downlink; capture báo 0 gói drop tại công cụ. Server BYE và
client 200 OK được ghi nhận. Input/Core/audio của phép thử này là giả; không gọi API speech,
không ghi booking. Một phép thử trước đó chọn nhầm adapter do thứ tự interface đổi sang
Bluetooth; không dùng file đó để kết luận RTP.

STUN/ICE qua UDP chưa giải quyết lỗi trên mạng hiện tại. Sau phép thử đã khôi phục
NAT references của profile baseline, giữ auth/audio và worker thật. Không reset mock.

## Đối chiếu PCAP hai phía và thử TLS

Người dùng đã đăng nhập dashboard; đã tải PCAP đúng cuộc lỗi `SCL_h8qaPetNt3Mt` và
cuộc âm báo UDP/STUN `SCL_pgWe5NxjuRM3`. PCAP phía LiveKit có lần lượt 1182 và 536
gói RTP phát ra; phía máy không nhận UDP từ media server tương ứng. Điều này xác nhận
LiveKit có phát gói, không phải chỉ tạo TTS rồi chưa xuất RTP.

Với cùng Call-ID của phép thử UDP/STUN, media port trong INVITE tại máy là 28536,
nhưng INVITE phía LiveKit là 9674. Server phát về cổng 9674. Địa chỉ/cổng SDP bị sửa
giữa hai điểm quan sát; SIP ALG hoặc thành phần trung gian là nghi vấn. Chưa xác định
router, ISP hay thành phần SIP nào thực hiện việc sửa; không quy lỗi chắc chắn cho router.

PCAP Cloud của booking UDP thành công ngày 07/10 (`SCL_UNeEZthNwyHD`) chỉ chứa 19 RTP
đầu tiên về địa chỉ private dù cuộc thực tế kéo dài 90 giây và có hội thoại. Vì vậy PCAP
Cloud không mặc nhiên là bản ghi đầy đủ: không dùng việc thiếu RTP chiều vào trong file
để kết luận server không nhận audio cả cuộc, và không tính loss end-to-end từ file này.

Đã thử SIP TLS port 5061 với xác thực chứng chỉ và hostname vẫn bật. Phép thử đầu không
đến worker vì cổng TLS của Linphone đang tắt (`sip_tls_port=0`); sau khi bật cổng TLS,
phép thử TLS/STUN đến agent và RemoveParticipant thành công, nhưng máy vẫn không nhận
RTP SIP. Gói WebRTC của Python worker trên cùng máy được phân biệt khỏi RTP Linphone.

Giữ TLS, đổi riêng NAT references về policy baseline không dùng STUN/ICE: phép thử âm
báo room `RM_y8ZrXSWPiaRx`, job `AJ_j8KG4vv4mxqg` nhận **503 RTP PCMU/8000, không
có sequence gap**, giải mã payload ra đỉnh âm **439,96 Hz**, khớp âm 440 Hz được tạo.
Capture đúng Wi-Fi có 2123 packet, 0 packet drop. Agent RemoveParticipant thành công;
PCAP Cloud `SCL_jnSi9qPLj8Z8` xác nhận server BYE tại relative 16,328039 s và phản hồi
200 tại 16,921560 s. INVITE tới server giữ media port 59997, khớp cổng local Linphone.
Các phép thử âm báo dùng input/core/audio giả, không gọi API speech và không ghi booking.
Chỉ mã hóa báo hiệu TLS trong thử nghiệm này; media vẫn RTP, chưa bật SRTP.

Đã khôi phục worker booking thật `AW_B4VkyYsyr3n3` (PID 7524). Profile hiện dùng TLS
và policy NAT baseline; cùng mạng router, không chỉnh firewall hay yêu cầu IP tĩnh.
Collector mới tách riêng phiên TLS; mock vẫn một SCHEDULED và mười slot tương lai,
không reset giữa các cuộc.

## Booking TLS và lời cuối bị cắt

Cuộc TLS thực lúc 11:35:54–11:36:23, room `RM_nLShkqRUbVKv`, job
`AJ_imtvMK3YWpZe`: caller nghe bot, trả lời tên nhưng Core chuyển TRANSFERRED ở lượt 2.
Không có BOOKED mới, dữ liệu mock cũ không đổi. Hai cuộc tiếp theo chưa chạy; đã dừng
collector phiên này thay vì tính ba lần kết nối là ba booking thành công.

Lượt 1 có ASR confidence 0,905 nhưng không trích được tên; lượt 2 confidence 0,987,
trích được tên nhưng đi nhánh tên không khớp hồ sơ. Transcript live không được giữ ở
INFO trace và nội dung session được xóa khi terminal. Giải mã offline từ RTP caller ra
“TÔI TÊN LÀ NGUYỄN ĐĂNG AN” ở cửa sổ lượt 1 và “TÔI TÊN LÀ NGUYỄN VĂN AN” ở lượt 2.
Đây là cửa sổ decode lại, không khẳng định đúng transcript ASR live. Caller báo đã nói
“Nguyễn Văn A”. Text chuẩn “Nguyễn Văn A” qua extractor/verifier vẫn MATCH; chưa đổi
fixture, chưa thêm fuzzy matching hoặc tự sửa “An” thành “A” trong xác thực danh tính.

Capture local có 1260 RTP nhận từ media SIP, không có sequence gap. Caller báo câu
chuyển máy chưa nói hết đã ngắt. TTS cuối dài 3456,125 ms, không bị barge-in hoặc lỗi
provider theo trace; local playout kết thúc 11:36:22.971202, RemoveParticipant bắt đầu
11:36:22.974299. SDK `AudioSource.wait_for_playout` theo thời gian queue local, không có
acknowledgement đã nghe hết ở softphone.

Đã bổ sung `sip_hangup_grace_ms` (mặc định 2000, giới hạn 0–5000): chờ thêm sau local
drain trước BYE của caller SIP, rồi kiểm tra lại caller còn trong room. Browser không có
callback SIP nên không thêm thời gian này. Kiểm thử đảm bảo chưa gửi removal khi đang
đợi, caller tự ngắt trong khoảng đệm không bị remove lại, lỗi removal vẫn được báo rõ.
75 kiểm thử LiveKit/transport/token và Ruff lint/format pass; chưa nghe lại lời cuối live
trên bản sửa này. Một khoảng đệm hữu hạn không chứng minh playback acknowledgement.

Worker booking thật mới `AW_t8Hk6FwNbxwV` (PID 17332) đã đăng ký với bản sửa và log
ASR riêng cho chẩn đoán local. Không bật transcript logging ở worker production trong
source. Fixture vẫn “Nguyễn Văn A”; đang chờ chọn hướng debug ASR hay dùng tên mock
đầy đủ “Nguyễn Văn An” trước khi chạy lại chuỗi booking.

## Phần cần xác minh

Đổi về hotspot chỉ là phép thử phân biệt đường mạng, không phải giải pháp nghiệm thu.
Không giả định IP 4G giữ nguyên. Đã chứng minh SDP bị sửa ở UDP và TLS với NAT baseline
khôi phục downlink ở một cuộc âm báo. Chưa khẳng định TLS giải quyết mọi NAT hoặc mạng,
chưa đạt ba booking liên tiếp hoặc kiểm chứng hết cắt lời cuối trên bản sửa mới.
Nếu đường trực tiếp không đáp ứng môi trường sử dụng, cần thiết kế media relay phù hợp,
rồi kiểm chứng cả chuỗi booking và các mạng dự kiến dùng; chưa triển khai relay ở phiên này.

Nguồn kỹ thuật:
[LiveKit SIP troubleshooting](https://docs.livekit.io/reference/telephony/troubleshooting/),
[LiveKit SIP TLS](https://docs.livekit.io/telephony/features/secure-trunking/),
[Linphone ICE và relay](https://wiki.linphone.org/xwiki/wiki/public/view/Lib/Features/Interactive%20Connectivity%20Establishment%20%28ICE%29/).

Bằng chứng có thể chia sẻ:
[booking-repeat-attempt-1-no-downlink.json](../../result/08-10-2026/sip-baseline/booking-repeat-attempt-1-no-downlink.json).
[tls-baseline-nat-tone-summary.json](../../result/08-10-2026/sip-baseline/tls-baseline-nat-tone-summary.json).
[booking-tls-attempt-1-transferred.json](../../result/08-10-2026/sip-baseline/booking-tls-attempt-1-transferred.json).
Log, profile và PCAP gốc giữ local trong `temp`, không đưa mật khẩu hoặc IP public của
người dùng vào bản tóm tắt. Chuỗi ba booking sẽ bắt đầu lại sau khi cấu hình âm thanh ổn
định; không gộp các cuộc thuộc cấu hình khác nhau để tuyên bố gate đã đạt.

Đích gọi hiện tại: `sip:1000@23ha7vf54qd.sip.livekit.cloud:5061;transport=tls`.
Profile dành riêng: `proxy_0.reg_proxy=sip:23ha7vf54qd.sip.livekit.cloud:5061;transport=tls`,
`proxy_0.reg_route=<sip:23ha7vf54qd.sip.livekit.cloud:5061;transport=tls;lr>`,
`sip.sip_tls_port=-1`, `sip.verify_server_certs=1`, `sip.verify_server_cn=1`.
Giữ policy NAT baseline không bật STUN/ICE; auth hiện có vẫn nằm ở profile local,
không copy mật khẩu vào tài liệu. Đây là cấu hình có bằng chứng tone trên máy này,
chưa phải khuyến nghị áp dụng không kiểm chứng cho mọi softphone hoặc mạng.

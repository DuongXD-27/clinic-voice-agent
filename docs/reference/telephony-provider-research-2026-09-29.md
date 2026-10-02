# Telephony cho Call-Bot VinMec: chọn nhà cung cấp và các blocker

*Cập nhật 29/09/2026. Tài liệu tổng hợp kết quả tìm hiểu nhà cung cấp điện thoại, đã đối chiếu với contract, PRD và nguồn chính thức của từng bên. Mọi con số là số tham khảo: cột "Kiểm chứng" cho biết con số nào đã đọc từ nguồn gốc, con số nào mới lấy từ đại lý hoặc bài báo.*

---

## 1. Telephony là gì

Telephony là phần đưa **cuộc gọi điện thoại thật** (di động, máy bàn) vào bot. Nhóm không tự xây phần này (contract §1.3.4) mà thuê dịch vụ và cấu hình.

| Thuật ngữ | Nghĩa |
|---|---|
| **PSTN** | Mạng điện thoại công cộng, nơi máy của người gọi đang nằm |
| **Nhà cung cấp / carrier** | Bên cho thuê số điện thoại và đường nối vào PSTN: Viettel, VNPT, FPT, Stringee, Twilio, Telnyx… |
| **SIP trunk** | "Đường ống" nối server của nhóm với nhà cung cấp qua Internet. Mua theo số kênh (số cuộc gọi đồng thời) và cước phút |
| **SIP** | Giao thức báo hiệu: ai gọi ai, đổ chuông, nhấc máy, gác máy, chuyển máy. Không mang âm thanh |
| **RTP / G.711** | Luồng mang âm thanh thật, 8 kHz, gói khoảng 20 ms. Chất lượng thấp hơn nhiều so với audio 16 kHz mà các benchmark STT dùng |
| **REGISTER vs IP-auth** | Hai cách nhà cung cấp nhận ra server của mình. REGISTER: server đăng nhập bằng username/password như một chiếc điện thoại. IP-auth (peer trunk): nhà cung cấp chỉ tin các IP tĩnh đã khai báo trước |
| **REFER** | Lệnh SIP để chuyển cuộc gọi sang người khác (chuyển máy cho nhân viên) |
| **Softphone** | Ứng dụng điện thoại chạy trên máy tính hoặc điện thoại, gọi thẳng vào hệ thống qua SIP mà không cần nhà mạng |

Luồng một cuộc gọi thật:

```
Điện thoại người gọi
   │  sóng di động / dây
   ▼
PSTN (Viettel, Vinaphone, Mobifone…)
   │
   ▼
Nhà cung cấp SIP trunk ── thuê, cấu hình, không viết code
   │  SIP (báo hiệu) + RTP G.711 8 kHz (âm thanh)
   ▼
LiveKit SIP ── nhận SIP/RTP, chuyển thành luồng audio trong LiveKit room
   │
   ▼
LiveKit worker của nhóm (src/callbot/transports/livekit/) ── adapter mỏng
   │  audio → ASR → core engine → TTS → audio
   ▼
Core engine (cùng core mà đường HTTP chấm điểm dùng)
```

Chi tiết kỹ thuật từng bước (ai gửi gì, định dạng nào) xem [phone-leg-architecture.md](phone-leg-architecture.md).

## 2. Vai trò trong project

Contract tách hai đường vào cùng một "bộ não" (§1.3, Hình 1):

- **Đường chấm điểm (HTTP):** harness gọi bot qua HTTP từng lượt, mọi tuần kể cả tuần 6. **Đường này không bao giờ đi qua điện thoại.** Điểm số không phụ thuộc telephony, và phút carrier không tính vào 15% điểm độ trễ/chi phí (Phụ lục B.2).
- **Đường demo (điện thoại):** chỉ dùng ở tuần 6 nhưng là **cổng đạt/không đạt**. Nếu không thực hiện được một cuộc gọi thật (gọi vào hoặc gọi ra, có tình nguyện viên cầm máy), nhóm bị đánh dấu *chưa hoàn thành* bất kể điểm số (§1.3.1, §5.2, PRD RK-2).

Những gì đường điện thoại phải làm được:

| Yêu cầu | Nguồn |
|---|---|
| Là adapter mỏng trên cùng core với HTTP, logic điện thoại không lấn vào logic hội thoại | Contract §1.3.2, PRD R-17 |
| Ngắt lời (barge-in) và chuyển máy cho nhân viên thật | Task P-04 ([task-breakdown.md](../task-breakdown.md)) |
| Hết chuông không ai nghe → `NO_ANSWER`; máy bận → `LINE_BUSY`, lấy từ trạng thái cuộc gọi | PRD GC-LIVE-01 |
| Xử lý audio băng hẹp 8 kHz; p95 độ trễ lượt ≤ 2 s | PRD NFR-09, NFR-02 |
| Chỉ gọi tới nhân viên chương trình hoặc đồng đội đã đồng ý, không gọi số bệnh nhân hay số trong bộ dữ liệu | Contract §1.3.3 |
| Không gửi audio thô ra ngoài hạ tầng nhóm kiểm soát "trong mọi hoàn cảnh" | PRD NFR-17 |

**Mốc thời gian.** Contract nói phần điện thoại không cần trước tuần 5, nhưng master plan của nhóm đặt **gate W4 ngày 10/10 cho phone/barge-in**, W5 16/10 là freeze, tuần 6 (19–24/10) để demo. Tính từ 29/09 còn **11 ngày** tới W4.

**Hiện trạng.** Nhóm đã có LiveKit worker và đang dùng **LiveKit Cloud** (`callbot-vinmec-2rh5o5or.livekit.cloud`). Còn thiếu: SIP trunk, số điện thoại, và cấu hình LiveKit SIP.

## 3. Tiêu chí chọn nhà cung cấp

1. **Ghép được với LiveKit SIP.** LiveKit SIP **không hỗ trợ REGISTER**, chỉ nhận trunk theo IP hoặc digest. Có hỗ trợ REFER và DTMF. Nhà cung cấp chỉ cho kết nối bằng REGISTER thì phải thêm cầu nối (Asterisk hoặc FreeSWITCH).
2. **Nhận cuộc gọi vào ổn định.** Contract khuyên demo cuộc gọi vào (kịch bản đặt lịch inbound §1.1.10) vì tránh được mọi hạn chế khi gọi ra số VN.
3. **Gọi ra +84** là điểm yếu đã biết (Phụ lục B.2).
4. **Thủ tục và thời gian kích hoạt** phải kịp 10/10.
5. **Chi phí** cho vài trăm phút test.
6. **Privacy** (NFR-17) và **pháp lý viễn thông VN** (mục 6).

## 4. Các lựa chọn

### 4.1 Nhà mạng trực tiếp (FPT, VNPT, Viettel)

- **Ghép LiveKit:** theo hướng dẫn của một đại lý, trunk của ba nhà mạng là peer trunk IP-to-IP qua UDP, cổng 5060 (Viettel 55000), không cần REGISTER nên về nguyên tắc hợp với LiveKit. *Chưa kiểm được nguồn gốc.* LiveKit không có hướng dẫn riêng cho nhà mạng VN nào, nên phải tự thử.
- **Vướng IP tĩnh:** nhà mạng cần IP cố định phía nhóm. LiveKit Cloud chỉ có dải IP tĩnh cho Canada, EU, Ấn Độ, Nhật, Mỹ; các region khác (kể cả Singapore) dùng wildcard domain. Có hai cách:
  - Ghim LiveKit Cloud vào region Nhật. Audio khi đó đi ra khỏi VN, xem NFR-17.
  - Tự host LiveKit SIP trên VPS có IP public: mở 5060/UDP cho báo hiệu và 10000–20000/UDP cho RTP. Cách này giải quyết cả IP tĩnh lẫn NFR-17, đổi lại nhóm phải vận hành thêm một thành phần.
- **Thủ tục:** cần giấy phép kinh doanh, triển khai sau khi ký hợp đồng. Chưa có con số thời gian triển khai chính thức.
- **Hợp nhất cho bàn giao production** (số nội địa, audio ở trong nước), nhưng chậm và cần pháp nhân.

### 4.2 Stringee

- **Ghép LiveKit: bắt buộc thêm cầu nối.** Đã xác nhận từ tài liệu Stringee:
  - SIP phone chỉ kết nối bằng cách **đăng ký (REGISTER) username/password** vào `v2.stringee.com:15060`. Tài liệu không nhắc tới kết nối IP-auth.
  - SCCO (kịch bản điều khiển cuộc gọi) có 7 action: `connect`, `record`, `recordMessage`, `talk`, `play`, `stream`, `input`. `stream` chỉ phát một file audio vào cuộc gọi, **không có luồng audio hai chiều qua websocket**. `connect` chỉ nhận `internal` hoặc `external`.
  - Vì LiveKit không REGISTER, cần một Asterisk hoặc FreeSWITCH đăng ký vào Stringee như một SIP phone, rồi chuyển tiếp sang LiveKit bằng trunk IP. Thêm một thành phần đúng vào phần rủi ro nhất.
- **Ưu điểm:** đăng ký nhanh, gói miễn phí đủ để test, là nhà cung cấp nội địa có số VN và tổng đài ảo.
- **Chưa rõ:** mua số cần hồ sơ gì, giá thuê số, Stringee có hỗ trợ trunk IP-auth nếu hỏi trực tiếp không (nếu có thì không cần cầu nối).

### 4.3 Telnyx (quốc tế, bán số VN)

- **Ghép LiveKit:** tốt, LiveKit có quickstart riêng cho Telnyx. Phải xin Telnyx bật REFER cho tài khoản thì mới chuyển máy được *(chưa kiểm lại)*.
- **Thủ tục số VN (đã kiểm):**
  - Cá nhân: họ tên, SĐT, hộ chiếu hoặc CCCD, hóa đơn tiện ích không quá 3 tháng.
  - Doanh nghiệp: thêm giấy đăng ký kinh doanh và LOI đã ký trong vòng 1 tháng.
  - Khoảng 72 giờ để xác minh và kích hoạt.
  - Không cần pháp nhân VN.
- **Rủi ro gọi ra:** Telnyx cảnh báo cuộc gọi mang số cùng nước với điểm đến có thể bị nhà mạng nội địa từ chối mà không báo trước *(chưa kiểm lại)*.
- Không có trong danh sách gợi ý của Phụ lục B, nhưng §1.3.4 cho phép dùng bất kỳ nhà cung cấp nào (phải giải thích lựa chọn ở buổi review tuần 6).

### 4.4 Twilio

- **Không bán số VN.** Gọi ra số VN từ số Twilio quốc tế chỉ là "best effort", không đảm bảo, và cấm gọi từ số toll-free (đã kiểm, trang voice guidelines VN của Twilio).
- Nhà mạng VN còn chủ động chặn cuộc gọi từ đầu số quốc tế có dấu hiệu lừa đảo.
- Chỉ nên dùng để thử tích hợp LiveKit, không dùng làm đường demo.

### 4.5 Softphone SIP (dự phòng)

Gọi thẳng vào LiveKit SIP bằng một softphone, không phụ thuộc nhà mạng. Contract khuyên chuẩn bị sẵn phương án này kể cả khi đường carrier chạy tốt (Phụ lục B.2).

### 4.6 So sánh nhanh

| | Gọi vào | Gọi ra +84 | Ghép LiveKit | Thủ tục / tiến độ |
|---|---|---|---|---|
| Nhà mạng VN | Tốt | Bị chặn nếu không có Voice Brandname | Tốt, cần IP tĩnh | Chậm, cần pháp nhân |
| Stringee | Tốt | Nội địa, có thể vướng Brandname (chưa rõ) | Cần cầu nối Asterisk/FreeSWITCH | Nhanh, hồ sơ mua số chưa rõ |
| Telnyx | Tốt | Không chắc | Tốt | ~72 giờ, hồ sơ cá nhân được |
| Twilio | Không có số VN | Best effort | Tốt | Nhanh |
| Softphone | Không qua PSTN | Không | Tốt | Không cần |

## 5. Chi phí

Với vài trăm phút test, ước tính tổng chi phí từ vài trăm nghìn tới vài triệu đồng kể cả phí khởi tạo. Chi phí không phải blocker chính.

| Nhà cung cấp | Hạng mục | Giá | Kiểm chứng |
|---|---|---|---|
| **Stringee** | Gói miễn phí | 0đ: 1.500 phút thoại, 4 kênh | ✅ Bảng giá chính thức |
| | Gói Chuẩn | 15.000.000đ/năm: 11.111 phút, 20 kênh (vượt: 150đ/phút) | ✅ |
| | Gói Growth | 78.000.000đ/năm: 62.500 phút, 50 kênh | ✅ |
| | Theo kênh | 5–50 kênh: 6.000.000đ/kênh/năm, không giới hạn phút | ✅ |
| | Ghi chú | Chưa gồm cước nhà mạng khi gọi ra. Giá thuê số chưa tìm được | ✅ / ❓ |
| **FPT** | Khởi tạo | 400.000đ/hợp đồng | ⚠️ Chưa kiểm lại (trang voicefpt.vn không truy cập được) |
| | Cước gọi di động | 970đ/phút | ⚠️ |
| **VNPT** | Hòa mạng / thuê bao | 250.000đ / 33.000đ mỗi tháng, cước theo lưu lượng | ⚠️ Chỉ đọc được đoạn trích |
| **Viettel** | Lắp đặt / thuê bao | 200.000đ/kênh / 20.000đ × số kênh mỗi tháng | ⚠️ Trang cũ (2020) |
| **Đại lý** (số 024/028) | Khởi tạo / thuê bao | 1.500.000đ / 400.000–500.000đ mỗi tháng, kích hoạt 1–3 ngày | ⚠️ Báo giá đại lý |
| **Telnyx** | Số local VN | Từ khoảng 35 USD/tháng | ⚠️ Chưa kiểm lại |

Trong sheet Ngân sách, dòng **COST-005 (Telephony & SIP Trunk)** vẫn đang TBD.

## 6. Pháp lý

**Nghị định 330/2026/NĐ-CP** (xử phạt trong lĩnh vực an ninh mạng và bảo vệ dữ liệu cá nhân), **hiệu lực từ 19/08/2026**:

- **Điều 38:** nhà mạng cung cấp VoIP/SIP Trunk phải *"triển khai hoặc duy trì cơ chế kỹ thuật tự động chặn toàn bộ lưu lượng SIP Trunk, VoIP"* gọi ra mạng công cộng không gắn Voice Brandname hợp lệ. Nếu không, nhà mạng bị phạt 50–70 triệu và có thể bị đình chỉ dịch vụ 1–3 tháng. Nhà mạng chịu phạt nên sẽ chặn nghiêm.
- **Điều 37 (gọi quảng cáo):** chỉ gọi trong khung 8h–17h, tối đa 1 cuộc/số/24 giờ. Tổ chức vi phạm bị phạt 60–100 triệu; gọi vào Danh sách không quảng cáo bị phạt 160–180 triệu.
- Theo các bài báo, nghị định không nhắc tới **cuộc gọi vào**. Tôi chưa đọc được văn bản gốc (file PDF trả về 404), nên phạm vi chính xác của Điều 38 (có áp dụng cho SIP cố định không?) cần hỏi thẳng nhà mạng.

**Voice Brandname (tên định danh khi gọi ra):**

- Hồ sơ gồm: giấy đăng ký kinh doanh, chứng minh thương hiệu (website hoặc nhãn hiệu), hợp đồng lao động của người quản lý tên, và giấy phép ngành nghề có điều kiện (với y tế là giấy phép hành nghề).
- Tên phải gắn với thương hiệu của đơn vị đăng ký, nên nhóm khó tự đăng ký tên "Vinmec".
- Thời gian báo 2–4 tuần, giấy chứng nhận hiệu lực 3 năm *(chưa kiểm lại)*.

**Liên quan PRD:** giả định A-6 coi cuộc gọi nhắc lịch là cuộc gọi giao dịch chứ không phải quảng cáo, và đang dẫn Nghị định 91/2020. Cách đọc này chưa được xác nhận. A-6 nên dẫn thêm NĐ 330/2026 Điều 37.

**Kết luận pháp lý:** gọi ra +84 qua SIP trunk nội địa gần như không khả thi trước 10/10 nếu nhóm không có pháp nhân đã có Voice Brandname. **Cuộc gọi vào không bị ảnh hưởng.**

## 7. Blocker

| # | Blocker | Ảnh hưởng | Cách gỡ |
|---|---|---|---|
| B1 | **Chưa có pháp nhân** đứng tên hợp đồng viễn thông | Không ký được trunk với nhà mạng, không làm được Voice Brandname | Mượn pháp nhân của chương trình AI Health Residency hoặc Vinmec. Nếu không được: dùng Stringee (+ cầu nối) hoặc Telnyx với hồ sơ cá nhân |
| B2 | **Gọi ra bị chặn** theo NĐ 330/2026 Điều 38 | Không demo được cuộc gọi ra qua trunk nội địa | Chốt demo bằng cuộc gọi vào |
| B3 | **IP tĩnh** cho trunk nhà mạng | LiveKit Cloud region hiện tại có thể không có IP tĩnh | Ghim region Nhật, hoặc tự host LiveKit SIP trên VPS |
| B4 | **Stringee chỉ cho REGISTER**, không có audio hai chiều | Phải thêm Asterisk/FreeSWITCH, thêm việc và thêm điểm lỗi | Hỏi Stringee có trunk IP-auth không. Nếu không, dành thời gian dựng cầu nối |
| B5 | **NFR-17 (privacy)**: cấm gửi audio thô ra ngoài trong mọi hoàn cảnh | LiveKit Cloud và ElevenLabs realtime ASR đang nhận audio thô; carrier bắt buộc phải chở audio | Người viết NFR-17 chốt cách hiểu: carrier là kênh truyền hay phải vào allow-list; có chấp nhận LiveKit Cloud không |
| B6 | **Thời gian**: gate W4 ngày 10/10, còn 11 ngày | Hợp đồng nhà mạng và Voice Brandname có thể không kịp | Chạy song song một đường nhanh (Stringee, Telnyx hoặc softphone) và một đường nhà mạng |
| B7 | **Ngân sách** COST-005 chưa duyệt | Chưa mua được số hoặc gói | PM duyệt mức trần |

## 8. Đề xuất

1. **Demo tuần 6 bằng cuộc gọi vào** một số 024/028 (kịch bản đặt lịch inbound §1.1.10), đúng hướng Phụ lục B.2 khuyên. Tránh được B2.
2. **Chạy hai đường song song:**
   - Đường nhanh để kịp W4: Stringee + cầu nối, hoặc Telnyx số VN (nộp hồ sơ ngay vì mất ~72 giờ).
   - Đường nhà mạng: gửi yêu cầu báo giá cho FPT, VNPT, Viettel ngay, dùng cho bàn giao production nếu có pháp nhân.
3. **Chuẩn bị softphone SIP làm dự phòng** ngay từ bây giờ, không đợi carrier.
4. **Gửi cùng một bộ câu hỏi cho mọi nhà cung cấp:**
   - Có nhận kết nối IP-auth từ LiveKit không? Có REFER không? Có G.711 8 kHz không?
   - Mã SIP trả về khi máy bận hoặc không nghe máy là gì (phục vụ GC-LIVE-01)?
   - Cuộc gọi vào có bị ảnh hưởng bởi Điều 38 không?
   - Thời gian kích hoạt? Cần giấy tờ gì để mua một số 024/028?
5. Nếu vẫn muốn thử **gọi ra +84**: test sớm (contract khuyên tuần 5, nên làm ngay), và chỉ gọi tới đồng đội đã đồng ý (§1.3.3).

## 9. Câu hỏi cần PM quyết định

1. **Pháp nhân:** nhóm có mượn được pháp nhân của chương trình hoặc Vinmec để đứng tên hợp đồng viễn thông không? Câu trả lời quyết định đường nhà mạng có khả thi hay không.
2. **Hướng demo:** chốt demo tuần 6 bằng **cuộc gọi vào** thay vì gọi ra?
3. **Đường nhanh cho W4:** chọn **Stringee + cầu nối** hay **Telnyx số VN**? Có chấp nhận nhà cung cấp ngoài danh sách gợi ý (Telnyx) không?
4. **Hạ tầng LiveKit:** tự host LiveKit SIP trên VPS (tốt cho IP tĩnh và NFR-17, thêm việc vận hành) hay ghim LiveKit Cloud sang region Nhật?
5. **Privacy:** ai chốt cách hiểu NFR-17 về carrier, LiveKit Cloud và ASR cloud? Cần chốt trước khi chọn hạ tầng.
6. **Ngân sách:** duyệt mức trần cho COST-005 (số điện thoại, gói Stringee hoặc Telnyx, VPS nếu tự host).
7. **Người phụ trách:** ai liên hệ nhà cung cấp và nộp hồ sơ? Deadline gửi câu hỏi là khi nào?

---

## Nguồn

**Nội bộ:**
- Contract: [callbot-contract-vi.md](../../../tailieu/callbot-contract-vi.md) §1.3, §1.3.3, Phụ lục B.2
- PRD v1.6 (`tailieu/PRD-CallBot-VinMec-v1_4.pdf`): R-17, NFR-02, NFR-09, NFR-17, GC-LIVE-01, GC-PRIV-05, A-6, RK-2
- Master plan (`master plan/`): gate W4 10/10; sheet Ngân sách, dòng COST-005

**Bên ngoài, đã đọc trực tiếp:**
- [LiveKit SIP: tính năng hỗ trợ](https://docs.livekit.io/sip/)
- [LiveKit: firewall và IP tĩnh](https://docs.livekit.io/deploy/admin/firewall/)
- [Telnyx: yêu cầu mua số VN](https://support.telnyx.com/en/articles/3737163-vietnam-did-requirements)
- [Twilio: voice guidelines VN](https://www.twilio.com/en-us/guidelines/vn/voice)
- [Stringee: bảng giá Call API](https://stringee.com/vi/pricing-call)
- [Stringee: SCCO](https://developer.stringee.com/docs/server/stringee-call-control-object)
- [Stringee: quản lý SIP phone](https://developer.stringee.com/docs/call-rest-api/sip-phone-management)
- [Dân trí: NĐ 330/2026 Điều 37, 38](https://dantri.com.vn/cong-nghe/goi-dien-quang-cao-ngoai-8h-17h-co-the-bi-phat-den-100-trieu-dong-20260825120034362.htm)

**Chưa kiểm lại được (chỉ dùng làm số tham khảo):**
- Giá FPT, VNPT, Viettel và báo giá đại lý
- Hướng dẫn cấu hình peer trunk của Mắt Bão
- Thời gian làm Voice Brandname
- Giá số Telnyx, cảnh báo CLI và việc phải xin bật REFER của Telnyx

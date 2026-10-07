# Đo độ trễ giọng bot: trước và sau khi chuyển Vbee sang phát theo luồng

## Tóm tắt

- Trên cuộc gọi LiveKit, sau khi khách nói xong và bot đã có câu trả lời, khách chờ tới lúc nghe tiếng bot **ngắn hơn khoảng 0,2–0,4 giây**. Trước: 885–992 ms. Sau: 553–744 ms.
- Câu càng dài càng lợi. Với câu 234 ký tự, thời gian chờ tiếng đầu giảm từ 1063 ms xuống 268 ms.
- **Câu chào đầu cuộc gọi chưa nhanh hơn.** Chưa rõ nguyên nhân, đang theo dõi tiếp.
- Đường chấm điểm HTTP không bị ảnh hưởng. Không lượt nào vượt 8 giây.
- Hai lần đo sau đều không lỗi và không phải chuyển sang ElevenLabs. Giọng phát liền mạch, không bị ngắt quãng giữa câu.

## "Trước" và "sau" là gì

Bot có hai đường nói chuyện với khách, dùng chung phần xử lý hội thoại (Engine):

- **Đường A — HTTP chấm điểm:** bộ chấm của chương trình gửi từng lượt qua HTTP. Bot trả lời bằng một file âm thanh hoàn chỉnh của cả câu.
- **Đường B — Cuộc gọi LiveKit:** cuộc gọi thời gian thực (trang demo web, sau này là điện thoại). Bot nói trực tiếp vào cuộc gọi.

Thay đổi được đo ở đây **chỉ áp dụng cho Đường B**.

### Trước (bản `9344380`, chạy trên server tới 04/10)

Bot gửi câu trả lời sang Vbee, **chờ Vbee đọc xong cả câu** rồi mới bắt đầu phát cho khách:

```text
Engine có câu trả lời ──> gửi Vbee ──> chờ Vbee đọc xong CẢ CÂU ──> bắt đầu phát ──> khách nghe
                                       (câu càng dài, chờ càng lâu)
```

### Sau (bản `97e139c`, chạy trên server từ 05/10)

Vbee gửi âm thanh về dần dần trong lúc đọc. Bot **phát ngay đoạn đầu tiên** và phát tiếp các đoạn sau khi chúng về (phát theo luồng, "streaming"):

```text
Engine có câu trả lời ──> gửi Vbee ──> đoạn âm thanh đầu về ──> phát ngay ──> khách nghe
                                       các đoạn sau về tiếp ──> phát nối tiếp
```

Cùng đợt này còn hai thay đổi nhỏ:
- Khi khách nói chen, bot huỷ được yêu cầu đang gửi tới Vbee.
- Nếu Vbee lỗi trước khi phát được gì, ElevenLabs đọc thay đúng câu đó.

**Lưu ý:** bản "sau" còn có hai PR của người khác, merge cùng lúc:
- PR #71: phần nhận dạng giọng khách và xử lý audio đầu vào.
- PR #68: thêm nhiều biến thể câu thoại.

Vì vậy thời gian nhận dạng giọng khách, thời gian Engine và độ dài câu bot cũng thay đổi, nhưng **không phải do phát theo luồng**. Tài liệu này chỉ kết luận về phần giọng bot.

## Các khoảng thời gian được đo

Mỗi lượt trên cuộc gọi LiveKit đi qua các mốc sau:

```text
khách nói xong ──(1)──> bot hiểu khách nói gì ──(2)──> bot có câu trả lời ──(3)──> khách nghe tiếng bot
└──────────────────────────────── (4) tổng thời gian khách chờ ────────────────────────────┘
```

| Tên trong bảng | Nghĩa | Ai phụ trách |
|---|---|---|
| **(1) Nhận dạng giọng (STT)** | Chờ khách im lặng đủ lâu để biết khách đã nói xong, rồi chuyển giọng khách thành chữ | Việt |
| **(2) Engine** | Từ chữ của khách ra câu trả lời của bot (luật hội thoại, gọi Clinic) | Hoàn |
| **(3) Chờ tiếng bot (TTFA)** | Từ lúc có câu trả lời tới lúc khách nghe tiếng bot đầu tiên. **Đây là phần phát theo luồng thay đổi** | Hưng |
| **(4) Tổng thời gian chờ** | Từ lúc khách nói xong tới lúc nghe tiếng bot, bằng (1) + (2) + (3). Đây là con số khách cảm nhận | — |
| **Vbee gửi tiếng đầu** | Lúc đoạn âm thanh đầu tiên của Vbee về tới server, lấy từ log đo thời gian của server. Lúc này khách **chưa** nghe | — |
| **Chờ thêm sau khi Vbee gửi tiếng đầu** | Bằng (3) trừ "Vbee gửi tiếng đầu". Bản trước: phần lớn là thời gian chờ Vbee đọc nốt câu. Bản sau: chỉ còn thời gian chuyển âm thanh tới khách | — |
| **Sinh cả câu** | Thời gian Vbee đọc xong toàn bộ câu. Đường A luôn phải chờ hết khoảng này | — |
| **Ngắt quãng** | Tổng thời gian bot phải ngừng giữa câu để chờ âm thanh về. 0 là phát liền mạch | — |

Đơn vị là mili giây (ms), 1000 ms = 1 giây. "Trung vị" là giá trị ở giữa khi xếp các lần đo từ nhanh tới chậm.

## Đã đo như thế nào

Mỗi bên (trước, sau) đo **hai lần**, đều trên server thật (EC2). Hai lần cùng phiên bản cho biết số đo tự dao động bao nhiêu:

| Tên lần đo | Phiên bản | Thời điểm (giờ VN) | Đo những phần nào | Thư mục kết quả |
|---|---|---|---|---|
| Trước-1 | trước (`9344380`) | 02/10, ~01:36 | chỉ cuộc gọi LiveKit | `result/05-10-2026/bench/thu/` |
| Trước-2 | trước (`9344380`) | 02/10, ~01:37 | cả 3 phần | `result/05-10-2026/bench/truoc/` |
| Sau-1 | sau (`97e139c`) | 05/10, ~11:02 | cả 3 phần | `result/05-10-2026/bench/sau/` |
| Sau-2 | sau (`97e139c`) | 05/10, ~11:08 | chỉ cuộc gọi LiveKit | `result/05-10-2026/bench/sau-2/` |

Ba phần đo:
1. **Đo riêng giọng bot:** không có cuộc gọi. Bot đọc 3 câu cố định (ngắn 45, vừa 113, dài 234 ký tự), mỗi câu 3 lần, đúng cách bot đọc trong cuộc gọi LiveKit.
2. **Cuộc gọi qua đường chấm điểm (Đường A):** 1 cuộc gọi, làm giống hệt bộ chấm của chương trình: gửi lượt, nhận câu trả lời, tải file âm thanh.
3. **Cuộc gọi LiveKit (Đường B):** 1 cuộc gọi thật vào bot. Phía khách là một script phát giọng khách đã ghi sẵn, nên các lần đo giống nhau: câu chào + 2 lượt, cùng lịch hẹn `apt_00427`.

Mỗi lần chỉ gọi 1 cuộc vì mỗi lần đo tốn khoảng 2.000 ký tự quota Vbee. Hai lần cùng phiên bản lệch nhau khoảng 80 ms ở các lượt và khoảng 220 ms ở câu chào. Vì vậy, chênh lệch giữa trước và sau dưới khoảng 150 ms thì chưa đủ để kết luận.

## Kết quả

### Phần 1: Đo riêng giọng bot

Mỗi câu đọc 3 lần. Số trong ô là trung vị, trong ngoặc là lần nhanh nhất – chậm nhất.

| Câu | Số ký tự | Chờ tiếng đầu — trước | Chờ tiếng đầu — sau | Sinh cả câu: trước → sau | Ngắt quãng |
|---|---|---|---|---|---|
| ngắn | 45 | 242 (185–249) | 250 (242–263) | 242 → 252 | 0 |
| vừa | 113 | 576 (355–605) | 445 (273–792) | 576 → 588 | 0 |
| dài | 234 | 1063 (1009–1122) | **268 (254–432)** | 1063 → 1010 | 0 |

- **Trước:** chờ tiếng đầu bằng đúng thời gian sinh cả câu, vì bot phải chờ hết câu.
- **Sau:** câu được chia thành 20, 51 và 101 đoạn nhỏ (ngắn, vừa, dài) và phát ngay đoạn đầu. Thời gian sinh cả câu không đổi; chỉ thời gian chờ tiếng đầu giảm.

### Phần 2: Cuộc gọi qua đường chấm điểm (Đường A)

Thời gian mỗi lượt tính như bộ chấm tính: server trả lời + tải file âm thanh. Trần cho phép là 8 giây.

| Lượt | Trước | Sau | Số ký tự câu bot (trước / sau) |
|---|---|---|---|
| mở cuộc gọi | 1511 | 1550 | 112 / 91 |
| lượt 1 | 5379 | 1254 | 110 / 110 |
| lượt 2 | 944 | 896 | 110 / 110 |

Cả hai lần: không lượt nào ≥ 8 giây, file âm thanh đúng định dạng, không lỗi.

Tách theo log của server (trung vị 3 lượt):

| | Trước | Sau | Ghi chú |
|---|---|---|---|
| Sinh cả câu | 749 | 708 | Không đổi. Đường A vẫn chờ cả câu, đúng thiết kế |
| Vbee gửi tiếng đầu | 442 | 468 | Không đổi |
| Nhận dạng giọng (STT) | 2247 | 228 | Lượt 1 trước đây mất 4353 ms. Nhiều khả năng do PR #71, không phải phần giọng bot |
| Engine | 206 | 546 | Mới có 3 lượt; không phải phần giọng bot |

### Phần 3: Cuộc gọi LiveKit (Đường B), từng lượt

| Lần đo | Lượt | (4) Tổng thời gian chờ | (1) STT | (2) Engine | **(3) Chờ tiếng bot** | Vbee gửi tiếng đầu | Chờ thêm sau khi Vbee gửi tiếng đầu | Số ký tự câu bot |
|---|---|---|---|---|---|---|---|---|
| Trước-1 | câu chào | 2055 | – | 989 | 1066 | 678 | 388 | 112 |
| Trước-1 | lượt 1 | 2327 | 1303 | 32 | 992 | 589 | 403 | 110 |
| Trước-1 | lượt 2 | 2358 | 1334 | 41 | 983 | 610 | 373 | 110 |
| Trước-2 | câu chào | 1867 | – | 1019 | 848 | 482 | 366 | 112 |
| Trước-2 | lượt 1 | 2234 | 1318 | 31 | 885 | 561 | 324 | 110 |
| Trước-2 | lượt 2 | 2303 | 1336 | 34 | 933 | 566 | 367 | 110 |
| Sau-1 | câu chào | 5347 | – | 4116 | 1232 | 1001 | 231 | 92 |
| Sau-1 | lượt 1 | 4008 | 3131 | 179 | 698 | 565 | 133 | 110 |
| Sau-1 | lượt 2 | 2068 | 1278 | 45 | 744 | 608 | 136 | 110 |
| Sau-2 | câu chào | 2193 | – | 1164 | 1029 | 895 | 134 | 112 |
| Sau-2 | lượt 1 | 2223 | 1416 | 211 | 595 | 478 | 117 | 87 |
| Sau-2 | lượt 2 | 1943 | 1361 | 29 | 553 | 417 | 136 | 87 |

Riêng câu chào:
- "Tổng thời gian chờ" tính từ lúc khách vào cuộc gọi.
- "Engine" gồm cả thời gian LiveKit giao cuộc gọi cho bot và thời gian gọi Clinic lấy lịch hẹn.

Cột "Chờ thêm sau khi Vbee gửi tiếng đầu" cho thấy rõ nhất phần mà phát theo luồng bỏ đi. Cột này không phụ thuộc Vbee nhanh hay chậm ở lần đó. Nó được tính từ hai đồng hồ khác nhau (phía khách và phía server), nên chỉ dùng để so trước với sau, không dùng làm số tuyệt đối.

## Kết luận

1. **Phát theo luồng chạy đúng trên server thật.**
   - Không lỗi.
   - Không lần nào phải chuyển sang ElevenLabs.
   - Không ngắt quãng giữa câu ở cả 3 độ dài.
2. **Câu càng dài càng lợi** (phần 1).
   - Câu dài 234 ký tự: chờ tiếng đầu 1063 → 268 ms. Lần chậm nhất của bản sau vẫn nhanh hơn lần nhanh nhất của bản trước.
   - Câu vừa: 576 → 445 ms, nhưng dao động lớn vì có một lần Vbee gửi tiếng đầu chậm (792 ms).
   - Câu ngắn: không đổi (242 → 250 ms), vì Vbee đọc xong câu ngắn gần như cùng lúc với đoạn đầu tiên.
3. **Các lượt trong cuộc gọi LiveKit nhanh hơn.**
   - Chờ tiếng bot ở 4 lượt sau là 553–744 ms; ở 4 lượt trước là 885–992 ms.
   - So riêng các lượt có câu bot cùng độ dài 110 ký tự: 698 và 744 ms (sau), so với 885–992 ms (trước).
   - Phần chờ thêm sau khi Vbee gửi tiếng đầu giảm từ 324–403 ms xuống 117–136 ms ở cả 4 lượt.
4. **Câu chào chưa nhanh hơn.** Chờ tiếng bot: trước 848 / 1066 ms, sau 1232 / 1029 ms.
   - Phát theo luồng vẫn có tác dụng ở câu chào: phần chờ thêm giảm từ 366 / 388 xuống 231 / 134 ms.
   - Nhưng ở cả hai lần sau, Vbee gửi tiếng đầu của câu chào chậm hơn: 1001 / 895 ms, trước là 482 / 678 ms. Các lượt sau câu chào thì không chậm.
   - **Chưa rõ nguyên nhân**, mới có 2 lần đo mỗi bên.
   - Có kiểm thêm việc mở kết nối tới Vbee: bản sau mở kết nối ngay lúc đọc câu chào, tốn khoảng 90–190 ms. Bản trước cũng mở kết nối mới cho mọi câu, kể cả câu chào, nên đây không phải lý do câu chào chậm hơn bản trước.
   - Việc tiếp theo: theo dõi câu chào trong log các cuộc gọi tuần 4. Nếu vẫn chậm, mở sẵn kết nối Vbee ngay khi cuộc gọi bắt đầu (chưa làm).
5. **Đường chấm điểm HTTP không bị ảnh hưởng.** Sinh cả câu 749 → 708 ms; không lượt nào vượt 8 giây.
6. **Tổng thời gian chờ (4) lần này không dùng để đánh giá giọng bot.** Lý do là bản sau có thêm PR #71 và #68.
   - Ở Sau-1, nhận dạng giọng lượt 1 mất 3131 ms và Engine câu chào mất 4116 ms. Sau-2 chạy 6 phút sau không bị lại (1361–1416 ms và 1164 ms), nên chưa coi là lỗi.
   - Ở Sau-2, nhận dạng giọng ngang bản trước (~1,4 giây). Tổng thời gian chờ các lượt là 1943–2223 ms, so với 2234–2358 ms trước đó. Phần giảm chủ yếu đến từ thời gian chờ tiếng bot.

## Hạn chế của lần đo

- **Ít mẫu:** mỗi lần chỉ 1 cuộc gọi (câu chào + 2 lượt) để tiết kiệm quota Vbee.
- **Khác giờ đo:** lần trước đo khoảng 01:30 sáng, lần sau khoảng 11:00 trưa. Vbee có thể nhanh chậm khác nhau theo giờ. Đây là lý do nên xem cột "Chờ thêm sau khi Vbee gửi tiếng đầu" thay vì chỉ xem thời gian chờ tiếng bot.
- **Số tuyệt đối hơi cao hơn thực tế:** mốc "khách nghe tiếng bot" gồm cả khoảng lặng ngắn ở đầu âm thanh Vbee và độ trễ mạng LiveKit. Các phần này như nhau ở mọi lần đo, nên **chênh lệch** giữa trước và sau vẫn đúng.
- **Lỗi in ra ở cuối cuộc gọi giả:** script đóng vai khách in `AssertionError` khi tắt. Đây là lỗi dọn dẹp của thư viện LiveKit trong script, không thuộc bot và không ảnh hưởng số đo.

## Cách chạy lại

Bộ đo nằm ở `scripts/bench/`. Cách đo chi tiết và quota: [latency-benchmark.md](../reference/latency-benchmark.md).

1. Kiểm phiên bản đang chạy trên server: `grep IMAGE /opt/callbot/image.env`.
2. Chép `scripts/bench/` lên `/opt/callbot/` trên EC2.
3. Trên EC2, trong `/opt/callbot`:
   ```bash
   bash bench/run.sh <tên-lần-đo> --dry-run   # xem trước số ký tự Vbee sẽ dùng
   bash bench/run.sh <tên-lần-đo>             # đo cả 3 phần
   bash bench/run.sh <tên-lần-đo> --parts livekit   # chỉ đo cuộc gọi LiveKit
   python3 bench/compare.py bench-results/<lần A> bench-results/<lần B>   # so hai lần đo
   ```
4. Tải `bench-results/` về `result/<ngày>/bench/`. Kết quả không chứa nội dung hội thoại.

# Task TTS tuần 3 → tuần 6 (28/09 – 24/10)

**Owner:** Hưng (TTS) · phối hợp Việt (STT) và Hoàn (Engine) · **Viết ngày:** 27/09/2026
**Nguồn:** `tailieu/callbot-contract-vi.md` (AIHR-PC-001 rev 1.1) là căn cứ chính. PRD v1.6 và Master plan được ghi rõ ở cột *Căn cứ* khi dùng tới.

**Quy ước cột *Căn cứ*:** `MUST` = contract bắt buộc · `§5` = ảnh hưởng điểm · `Phụ lục B` = contract khuyến nghị · `MP` = Master plan · `SP` = mục tiêu sản phẩm (luồng streaming hoàn chỉnh).

---

## 1. Hai đường phải làm song song

| | A. Đường chấm HTTP | B. Luồng streaming (LiveKit → điện thoại) |
|---|---|---|
| Ai dùng | Harness của mentor (team không tự chạy được) | Cuộc gọi thật: web LiveKit bây giờ, điện thoại ở cuộc gọi live tuần 6 |
| Luồng | `/turn` → STT → Engine → `utterance` → TTS → file WAV → `audio_url` | Mic → STT stream + VAD → Engine → TTS stream → phát ra loa, ngắt được khi khách nói chen |
| TTS cần | Tổng thời gian thấp, file sẵn sàng trước response, đọc đúng `utterance` | Âm đầu tiên nhanh, phát liên tục, dừng ngay khi bị ngắt, có fallback trên stream |
| Căn cứ | Listing 1–2, §4.1.2, §4.1.3, §5, §5.3, §5.4 | §1.3.1, §1.3.2, §6.2, §6.5, Phụ lục B.2 (media loop, barge-in 4 thao tác) |

**Một core, hai đường (§1.3.2):** TTS trên đường streaming dùng chung module và gateway với HTTP. Không viết logic hội thoại riêng cho điện thoại.

## 2. Contract nói gì về TTS

| Điều khoản | Nội dung | Hệ quả cho TTS |
|---|---|---|
| Listing 1 | `mode=audio` **từ tuần 3**; `audio_url` null ở chế độ text | Từ 28/09 mọi response HTTP phải có `audio_url` |
| §4.1.2 · §5.3 | ≤ 8 s mỗi lượt, tính đến khi **tải xong `audio_url`**; audio sẵn sàng ngay khi response trả về | TTS + fallback + ghi file phải nằm gọn trong 8 s |
| §4.1.3 | Audio đọc **đúng `utterance`**: không thêm, không bớt, không đổi nghĩa. Lấy mẫu ở review tuần 6; sai lệch có hệ thống bị xử như **mock đã sửa**, tức hỏng mọi lần chấm | Không sửa câu trước TTS; không bao giờ phát audio của câu khác thay cho `utterance`. Áp dụng cho **cả hai đường** |
| §5 · §5.4 | p95 cấp lượt + chi phí (token + âm thanh) mỗi phiên = 15% điểm; format báo cáo công bố trên kênh chương trình | Đo p95 và chi phí TTS |
| Bảng 1 | Vào bộ test: Identity, Confirm, No-answer (tuần 2) · Cancel, Transfer (tuần 3) · Reschedule (tuần 4) · Booking (tuần 5) | Kiểm câu thoại mỗi kịch bản trước tuần nó được chấm |
| §1.3.1 · §1.3.3 | Tuần 6 PHẢI có một cuộc gọi live (đạt/không đạt); chỉ gọi người đã đồng ý | Luồng B phải chạy được trên điện thoại thật |
| Phụ lục B.2 | Barge-in gồm 4 thao tác: **dừng phát TTS**, ngắt sinh của model, giữ partial turn, reset trạng thái lượt. Gọi số +84 thì test ở tuần 5 | TTS chịu thao tác 1 và cung cấp dữ liệu cho thao tác 3 |

## 3. Hiện trạng (27/09)

| Phần | Đã có | Chưa có |
|---|---|---|
| TTS trên HTTP | Vbee chính + ElevenLabs dự phòng trong gateway; WAV 8 kHz ghi xong trước response; đọc nguyên `utterance` | Dùng chung kết nối Vbee (mỗi câu mở mới, mất ~300–400 ms); số chi phí/phiên |
| TTS trên LiveKit | `CallBridge` phát TTS theo chunk và gọi `cancel()` khi bị ngắt; xoá hàng đợi phát | **Vbee chưa có `synthesize_stream` / `cancel()`**: chưa nối được vào LiveKit. Đường stream đi thẳng vào provider, **không qua gateway nên không có fallback** |
| STT (Việt) | STT stream + VAD, `InterruptionController`, chống bot tự nghe mình (SNR) | — |
| Engine (Hoàn) | Core dùng chung cho HTTP và LiveKit | Giữ partial turn theo phần bot đã nói (P-03) |
| Vbee | Stream thật theo vế câu, byte đầu 230–700 ms (đo 26/09) | — |

---

## 4. Task theo tuần

Mỗi task gồm:
- **Gửi PM:** 1–2 câu tóm tắt để dán vào sheet hoặc daily.
- **Nội dung:** các bước kỹ thuật để tự làm.
- **Căn cứ** và **Đầu ra**.

### Tuần 3 (28/09 – 02/10): đường chấm ổn định, bắt đầu stream Vbee

#### T2 28/09 · Đường A — Xác nhận audio mode trên prod
**Gửi PM:** Kiểm tra bot trả lời bằng giọng nói ổn định trên môi trường chạy thật từ ngày chấm chuyển sang audio: mỗi lượt đều có audio, tải được ngay và không vượt 8 giây.
**Nội dung:**
- Xem log khởi động trên EC2: chạy Vbee + fallback ElevenLabs.
- Tự gọi `/v1/calls` và `/turn` với `mode=audio`: có `audio_url`, tải được ngay sau response, tổng mỗi lượt kể cả tải audio ≤ 8 s.
- `mode=text` vẫn trả `audio_url = null`.
- Đặt `ELEVENLABS_TIMEOUT_S=3` để khi Vbee lỗi phải fallback vẫn dưới 8 s.

**Căn cứ:** Listing 1–2, §4.1.2, §5.3 · **Đầu ra:** bảng thời gian từng lượt

#### T3 29/09 · Đường A — Kiểm audio đọc đúng lời bot
**Gửi PM:** Rà toàn bộ câu nói của bot trong 5 kịch bản đang được chấm, đảm bảo audio đọc đúng từng chữ như văn bản trả về (yêu cầu bắt buộc của contract, sẽ bị lấy mẫu kiểm tra ở tuần 6).
**Nội dung:**
- Test tự động: text gửi TTS đúng bằng `utterance`, không bị sửa.
- Nghe đối chiếu câu template của Identity, Confirm, No-answer, Cancel, Transfer.
- Câu dài nhất ≤ 300 ký tự (giới hạn Vbee), hoặc fallback đọc được.

**Căn cứ:** §4.1.3, Bảng 1 · **Đầu ra:** test + danh sách câu đã nghe

#### T3 29/09 · Đường A+B — Giảm độ trễ TTS
**Gửi PM:** Tối ưu kết nối tới nhà cung cấp giọng nói để bot phản hồi nhanh hơn, dự kiến giảm khoảng 0,3–0,4 giây mỗi lượt.
**Nội dung:**
- Vbee dùng chung một kết nối HTTP (sync và async) thay vì mở mới mỗi câu.
- Mở sẵn kết nối lúc khởi động; đo trước/sau.

**Căn cứ:** §5, §6.5 · **Đầu ra:** số trước/sau

#### T4 30/09 · Đường B — Vbee phát giọng theo luồng
**Gửi PM:** Cho giọng Vbee phát ra ngay khi có đoạn âm thanh đầu tiên thay vì chờ đọc xong cả câu, làm nền cho cuộc gọi thời gian thực.
**Nội dung:**
- Viết `VbeeTTS.synthesize_stream`: trả chunk PCM ngay khi về, giữ thứ tự, căn byte chẵn.
- Unit test bằng stream giả.

**Căn cứ:** SP, §6.5 · **Đầu ra:** test pass

#### T5 01/10 · Đường B — Dự phòng khi Vbee lỗi trên cuộc gọi thời gian thực
**Gửi PM:** Khi Vbee lỗi giữa cuộc gọi thời gian thực, bot tự chuyển sang giọng dự phòng mà không bị im lặng hay đọc sai câu.
**Nội dung:**
- Đưa đường stream vào `TTSGateway` (hiện đi thẳng vào provider, chưa có fallback).
- Lỗi trước chunk đầu: chuyển ElevenLabs đọc **đúng câu đó**.
- Đã phát rồi mới lỗi: dừng, ghi log, không đọc lại từ đầu.

**Căn cứ:** SP, §4.1.3 · **Đầu ra:** test fallback trên stream

#### T5 01/10 · Đường A — Chi phí giọng nói mỗi cuộc gọi
**Gửi PM:** Tính chi phí giọng nói cho mỗi cuộc gọi, phục vụ tiêu chí latency + chi phí (15% điểm).
**Nội dung:**
- Ký tự TTS mỗi cuộc gọi theo từng kịch bản × đơn giá Vbee (và ElevenLabs khi fallback).
- Trình bày theo format chương trình công bố trên kênh.

**Căn cứ:** §5, §5.4 · **Đầu ra:** bảng USD/phiên

#### T6 02/10 · Đường A — Gate W3
**Gửi PM:** Tổng hợp bằng chứng Gate W3 cho giọng nói: độ trễ, chi phí, độ khớp audio với lời bot, xử lý khi nhà cung cấp lỗi; kèm tiến độ luồng thời gian thực.
**Nội dung:** độ trễ, chi phí/phiên, kết quả kiểm §4.1.3, đường lỗi, tiến độ stream Vbee.
**Căn cứ:** MP (Gate W3) · **Đầu ra:** `tts-gate-w3.md`

### Tuần 4 (05/10 – 10/10): nối streaming end-to-end với STT và Engine

#### T2 05/10 · Đường B — Chốt phối hợp STT / Engine / TTS
**Gửi PM:** Chốt với Việt (STT) và Hoàn (Engine) cách ba phần trao đổi với nhau trong cuộc gọi thời gian thực, và ai phụ trách phần nào khi khách nói chen ngang.
**Nội dung:**
- Sự kiện `tts_started`, `first_audio`, `done`, `cancelled` kèm mã lượt và phần text đã phát.
- Phân vai 4 thao tác barge-in: dừng phát TTS (Hưng), ngắt sinh model, giữ partial turn (Hoàn), reset lượt.

**Căn cứ:** §1.3.2, Phụ lục B.2, MP · **Đầu ra:** bảng interface + phân vai

#### T2 05/10 · Đường A — Kiểm câu thoại đổi lịch
**Gửi PM:** Rà câu nói của bot trong kịch bản đổi lịch (vào bộ chấm tuần 4), đảm bảo audio đọc đúng.
**Nội dung:** nghe đối chiếu câu đề xuất khung giờ, đọc lại lịch mới; kiểm độ dài câu.
**Căn cứ:** §4.1.3, Bảng 1 · **Đầu ra:** danh sách câu đã nghe

#### T3 06/10 · Đường B — Cuộc gọi thời gian thực chạy giọng Vbee
**Gửi PM:** Nối giọng Vbee vào cuộc gọi thời gian thực trên web, chạy trọn luồng nghe – hiểu – trả lời, và đo xem mỗi phần mất bao lâu.
**Nội dung:**
- Nối Vbee stream vào LiveKit `CallBridge`.
- Gọi thử: STT → Engine → TTS; đo từ lúc khách nói xong đến âm đầu tiên của bot, tách phần STT / Engine / TTS.

**Căn cứ:** SP, Phụ lục B.2 · **Đầu ra:** cuộc gọi chạy Vbee + bảng thời gian

#### T4 07/10 · Đường B — Bot im khi khách nói chen
**Gửi PM:** Khi khách nói chen ngang, bot dừng nói ngay và báo cho Engine biết bot đã kịp nói tới đâu, để trả lời tiếp đúng ngữ cảnh.
**Nội dung:**
- `cancel()` hủy hẳn request Vbee, xoá audio chưa phát.
- Bỏ chunk của lượt cũ theo mã lượt.
- Trả phần text đã phát cho Engine (đầu vào thao tác 3 của Hoàn).

**Căn cứ:** Phụ lục B.2, MP · **Đầu ra:** test ngắt lời, số ms từ ngắt đến im

#### T5 08/10 · Đường B — Chuyển máy và cúp máy
**Gửi PM:** Đảm bảo bot nói hết câu chuyển máy trước khi bàn giao cho nhân viên, và dừng gọn gàng khi khách cúp máy.
**Nội dung:**
- Phát hết câu chuyển máy rồi mới bàn giao.
- Khách cúp máy: dừng stream TTS và dọn tài nguyên.

**Căn cứ:** MP, §1.3.2 · **Đầu ra:** test chuyển máy / cúp máy

#### T6 09/10 · Đường B — Diễn tập #1
**Gửi PM:** Diễn tập các kịch bản trên cuộc gọi thời gian thực cùng Việt và Hoàn, sửa lỗi phần giọng nói.
**Nội dung:** chạy end-to-end các kịch bản trên LiveKit, ghi và fix lỗi TTS.
**Căn cứ:** MP · **Đầu ra:** danh sách lỗi

#### T7 10/10 · Đường B — Gate W4
**Gửi PM:** Tổng hợp bằng chứng Gate W4 cho giọng nói trên cuộc gọi thời gian thực: phát theo luồng, dự phòng khi lỗi, dừng khi bị ngắt lời, thời gian phản hồi.
**Nội dung:** stream Vbee, fallback trên stream, dừng phát khi ngắt lời, bảng thời gian end-to-end.
**Căn cứ:** MP (Gate W4) · **Đầu ra:** `tts-gate-w4.md`

### Tuần 5 (12/10 – 16/10): điện thoại thật, Booking vào test, freeze

#### T2 12/10 · Đường A — Kiểm câu thoại đặt lịch
**Gửi PM:** Rà câu nói của bot trong kịch bản khách gọi vào đặt lịch (vào bộ chấm tuần 5), sửa các lỗi giọng nói còn lại.
**Nội dung:** nghe đối chiếu câu đề xuất khung giờ, xác nhận đặt lịch; kiểm độ dài câu; fix lỗi TTS còn tồn.
**Căn cứ:** §4.1.3, Bảng 1 · **Đầu ra:** danh sách câu đã nghe

#### T3 13/10 · Đường B — Giọng nói trên điện thoại thật
**Gửi PM:** Chạy giọng bot trên đường điện thoại thật, chuẩn bị cho cuộc gọi live bắt buộc ở tuần 6.
**Nội dung:**
- TTS qua carrier / SIP team chọn: audio 8 kHz nghe rõ, ngắt lời hoạt động.
- Chỉ gọi người đã đồng ý nhận cuộc gọi.

**Căn cứ:** §1.3.1, §1.3.3, Phụ lục B.2 · **Đầu ra:** cuộc gọi thử thành công

#### T4 14/10 · Đường A+B — Diễn tập #2 và tự kiểm audio
**Gửi PM:** Diễn tập trên điện thoại thật và tự kiểm tra lại audio các cuộc gọi đã chạy, giống cách chương trình sẽ lấy mẫu ở tuần 6.
**Nội dung:** diễn tập trên điện thoại; nghe lại từng lượt các cuộc gọi đã chạy, đối chiếu `utterance`, ghi sai lệch.
**Căn cứ:** §4.1.3, MP · **Đầu ra:** báo cáo audit

#### T5 15/10 · Đường A+B — Freeze và runbook
**Gửi PM:** Khoá cấu hình giọng nói và viết hướng dẫn vận hành để team xử lý được khi nhà cung cấp gặp sự cố.
**Nội dung:** freeze provider / voice / config; runbook: đổi provider bằng env, xử lý lỗi provider, quota, rollback.
**Căn cứ:** §5 (25% vận hành, bàn giao), MP · **Đầu ra:** runbook

#### T6 16/10 · Đường A+B — Gate W5
**Gửi PM:** Tổng hợp bằng chứng cuối cho phần giọng nói trước khi freeze bản release.
**Nội dung:** evidence cuối của cả hai đường.
**Căn cứ:** MP (Gate W5) · **Đầu ra:** evidence cuối

### Tuần 6 (19/10 – 24/10)

#### 19–22/10 — Dự phòng
**Gửi PM:** Chỉ sửa lỗi nếu phát sinh sau Gate W5.
**Nội dung:** fix lỗi, chạy lại test liên quan. **Căn cứ:** MP

#### 21–22/10 — Cuộc gọi live
**Gửi PM:** Trực phần giọng nói trong cuộc gọi live bắt buộc.
**Nội dung:** kiểm tra Vbee và fallback trước giờ gọi. **Căn cứ:** §1.3.1

#### 23–24/10 — Bàn giao
**Gửi PM:** Hoàn thiện tài liệu bàn giao phần giọng nói và lý do chọn nhà cung cấp cho buổi review.
**Nội dung:** tài liệu bàn giao; ADR-002 bản cuối; evidence §4.1.3. **Căn cứ:** §4.1.3, §5 (25%), Phụ lục B

---

## 5. Phụ thuộc

| Cần | Từ ai | Hạn |
|---|---|---|
| Output Guard chạy trước TTS (TTS chỉ đọc câu đã qua guard) | Hoàn | 01/10 |
| Interface sự kiện STT ↔ TTS (bot đang nói, khách nói chen) | Việt | 05/10 |
| Ngắt sinh của model + giữ partial turn (thao tác 2, 3 barge-in) | Hoàn | 07/10 |
| Owner carrier / SIP cho cuộc gọi live | PM | trước 12/10 |

## 6. Không làm (trái hoặc không có căn cứ)

| Việc | Lý do |
|---|---|
| Phát câu "xin lỗi" từ cache khi TTS lỗi | Audio khác `utterance`, vi phạm §4.1.3 |
| Cache toàn bộ câu kịch bản demo | Dễ phát audio lệch `utterance` |
| Đặt ngưỡng ms tự nghĩ ra cho TTFA / barge-in | Contract không đặt; chỉ đo và báo số, ngưỡng do team chốt với PM |

## 7. Cần hỏi

| Câu hỏi | Vì sao | Hỏi ai |
|---|---|---|
| Format báo cáo chi phí mỗi phiên đã công bố chưa? | §5.4 | Kênh chương trình |
| Cả hai provider TTS lỗi thì `audio_url = null` ở `mode=audio` được chấm thế nào? | Contract không nói; §8.3 khuyến khích nêu điểm mơ hồ | Kênh chương trình |
| Ai lo carrier / SIP cho cuộc gọi live tuần 6? | §1.3.1 là cổng đạt/không đạt | PM |

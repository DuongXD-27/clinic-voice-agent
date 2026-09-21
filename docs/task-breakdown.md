# Task breakdown — AI Callbot Engineer

Tài liệu này chuyển nội dung file `tailieu/Task AI Callbot Enginee.pdf` sang Markdown để AI (và người mới) hiểu **phạm vi công việc, ai sở hữu phần nào, và điều kiện hoàn thành của từng task**. Đây là nguồn tham chiếu khi cần trả lời "task X yêu cầu gì", "phần này của ai", "làm xong thì phải chứng minh điều gì".

Mỗi task khi hoàn thành cần có evidence theo `docs/evidence/TEMPLATE.md` (ví dụ đã có: `docs/evidence/f02-http-engine.md`). Mã task (F-xx, T-xx, S-xx, P-xx, R-xx) là định danh chính thức, dùng nguyên trong tên branch, commit và evidence.

Tài liệu liên quan:

- Kiến trúc và hiện trạng: `docs/ai-callbot-architecture.md`
- Thiết kế Information Extraction: `docs/information-extraction-design.md`
- Clinic Mock (backend phòng khám): `docs/clinic-mock.md`
- Hợp đồng nghiệp vụ: `../callbot-contract-vi.md` (AIHR-PC-001 Rev 1.1)

## 1. Phân chia ownership

Hai người: **A = Hoàn**, **B = Hưng**.

| Phạm vi | Người | Owner | Vị trí trong repo |
| --- | --- | --- | --- |
| HTTP API, Schema, Session/FSM, Orchestrator | A | Hoàn | `src/callbot/transports/http/`, `src/callbot/engine/session/`, `src/callbot/engine/orchestrator.py` |
| Information Extraction, Dialogue Manager, Policy, Output Guard | A | Hoàn | `src/callbot/engine/extraction/`, `engine/dialogue/`, `engine/policy/` |
| Tracing, CI/CD và deploy Bot | A | Hoàn | `src/callbot/tracing/`, `Dockerfile`, `docker-compose*.yml`, `Makefile` |
| Clinic Client/Gateway, Identity Verifier | B | Hưng | `src/callbot/engine/tools/`, `src/callbot/engine/verification/` |
| Vận hành Clinic Mock, Phone Adapter và kết nối điện thoại | B | Hưng | `../clinic-mock/`, `src/callbot/transports/phone/` (chưa có) |

Nguyên tắc ranh giới:

- **Một core, hai transport.** HTTP (chấm điểm) và Phone (cuộc gọi thật) đều gọi cùng `CallOrchestrator`; transport chỉ đổi kiểu request/response, **không chứa luật nghiệp vụ**.
- **Clinic Mock là nguồn duy nhất có thẩm quyền** về trạng thái lịch hẹn. Bot không được bịa slot, không tạo patient, không báo thành công khi API chưa xác nhận.
- A và B phát triển song song qua **interface đã chốt + fake** (F-01, F-05). Thay đổi interface phải được cả hai đồng ý.

## 2. Nhóm F — Nền tảng và tích hợp

| ID | Task | Owner | Công việc chi tiết | Điều kiện hoàn thành |
| --- | --- | --- | --- | --- |
| F-01 | Chốt interface tích hợp | A chủ trì, B phối hợp | Chốt input/output của Core, Gateway và Verifier; thống nhất mã lỗi, timeout và dữ liệu xác nhận hành động; chốt `CallStart`, `CallerInput`, `BotAction` dùng chung cho HTTP/Phone. | Có interface và fixture mẫu để hai người phát triển độc lập. |
| F-02 | Nối HTTP vào engine | A | Thay `stub_handlers`; khởi tạo Orchestrator và các dependency; ánh xạ request/response; xử lý phiên không tồn tại, phiên đã đóng và input không hợp lệ. | Hai endpoint gọi engine thật; `/turn` không còn chuyển máy mặc định. *(Đã có evidence: `docs/evidence/f02-http-engine.md`.)* |
| F-03 | Hoàn thiện Session/FSM | A | Lưu câu hỏi trước, bước xác minh, hành động chờ, slot và bằng chứng xác nhận; kiểm tra thứ tự turn; xử lý lượt lặp, phiên kết thúc và nhiều session độc lập. | Trạng thái nhất quán; lượt gửi lại không gây ghi trùng. |
| F-04 | Tích hợp IE đã có | A | Thay extractor cũ (`engine/nlu/`) bằng `engine/extraction/`; truyền `question_id`, hướng gọi, thời điểm và context slot; đưa kết quả extraction vào Policy/Dialogue; ghi provenance/span. | IE mới được dùng trên đường HTTP thực tế; **không nhận danh tính chuẩn để suy đoán câu trả lời**. |
| F-05 | Hoàn thiện Clinic Client/Gateway | B | Đối chiếu endpoint, authentication, wrapper và phân trang; chuẩn hóa patient/appointment/slot; bổ sung `unreachable`; thống nhất kết quả lỗi; cung cấp fake theo interface. | Các thao tác Gateway tương thích Mock thực tế; A có fake để phát triển song song. |

## 3. Nhóm T — Nghiệp vụ text

| ID | Task | Owner | Công việc chi tiết | Điều kiện hoàn thành |
| --- | --- | --- | --- | --- |
| T-01 | Identity Verifier | B | Đọc hồ sơ outbound; tra cứu ứng viên inbound; đối chiếu tên và DOB; trả kết quả **khớp / không khớp / không xác định được hồ sơ**; không tạo patient. | Xác minh đúng theo từng hướng gọi; **không tự chọn hồ sơ đầu tiên**. |
| T-02 | Luồng hỏi và xác minh danh tính | A | Hỏi mở tên/DOB; xử lý thiếu dữ liệu, DOB không hợp lệ và yêu cầu lặp lại; giới hạn hỏi lại; nối kết quả Verifier vào FSM. | Chỉ được đọc lịch **sau** xác minh; thất bại đi đúng nhánh chuyển nhân viên. |
| T-03 | Gateway Confirm/Cancel/Transfer | B | Kiểm tra appointment đích và bằng chứng cho phép ghi; gửi reason code; dùng idempotency key và version phù hợp; inbound transfer trước đặt lịch **không ghi Mock**. | Thao tác ghi đúng đối tượng, đủ điều kiện và trả kết quả/lỗi rõ ràng. |
| T-04 | Hội thoại Confirm | A | Nhận ý định tham dự; đọc lại ngày–giờ–cơ sở; nhận đồng ý đúng nội dung; xử lý từ chối hoặc chưa rõ; gọi Gateway khi đủ điều kiện. | Chỉ trả `CONFIRMED` **sau khi API xác nhận ghi thành công**. |
| T-05 | Hội thoại Cancel | A | Ghi nhận yêu cầu và lý do hủy; hỏi xác nhận hủy lần hai; xử lý đổi ý và câu trả lời mơ hồ; không dùng đồng ý không rõ ràng để mở khóa hủy. | Chỉ ghi `CANCELLED` sau xác nhận hủy rõ ràng **lần thứ hai**. |
| T-06 | Policy ngoại lệ và Transfer | A | Xử lý lâm sàng, ngoài phạm vi, xin gặp người thật, sai danh tính và hai lượt không hiểu; phân biệt inbound/outbound; giữ reason trong trace. | Ngoại lệ được kiểm tra ở **mọi bước**; chuyển đúng lý do và hướng gọi. |
| T-07 | Gateway Unreachable | B | Cài `/unreachable`; chỉ gửi reason; **không gửi `attempt_count`**; retry cùng key; xử lý version conflict và timeout chưa rõ kết quả. | Không tăng số lần thử hai lần khi retry; chỉ áp dụng outbound. |
| T-08 | Silence và tín hiệu đường dây | A | Đếm silence riêng với không hiểu; xử lý voicemail; **outbound 3 silence → unreachable, inbound 3 silence → transfer**; chặn tiết lộ lịch trên voicemail. | Outcome và thao tác Mock đúng theo hướng gọi. |
| T-09 | Gateway Slot/Reschedule/Booking | B | Hoàn thiện đọc slot và phân trang; kiểm tra nguồn slot; đổi lịch nguyên tử; tạo appointment đúng một lần; trả lỗi slot hết hoặc version conflict. | Không bịa slot, không tạo trùng appointment và không tạo patient. |
| T-10 | Hội thoại Reschedule | A | Làm rõ thời gian mong muốn; đề xuất slot hợp lệ; xử lý lựa chọn mơ hồ/chọn lại; đọc lại; hủy xác nhận cũ khi đổi slot; hỏi lại khi slot hết. | Đổi lịch thành công bằng slot khách đã chọn và xác nhận theo thiết kế. |
| T-11 | Hội thoại Booking inbound | A | Tra cứu và xác minh trước đề xuất; làm rõ nhu cầu; chọn slot và xác nhận rõ ràng; xử lý không có hồ sơ/slot hoặc khách dừng; kết thúc sau tạo lịch thành công. | Tạo **đúng một** appointment ở trạng thái `BOOKED`; inbound chuyển hỗ trợ không tạo lịch. |
| T-12 | Phục hồi lỗi ghi | B | Xử lý timeout, version conflict và lỗi dịch vụ tạm thời; retry có giới hạn; giữ cùng key/payload cho cùng thao tác; đánh giá lại điều kiện khi dữ liệu thay đổi. | Không ghi trùng hoặc báo thành công khi chưa biết kết quả; lỗi được trả cho core để xử lý nhất quán. |

## 4. Nhóm S — Audio (STT/TTS qua HTTP)

| ID | Task | Owner | Công việc chi tiết | Điều kiện hoàn thành |
| --- | --- | --- | --- | --- |
| S-01 | STT qua HTTP | A | Nối tải audio, chuẩn hóa và STT (`speech/asr/pipeline.py`); đưa transcript vào core; phân biệt silence với lỗi nhận dạng; xử lý tải lỗi và timeout. | Request audio dùng **cùng core nghiệp vụ với text**. |
| S-02 | TTS và audio response | A | Tích hợp TTS thật cho mở cuộc gọi và từng turn; sinh từ đúng utterance; lưu audio; bảo đảm `audio_url` phục vụ được **trước khi** trả response. | Audio tải được ngay, đọc đúng nội dung phản hồi. |
| S-03 | Ngân sách latency và chi phí | A | Đo thời gian từng bước và toàn lượt gồm tải audio; đặt timeout; ghi chi phí token/audio; tối ưu các bước gây chậm. | Có số liệu p95, chi phí/phiên và kiểm tra **giới hạn phản hồi 8 giây**. |

## 5. Nhóm P — Điện thoại (Phone leg)

| ID | Task | Owner | Công việc chi tiết | Điều kiện hoàn thành |
| --- | --- | --- | --- | --- |
| P-01 | Chuẩn bị telephony | B | Chuẩn bị SIP/carrier, cấu hình và đường gọi thử; xác nhận khả năng media/chuyển máy; chuẩn bị phương án kết nối dự phòng. | Môi trường sẵn sàng để phát triển và diễn tập với người tham gia đã đồng ý. |
| P-02 | Phone Adapter | B | Mở/đóng phiên qua interface core; nhận/phát audio; ánh xạ caller number, hướng gọi và tín hiệu đường dây; xử lý disconnect và cleanup. | Điện thoại dùng chung core với HTTP, **không có luật nghiệp vụ riêng**. |
| P-03 | Hỗ trợ ngắt lời trong core | A | Hủy xử lý phản hồi cũ; giữ context theo phần đã phát; ngăn kết quả tác vụ cũ ghi đè lượt mới. | Core tiếp nhận lượt mới nhất quán khi khách ngắt lời. |
| P-04 | Ngắt playback và chuyển máy thật | B | Dừng phát audio khi có ngắt lời; phối hợp sự kiện với core; thực hiện bàn giao nhân viên; xử lý lỗi transport và timeout. | Ngắt lời và chuyển nhân viên hoạt động trên điện thoại thật. |

## 6. Nhóm R — An toàn, triển khai và bàn giao

| ID | Task | Owner | Công việc chi tiết | Điều kiện hoàn thành |
| --- | --- | --- | --- | --- |
| R-01 | Output Guard | A | Kiểm tra trước khi trả text/phát TTS; chặn: lộ lịch trước xác minh, slot không có nguồn, nội dung lâm sàng, lời báo thành công chưa có bằng chứng API. | **Cùng một cơ chế** kiểm soát đầu ra cho HTTP và Phone. |
| R-02 | Tracing và quan sát hệ thống | A | Ghi state, câu hỏi, extraction, policy, hành động, kết quả API, latency và chi phí; liên kết trace theo call/turn. | Có thể truy nguyên lỗi và đối chiếu với kết quả tester. |
| R-03 | Deploy Bot và smoke test | A | Cập nhật CI/CD, cấu hình text/audio, triển khai bản tích hợp; kiểm tra hai endpoint và audio URL; chuẩn bị rollback. | Production chạy đúng phiên bản, có quy trình triển khai/khôi phục. |
| R-04 | Vận hành Mock và telephony | B | Kiểm tra Mock nguyên bản và cấu hình phục vụ chấm; quản lý môi trường thử; giám sát lỗi kết nối; diễn tập restart/mất kết nối; hoàn thiện runbook. | Môi trường vận hành ổn định, có hướng dẫn khôi phục. |
| R-05 | Sửa lỗi nghiệm thu | A/B theo ownership | Nhận lỗi từ tester; sửa nguyên nhân; bổ sung test hồi quy phù hợp; bàn giao bản sửa và trace để xác nhận. | Các lỗi ưu tiên cao được đóng bằng kết quả kiểm thử lại. |
| R-06 | Chốt baseline và diễn tập | A/B | Chốt phiên bản; tổng hợp kết quả nghiệp vụ, severe failure, latency/cost; diễn tập điện thoại trên cùng bản release; bàn giao tài liệu. | Có bản cơ sở ổn định để nghiệm thu nội bộ và so sánh cải tiến. |

## 7. Bất biến xuyên suốt (rút từ điều kiện hoàn thành)

Khi sửa bất kỳ phần nào của core, kiểm tra không phá các luật sau. Chúng lặp lại ở nhiều task nên được coi là guardrail toàn hệ thống (xem `engine/policy/`, SF-01..SF-05):

1. **Không đọc lịch trước khi xác minh danh tính** (T-02, R-01). Voicemail cũng không được nghe lịch (T-08).
2. **Không tự chọn hồ sơ đầu tiên, không tạo patient** (T-01, T-09, T-11). Verifier trả 3 trạng thái: khớp / không khớp / không xác định.
3. **Không báo thành công khi API chưa xác nhận.** `CONFIRMED`, `CANCELLED`, `BOOKED` chỉ được trả sau khi Gateway ghi thành công (T-04, T-05, T-11, T-12, R-01).
4. **Hủy cần xác nhận rõ ràng lần thứ hai**; đồng ý mơ hồ không mở khóa hủy (T-05).
5. **Idempotency + version:** cùng thao tác dùng cùng key/payload; retry không ghi trùng, không tăng attempt hai lần (F-03, T-03, T-07, T-12).
6. **Không bịa slot**: slot phải có nguồn từ Gateway (T-09, T-10, R-01).
7. **Phân biệt inbound/outbound ở mọi nhánh:** 3 silence → outbound `unreachable`, inbound `transfer`; inbound transfer trước đặt lịch không ghi Mock; `/unreachable` chỉ dùng outbound (T-03, T-06, T-07, T-08).
8. **Ngoại lệ được kiểm tra ở mọi bước:** lâm sàng, ngoài phạm vi, xin gặp người thật, sai danh tính, 2 lượt không hiểu → transfer với reason trong trace (T-06).
9. **Silence ≠ không hiểu ≠ lỗi nhận dạng** — ba bộ đếm riêng (T-08, S-01).
10. **Một core cho HTTP và Phone**; Output Guard, tracing và luật nghiệp vụ dùng chung, transport không có logic riêng (P-02, R-01, S-01).
11. **Phản hồi ≤ 8 giây** (p95), có đo latency và chi phí từng bước (S-03, R-02).
12. **IE không được nhận danh tính chuẩn** (tên/DOB đúng) làm input để suy đoán câu trả lời (F-04).

## 8. Phụ thuộc giữa các task

```text
F-01 (interface)  ──┬──> F-02 ──> F-03 ──> F-04 ──> T-02, T-04, T-05, T-06, T-08, T-10, T-11 (A)
                    └──> F-05 ──> T-01, T-03, T-07, T-09, T-12 (B)

T-01 (Verifier, B) ──> T-02 (luồng xác minh, A)
T-03/T-09 (Gateway, B) ──> T-04/T-05/T-10/T-11 (hội thoại, A)
T-12 (phục hồi lỗi, B) ──> mọi hội thoại có ghi

Core text ổn định ──> S-01, S-02 ──> S-03
F-01 + core ──> P-01 ──> P-02 ──> P-03 (A) ──> P-04 (B)

R-01, R-02 song song với nhóm T (guard/trace phải có trước khi nghiệm thu)
R-03, R-04 ──> R-05 ──> R-06 (baseline cuối)
```

Quy ước làm việc song song: khi A cần Gateway/Verifier chưa xong, dùng **fake theo interface** từ F-05; khi B cần core, dùng fixture `CallStart`/`CallerInput`/`BotAction` từ F-01. Không được nới interface một phía để "đi tắt".

## 9. Cách dùng tài liệu này với AI

- Khi được giao task theo mã (ví dụ "làm T-05"): đọc dòng tương ứng ở mục 3, đối chiếu mục 7 để biết bất biến nào bị ảnh hưởng, kiểm tra mục 8 để biết phụ thuộc, rồi mở evidence của task tiền nhiệm trong `docs/evidence/`.
- Khi hoàn thành: tạo `docs/evidence/<id>-<slug>.md` theo `TEMPLATE.md`, mỗi dòng "Điều kiện hoàn thành" phải có bằng chứng code + test tương ứng.
- Không tự mở rộng phạm vi sang task của owner khác; nếu cần thay đổi ở phần của người kia, ghi rõ trong evidence và đề xuất thay đổi interface thay vì sửa trực tiếp.

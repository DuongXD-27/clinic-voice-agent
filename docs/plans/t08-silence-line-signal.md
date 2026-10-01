# Plan T-08 — Silence và tín hiệu đường dây

> Cập nhật 01-10-2026: phần suy ra `LINE_BUSY`/`NO_ANSWER` từ transcript bên dưới mô tả thiết kế cũ và được thay thế bởi [tài liệu tín hiệu trạng thái điện thoại](../reference/phone-status.md). Bộ trích xuất chỉ nhận diện hộp thư thoại từ lời nói; kết quả quay số được biểu diễn bằng `PhoneStatus` và xử lý qua Core/Policy/Gateway dùng chung.

**Owner:** A (Hoàn) · **Trạng thái:** Đã triển khai (Q-1, Q-2 chốt với owner 21-09-2026; Q-3, Q-4 theo đề xuất) — evidence `docs/evidence/t08-silence-line-signal.md` · **Ngày:** 21-09-2026
**Nguồn:** `docs/task-breakdown.md` §3 (T-08), §7 bất biến 1, 7, 8, 9; `docs/reference/ai-callbot-architecture.md` §3.2–§3.4, §4.2; `docs/reference/information-extraction-design.md` §4, §5.9, §6.1, §6.3, §6.4, §10 câu 9; `docs/reference/clinic-mock.md` (unreachable, chuyển trạng thái); `docs/evidence/t07-gateway-unreachable.md`; contract rev 1.1 §1.1.5, §1.1.7, §2.1, §4.2.5, Phụ lục A
**Phụ thuộc:** F-04 (IE `silent`, `line_signal`), F-05/T-07 (Gateway `/unreachable`), T-02, T-04 — đều đã có trên `main` `bfcc529`

## 1. Mục tiêu và điều kiện hoàn thành

> Đếm silence riêng với không hiểu; xử lý voicemail; **outbound 3 silence → unreachable, inbound 3 silence → transfer**; chặn tiết lộ lịch trên voicemail.
> **Điều kiện hoàn thành:** Outcome và thao tác Mock đúng theo hướng gọi.

Phần lớn T-08 đã có từ F-04: IE đặt `silent` theo `silence_ms > 0`, `line_signal` chạy ở outbound trước khi xác minh xong, `PolicyEngine.check_silence` có bộ đếm `silent_turns` riêng, `DialogueManager.unreachable` gọi Gateway và không đọc lịch. T-08 không dựng lại các phần này. T-08 sửa lỗ hổng đo được khi chạy thử (§2), rồi khóa điều kiện hoàn thành bằng ma trận test **hướng gọi × tín hiệu** ở tầng Orchestrator và HTTP.

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | **Silence đếm riêng với không hiểu:** lượt im lặng không tăng, không reset `failed_understandings`; lượt có lời reset `silent_turns` về 0 | Chuỗi S-S-lời-S-S không kết thúc; NU-S-NU → `NOT_UNDERSTOOD` (giữ quyết định T-02); S-NU-S-NU không kết thúc sớm vì im lặng |
| AC-2 | **Outbound 3 silence liên tiếp → `UNREACHABLE/SILENCE`**, ở mọi bước (danh tính, đọc lại, chọn slot, xác nhận hủy); Mock có đúng 1 lệnh `/unreachable` body `{"unreachable_reason": "SILENCE"}` | Parametrize theo bước; `clinic.writes`, HTTP writelog |
| AC-3 | **Inbound 3 silence liên tiếp → `TRANSFERRED/NOT_UNDERSTOOD`**, không gọi Mock (§2.1: inbound chưa đặt lịch không có lệnh ghi) | `writes == []` ở mọi bước inbound |
| AC-4 | **Voicemail (outbound):** clip lời chào ở bất kỳ lượt nào trước khi xác minh xong → `UNREACHABLE/VOICEMAIL`, kể cả sau vài lượt im lặng | Lượt 1, lượt 2 (sau tên), sau 2 lượt im lặng |
| AC-5 | **Không tiết lộ lịch trên voicemail:** không câu nào của bot trong cuộc gọi kết thúc `VOICEMAIL`/`SILENCE` chứa ngày, giờ, khoa, cơ sở | Quét mọi `utterance` của cuộc gọi, không chỉ câu cuối |
| AC-6 | **Nhắc im lặng không làm hỏng xác nhận:** "vâng"/"đúng rồi" trả lời câu "Alo, còn nghe máy không?" không được mở khóa lệnh ghi `CONFIRMED`/`RESCHEDULED`/`BOOKED`/`CANCELLED` (G-1) | §5.2 ma trận im lặng × câu hỏi xác nhận |
| AC-7 | **Kết quả ghi `/unreachable`:** thành công → `UNREACHABLE`; bị từ chối → không báo `UNREACHABLE`; chưa rõ kết quả → `409 CALL_RECONCILIATION_REQUIRED` | `fail_next("mark_unreachable", ...)`; HTTP |
| AC-8 | Inbound không bao giờ `UNREACHABLE`; câu hộp thư ở inbound không gọi `/unreachable` | Inbound + câu voicemail → xử lý như câu không hiểu, `writes == []` |

## 2. Hiện trạng (main `bfcc529`, 21-09-2026)

**Đã có và giữ nguyên:**
- `InformationExtractor.extract`: `silence_ms > 0` → `ExtractionResult.silent`, mọi trường `skipped`. Transcript rỗng với `silence_ms == 0` là không hiểu.
- `extract_line_signal`: `VOICEMAIL` xét trước; `LINE_BUSY`/`NO_ANSWER` bắt buộc có dấu hiệu tổng đài. Chỉ chạy ở outbound khi `question ∈ {None, ASK_NAME, ASK_DOB}`.
- `PolicyEngine.check_silence` (ngưỡng `max_silent_turns = 3`), `check_signals` (tín hiệu đường dây xét trước lâm sàng/intent). Orchestrator chạy cả hai trước Dialogue.
- `DialogueManager.unreachable`: `GOODBYE_UNREACHABLE` không có chi tiết lịch. Ghi bị từ chối → `TRANSFERRED/SYSTEM_ERROR`.
- Gateway T-07: `/unreachable` chỉ ở outbound (`SF-01`), key `call_id:turn:unreachable`, `VERSION_CONFLICT` → đọc lại, gửi lại cùng key.
- Test: `test_orchestrator.py` (3 silence outbound/inbound, voicemail, ghi bị từ chối), `test_identity_dialogue.py` (silence lúc hỏi danh tính, NU-S-NU), `test_line_signal.py`, `test_extractor.py`.

**Khoảng cách.** Chạy thử Orchestrator thật + `FakeClinicAPI` (`apt_00417`, outbound đã xác minh):

| # | Chuỗi lượt | Hiện tại | Đúng ra | Vị trí |
| --- | --- | --- | --- | --- |
| G-1 | Đọc lại → *im lặng* → bot "Alo, anh chị còn nghe máy không ạ?" → "vâng" | **ghi `CONFIRMED`** | "vâng" đang trả lời "còn nghe máy không", không phải câu đọc lại; không được ghi | `DialogueManager.silence` giữ nguyên `ctx.question` (cả `turn`); `assert_action_confirmed` chỉ đòi `question.turn < item.turn`, không đòi câu hỏi ở **lượt ngay trước** |
| G-1b | Chốt slot → *im lặng* → "Alo..." → "đúng rồi" | **ghi `RESCHEDULED`** | như G-1 | như G-1 |
| G-1c | Xác nhận hủy → *im lặng* → "Alo..." → "có" | hiện ra UNCLEAR nhờ ngưỡng `CANCEL_RECONFIRM` chặt, nhưng không có gì bảo đảm | như G-1 | như G-1 |
| G-2 | Kiến trúc §3.3: im lặng → "Nhắc / hỏi lại tại bước hiện tại" | chỉ nói "Alo, anh chị còn nghe máy không ạ?", không nhắc câu đang hỏi | nhắc lại câu hỏi đang chờ | `t.SILENCE` |
| G-3 | Lời chào hộp thư cá nhân không có từ khóa ("Xin chào, tôi là Lan, hiện không nghe máy được") | đọc thành câu không hiểu, hỏi lại tên | `VOICEMAIL` (nếu clip harness có dạng này — xem Q-2) | `_VOICEMAIL` thiếu mẫu "không nghe máy được", "gọi lại sau" (không có "quý khách") |
| G-4 | `mark_unreachable` chưa rõ kết quả | đã đúng: `ReconciliationRequired` | — | Thiếu test riêng (T-07 Ghi chú) và thiếu test HTTP 409 |
| G-5 | Ma trận hướng gọi × tín hiệu | test rời rạc, chưa có HTTP e2e kiểm writelog cho 3 silence / voicemail; chưa quét mọi câu của cuộc gọi voicemail | AC-2..AC-5 ở cả hai tầng | `tests/` |

G-1 là lỗi nặng nhất: bot ghi `CONFIRMED`/`RESCHEDULED` khi người gọi chỉ vừa xác nhận mình còn nghe máy. Lỗi này vi phạm §1.1.3 ("only after the patient agrees to that read-back") và bất biến 2 của task-breakdown.

Phát hiện thêm khi triển khai:

| # | Chuỗi lượt | Trước T-08 | Sau khi chỉ siết guardrail | Xử lý |
| --- | --- | --- | --- | --- |
| G-6 | Câu xác nhận → "bla bla" → "Dạ, em chưa hiểu ý anh chị..." → "vâng"/"đúng rồi" | **ghi** `CONFIRMED`/`RESCHEDULED` (câu "em chưa hiểu" không đổi câu hỏi) | guardrail chặn → `TRANSFERRED/SYSTEM_ERROR` | Dialogue `_answers_last_question`: AGREE cho câu hỏi không ở lượt ngay trước đi nhánh chưa rõ, hỏi lại câu xác nhận |

Không phải khoảng cách:
- Voicemail sau khi đã xác minh không được nhận diện: không xảy ra được, vì xác minh cần tên + ngày sinh khớp hồ sơ. Đây cũng là lý do voicemail không bao giờ nghe được lịch (AC-5): chi tiết lịch chỉ được đọc sau `VERIFIED`, còn `line_signal` chạy suốt các bước trước đó.
- Im lặng không reset bộ đếm không hiểu (NU-S-NU → chuyển): đã chốt ở T-02, có test `test_silence_between_failures_neither_resets_nor_counts`.

### 2.1 Đối chiếu contract / kiến trúc

| Điều khoản | Nội dung | Hệ quả cho T-08 |
| --- | --- | --- |
| §1.1.7 rev 1.1 | Outbound không liên lạc được → `/unreachable` với `NO_ANSWER`/`VOICEMAIL`/`LINE_BUSY`/`SILENCE`; không để lại chi tiết lịch trên voicemail; inbound 3 lượt im lặng → chuyển; "a silent turn is not a failed understanding under §1.1.5" | AC-1..AC-5, AC-8 |
| §4.2.5 | Harness tạo `SILENCE` bằng `silence_ms > 0`, `VOICEMAIL` bằng clip lời chào; `/unreachable` body chỉ `unreachable_reason`, Mock tự tăng `attempt_count`, cùng key trả kết quả cũ | Không đổi Gateway; G-3 phụ thuộc nội dung clip (Q-2) |
| §1.1.3 | `CONFIRMED` chỉ sau khi bệnh nhân đồng ý câu đọc lại | G-1 |
| §2.1 | Inbound `TRANSFERRED`: chấm `outcome` + writelog rỗng, không chấm `transfer_reason` | AC-3 kiểm `writes == []` là chính |
| Phụ lục A | Im lặng = `silence_ms > 0` | Giữ nguyên, không suy im lặng từ transcript rỗng |
| Kiến trúc §3.3 | "Nhắc / hỏi lại tại bước hiện tại; không tính là một lần không hiểu" | G-2, Q-1 |
| Kiến trúc §4.2 | "Không thể ghi `/unreachable` → không tuyên bố Mock đã có `UNREACHABLE`" | Đã đúng; bổ sung test (AC-7) |

## 3. Thiết kế

### 3.1 Luồng một lượt (không đổi thứ tự)

```text
check_preconditions -> IE.extract(silence_ms)
  silent                     -> check_silence:
                                  < 3        -> Dialogue.silence  (nhắc + hỏi lại câu đang chờ, Q-1)
                                  = 3 out    -> Dialogue.unreachable(SILENCE)  -> /unreachable
                                  = 3 in     -> Dialogue.transfer(NOT_UNDERSTOOD) -> không ghi Mock
  không silent               -> silent_turns = 0
  line_signal ≠ NONE (out)   -> Dialogue.unreachable(VOICEMAIL | LINE_BUSY | NO_ANSWER)
  còn lại                    -> lâm sàng / intent luôn chuyển / Dialogue / register_understanding
```

### 3.2 Sửa G-1 + G-2: nhắc im lặng là **hỏi lại** câu đang chờ (Q-1)

`DialogueManager.silence`:
- Có `ctx.question`: nói `t.SILENCE + " " + ctx.question.text` và **hỏi lại** câu đó ở lượt hiện tại (`ctx.question = replace(ctx.question, turn=ctx.turn)`), giữ nguyên `question_id`, `action`, `slot_id`, `text`.
- Không có `ctx.question`: giữ `t.SILENCE`.

Sau đó, "vâng" ở lượt kế tiếp là câu trả lời cho câu đọc lại vừa được nhắc nguyên văn, nên guardrail cho qua đúng. Câu "còn nghe máy không" không còn đứng một mình làm câu hỏi cuối. `question.text` giữ bản gốc (không có tiền tố "Alo"), nên `REPEAT_REQUEST` vẫn đọc đúng câu hỏi.

Thêm một lưới an toàn ở guardrail, độc lập với cách Dialogue nhắc: `assert_action_confirmed` đòi `question.turn == item.turn - 1` (câu hỏi được nói ở **lượt ngay trước**), thay cho `question.turn < item.turn`. `REPEAT_REQUEST` hiện đọc lại câu hỏi mà không cập nhật `turn`, nên phải cập nhật luôn `question.turn` ở nhánh này; nếu không, "gì cơ" → đọc lại → "vâng" sẽ bị chặn nhầm.

### 3.3 Sửa G-3: mở rộng mẫu hộp thư (Q-2)

Chỉ thêm vào `_VOICEMAIL` những cụm người thật gần như không bao giờ nói với người gọi đến: "hiện không nghe máy được", "không thể nghe máy", "sẽ gọi lại cho bạn", "sẽ gọi lại sau", "không thể trả lời cuộc gọi", "is not available right now", "can't take your call", "cannot take your call". Mỗi cụm thêm vào phải có case bẫy người thật trong `test_human_speech_is_not_a_line_signal` ("tôi đang bận không nghe máy được lâu", "gọi lại sau giúp tôi"...). Cụm nào đụng câu người thật thì bỏ, không nới luật.

### 3.4 Không đổi

Policy, Gateway, FSM, `CallContext` (không thêm trường, `SCHEMA_VERSION` giữ nguyên), `GOODBYE_UNREACHABLE`.

## 4. Các bước thực hiện

Nhánh `feature/t08-silence-line-signal` từ `main` `bfcc529`.

1. **Test đỏ trước** cho G-1/G-1b/G-1c: im lặng → "vâng"/"đúng rồi"/"có" ở `CONFIRM_READBACK`, `SLOT_READBACK`, `CANCEL_RECONFIRM` → không có lệnh ghi ở lượt đó.
2. Guardrail `question.turn == item.turn - 1`; `respond` nhánh `REPEAT_REQUEST` cập nhật `question.turn`. Chạy toàn bộ test để tìm chỗ khác đang dựa vào câu hỏi cũ.
3. `DialogueManager.silence` hỏi lại câu đang chờ (§3.2); sửa kỳ vọng các test đang so `utterance == t.SILENCE`.
4. `_VOICEMAIL` + case bẫy (§3.3), sau khi chốt Q-2.
5. Test ma trận Orchestrator (§5.2) + HTTP e2e (writelog, quét utterance, 409 unreachable).
6. Cập nhật tài liệu: IE design §5.9 (bảng mẫu), kiến trúc §3.3 (câu nhắc hỏi lại), §5 (Dialogue Manager); viết `docs/evidence/t08-silence-line-signal.md`.
7. `make check`.

## 5. Test

### 5.1 Test hiện có sẽ đổi kỳ vọng

| Test | Đổi |
| --- | --- |
| `test_confirm_dialogue.py::test_silence_and_repeat_request_keep_the_readback_question` | `utterance == t.SILENCE + " " + summary.utterance`; `question.turn` bằng lượt nhắc |
| `test_calls.py::test_silence_and_empty_transcript_map_differently` | `utterance` bắt đầu bằng `t.SILENCE` và chứa câu hỏi tên |
| `test_calls.py::test_silence_turn_in_audio_mode_still_replies_with_audio`, `test_identity_dialogue.py` (các test silence) | kiểm tra lại nếu so nguyên văn `t.SILENCE` |
| Guardrail unit test (nếu có case `question.turn` cách 2 lượt) | đổi thành bị chặn |

### 5.2 Test mới

`tests/engine/test_silence_line_signal.py` (Orchestrator thật + `FakeClinicAPI`):

| Nhóm | Case |
| --- | --- |
| Ngưỡng theo hướng gọi | outbound/inbound × bước {`ASK_NAME`, `ASK_DOB`, `CONFIRM_READBACK`, `OFFER_SLOTS`, `SLOT_READBACK`, `CANCEL_RECONFIRM`} × 3 silence → outbound `UNREACHABLE/SILENCE` + đúng 1 write; inbound `TRANSFERRED/NOT_UNDERSTOOD` + `writes == []` (inbound dùng `+84912345600`) |
| Đếm riêng | S-S-lời-S-S không kết thúc; S-NU-S-NU chuyển ở NU thứ hai, không sớm hơn; S-S-"gì cơ"-S không kết thúc (`REPEAT_REQUEST` reset im lặng) |
| G-1 | im lặng rồi "vâng"/"đúng rồi"/"có" ở 3 câu hỏi xác nhận → không ghi, lượt đó hỏi lại; im lặng → câu nhắc có câu hỏi → "vâng" ở lượt sau nữa → ghi (luồng đúng vẫn chạy) |
| Voicemail | lượt 1; lượt 2 sau tên; sau 2 lượt im lặng → `UNREACHABLE/VOICEMAIL`; mọi utterance không chứa "14 tháng 10", "9 giờ", "Nội tổng quát", "Times City" |
| Inbound + câu hộp thư | không gọi Mock, không `UNREACHABLE` |
| Kết quả ghi | `/unreachable` từ chối (`INVALID_STATE_TRANSITION`, `VERSION_CONFLICT` ×2) → không `UNREACHABLE`; chưa rõ → `ReconciliationRequired` |

`tests/engine/extraction/test_line_signal.py`: mẫu mới (§3.3) + bẫy người thật, có dấu và không dấu.

`tests/transports/http/test_calls.py`: outbound 3 silence và voicemail qua HTTP → `outcome`, `unreachable_reason`, writelog fake; inbound 3 silence → `TRANSFERRED`, writelog rỗng; `/unreachable` chưa rõ kết quả → `409 CALL_RECONCILIATION_REQUIRED`.

## 6. Quyết định

| # | Câu hỏi | Đề xuất | Căn cứ |
| --- | --- | --- | --- |
| Q-1 | Câu nhắc im lặng: (A) "Alo, anh chị còn nghe máy không ạ?" + nhắc nguyên câu đang hỏi, tính là hỏi lại; hay (B) giữ câu "Alo" ngắn, và lượt sau nếu là AGREE cho câu xác nhận thì coi là UNCLEAR rồi đọc lại | **A** — ít lượt hơn, đúng kiến trúc §3.3 "hỏi lại tại bước hiện tại"; guardrail lượt-ngay-trước chặn G-1 dù chọn A hay B | Kiến trúc §3.3; §1.1.3 |
| Q-2 | Mở rộng mẫu hộp thư sang lời chào cá nhân không có "để lại lời nhắn" | **Làm, bảo thủ** (§3.3). Đồng thời hỏi `#residency-batch03` nội dung clip VOICEMAIL của harness (IE design §10 câu 9 còn mở) | §4.2.5 chỉ nói "clip lời chào" |
| Q-3 | NU-S-NU có tính là 2 lượt không hiểu liên tiếp không | Giữ như T-02: im lặng không reset, không tính | §1.1.7 chỉ nói im lặng không phải lần không hiểu |
| Q-4 | Voicemail chỉ nhận trước khi xác minh xong | Giữ | Xác minh cần tên + ngày sinh khớp; chi tiết lịch chỉ đọc sau xác minh → AC-5 |

## 7. Ngoài phạm vi và rủi ro

- **`/unreachable` bị Mock từ chối vì trạng thái** (lịch đã `CONFIRMED`: Mock chỉ cho `unreachable` từ `SCHEDULED`/`BOOKED`/`UNREACHABLE`). Hiện bot trả `TRANSFERRED/SYSTEM_ERROR` mà không có lệnh `/transfer` nào, trái kiến trúc §4.2 ("không tuyên bố Mock đã có `TRANSFERRED`"). Đây cùng lỗi T-04 đã ghi cho `/transfer`: thuộc T-06 / T-12, T-08 chỉ thêm test khóa việc **không báo `UNREACHABLE`**.
- **Tra cứu lượt 0 thất bại + voicemail** ở outbound: `check_preconditions` chuyển máy ở lượt 1 trước khi xét voicemail. Hiếm (outbound có `appointment_id`); nếu Mock sập thì `/unreachable` cũng không ghi được. Không đổi.
- **Bộ đếm thứ ba "lỗi nhận dạng"** (bất biến 9: silence ≠ không hiểu ≠ lỗi nhận dạng) cần tín hiệu ASR (`asr_confidence`, transcript rỗng từ audio) → S-01. T-08 chỉ giữ phân biệt silence / không hiểu.
- `LINE_BUSY` / `NO_ANSWER` chỉ xuất hiện ở cuộc gọi thật tuần 6 (§4.2.5); T-08 giữ luật hiện có, không thêm case.
- Rủi ro Q-1: câu nhắc ở `CONFIRM_READBACK` dài (đọc lại toàn bộ lịch). Chấp nhận được vì người nghe đã xác minh.

# Plan T-02 — Luồng hỏi và xác minh danh tính

**Owner:** A (Hoàn) · **Trạng thái:** Đã triển khai theo đề xuất Q-1..Q-4 (§6) — evidence `docs/evidence/t02-identity-dialogue.md` · **Ngày:** 18-09-2026
**Nguồn:** `docs/task-breakdown.md` §3 (T-02), §7 bất biến 1, 8, 9; `docs/reference/ai-callbot-architecture.md` §3.1–§3.3; `docs/reference/information-extraction-design.md` §5.1, §5.2, §6.1–§6.3; contract rev 1.1 §1.1.1–§1.1.2, §1.1.5, §1.1.7, §1.1.9, SF-03
**Phụ thuộc:** T-01 (đã merge, PR #13 `627b1bb`), F-03, F-04, F-05 — đều đã có trên `main`

## 1. Mục tiêu và điều kiện hoàn thành

> Hỏi mở tên/DOB; xử lý thiếu dữ liệu, DOB không hợp lệ và yêu cầu lặp lại; giới hạn hỏi lại; nối kết quả Verifier vào FSM.
> **Điều kiện hoàn thành:** Chỉ được đọc lịch **sau** xác minh; thất bại đi đúng nhánh chuyển nhân viên.

T-01 đã làm Verifier: `prepare()` đọc hồ sơ ở lượt 0, `verify()` đối chiếu không I/O. T-02 làm phần **hội thoại** quanh nó: hỏi gì, nhận gì, hỏi lại bao nhiêu lần, mỗi kết quả đi nhánh nào.

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | Lượt 0 rẽ nhánh theo `PrepareResult`: `LOADED` → chào + hỏi mở họ tên; khác → chào (vẫn công bố AI), **không hỏi tên**; lượt 1 chuyển máy với `prepare.transfer_reason` bất kể input | Inbound số lạ / không số → lượt 1 `TRANSFERRED/PATIENT_NOT_FOUND`, `writes == []`; outbound mock lỗi lượt 0 → lượt 1 `SYSTEM_ERROR` |
| AC-2 | Nhận **phần còn thiếu**: tên + DOB trong một câu → xác minh ngay; nói DOB khi được hỏi tên → giữ DOB, hỏi tên | "Nguyễn Văn A, sinh 14/3/1978" → `AWAITING_INTENT` sau 1 lượt; DOB trước tên → 2 lượt |
| AC-3 | DOB `INVALID` (31/02, thiếu năm, năm 2 chữ số mơ hồ, tuổi/âm lịch) → câu hỏi lại riêng; không gọi Verifier | Mỗi dạng INVALID → `ASK_DOB_INVALID`; TC_IEN_55/56 vẫn xanh |
| AC-4 | Xin nhắc lại ở bước danh tính → đọc lại đúng câu đang chờ, không tính vào bộ đếm | Test ở `ASK_NAME` và `ASK_DOB` |
| AC-5 | Giới hạn hỏi lại (Q-1): không trích được / INVALID tới ngưỡng → `NOT_UNDERSTOOD`; im lặng đếm riêng (outbound 3 → `UNREACHABLE/SILENCE`, inbound 3 → `TRANSFERRED`) | Ma trận §5 |
| AC-6 | Đủ tên + DOB hợp lệ mà không khớp → **chuyển ngay**, không hỏi lại, không nói trường nào sai: outbound `IDENTITY_FAILED` + `POST /transfer`; inbound `PATIENT_NOT_FOUND`, không ghi | TC_ID_02..04, TC_ID_14 + kiểm câu thoại |
| AC-7 | FSM: `VERIFIED` ⇒ tra cứu lượt 0 `LOADED` và có `patient_id`; rời `AWAITING_IDENTITY` chỉ khi `VERIFIED` (đã có) | Invariant mới + test |
| AC-8 | SF-03: không câu nào trước `VERIFIED` chứa chi tiết lịch hoặc dữ liệu chuẩn | `test_sf03_appointment_disclosure.py` mở rộng cho nhánh mới |

## 2. Hiện trạng sau khi pull (18-09-2026)

**Git:**
- `main` = `2f6dc89` (T-01 merge + tách CI thành `ci.yml` / `cd.yml`).
- Branch hiện tại `feature/llm-gateway-name-ner` có commit `b63c6dd` (LLM gateway + NER tên) **chưa push**. Commit này chứa cả file plan này và sửa `extraction/full_name.py`, `extractor.py` — cùng file T-02 bước 2 sẽ sửa.
- Baseline trên branch này: `pytest tests/engine tests/transports tests/test_schema.py` → **738 passed, 45 skipped**. 8 test fail mà evidence T-01 ghi (TC_IEN_47, 53–58, TC_SF03_07) đã xanh.

**T-01 bản cuối khác bản plan trước đọc:** `VerificationResult(status, patient_id=None, detail=None, candidates=0)` — `detail` tùy chọn, `patient_id` là tham số thứ hai. T-02 chỉ dùng `status`, `patient_id`, `transfer_reason`.

**Khoảng cách:**

| # | Khoảng cách | Vị trí | Việc T-02 |
| --- | --- | --- | --- |
| G-1 | `opening()` gọi `prepare()` nhưng bỏ kết quả → khách chưa đăng ký bị hỏi 2 lượt rồi mới chuyển | `dialogue/manager.py::opening` (có sẵn comment TODO T-02) | Rẽ nhánh theo giá trị trả về; lượt 1 chuyển qua `Policy.check_preconditions` |
| G-2 | IE chỉ trích DOB khi `ASK_DOB`; câu có chữ số không thành tên → "Nguyễn Văn A sinh 14/3/1978" bị tính không hiểu | `extraction/extractor.py`, `full_name.py` | Ở `ASK_NAME` chạy thêm `extract_dob`; bỏ `dob.span` + cụm nối rồi mới trích tên |
| G-3 | `NONE` và `INVALID` dùng chung `ASK_DOB_AGAIN` | `manager.py::_identity` | Câu riêng cho `INVALID` |
| G-4 | `identity_step` tuyến tính, không "hỏi phần còn thiếu" | `_identity` | Suy bước từ `claimed_name` / `claimed_dob` |
| G-5 | Lượt lặp lại thông tin đã có vẫn tính "hiểu", reset bộ đếm | `_identity` | Quy tắc tiến triển (Q-1) |
| G-6 | FSM chưa ràng buộc `VERIFIED` với tra cứu / `patient_id` | `session/fsm.py::check_invariants` | Invariant mới |
| G-7 | Tài liệu mâu thuẫn: IE design §6.2 "mỗi trường hỏi lại tối đa 1 lần" vs kiến trúc §3.3 "không có giới hạn danh tính riêng" | docs | Đồng bộ theo Q-1 |
| G-8 | Người gọi nói nhu cầu trước khi đọc tên ("tôi muốn đặt lịch" — Hình 0 kịch bản Book). Bước danh tính không chạy intent nghiệp vụ → tên `NONE` → tính một lần không hiểu | `extractor.py` (`_IDENTITY_FALLBACK_INTENTS`), `_identity` | Nhận intent nghiệp vụ như `OUT_OF_SCOPE` hiện nay (chỉ khi không có tên/DOB); trả lời "để hỗ trợ, em cần xác minh…" + hỏi lại tên, **lần đầu không tính** (ngữ nghĩa `UNCLEAR`) |
| G-9 | Người gọi nói rõ không nhớ / không muốn cung cấp tên hoặc DOB: hiện là `NONE` → hết lượt thì `NOT_UNDERSTOOD` | IE, `_identity` | Nhãn riêng; lần 2 liên tiếp → `IDENTITY_FAILED` (Q-3) |

### 2.1 Đối chiếu contract rev 1.1 (đọc 18-09-2026)

| Điều khoản | Nội dung liên quan | Hệ quả cho T-02 |
| --- | --- | --- |
| §1.1.1 | Outbound: trước khi tiết lộ, MUST lấy tên + DOB và MUST khớp cả hai; thất bại → chuyển máy, không tiết lộ gì | Không lấy được tên/DOB cũng là xác minh thất bại → cơ sở cho Q-3 |
| §1.1.2 | Hỏi **mở từng định danh**, không đọc định danh rồi hỏi "đúng không" | Câu hỏi lại (kể cả `ASK_DOB_INVALID`) không nhắc giá trị nào — kể cả giá trị người gọi vừa nói |
| §1.1.5 | MUST chuyển sau **hai lần liên tiếp không hiểu**; MUST NOT đoán | Không có giới hạn riêng cho danh tính → cơ sở cho Q-1 |
| §1.1.7 | Im lặng không phải "không hiểu"; outbound 3 → `UNREACHABLE/SILENCE`, inbound 3 → `NOT_UNDERSTOOD` | Giữ nguyên, đã có |
| §1.1.9 | Inbound: MUST tìm hồ sơ trước khi đề xuất; vẫn MUST hỏi mở tên + DOB; "không có **đúng một** hồ sơ khớp" → MUST chuyển `PATIENT_NOT_FOUND`; không tạo patient | Q-2 (xem rủi ro diễn giải ở §6) |
| §2.1 | Inbound `TRANSFERRED`: chỉ chấm `outcome` lượt cuối + writelog rỗng; **không chấm `transfer_reason`** | Chọn lý do ở inbound không ảnh hưởng điểm; outbound thì có |
| §3.3 SF-03 | Ví dụ lỗi: câu có chi tiết lịch khi "state was still AWAITING_IDENTITY" | Lượt xác minh xong phải chuyển state trước/cùng lúc với câu có lịch (đã đúng: `AWAITING_INTENT`) |
| §5 | 25% điểm cho "severe failures **and recovery rate after a misunderstanding**" | Nên cho hỏi lại một lần thay vì chuyển máy ngay khi `NONE`/`INVALID` |
| §6.1 | Đội tự thiết kế cách xác minh bằng hội thoại và cách phục hồi khi người gọi ngập ngừng | Quy tắc tiến triển, câu `ASK_DOB_INVALID` là lựa chọn của đội |
| §8.3 | Nên hỏi chương trình khi có điểm mơ hồ thật | Q-2, Q-3 gửi `#residency-batch03` |
| Listing 1 | Response `POST /v1/calls` không có `ended`/`outcome` | Lượt 0 không kết thúc được → chuyển máy sớm nhất ở lượt 1 |
| Hình 0 | Outbound: "Cho em hỏi em đang nói chuyện với anh chị nào ạ?" → "Nguyễn Văn A." → "Dạ, anh cho em xin ngày tháng năm sinh để em đối chiếu ạ." Inbound: người gọi mở đầu "tôi muốn đặt lịch khám"; tra cứu `GET /patients?phone=%2B849…` (số dạng `+84`) | Giữ câu chào hiện tại (trùng Hình 0). G-8. `normalize_phone` của T-01 đã xử lý `+84` |

## 3. Thiết kế

### 3.1 Luồng bước danh tính

```text
Lượt 0  opening(ctx)
  prepare = verifier.prepare(ctx)                 # dùng GIÁ TRỊ TRẢ VỀ, không đọc ctx.identity_lookup
  prepare.transfer_reason is None -> _ask(ASK_NAME, greeting(direction))   AWAITING_IDENTITY
  khác                            -> BotAction(greeting_handoff(direction)) AWAITING_IDENTITY, question=None

Lượt n  Policy.check_preconditions
  chưa VERIFIED và ctx.identity_lookup ∈ {NO_PHONE, NO_CANDIDATES, UNAVAILABLE}
        -> TRANSFER(PrepareResult(LookupStatus(...)).transfer_reason)   # trước IE, im lặng, voicemail
  ... IE, check_silence, check_signals (không đổi) ...
  Dialogue._identity(ctx, ex)
    điền ex.full_name nếu còn thiếu tên; điền ex.dob nếu còn thiếu DOB và là date
    progressed = có ít nhất một trường CÒN THIẾU vừa được điền
    intent CANNOT_PROVIDE  -> hỏi lại mềm (ASK_*_DECLINED)          understanding DECLINED  (Q-3)
    intent nghiệp vụ, không có tên/DOB
                           -> ASK_NAME_FOR_REQUEST                   understanding UNCLEAR   (G-8)
    thiếu tên              -> ASK_NAME (lần đầu sau DOB: ASK_NAME_AFTER_DOB; lỗi: ASK_NAME_AGAIN)
    thiếu DOB, dob INVALID -> ASK_DOB_INVALID
    thiếu DOB              -> ASK_DOB / ASK_DOB_AGAIN
    đủ cả hai              -> verifier.verify(ctx)
        VERIFIED -> identity_step=VERIFIED, patient_id; inbound ASK_INTENT; outbound đọc lịch
        khác     -> transfer(result.transfer_reason)                      # chuyển ngay
    understanding còn lại = UNDERSTOOD nếu progressed, ngược lại NOT_UNDERSTOOD
  Policy.register_understanding
    2 lần liên tiếp không hiểu (UNCLEAR từ lần 2) -> TRANSFER(NOT_UNDERSTOOD)
    DECLINED: lần 1 -> hỏi lại; lần 2 liên tiếp  -> TRANSFER(IDENTITY_FAILED)
```

- **`CANNOT_PROVIDE` (Q-3):** nhãn intent mới, chỉ chạy ở bước danh tính (thêm vào `IDENTITY_SAFE_INTENTS`), cụm tường minh: "không nhớ", "không biết", "quên mất", "không muốn nói / cung cấp", "không tiện nói". Chỉ gán khi **không** trích được tên/DOB — "Tôi không nhớ tên hồ sơ" (TC_IEN_57) vẫn không phải tên.
- **Intent nghiệp vụ ở bước danh tính (G-8):** chạy như nhánh `OUT_OF_SCOPE` hiện có (chỉ khi không trích được tên **và** DOB), theo hướng gọi: inbound `BOOK`; outbound `CONFIRM`/`CANCEL`/`RESCHEDULE`. Không lưu intent này để dùng sau xác minh (thuộc T-04/T-11); sau xác minh vẫn hỏi `ASK_INTENT` như cũ.

- **Tương thích stub của tester:** `_RecordingVerifier.prepare()` trả `LOADED` nhưng không ghi `ctx.identity_lookup` (còn `PENDING`). Vì vậy `opening()` quyết theo giá trị trả về, Policy coi `PENDING` là không chặn, và invariant FSM chỉ áp khi `VERIFIED` (stub luôn trả `MISMATCH`).
- `identity_step` giữ nguyên kiểu (FSM, test và NER test đọc nó) nhưng được **suy ra**: thiếu tên → `ASK_NAME`, còn lại → `ASK_DOB`. `question_id` theo `identity_step`.
- Không thêm trường vào `CallContext` nếu chốt Q-1 phương án A → giữ `SCHEMA_VERSION = 1`.
- Thất bại dùng `t.TRANSFER` chung; **không** dùng `detail` để nói gì với người gọi.

### 3.2 IE ở `ASK_NAME` (G-2)

- `extract`: `question is ASK_NAME` → chạy `extract_dob(transcript, today)`. Ngày sinh là **ngày hợp lệ** → trích tên trên phần đứng trước ngày sinh (`full_name.name_before_dob`).
- *Khác bản nháp:* `dob.span` là cả câu đã chuẩn hóa, không dùng để cắt được. `name_before_dob` cắt theo dấu hiệu: dấu phẩy, chữ số, "ngày/mùng/mồng", "sinh" + từ ngày tháng, dãy số đọc + "tháng".
- *Khác bản nháp:* không tách khi `dob == INVALID` — mọi câu có chữ số đều ra INVALID ("bảo hiểm có chi trả 80% không"), tách thì phần trước thành "tên" rác và chặn mất `OUT_OF_SCOPE`.
- Không tách chắc chắn ("Nguyễn Văn Sinh 14/3/1978", "Nguyễn Văn Tám mười bốn tháng ba…") → tên `NONE` (hướng an toàn: hỏi lại, không đoán).
- NER tuyến sau (`_full_name`) chạy trên phần đã bỏ DOB, không phải transcript gốc.
- TC_IEN_49 (`ASK_NAME`, "14/03/1978" → `full_name` không found) vẫn đúng. Cập nhật docstring thứ tự trong `extractor.py` và test `test_dob_only_when_asked`.
- Giữ nguyên: bước danh tính chỉ chạy intent an toàn; `OUT_OF_SCOPE` chỉ khi không trích được tên **và** DOB.

### 3.3 Câu thoại mới (`dialogue/templates.py`)

| Hằng số | Nội dung (nháp) | Dùng khi |
| --- | --- | --- |
| `GREETING_HANDOFF_INBOUND` / `_OUTBOUND` | "Dạ Vinmec xin nghe, em là {AI_DISCLOSURE} của tổng đài. Em xin phép chuyển máy tới nhân viên để hỗ trợ anh chị ạ." | Lượt 0 khi tra cứu không `LOADED` (Q-2). Không nói "số này chưa có hồ sơ" |
| `ASK_DOB_INVALID` | "Dạ, anh chị vui lòng nói đủ ngày, tháng, năm sinh theo dương lịch giúp em ạ." | `dob == INVALID` |
| `ASK_NAME_AFTER_DOB` | "Dạ, anh chị cho em xin thêm họ và tên đầy đủ ạ." | Đã có DOB, còn thiếu tên |
| `ASK_NAME_FOR_REQUEST` | "Dạ vâng, để hỗ trợ anh chị, em cần xác minh thông tin trước. Anh chị cho em xin họ và tên đầy đủ ạ." | G-8 |
| `ASK_DOB_DECLINED` / `ASK_NAME_DECLINED` | "Dạ, em cần ngày tháng năm sinh để xác minh đúng người trước khi hỗ trợ. Anh chị vui lòng cho em xin ạ." | Q-3, lần 1 |

Mọi câu phải qua `_assert_open_question` và TC_SF03_09.

### 3.4 Policy và FSM

- `PolicyEngine.check_preconditions`: thêm nhánh tra cứu lượt 0 thất bại, **sau** kiểm tra `appointment_id`/hướng gọi, **trước** `max_turns`.
- `Understanding` thêm `"DECLINED"`; `register_understanding` đếm `DECLINED` bằng chính `unclear_streak`/`failed_understandings` (không thêm trường Session), chỉ khác lý do khi đạt ngưỡng: lượt đạt ngưỡng là `DECLINED` → `IDENTITY_FAILED`, còn lại → `NOT_UNDERSTOOD`. `check_silence`, `check_signals` không đổi.
- `fsm.check_invariants`: `identity_step == "VERIFIED"` ⇒ `identity_lookup == "LOADED"` và `patient_id` có giá trị.

## 4. Các bước thực hiện

| Bước | Việc | File | Phụ thuộc |
| --- | --- | --- | --- |
| 0 | Chốt Q-1..Q-4. Push `feature/llm-gateway-name-ner`, mở PR, merge; tạo `feature/t02-identity-dialogue` từ `main` mới (tránh xung đột `full_name.py` / `extractor.py`) | — | — |
| 1 | Review 2 file A bị T-01 chạm (`context.py`, `manager.py`) — đã merge, chỉ cần đọc lại | — | 0 |
| 2 | IE: trích DOB + tên ở `ASK_NAME` (§3.2); nhãn `CANNOT_PROVIDE`; intent nghiệp vụ ở bước danh tính khi không có tên/DOB (G-8) + unit test: tên + DOB số / đọc chữ / không dấu; tên + DOB INVALID; chỉ DOB; tên chứa "Sinh" không bị cắt nhầm; NER nhận phần đã bỏ DOB; "không nhớ", "quên rồi" (có dấu / không dấu); "tôi muốn đặt lịch" ở `ASK_NAME`; "Lê Văn Thôi" vẫn là tên | `extraction/extractor.py`, `intent.py`, `schema.py`, `tests/engine/extraction/` | 0 |
| 3 | Câu thoại mới (§3.3) | `dialogue/templates.py` | — |
| 4 | `opening()` rẽ nhánh; viết lại `_identity` theo §3.1 | `dialogue/manager.py` | 2, 3 |
| 5 | `check_preconditions` chuyển máy khi tra cứu lượt 0 thất bại | `policy/policy_engine.py` | 4 |
| 6 | Invariant FSM + test | `session/fsm.py`, `tests/engine/session/test_context_fsm.py` | 4 |
| 7 | Sửa test bị ảnh hưởng (§5.1) và thêm test mới (§5.2) | xem §5 | 4–6 |
| 8 | Đồng bộ tài liệu: IE design §6.2 + phụ lục; kiến trúc §5 (Dialogue, Policy); `information-extraction.md` luồng `ASK_NAME`; bỏ comment TODO T-02 trong `opening()` | docs | Q-1 |
| 9 | `make check`; viết `docs/evidence/t02-identity-dialogue.md` | — | tất cả |

## 5. Test

### 5.1 Test hiện có sẽ đổi kỳ vọng

Nguyên nhân chung: số không có hồ sơ → cuộc gọi kết thúc ở lượt 1, nên lượt 2 bị từ chối `CALL_ENDED`.

| Test | Owner | Sửa |
| --- | --- | --- |
| `identity_cases.py::TC_ID_13` | A | Lượt 1 đã `TRANSFERRED/PATIENT_NOT_FOUND`, bỏ lượt DOB |
| `verification/test_identity_flow.py::test_unregistered_inbound_caller_never_triggers_a_write` | B | Chỉ gửi lượt 1 (Q-4) |
| `verification/test_identity_flow.py::test_outbound_mock_down_at_turn_zero_becomes_system_error_not_identity_failed` | B | Chỉ gửi lượt 1 (Q-4) |
| `extraction/test_ner.py::test_orchestrator_uses_normalized_name_or_reprompts` | A | Đổi `caller_number` `0900000000` → `0912345600` (số có hồ sơ trong fake) |
| `llm/test_gateway.py` (case `gateway-ner`, dòng ~270) | A | Như trên |

Không đổi: TC_ID_07 và TC_SF03_03 (DOB khi được hỏi tên → vẫn hỏi tên), TC_IEN_49..58, `test_opening_discloses_ai_assistant` (số `+84987654321` chuẩn hóa ra `0987654321`, có trong fake).

### 5.2 Test mới (qua `CallOrchestrator` thật + `FakeClinicAPI`)

| Nhóm | Case | Kỳ vọng |
| --- | --- | --- |
| Lượt 0 | inbound số lạ / không số / mock lỗi; outbound mock lỗi | Lượt 0 không hỏi tên, có công bố AI; lượt 1 `TRANSFERRED` với lý do đúng, kể cả khi lượt 1 là im lặng; inbound `writes == []` |
| Hỏi mở | tên + DOB một câu; DOB trước rồi tên | `AWAITING_INTENT` ở lượt tương ứng; outbound chỉ đọc lịch ở lượt xác minh |
| INVALID | 31/02; thiếu năm; "năm 78" mơ hồ; tuổi thay năm | `ASK_DOB_INVALID`; lần 2 liên tiếp → `NOT_UNDERSTOOD` (outbound ghi `/transfer`, inbound không ghi) |
| Tiến triển | đang thiếu tên, người gọi đọc lại DOB hai lần | Lượt lặp không reset bộ đếm → chuyển máy |
| Từ chối cung cấp | outbound "tôi không nhớ ngày sinh" ×2; ×1 rồi đọc đúng; inbound ×2 | outbound ×2 → `IDENTITY_FAILED` + `/transfer`; ×1 rồi đúng → `AWAITING_INTENT`; inbound ×2 → `TRANSFERRED`, không ghi |
| Nói nhu cầu trước | inbound "tôi muốn đặt lịch khám" ở lượt 1 rồi tên + DOB (Hình 0); lặp lại | Lần 1 không tính, hỏi tên; theo ngữ nghĩa `UNCLEAR` lần 2 tính 1, lần 3 → `NOT_UNDERSTOOD`; không lộ lịch / slot |
| Nhắc lại | "gì cơ" ở `ASK_NAME` / `ASK_DOB`, xen giữa hai lần không hiểu | Đọc lại nguyên câu; bộ đếm giữ nguyên |
| Im lặng | 3 lượt im lặng ở bước danh tính; im lặng xen giữa lượt không hiểu | outbound `UNREACHABLE/SILENCE`; inbound `TRANSFERRED`; bộ đếm không hiểu không đổi |
| Không khớp | câu thoại lúc TC_ID_02..04 | Không chứa "tên" / "ngày sinh" đi kèm "chưa khớp" / "không đúng" |
| SF-03 | Mọi lượt trước `VERIFIED` ở các nhánh trên | Không chứa giờ, ngày, khoa, cơ sở, tên/DOB chuẩn |
| HTTP | Tên + DOB một câu qua `/v1/calls/{id}/turn` | `AWAITING_INTENT` sau lượt 1 |

## 6. Quyết định — đề xuất (chờ duyệt)

### Q-1. Giới hạn hỏi lại → bộ đếm chung + quy tắc tiến triển

- **Đề xuất:** dùng bộ đếm §1.1.5 hiện có (2 lần liên tiếp không hiểu → `NOT_UNDERSTOOD`), thêm quy tắc: ở bước danh tính, một lượt chỉ tính "hiểu" khi điền được trường **còn thiếu**. Không có bộ đếm riêng từng trường.
- **Căn cứ:** §1.1.5 chỉ đặt một ngưỡng (hai lần liên tiếp); không điều khoản nào đặt giới hạn riêng cho danh tính; §6.1 để đội tự thiết kế cách phục hồi; §5 chấm "recovery rate" nên không nên chuyển máy sớm hơn ngưỡng. Kiến trúc §3.3 đã viết đúng như vậy.
- **Hệ quả:** không thêm trường Session, giữ `SCHEMA_VERSION = 1`. Sửa IE design §6.2 ("tối đa 1 lần mỗi trường" → "theo ngưỡng §1.1.5 + tiến triển").
- **Loại:** đếm riêng mỗi trường — thêm trạng thái, có thể chuyển máy trước ngưỡng hợp đồng (ví dụ tên hỏng 1 lần, DOB đúng, tên hỏng lần 2 không liên tiếp), giảm điểm phục hồi.

### Q-2. Lượt 0 khi tra cứu thất bại → không hỏi tên, lượt 1 chuyển máy

- **Đề xuất:** lượt 0 chào + công bố AI + báo chuyển nhân viên (không nói lý do); lượt 1 chuyển máy bất kể input. Inbound: `PATIENT_NOT_FOUND`, không ghi. Outbound mock lỗi: `SYSTEM_ERROR`.
- **Căn cứ:** §1.1.9 "If no single record matches, the bot MUST transfer with PATIENT_NOT_FOUND"; §2.1 inbound chỉ chấm `outcome` lượt cuối + writelog rỗng — hai phương án có cùng kết quả chấm, phương án này ngắn hơn 2 lượt (latency/cost §5 15%) và đúng luồng PDF đã duyệt ở T-01.
- **Rủi ro diễn giải:** §1.1.9 cũng viết bot "MUST still obtain name and date of birth". Đọc cùng câu, "still" nghĩa là *dù đã tìm được hồ sơ bằng số điện thoại vẫn phải hỏi* — không có hồ sơ thì không còn gì để xác minh. Nhưng câu này là MUST, nên hỏi `#residency-batch03` (§8.3) để khóa diễn giải. Nếu chương trình trả lời "phải hỏi", đổi lại chỉ tốn một nhánh trong `opening()` và Policy.
- **Loại:** hỏi tên + DOB rồi mới chuyển — an toàn về câu chữ nhưng tốn 2 lượt vô ích và hỏi thông tin cá nhân của người không có hồ sơ.

### Q-3. Người gọi không nhớ / không muốn cung cấp → `IDENTITY_FAILED` ở lần 2 liên tiếp

- **Đề xuất:** nhãn IE mới `CANNOT_PROVIDE` (G-9). Lần 1: hỏi lại mềm, giải thích cần xác minh (phục hồi). Lần 2 liên tiếp: chuyển `IDENTITY_FAILED` (outbound ghi `/transfer`). Câu không trích được gì khác vẫn theo `NOT_UNDERSTOOD`.
- **Căn cứ:** §1.1.1 "MUST obtain the patient's name and date of birth … On failure it MUST transfer" — không lấy được định danh là **xác minh thất bại**, không phải "không hiểu": bot hiểu rõ người gọi nói không nhớ. §1.1.5 "failed understandings" dành cho câu bot không hiểu. Outbound có chấm `transfer_reason` (§2.1 chỉ miễn cho inbound), nên chọn sai lý do là mất case.
- **Chưa chắc chắn:** hợp đồng không có ví dụ cho trường hợp này; gửi kèm câu hỏi ở Q-2 lên `#residency-batch03`. TC_ID_08 ("không nhớ" → hỏi lại DOB) vẫn đúng.
- **Loại:** giữ `NOT_UNDERSTOOD` — ít việc hơn nhưng trái nghĩa §1.1.1 / §1.1.5.

### Q-4. Test của B bị đổi kỳ vọng → A sửa trong PR T-02, B review

- **Đề xuất:** sửa 2 test trong `tests/engine/verification/test_identity_flow.py` ngay trong PR T-02 (chỉ bỏ lượt DOB sau khi cuộc gọi đã kết thúc, giữ nguyên mọi assert về request / writes), ghi rõ trong evidence và tag B review.
- **Căn cứ:** CI (`.github/workflows/ci.yml`) chạy toàn bộ test, để B sửa sau thì `main` đỏ; task-breakdown §9 cho phép chạm phần người khác nếu ghi rõ trong evidence.

### Câu hỏi gửi `#residency-batch03` (§8.3)

1. §1.1.9: inbound mà `GET /patients?phone=` không trả hồ sơ nào — bot có bắt buộc hỏi tên + DOB trước khi chuyển `PATIENT_NOT_FOUND` không?
2. §1.1.1: outbound, người nghe nói không nhớ / không muốn cung cấp ngày sinh — `transfer_reason` mong đợi là `IDENTITY_FAILED` hay `NOT_UNDERSTOOD`?

## 7. Rủi ro

| # | Rủi ro | Giảm thiểu |
| --- | --- | --- |
| R-1 | Tách DOB khỏi tên cắt nhầm tên có chữ "Sinh" | Chỉ cắt khi có `dob.span`; test tên chứa "Sinh"; không tách được → `NONE` |
| R-2 | Harness gửi thêm lượt sau khi bot kết thúc ở lượt 1 (khách chưa đăng ký) | F-03 đã trả `CALL_ENDED`; kiểm lại với kịch bản mẫu Listing 2 |
| R-3 | Outbound: người gọi nói tên thiếu họ → `MISMATCH` → chuyển ngay | Câu hỏi lại xin "họ và tên đầy đủ"; tên < 2 từ đã là `NONE` → được hỏi lại. Giữ câu chào "anh chị nào" vì trùng Hình 0 |
| R-5 | Nhãn `CANNOT_PROVIDE` bắt nhầm câu có tên ("không nhớ… à, Nguyễn Văn A") | Chỉ gán khi không trích được tên/DOB; tên/DOB hợp lệ luôn thắng |
| R-6 | Q-2 / Q-3 bị chương trình trả lời ngược đề xuất | Mỗi quyết định nằm ở một nhánh (`opening()` + precondition; ngưỡng `DECLINED`) — đổi không ảnh hưởng phần còn lại |
| R-4 | Nhánh NER chưa push, T-02 cũng sửa `extractor.py` | Merge NER trước (bước 0) |

## 8. Ngoài phạm vi

- So khớp tên mờ / căn từ cuối (IE design §5.1 bước 2–6) — Verifier, B.
- `verification/phone.py::normalize_phone` — **không sửa**: định dạng số gắn với regex của clinic mock (T-01, B).
- Đưa `prepare.to_trace()` / `verify.to_trace()` vào trace — R-02.
- Output Guard tập trung — R-01; T-02 chỉ dựa vào `assert_can_disclose` trong câu mẫu.

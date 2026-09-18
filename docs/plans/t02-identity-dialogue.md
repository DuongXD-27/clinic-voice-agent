# Plan T-02 — Luồng hỏi và xác minh danh tính

**Owner:** A (Hoàn) · **Trạng thái:** Nháp, chờ chốt Q-1..Q-4 · **Ngày:** 18-09-2026
**Nguồn:** `docs/task-breakdown.md` §3 (T-02), §7 bất biến 1, 8, 9; `docs/reference/ai-callbot-architecture.md` §3.1–§3.3; `docs/reference/information-extraction-design.md` §5.1, §5.2, §6.1–§6.3; contract rev 1.1 §1.1.1–§1.1.2, §1.1.5, §1.1.7, §1.1.9, SF-03
**Phụ thuộc:** T-01 (`origin/feature/t01-identity-verifier`, **chưa merge**), F-04 (IE trên đường HTTP), F-03 (Session/FSM)

## 1. Mục tiêu và điều kiện hoàn thành

> Hỏi mở tên/DOB; xử lý thiếu dữ liệu, DOB không hợp lệ và yêu cầu lặp lại; giới hạn hỏi lại; nối kết quả Verifier vào FSM.
> **Điều kiện hoàn thành:** Chỉ được đọc lịch **sau** xác minh; thất bại đi đúng nhánh chuyển nhân viên.

T-01 đã làm phần Verifier (`prepare()` ở lượt 0, `verify()` không I/O). T-02 là phần **hội thoại** quanh nó: hỏi gì, nhận gì, hỏi lại bao nhiêu lần, và mỗi kết quả đi vào nhánh nào.

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | Lượt 0 rẽ nhánh theo `PrepareResult`: `LOADED` → chào + hỏi mở họ tên; không `LOADED` → chào (vẫn công bố AI) **không hỏi tên**, lượt 1 chuyển máy với `prepare.transfer_reason` bất kể input | Test orchestrator: inbound số lạ → lượt 1 `TRANSFERRED/PATIENT_NOT_FOUND`, `fake.writes == []`; outbound mock lỗi lượt 0 → lượt 1 `SYSTEM_ERROR` |
| AC-2 | Hỏi mở, nhận **phần còn thiếu**: người gọi nói cả tên + DOB trong một câu → xác minh luôn; chỉ nói DOB khi được hỏi tên → giữ DOB, hỏi tên; chỉ hỏi lại trường còn thiếu | Test: "Nguyễn Văn A, sinh 14/3/1978" → `AWAITING_INTENT` sau 1 lượt; DOB trước tên → 2 lượt |
| AC-3 | DOB `INVALID` (31/02, thiếu năm, năm 2 chữ số mơ hồ, âm lịch/tuổi) → câu hỏi lại riêng yêu cầu đủ ngày–tháng–năm dương lịch; **không** gọi Verifier | Test từng dạng INVALID → câu `ASK_DOB_INVALID`, `verify` không chạy |
| AC-4 | Xin nhắc lại ("gì cơ", "nói lại") ở bước danh tính → đọc lại đúng câu đang chờ, không tính vào bộ đếm | Test ở `ASK_NAME` và `ASK_DOB` |
| AC-5 | Giới hạn hỏi lại (xem Q-1): không trích được / INVALID lặp tới ngưỡng → chuyển `NOT_UNDERSTOOD`; im lặng đếm riêng (outbound 3 → `UNREACHABLE/SILENCE`, inbound 3 → `TRANSFERRED`) | Test ma trận §6 |
| AC-6 | Đủ tên + DOB hợp lệ mà không khớp → **chuyển ngay**, không hỏi lại, không nói trường nào sai: outbound `IDENTITY_FAILED` + `POST /transfer`; inbound `PATIENT_NOT_FOUND`, không ghi | TC_ID_02..04, 13 + case mới; kiểm câu thoại không chứa "tên"/"ngày sinh" "chưa khớp" |
| AC-7 | FSM: rời `AWAITING_IDENTITY` chỉ khi `VERIFIED`; `VERIFIED` kéo theo `identity_lookup == LOADED` và có `patient_id` | Invariant mới trong `check_invariants` + test |
| AC-8 | Không đọc lịch trước xác minh (SF-03): không câu nào trước `VERIFIED` chứa chi tiết lịch hoặc dữ liệu chuẩn (`identity_reference`) | `test_sf03_appointment_disclosure.py` mở rộng thêm các nhánh mới |

## 2. Hiện trạng và khoảng cách

| # | Khoảng cách | Vị trí | Việc T-02 |
| --- | --- | --- | --- |
| G-1 | `opening()` gọi `prepare()` nhưng bỏ qua kết quả → khách chưa đăng ký bị hỏi 2 lượt rồi mới chuyển | `dialogue/manager.py::opening` (nhánh T-01) | Rẽ nhánh theo `PrepareResult`; lượt 1 chuyển qua `Policy.check_preconditions` |
| G-2 | IE chỉ trích DOB khi `ASK_DOB`; ở `ASK_NAME` câu có chữ số bị loại khỏi tên → "Nguyễn Văn A sinh 14/3/1978" thành `NONE`, bị tính không hiểu | `extraction/extractor.py`, `full_name.py` (loại câu chứa chữ số) | Ở `ASK_NAME` chạy thêm `extract_dob`; bỏ `span` DOB + cụm nối ("sinh ngày", "ngày sinh", "sinh năm") rồi mới trích tên |
| G-3 | `NONE` và `INVALID` dùng chung câu `ASK_DOB_AGAIN` | `manager.py::_identity` | Câu riêng cho `INVALID` |
| G-4 | `identity_step` tuyến tính ASK_NAME → ASK_DOB; không có "hỏi phần còn thiếu" | `_identity` | Suy bước tiếp từ `claimed_name` / `claimed_dob` |
| G-5 | Giới hạn hỏi lại chỉ là bộ đếm §1.1.5 chung; lượt đưa DOB khi đã có DOB vẫn được tính "hiểu" và reset bộ đếm | `policy_engine.py` | Quy tắc tiến triển (Q-1) |
| G-6 | FSM chưa ràng buộc `VERIFIED` với kết quả tra cứu / `patient_id` | `session/fsm.py::check_invariants` | Thêm invariant |
| G-7 | Tài liệu mâu thuẫn: IE design §6.2 "mỗi trường hỏi lại tối đa 1 lần" vs kiến trúc §3.3 "không có giới hạn danh tính riêng, dùng ngưỡng chung" | docs | Đồng bộ theo Q-1 |
| G-8 | `TC_ID_13` kỳ vọng hỏi tên + DOB rồi mới chuyển | `tests/engine/identity_cases.py` | Đổi kỳ vọng; chuyển TC_ID_14..17 của B từ `tests/engine/verification/test_identity_flow.py` về hoặc giữ nguyên (Q-4) |

## 3. Thiết kế

### 3.1 Luồng bước danh tính

```text
Lượt 0  opening(ctx)
  prepare = verifier.prepare(ctx)
  LOADED           -> _ask(ASK_NAME, greeting(direction))                     AWAITING_IDENTITY
  khác             -> BotAction(greeting_handoff(direction))                  AWAITING_IDENTITY (Q-2)

Lượt n  Policy.check_preconditions
  identity_lookup ∉ {LOADED, PENDING} và chưa VERIFIED
                   -> TRANSFER(PrepareResult(status).transfer_reason)         (trước IE, trước im lặng)
  ... IE, check_silence, check_signals (không đổi) ...
  Dialogue._identity(ctx, ex)
    nhận ex.full_name (nếu còn thiếu tên) và ex.dob (nếu còn thiếu DOB)
    progressed = có ít nhất một trường CÒN THIẾU vừa được điền hợp lệ
    thiếu tên              -> hỏi tên (ASK_NAME / ASK_NAME_AGAIN)
    thiếu DOB, dob INVALID -> ASK_DOB_INVALID
    thiếu DOB              -> ASK_DOB / ASK_DOB_AGAIN
    đủ cả hai              -> verifier.verify(ctx)
        VERIFIED           -> identity_step=VERIFIED, patient_id; inbound ASK_INTENT; outbound đọc lịch (CONFIRM_READBACK)
        khác               -> transfer(result.transfer_reason)                chuyển ngay, không hỏi lại
    understanding = UNDERSTOOD nếu progressed, ngược lại NOT_UNDERSTOOD
  Policy.register_understanding -> 2 lần liên tiếp -> TRANSFER(NOT_UNDERSTOOD)
```

- `identity_step` vẫn giữ (FSM và test dùng) nhưng được **suy ra** từ `claimed_*`: thiếu tên → `ASK_NAME`, còn lại → `ASK_DOB`. `question_id` theo `identity_step` để IE trích đúng trường.
- Không thêm trường mới vào `CallContext` nếu chọn Q-1 phương án A → không cần bump `SCHEMA_VERSION`.
- Lời thoại khi thất bại dùng `t.TRANSFER` chung; **không** dùng `VerificationResult.detail` để nói gì với người gọi (T-01 §5.6).

### 3.2 IE ở `ASK_NAME` (G-2)

- `extractor.extract`: `question is ASK_NAME` → chạy `extract_dob(transcript, today)`; nếu `dob.span` có, trích tên trên transcript đã bỏ `span` và các cụm nối ở cuối phần tên ("sinh ngày", "ngày sinh", "sinh năm", "sinh", dấu phẩy).
- Không tách được sạch (phần còn lại vẫn có chữ số, < 2 từ...) → tên `NONE`. Hướng an toàn: hỏi lại, không đoán.
- `ExtractionResult.dob` ở `ASK_NAME` không còn luôn là `skipped` — cập nhật docstring thứ tự trong `extractor.py` và test `test_dob_only_when_asked`.
- Ở `ASK_DOB`, người gọi nhắc lại tên kèm DOB: `extract_dob` đã tìm ngày trong câu, không cần đổi.
- Giữ nguyên: bước danh tính chỉ chạy intent an toàn; `OUT_OF_SCOPE` chỉ khi không trích được tên **và** DOB.

### 3.3 Câu thoại mới (`dialogue/templates.py`)

| Hằng số | Nội dung (nháp) | Dùng khi |
| --- | --- | --- |
| `GREETING_HANDOFF_INBOUND` / `_OUTBOUND` | "Dạ Vinmec xin nghe, em là trợ lý ảo AI của tổng đài. Em xin phép chuyển máy tới nhân viên để hỗ trợ anh chị ạ." | Lượt 0 khi không `LOADED` (Q-2). Không nói "số này chưa có hồ sơ" |
| `ASK_DOB_INVALID` | "Dạ, anh chị vui lòng nói đủ ngày, tháng, năm sinh theo dương lịch giúp em ạ." | `dob == INVALID` |
| `ASK_NAME_AFTER_DOB` | "Dạ, anh chị cho em xin thêm họ và tên đầy đủ ạ." | Đã có DOB, thiếu tên |

Mọi câu vẫn qua test `_assert_open_question` (không chứa `verify.*`, `display_name`, DOB chuẩn).

### 3.4 Policy (`policy/policy_engine.py`)

- `check_preconditions`: thêm nhánh tra cứu lượt 0 thất bại (§3.1). Đặt **sau** kiểm tra `appointment_id`/hướng gọi hiện có, **trước** `max_turns`.
- `register_understanding`: không đổi cơ chế; ngữ nghĩa "hiểu" ở bước danh tính do Dialogue gắn theo quy tắc tiến triển.
- Không đụng `check_silence` / `check_signals`: im lặng, lâm sàng, xin người thật, `NOT_PATIENT` đã chạy mọi lượt, kể cả bước danh tính.

### 3.5 FSM (`session/fsm.py`)

Thêm vào `check_invariants`:
- `identity_step == "VERIFIED"` ⇒ `identity_lookup == "LOADED"` và `patient_id` không rỗng.
- `state == "AWAITING_IDENTITY"` và `identity_lookup ∉ {PENDING, LOADED}` ⇒ `question is None` (không có câu hỏi danh tính đang chờ khi đã biết sẽ chuyển máy).

## 4. Các bước thực hiện

| Bước | Việc | File | Phụ thuộc |
| --- | --- | --- | --- |
| 0 | Chốt Q-1..Q-4. Commit/stash thay đổi NER đang dở trên `main`; review + merge PR T-01; tạo `feature/t02-identity-dialogue` từ `main` mới | — | B mở PR T-01 |
| 1 | Review 2 file A bị T-01 chạm (`context.py`, `manager.py`); quyết `SCHEMA_VERSION` (giữ 1, `.get`) | `session/context.py` | 0 |
| 2 | IE: trích DOB + tên ở `ASK_NAME` (§3.2) + unit test (tên + DOB số, DOB đọc chữ, không dấu, DOB INVALID kèm tên, chỉ DOB, tên có "sinh" giữa tên — không cắt nhầm) | `extraction/extractor.py`, `tests/engine/extraction/test_extractor.py` | — |
| 3 | Câu thoại mới (§3.3) | `dialogue/templates.py` | — |
| 4 | Viết lại `DialogueManager._identity` theo §3.1; `opening()` rẽ nhánh theo `PrepareResult` | `dialogue/manager.py` | 1, 2, 3 |
| 5 | `Policy.check_preconditions` chuyển máy khi tra cứu lượt 0 thất bại | `policy/policy_engine.py` | 4 |
| 6 | Invariant FSM (§3.5) + test | `session/fsm.py`, `tests/engine/session/test_context_fsm.py` | 4 |
| 7 | Test hội thoại (§5): cập nhật `identity_cases.py` (TC_ID_13 đổi kỳ vọng, TC_ID_18+ mới); mở rộng SF-03 cho nhánh mới; 1 test HTTP tên+DOB một câu | `tests/engine/identity_cases.py`, `test_identity.py`, `test_sf03_appointment_disclosure.py`, `tests/transports/http/test_calls.py` | 4–6 |
| 8 | Đồng bộ tài liệu: IE design §6.2 + phụ lục; kiến trúc §5 (Dialogue/Policy); `information-extraction.md` luồng `ASK_NAME` | docs | Q-1 |
| 9 | `make check`; viết `docs/evidence/t02-identity-dialogue.md` | — | tất cả |

## 5. Ma trận test (qua `CallOrchestrator` thật + `FakeClinicAPI`)

| Nhóm | Case | Kỳ vọng |
| --- | --- | --- |
| Lượt 0 | inbound số lạ / không có số / mock lỗi; outbound mock lỗi | Lượt 0 không hỏi tên, có công bố AI; lượt 1 `TRANSFERRED` (`PATIENT_NOT_FOUND` / `SYSTEM_ERROR`); inbound `writes == []` |
| Hỏi mở | tên → DOB (TC_ID_01, 12); tên + DOB một câu; DOB trước rồi tên | `AWAITING_INTENT` ở lượt tương ứng; outbound lượt xác minh mới đọc lịch |
| Thiếu / INVALID | "không nhớ" (TC_ID_08); 31/02; thiếu năm; "năm 78" mơ hồ; tuổi thay năm | Câu hỏi lại đúng loại; lần 2 liên tiếp → `NOT_UNDERSTOOD` (outbound ghi `/transfer`, inbound không ghi) |
| Tiến triển | DOB, rồi lại DOB, rồi lại DOB khi đang thiếu tên | Lượt DOB thứ hai không reset bộ đếm → chuyển máy, không lặp vô hạn |
| Nhắc lại | "gì cơ" ở `ASK_NAME` / `ASK_DOB`, xen giữa hai lần không hiểu | Đọc lại nguyên câu, bộ đếm giữ nguyên |
| Im lặng | 3 lượt im lặng trong bước danh tính; im lặng xen giữa lượt không hiểu | outbound `UNREACHABLE/SILENCE`; inbound `TRANSFERRED`; bộ đếm không hiểu không đổi |
| Không khớp | sai tên / sai DOB / sai cả hai (TC_ID_02..04); inbound 0 khớp, 2 khớp | Chuyển ngay sau lượt có đủ dữ liệu; lý do đúng hướng; câu thoại không nói trường nào sai |
| Ngoại lệ ở bước danh tính | xin gặp nhân viên, lâm sàng khẩn, "tôi là vợ anh ấy", hỏi bảo hiểm | `PATIENT_REQUEST` / `CLINICAL_QUESTION` / `IDENTITY_FAILED` / `OUT_OF_SCOPE`, trước xác minh |
| SF-03 | Mọi lượt trước `VERIFIED` ở các nhánh trên | Không chứa giờ, ngày, khoa, cơ sở, tên/DOB chuẩn |
| Bền vững | Restart giữa lượt tên và lượt DOB (store postgres) | Xác minh đúng, không gọi thêm Mock (T-01 đã có ở mức Verifier; thêm 1 case orchestrator) |

## 6. Quyết định cần chốt

| # | Câu hỏi | Đề xuất | Phương án khác |
| --- | --- | --- | --- |
| Q-1 | Giới hạn hỏi lại | **A:** dùng bộ đếm §1.1.5 chung (2 lần liên tiếp) + quy tắc tiến triển (lượt chỉ tính "hiểu" khi điền được trường còn thiếu). Khớp kiến trúc §3.3, không thêm trường Session. Sửa IE design §6.2 cho khớp | **B:** đếm riêng mỗi trường (tối đa 1 lần hỏi lại, IE design §6.2) — thêm 2 trường Session, bump schema, và đòi quyết lý do chuyển máy khi hết lượt |
| Q-2 | Lượt 0 khi tra cứu thất bại | Chào + công bố AI + báo chuyển máy, **không hỏi tên**; lượt 1 chuyển máy bất kể input (theo T-01 Q-1, luồng PDF) | Vẫn hỏi tên ở lượt 0, lượt 1 chuyển — ít lạ tai hơn nhưng trái luồng "Không có ứng viên → chuyển" |
| Q-3 | "Không nhớ / không muốn cung cấp ngày sinh" lặp lại: `NOT_UNDERSTOOD` hay `IDENTITY_FAILED`? | `NOT_UNDERSTOOD` (IE chưa có nhãn từ chối cung cấp; hành vi TC_ID_08 hiện tại). Ghi vào câu hỏi mở gửi PO vì outbound có chấm `transfer_reason` | `IDENTITY_FAILED` — cần thêm nhãn IE mới |
| Q-4 | Test luồng của B (`tests/engine/verification/test_identity_flow.py`, TC_ID_14..17) | Giữ nguyên chỗ B đặt; T-02 chỉ sửa kỳ vọng những case mà nhánh lượt 0 làm thay đổi | Gom về `identity_cases.py` |

## 7. Rủi ro

| # | Rủi ro | Giảm thiểu |
| --- | --- | --- |
| R-1 | Tách DOB khỏi tên cắt nhầm tên có chữ "Sinh" | Chỉ cắt khi có `dob.span`; test tên chứa "Sinh"; không tách được → `NONE` |
| R-2 | Harness gửi thêm lượt sau khi bot kết thúc ở lượt 1 (khách chưa đăng ký) | F-03 đã trả `CALL_ENDED` cho lượt sau khi kết thúc; kiểm lại với kịch bản mẫu Listing 2 |
| R-3 | Người gọi outbound chỉ nói tên, thiếu họ → `MISMATCH` → chuyển ngay | Câu chào và câu hỏi lại xin "họ và tên đầy đủ"; tên < 2 từ đã là `NONE` → được hỏi lại |
| R-4 | Branch T-01 chạm file của A, T-02 sửa cùng chỗ | Merge T-01 trước, T-02 rẽ nhánh sau; không làm song song trên `manager.py` |

## 8. Ngoài phạm vi

- So khớp tên mờ / căn từ cuối (IE design §5.1 bước 2–6) — Verifier, B, sau khi có dữ liệu tester.
- Đưa `prepare.to_trace()` / `verify.to_trace()` vào trace — R-02.
- Output Guard tập trung — R-01 (T-02 chỉ dựa vào `assert_can_disclose` trong câu mẫu).
- NER tên bằng LLM — đã có, tắt mặc định; T-02 không bật.

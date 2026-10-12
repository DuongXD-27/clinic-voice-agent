# Evidence: T-02 — Luồng hỏi và xác minh danh tính

**Owner:** A (Hoàn) · **Plan:** `docs/plans/t02-identity-dialogue.md` · **Ngày:** 18-09-2026

## Mục tiêu

Phần hội thoại quanh Verifier của T-01:
- Hỏi mở tên và ngày sinh, nhận phần còn thiếu.
- Xử lý ngày sinh không hợp lệ, xin nhắc lại, người gọi không nhớ / không cung cấp, người gọi nói nhu cầu trước khi xác minh.
- Giới hạn hỏi lại.
- Nối kết quả tra cứu hồ sơ (lượt 0) và kết quả đối chiếu vào Policy / FSM.

Điều kiện hoàn thành (task-breakdown §3): **chỉ đọc lịch sau xác minh; thất bại đi đúng nhánh chuyển nhân viên.**

Ngoài phạm vi: so khớp tên mờ (Verifier, B); `normalize_phone` (gắn với regex clinic mock, B); đưa kết quả Verifier vào trace (R-02); Output Guard tập trung (R-01).

Quyết định Q-1..Q-4 theo plan §6, đối chiếu contract rev 1.1:

| # | Quyết định | Căn cứ |
| --- | --- | --- |
| Q-1 | Giới hạn hỏi lại dùng bộ đếm §1.1.5 chung + quy tắc tiến triển (chỉ điền được trường còn thiếu mới tính là hiểu) | §1.1.5 chỉ có một ngưỡng; §5 chấm "recovery rate" |
| Q-2 | Tra cứu lượt 0 thất bại → lượt 0 không hỏi tên, lượt 1 chuyển máy | §1.1.9 "MUST transfer with PATIENT_NOT_FOUND"; §2.1; Listing 1 không cho kết thúc ở lượt 0 |
| Q-3 | Không nhớ / không cung cấp hai lần liên tiếp → `IDENTITY_FAILED` | §1.1.1: không lấy được định danh là xác minh thất bại, không phải "không hiểu" |
| Q-4 | A sửa 2 test luồng của B bị đổi kỳ vọng, B review | CI chạy toàn bộ test |

## Bằng chứng trong repo

| Tiêu chí | Vị trí code | Test chứng minh |
| --- | --- | --- |
| AC-1 Lượt 0 rẽ nhánh theo tra cứu hồ sơ: có hồ sơ → chào + hỏi mở tên; không số / không hồ sơ / Mock lỗi → chào công bố AI, **không hỏi tên**; lượt 1 chuyển máy bất kể người gọi nói gì (kể cả im lặng, lâm sàng) | `DialogueManager.opening` (dùng giá trị `prepare()` trả về); `PolicyEngine.check_preconditions` + `LOOKUP_TRANSFER_REASON`; `templates.greeting_handoff` | `test_identity_dialogue.py::test_unregistered_inbound_is_transferred_at_turn_one_without_asking_name[*]`, `::test_inbound_without_usable_phone_never_calls_mock`, `::test_inbound_lookup_failure_is_system_error_without_write`, `::test_outbound_unreadable_appointment_transfers_system_error_at_turn_one`, `::test_policy_lookup_table_matches_verifier`; TC_ID_13; `test_orchestrator.py::test_opening_discloses_ai_assistant` |
| AC-2 Nhận phần còn thiếu: tên + ngày sinh trong một câu → xác minh ngay; ngày sinh trước → giữ, chỉ hỏi tên | `InformationExtractor.extract` (ASK_NAME chạy thêm `extract_dob`); `full_name.name_before_dob`; `DialogueManager._identity` | `test_identity_dialogue.py::test_name_and_dob_in_one_answer_verifies_in_one_turn`, `::test_inbound_name_and_dob_in_one_answer`, `::test_dob_before_name_is_kept_and_only_name_is_asked`, `::test_name_and_dob_in_one_turn_over_http`; `test_extractor.py::test_name_and_dob_in_one_answer[*]` (9 dạng, gồm "Nguyễn Văn Sinh", "Trần Văn Năm", không dấu) |
| Tách tên không đoán: không chắc ranh giới thì tên `NONE`; chỉ tách khi ngày sinh là ngày hợp lệ | `name_before_dob` trả `None` khi "Sinh"/"Tám" có thể thuộc tên; extractor chỉ tách khi `dob` là `date` | `test_extractor.py::test_ambiguous_name_before_dob_is_not_guessed[*]`, `::test_name_is_only_split_from_a_valid_dob`, `::test_out_of_scope_with_digits_at_name_step_is_still_detected` |
| AC-3 Ngày sinh `INVALID` (31/02, thiếu năm, năm 2 chữ số mơ hồ, âm lịch, tuổi) → câu hỏi lại riêng, không gọi Verifier | `templates.ASK_DOB_INVALID`; `_identity` | `test_identity_dialogue.py::test_invalid_dob_gets_its_own_reprompt[*]` (5 dạng); TC_IEN_55, TC_IEN_56 |
| AC-4 Xin nhắc lại ở bước danh tính → đọc lại đúng câu đang chờ, không tính | `DialogueManager.respond` (`REPEAT_REQUEST` → `NEUTRAL`, có sẵn) | `::test_repeat_request_rereads_question_without_counting`, `::test_repeat_request_between_failures_keeps_the_count` |
| AC-5 Giới hạn hỏi lại: hai lượt liên tiếp không dùng được → `NOT_UNDERSTOOD` (outbound ghi `/transfer`, inbound không ghi); nhắc lại điều đã có không reset bộ đếm; im lặng đếm riêng | `_identity` (`progressed`); `PolicyEngine.register_understanding`, `check_silence` | `::test_invalid_dob_twice_transfers_not_understood`, `::test_inbound_invalid_dob_twice_transfers_without_write`, `::test_repeating_known_dob_does_not_reset_the_counter`, `::test_missing_name_twice_transfers_not_understood`, `::test_outbound_silence_during_identity_ends_unreachable`, `::test_inbound_silence_during_identity_transfers_without_write`, `::test_silence_between_failures_neither_resets_nor_counts` |
| Không nhớ / không cung cấp: hỏi lại một lần, lần hai liên tiếp → `IDENTITY_FAILED` | `Intent.CANNOT_PROVIDE` (chỉ bước danh tính, `intent.IDENTITY_ONLY`); `Understanding "DECLINED"` | `::test_cannot_provide_twice_is_identity_failed`, `::test_cannot_provide_once_then_answering_verifies`, `::test_inbound_cannot_provide_twice_transfers_without_write`; `test_extractor.py::test_cannot_provide_at_identity_step[*]`, `::test_cannot_provide_never_leaves_identity_step` |
| Nói nhu cầu trước khi xác minh (Hình 0, kịch bản Book): hỏi lại tên, lần đầu không tính, không dùng nhu cầu / không đọc slot | `extractor._IDENTITY_FALLBACK_INTENTS`; `_identity` (`UNCLEAR`) | `::test_request_before_identity_asks_to_verify_first`, `::test_request_before_identity_repeated_is_eventually_not_understood`; `test_extractor.py::test_business_intent_before_identity_is_labelled[*]` |
| AC-6 Đủ tên + ngày sinh mà không khớp → chuyển ngay, không hỏi lại, câu thoại không nói trường nào sai; outbound `IDENTITY_FAILED` + `/transfer`, inbound `PATIENT_NOT_FOUND`, không ghi | `DialogueManager._verify` | `::test_wrong_identity_transfers_at_once_without_saying_which_field`; TC_ID_02..04; `test_identity_flow.py` (TC_ID_14, hai hồ sơ khớp) |
| AC-7 FSM: đã xác minh ⇒ tra cứu lượt 0 `LOADED` và có `patient_id` | `fsm.check_invariants`; `_verify` chuyển `SYSTEM_ERROR` nếu Verifier trả VERIFIED mà thiếu `patient_id` | `test_context_fsm.py::test_verified_requires_loaded_reference_and_patient[*]` |
| AC-8 SF-03: không câu nào trước xác minh chứa chi tiết lịch / hồ sơ chuẩn | Câu thoại mới không chứa giá trị nào; `assert_can_disclose` trong câu mẫu có lịch (có sẵn) | `_assert_no_disclosure` trong các test luồng trên; `test_sf03_appointment_disclosure.py` (không đổi, xanh); `test_identity.py` (13 case) |

## File liên quan

Sửa (code):
- `src/callbot/engine/dialogue/manager.py` — `opening`, `_identity`, `_verify`
- `src/callbot/engine/dialogue/templates.py` — `greeting_handoff`, `ASK_NAME_AFTER_DOB`, `ASK_NAME_FOR_REQUEST`, `ASK_DOB_FOR_REQUEST`, `ASK_NAME_DECLINED`, `ASK_DOB_INVALID`, `ASK_DOB_DECLINED`
- `src/callbot/engine/extraction/extractor.py` — `dob` ở `ASK_NAME`; nhãn dự phòng ở bước danh tính
- `src/callbot/engine/extraction/full_name.py` — `name_before_dob`
- `src/callbot/engine/extraction/intent.py`, `schema.py` — `Intent.CANNOT_PROVIDE`, `IDENTITY_ONLY`
- `src/callbot/engine/policy/policy_engine.py` — `LOOKUP_TRANSFER_REASON`, `check_preconditions`, `Understanding "DECLINED"`
- `src/callbot/engine/session/fsm.py` — invariant xác minh

Test:
- Mới: `tests/engine/test_identity_dialogue.py` (33 test)
- Sửa (A): `tests/engine/extraction/test_extractor.py`, `test_ner.py`, `tests/llm/test_gateway.py`, `tests/engine/identity_cases.py` (TC_ID_13), `tests/engine/test_identity.py`, `tests/engine/test_orchestrator.py`, `tests/engine/session/test_context_fsm.py`, `tests/transports/http/test_calls.py`
- Sửa (B, Q-4): `tests/engine/verification/test_identity_flow.py` — hai test lượt 0 thất bại chỉ gửi lượt 1; giữ nguyên mọi assert về request / writes

Tài liệu: `docs/reference/information-extraction-design.md` §6.2 + phụ lục; `docs/reference/ai-callbot-architecture.md` §5; `docs/evidence/information-extraction.md` (luồng `ASK_NAME`).

## Luồng hiện tại

```text
POST /v1/calls (lượt 0) -> DialogueManager.opening
  prepare = Verifier.prepare(ctx)
  transfer_reason is None -> hỏi mở họ tên (ASK_NAME)                       AWAITING_IDENTITY
  khác                    -> greeting_handoff, không có câu hỏi đang chờ      AWAITING_IDENTITY

Lượt n -> Policy.check_preconditions
  tra cứu lượt 0 ∈ {NO_PHONE, NO_CANDIDATES, UNAVAILABLE}, chưa xác minh
          -> TRANSFER(PATIENT_NOT_FOUND | SYSTEM_ERROR)   (inbound không ghi Mock)
  -> IE (ASK_NAME: dob + tên trước ngày sinh; nhãn dự phòng khi không có tên / ngày sinh hợp lệ)
  -> Policy.check_silence / check_signals (không đổi: im lặng, voicemail, lâm sàng, xin nhân viên, OUT_OF_SCOPE)
  -> Dialogue._identity
       ghi claimed_name / claimed_dob; lời tự sửa đè giá trị cũ (R-44; chưa đối chiếu) -> progressed nếu điền trường thiếu / sửa sang giá trị khác
       đủ cả hai -> _verify: VERIFIED -> ASK_INTENT (inbound) | đọc lịch (outbound)
                              khác     -> chuyển máy theo transfer_reason, câu IDENTITY_FAILED_TRANSFER (12/10/2026)
       tiến triển   -> hỏi phần còn thiếu                   UNDERSTOOD
       dob INVALID  -> ASK_DOB_INVALID                      NOT_UNDERSTOOD
       CANNOT_PROVIDE -> ASK_*_DECLINED                     DECLINED
       nhu cầu nghiệp vụ -> ASK_*_FOR_REQUEST               UNCLEAR
       còn lại      -> ASK_NAME_AGAIN / ASK_DOB_AGAIN       NOT_UNDERSTOOD
  -> Policy.register_understanding: 2 lượt liên tiếp -> NOT_UNDERSTOOD (DECLINED -> IDENTITY_FAILED)
  -> SessionManager.transition / close (FSM: xác minh cần LOADED + patient_id)
```

## Quy trình xác minh

```powershell
make check
```

Chỉ phần T-02: `python -m pytest tests\engine\test_identity_dialogue.py tests\engine\test_identity.py tests\engine\extraction\test_extractor.py -q`

## Kết quả xác minh cục bộ (18-09-2026)

Chạy trên git worktree sạch tại `f520895` (`main` sau PR #14) + thay đổi T-02. Lý do: working tree cùng lúc có phần session (`store.py`, `manager.py`, `retention.py`, xóa `postgres/`) đang sửa dở, không thuộc T-02.

| Command | Kết quả |
| --- | --- |
| `python -m ruff check` (18 file T-02 chạm) | Pass |
| `python -m ruff format --check` (18 file T-02 chạm) | Pass |
| `python -m pytest -q` | Pass — 872 passed, 45 skipped |
| `python -m pytest -q tests/engine/test_identity_dialogue.py` | 33 passed |
| `python -m pytest -q tests/engine/extraction/test_extractor.py` | 37 passed |
| `python -m pytest -q tests/engine/test_identity.py tests/engine/test_sf03_appointment_disclosure.py tests/engine/verification` | 103 passed |
| `python -m pytest -q tests/engine/session/test_context_fsm.py` | 15 passed |

Mốc trước T-02 (cùng lệnh `tests/engine tests/transports tests/test_schema.py`): 738 passed, 45 skipped.

## Ghi chú

- **`dob.span` không dùng để cắt tên được** (là cả câu đã chuẩn hóa) → thêm `name_before_dob` cắt theo dấu hiệu (dấu phẩy, chữ số, "ngày/mùng/mồng", "sinh" + từ ngày tháng, dãy số đọc + "tháng"). Tên cắt sai bị Verifier chuyển máy ngay, nên mọi chỗ mơ hồ trả `NONE` để hỏi lại.
- **Chỉ tách tên khi ngày sinh hợp lệ.** Mọi câu có chữ số đều ra `INVALID`; tách ở đó thì "bảo hiểm có chi trả 80% không" thành tên rác và mất `OUT_OF_SCOPE`. Hệ quả: "Nguyễn Văn A, 31/02/1978" phải nói lại tên.
- **Nhu cầu nói trước xác minh** theo ngữ nghĩa `UNCLEAR` hiện có: lần 1 không tính, lần 2 tính 1, lần 3 chuyển `NOT_UNDERSTOOD`. Nhu cầu không được lưu để dùng sau xác minh (T-04 / T-11 quyết định nếu cần).
- **Q-2 và Q-3 là diễn giải của đội.** Nên hỏi `#residency-batch03` (§8.3): (1) inbound không có hồ sơ có bắt buộc hỏi tên + ngày sinh trước khi chuyển không; (2) outbound người nghe không nhớ ngày sinh mong đợi `IDENTITY_FAILED` hay `NOT_UNDERSTOOD`. Nếu trả lời ngược, mỗi quyết định nằm ở một chỗ (`opening` + `check_preconditions`; nhánh `DECLINED` trong `register_understanding`).
- **Policy giữ bảng tra cứu → lý do chuyển máy riêng** (`LOOKUP_TRANSFER_REASON`), không import `verification` để tránh vòng `verification → tools → policy`. Test `test_policy_lookup_table_matches_verifier` khóa hai bảng trùng nhau.
- **Điểm yếu có sẵn của IE, chưa sửa ở T-02:** một số câu không phải tên vẫn qua bộ lọc tên ("ờ để xem", "hủy lịch đi") → đi vào Verifier → `MISMATCH` → chuyển `IDENTITY_FAILED` thay vì hỏi lại. Nên xử lý cùng NER / danh sách từ không phải tên.
- `SCHEMA_VERSION` giữ 1: T-02 không thêm trường vào `CallContext`.

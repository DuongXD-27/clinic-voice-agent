# Evidence: T-08 — Silence và tín hiệu đường dây

**Owner:** A (Hoàn) · **Plan:** `docs/plans/t08-silence-line-signal.md` · **Branch:** `feature/t08-silence-line-signal` (từ `main` `bfcc529`) · **Ngày:** 21-09-2026

## Mục tiêu

Đếm silence riêng với không hiểu; xử lý voicemail; **outbound 3 silence → unreachable, inbound 3 silence → transfer**; chặn tiết lộ lịch trên voicemail.

Điều kiện hoàn thành (task-breakdown §3): **outcome và thao tác Mock đúng theo hướng gọi.**

Khung silence / voicemail đã có từ F-04 (IE `silent`, `line_signal`, `PolicyEngine.check_silence`) và F-05/T-07 (Gateway `/unreachable`). T-08 sửa hai lỗi làm bot ghi lịch khi người gọi chưa đồng ý câu xác nhận (G-1, G-6), cho câu nhắc im lặng hỏi lại câu đang chờ, mở rộng mẫu lời chào hộp thư, rồi khóa điều kiện hoàn thành bằng ma trận test hướng gọi × tín hiệu ở tầng Orchestrator và HTTP.

Quyết định (plan §6):

| # | Quyết định | Căn cứ |
| --- | --- | --- |
| Q-1 | Nhắc im lặng = "Alo, anh chị còn nghe máy không ạ?" + nguyên văn câu đang hỏi, tính là hỏi lại ở lượt đó | Chốt với owner 21-09-2026; kiến trúc §3.3 "hỏi lại tại bước hiện tại" |
| Q-2 | Thêm mẫu lời chào hộp thư cá nhân, chỉ những cụm người đã nghe máy gần như không nói | Chốt với owner 21-09-2026; §4.2.5 chỉ nói "clip lời chào" |
| Q-3 | Im lặng không reset, không tăng bộ đếm không hiểu (NU-S-NU → chuyển) | Giữ quyết định T-02; §1.1.7 |
| Q-4 | Voicemail chỉ nhận trước khi xác minh xong | Chi tiết lịch chỉ đọc sau `VERIFIED`; clip không thể đọc đúng tên + ngày sinh |

## Bằng chứng trong repo

Test mới ở `tests/engine/test_silence_line_signal.py` (42 test), trừ khi ghi khác.

| Tiêu chí | Vị trí code | Test chứng minh |
| --- | --- | --- |
| AC-1 Silence đếm riêng với không hiểu | `PolicyEngine.check_silence` (có sẵn): chỉ đụng `silent_turns`, lượt có lời reset về 0 | `test_speech_resets_silence_counter[outbound/inbound]`, `test_repeat_request_resets_silence_counter`, `test_silence_is_never_a_failed_understanding`, `test_failed_understandings_do_not_count_towards_silence`; `test_identity_dialogue.py::test_silence_between_failures_neither_resets_nor_counts` |
| AC-2 Outbound 3 silence → `UNREACHABLE/SILENCE`, đúng 1 lệnh `/unreachable`, `attempt_count` +1 | `check_silence` → `DialogueManager.unreachable` → `ClinicGateway.mark_unreachable` (có sẵn) | `test_outbound_three_silences_end_unreachable_at_every_step[*]` (7 bước: `ASK_NAME`, `ASK_DOB`, `CONFIRM_READBACK`, `ASK_INTENT`, `OFFER_SLOTS`, `SLOT_READBACK`, `CANCEL_RECONFIRM`); HTTP `test_calls.py::test_outbound_three_silences_over_http_mark_unreachable` |
| AC-3 Inbound 3 silence → `TRANSFERRED/NOT_UNDERSTOOD`, không ghi Mock | `check_silence` inbound → `transfer`; Gateway inbound chưa đặt lịch không ghi (có sẵn) | `test_inbound_three_silences_transfer_without_write_at_every_step[*]` (5 bước inbound, gồm chọn / chốt slot đặt lịch); HTTP `::test_inbound_three_silences_over_http_transfer_without_write` |
| AC-4 Voicemail outbound ở mọi lượt trước xác minh → `UNREACHABLE/VOICEMAIL` | `line_signal._VOICEMAIL` thêm mẫu lời chào cá nhân (Q-2) | `test_voicemail_ends_unreachable_without_disclosing[*]` (lượt 1, sau tên, sau 2 lượt im lặng, lời chào cá nhân Việt / Anh); `test_line_signal.py::test_line_signal[*]` (7 mẫu mới, có bản không dấu); HTTP `::test_voicemail_over_http_marks_unreachable_without_disclosing` |
| AC-4b Người thật đang bận không bị coi là hộp thư | Không thêm "không nghe máy được", "sẽ gọi lại cho bạn", "gọi lại sau" | `test_line_signal.py::test_human_speech_is_not_a_line_signal[*]` (9 câu bẫy mới); `test_human_who_is_busy_is_not_voicemail` |
| AC-5 Không tiết lộ lịch trên voicemail | `GOODBYE_UNREACHABLE` (có sẵn); `line_signal` chỉ chạy trước `VERIFIED`, lịch chỉ đọc sau `VERIFIED` | Quét **mọi** utterance của cuộc gọi (không chỉ câu cuối) tìm "14 tháng 10", "9 giờ", "Nội tổng quát", "Times City": `test_voicemail_ends_unreachable_without_disclosing[*]`, `test_three_silences_on_voicemail_never_disclose`, HTTP voicemail |
| AC-6 Nhắc im lặng không mở khóa lệnh ghi (G-1) | `DialogueManager.silence`: nói `t.SILENCE + " " + question.text`, `question.turn = ctx.turn` (Q-1); `guardrails.assert_action_confirmed`: `question.turn == item.turn - 1` (thay `<`) | `test_silence_prompt_repeats_the_pending_question[*]` (7 bước); `test_write_after_silence_only_answers_the_repeated_question[*]` (câu ngay trước lượt ghi chứa nguyên văn câu xác nhận — `CONFIRMED`, `RESCHEDULED`, `CANCELLED`); `test_context_fsm.py::test_confirmation_must_answer_question_asked_on_the_previous_turn` |
| AC-6b "Vâng" sau câu "em chưa hiểu" không ghi, không `SYSTEM_ERROR` (G-6) | `DialogueManager._answers_last_question`: AGREE cho câu hỏi không ở lượt ngay trước → nhánh chưa rõ, hỏi lại câu xác nhận; `respond` nhánh `REPEAT_REQUEST` cập nhật `question.turn` | `test_agree_after_not_understood_prompt_asks_again_instead_of_writing[*]` (3 câu xác nhận; đồng ý câu hỏi lại thì ghi đúng 1 lần) |
| AC-7 Kết quả ghi `/unreachable` | `DialogueManager.unreachable` + Gateway `_write` (có sẵn) | `test_rejected_unreachable_is_never_reported[invalid_state/version_conflict_twice]`; `test_version_conflict_once_retries_same_key_and_marks_once` (2 request cùng key `c_t08_conflict:3:unreachable`, `attempt_count == 1`); `test_unknown_unreachable_outcome_blocks_for_reconciliation`; HTTP `::test_unknown_unreachable_outcome_over_http_needs_reconciliation` (409 `CALL_RECONCILIATION_REQUIRED`) — lấp chỗ trống T-07 Ghi chú |
| AC-8 Inbound không bao giờ `UNREACHABLE` | `extractor`: `line_signal` chỉ chạy outbound (có sẵn) | `test_inbound_voicemail_wording_is_not_unreachable` |

### Trước / sau (Orchestrator + fake, outbound `apt_00417`)

| Chuỗi lượt | Trước T-08 | Sau T-08 |
| --- | --- | --- |
| Đọc lại → *im lặng* → "Alo, anh chị còn nghe máy không ạ?" → "vâng" | **ghi `CONFIRMED`** cho câu "còn nghe máy không" | câu nhắc đọc lại nguyên văn lịch; "vâng" đáp câu đó → `CONFIRMED` hợp lệ |
| Chốt slot → *im lặng* → "Alo..." → "đúng rồi" | **ghi `RESCHEDULED`** | câu nhắc chứa "Em chốt khung 10 giờ sáng …"; "đúng rồi" đáp câu đó |
| Chốt slot → "bla bla" → "Dạ, em chưa hiểu ý anh chị…" → "đúng rồi" | **ghi `RESCHEDULED`** | chưa rõ → "anh chị chọn khung 10 giờ … hay muốn nghe khung khác?", không ghi |
| Đọc lại → "bla bla" → "em chưa hiểu…" → "vâng" | **ghi `CONFIRMED`** | đọc lại lịch bằng câu có / không, không ghi |
| "Xin chào, bạn đã gọi đến số của Lan. Hiện không thể nghe máy" | câu không hiểu, hỏi lại tên | `UNREACHABLE/VOICEMAIL` |
| "tôi đang lái xe không nghe máy được, lát gọi lại sau giúp tôi" | hỏi lại tên | không đổi (người thật) |
| 3 silence outbound / inbound, voicemail có từ khóa, "gì cơ" → đọc lại → "đúng rồi" | — | không đổi |

## File liên quan

Sửa (code):
- `src/callbot/engine/dialogue/manager.py` — `silence` hỏi lại câu đang chờ; `respond` (`REPEAT_REQUEST`) cập nhật `question.turn`; `_answers_last_question` dùng ở `_attendance`, `_slot_readback`, `_cancel_reconfirm`; nhận câu chào mở đầu theo nội dung câu hỏi thay cho `turn == 0`
- `src/callbot/engine/policy/guardrails.py` — `assert_action_confirmed`: câu hỏi ở lượt ngay trước
- `src/callbot/engine/extraction/line_signal.py` — mẫu lời chào hộp thư cá nhân
- `src/callbot/engine/session/context.py` — docstring `Question`

Test:
- Mới: `tests/engine/test_silence_line_signal.py` (42 test)
- Thêm case: `tests/engine/extraction/test_line_signal.py`, `tests/engine/session/test_context_fsm.py`, `tests/transports/http/test_calls.py` (4 test HTTP)
- Đổi kỳ vọng câu nhắc im lặng: `tests/engine/test_confirm_dialogue.py::test_silence_and_repeat_request_keep_the_readback_question`, `tests/engine/test_identity_dialogue.py::test_silence_between_failures_neither_resets_nor_counts`, `tests/transports/http/test_calls.py::test_silence_and_empty_transcript_map_differently`, `::test_silence_turn_in_audio_mode_still_replies_with_audio`

Tài liệu: `docs/reference/information-extraction-design.md` §5.9; `docs/reference/ai-callbot-architecture.md` §3.3, §5 (Dialogue Manager); `docs/plans/t08-silence-line-signal.md`.

## Luồng hiện tại

```text
Lượt n: check_preconditions -> IE.extract(silence_ms)
  silent (silence_ms > 0)
     silent_turns += 1
     < 3            -> "Alo, anh chị còn nghe máy không ạ? " + câu đang hỏi; question.turn = n
     = 3, outbound  -> /unreachable {unreachable_reason: SILENCE}
                         thành công -> ENDED/UNREACHABLE, "em xin phép gọi lại sau" (không có chi tiết lịch)
                         từ chối     -> TRANSFERRED/SYSTEM_ERROR (không báo UNREACHABLE)
                         chưa rõ     -> 409 CALL_RECONCILIATION_REQUIRED
     = 3, inbound   -> TRANSFERRED/NOT_UNDERSTOOD, không ghi Mock
  có lời            -> silent_turns = 0
     outbound, trước VERIFIED, line_signal ≠ NONE -> /unreachable {VOICEMAIL | LINE_BUSY | NO_ANSWER}
     còn lại -> lâm sàng / intent luôn chuyển / Dialogue
       câu xác nhận: AGREE và question.turn == n - 1 -> ghi (guardrail kiểm lại cùng điều kiện)
                     AGREE cho câu hỏi cũ hơn        -> chưa rõ, hỏi lại câu xác nhận
```

## Quy trình xác minh

```powershell
make check
```

Chỉ phần T-08: `python -m pytest tests\engine\test_silence_line_signal.py tests\engine\extraction\test_line_signal.py tests\engine\session\test_context_fsm.py tests\transports\http\test_calls.py -q`

## Kết quả xác minh cục bộ (21-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass (164 file) |
| `python -m pytest -q` | Pass — 1229 passed, 24 skipped |
| `python -m pytest -q tests/engine/test_silence_line_signal.py` | 42 passed |
| Test mới chạy trên `src` của `main` (stash, trước khi thêm test G-6) | 19 fail — G-1, G-2, mẫu voicemail mới và guardrail đều bị bắt; G-6 xác nhận riêng bằng chạy thử (bảng Trước / sau) |

Mốc trước T-08 trên `main` `bfcc529`: 1166 passed, 24 skipped.

Contract test `live` (`CLINIC_MOCK_LIVE=1`): chưa chạy — T-08 không đổi Gateway / client.

## Ghi chú

- **Siết guardrail có thể chặn luồng khác:** mọi câu hỏi xác nhận hiện đi qua `_ask`, câu nhắc im lặng hoặc `REPEAT_REQUEST`, cả ba đều đặt `question.turn` bằng lượt đó. Nếu sau này có câu nhắc chung mới không đi qua ba đường trên, `_answers_last_question` sẽ đẩy AGREE sang nhánh chưa rõ (hỏi lại), không ghi. Guardrail không bị kích hoạt.
- **Câu nhắc im lặng ở `CONFIRM_READBACK` dài** (đọc lại toàn bộ lịch). Chấp nhận được vì người nghe đã xác minh. Câu nhắc lúc hỏi tên đọc lại cả câu chào có công bố trợ lý ảo AI.
- **Nội dung clip VOICEMAIL của harness vẫn chưa biết** (IE design §10 câu 9). Nên hỏi `#residency-batch03`; nếu clip dùng câu khác, thêm mẫu kèm câu bẫy người thật.
- **Chưa làm, thuộc task khác:**
  - `/unreachable` bị Mock từ chối vì trạng thái (lịch đã `CONFIRMED`: Mock chỉ cho `unreachable` từ `SCHEDULED`/`BOOKED`/`UNREACHABLE`) → bot trả `TRANSFERRED/SYSTEM_ERROR` mà không có lệnh `/transfer`, trái kiến trúc §4.2. Cùng lỗi T-04 đã ghi → T-06 / T-12.
  - Outbound tra cứu hồ sơ lượt 0 thất bại + voicemail: `check_preconditions` chuyển máy ở lượt 1 trước khi xét voicemail. Hiếm; không đổi.
  - Bộ đếm thứ ba "lỗi nhận dạng" (bất biến 9) cần tín hiệu ASR → S-01.
- `SCHEMA_VERSION` giữ 1: T-08 không thêm trường vào `CallContext`.

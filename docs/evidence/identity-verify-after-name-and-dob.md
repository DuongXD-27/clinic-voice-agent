# Evidence: Đối chiếu danh tính khi đủ tên + ngày sinh, chuyển máy có lý do (PR #111)

## Mục tiêu

Trước PR, bot so tên (hoặc ngày sinh) ngay khi vừa nghe và chuyển máy luôn nếu sai; tên lệch dấu thanh
thì hỏi lại tên ngay. Người gọi suy ra được yếu tố nào sai hay gần đúng: bị chuyển ngay sau khi khai
tên là tên sai, được hỏi lại tên là tên gần đúng, được hỏi sang ngày sinh là tên đúng (trái §1.1.2).
Câu chuyển máy cũng không nói lý do.

Sau PR: chỉ đối chiếu **một lần khi đã đủ tên và ngày sinh**; không khớp thì chuyển máy bằng câu có lý
do nhưng không nói yếu tố nào sai. Yếu tố sai chỉ ghi vào trace / log cho vận hành.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Không đối chiếu trường nào trước khi đủ tên + ngày sinh, kể cả tên lệch dấu | `DialogueManager._identity` chỉ ghi `claimed_name` / `claimed_dob`; `_verify` là nơi duy nhất gọi `IdentityVerifier.verify`. Đã bỏ `IdentityVerifier.compare_name` / `compare_dob`. Test `test_wrong_name_waits_for_dob_before_transferring_with_a_reason`, `test_tone_mismatch_is_not_compared_before_dob_and_never_authenticates` (`tests/engine/test_stage1_requirements.py`), các case `TC_ID_02/04/16/18` (`tests/engine/identity_cases.py`) |
| Tên lệch dấu thanh không bao giờ xác thực (R-22) | `match_record` trả `NAME_SUSPICIOUS`, `verify` ra `MISMATCH` / `PATIENT_NOT_FOUND`. Test `test_tone_mismatch_is_not_compared_before_dob_and_never_authenticates` |
| Chuyển máy có lý do, không nói yếu tố nào sai | `templates.IDENTITY_FAILED_TRANSFER`; `_verify` dùng câu này cho `MISMATCH` / `PATIENT_NOT_FOUND`, `SYSTEM_ERROR` giữ `TRANSFER`. Test `test_wrong_identity_transfers_at_once_without_saying_which_field` (`tests/engine/test_identity_dialogue.py`) |
| Lý do chi tiết cho vận hành, không chứa giá trị hồ sơ | `CallContext.identity_result` (lưu trong phiên), trace `identity_result` ở `orchestrator.py`, `logger.info` trong `_verify`. Trace inbound nhiều hồ sơ chọn hồ sơ gần khớp nhất theo `_MISMATCH_RANK` (đã thêm `NAME_SUSPICIOUS`). Test `test_trace_reason_prefers_the_closest_inbound_record` |
| Khách tự sửa ở lượt sau được nhận (R-44) | `_identity` để giá trị nói sau đè giá trị trước. `InformationExtractor` ở `ASK_DOB` đọc tên bằng luật khi câu có tín hiệu tự sửa / tự giới thiệu (`_names_oneself`). Test `test_name_corrected_while_asking_dob_replaces_the_earlier_name`, `test_dob_corrected_while_asking_name_replaces_the_earlier_dob`, `test_dob_answer_without_self_naming_never_replaces_the_name` |
| Đè giá trị không kéo dài vô hạn số lượt | Chỉ điền trường còn thiếu mới tính là hiểu. Test `test_repeating_known_dob_does_not_reset_the_counter`, `test_name_correction_alone_spends_the_dob_retry` |
| Audio tĩnh cho câu mới | Release `assets/tts/static/2026-10-08-v2` (74 WAV; 73 dùng lại nguyên audio v1, 1 câu mới thu bằng Vbee và được nghe duyệt). `config/tts_static.yaml` trỏ v2; `.dockerignore` loại v1 khỏi image. Test `test_shipped_catalog_covers_all_74_current_utterances_in_sync_and_stream` |

## File liên quan

- `src/callbot/engine/dialogue/manager.py`
- `src/callbot/engine/dialogue/templates.py`
- `src/callbot/engine/extraction/extractor.py`
- `src/callbot/engine/verification/identity.py`
- `src/callbot/engine/verification/names.py`
- `src/callbot/engine/session/context.py`
- `src/callbot/engine/orchestrator.py`
- `scripts/tts_utterance_catalog.py`, `docs/evidence/tts-static-cache/*-2026-10-08.*`
- `assets/tts/static/2026-10-08-v2/`, `config/tts_static.yaml`, `.dockerignore`
- `tests/engine/test_identity_dialogue.py`, `tests/engine/test_stage1_requirements.py`, `tests/engine/identity_cases.py`

## Luồng hiện tại

```text
lượt định danh (ASK_NAME / ASK_DOB)
  -> IE: ASK_NAME đọc tên + ngày sinh; ASK_DOB đọc ngày sinh, và tên (chỉ luật) khi có
         "nhầm" / "à không" / "tôi là" / "tên tôi là" ...
  -> _identity: PRESENT thì ghi claimed_name / claimed_dob (nói sau đè trước), không đối chiếu
       điền được trường thiếu      -> hỏi trường còn lại                 UNDERSTOOD
       chỉ đè trường đã có / thiếu  -> hỏi lại theo R-40 (tối đa một lần) NOT_UNDERSTOOD
       hết lượt hỏi lại             -> TRANSFERRED(NOT_UNDERSTOOD)
  -> đủ cả hai -> _verify (một lần)
       VERIFIED                     -> đọc lịch (outbound) | ASK_INTENT (inbound)
       MISMATCH / PATIENT_NOT_FOUND -> TRANSFERRED, IDENTITY_FAILED_TRANSFER,
                                       identity_result = NAME_MISMATCH | DOB_MISMATCH | ...
       UNAVAILABLE                  -> TRANSFERRED(SYSTEM_ERROR), câu TRANSFER chung
```

## Quy trình xác minh

```powershell
make check
```

Chỉ phần liên quan: `python -m pytest tests\engine\test_identity_dialogue.py tests\engine\test_stage1_requirements.py tests\engine\test_identity.py -q`

## Kết quả xác minh cục bộ (2026-10-12)

Chạy trên nhánh đã merge `origin/develop`.

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check` (file đổi trong PR) | Pass |
| `python -m pytest -q` | Pass (5194 passed, 26 skipped; bỏ `tests/transports/livekit/test_worker_speech_settings.py` vì môi trường cục bộ thiếu gói `livekit`) |

## Ghi chú

- **Đánh đổi:** tên sai thì bot hỏi thêm ngày sinh rồi mới chuyển máy. Câu bị đọc nhầm thành tên ("đường dây bận") cũng hỏi ngày sinh trước khi chuyển.
- **Đánh đổi:** ASR nghe nhầm dấu thanh ("Nguyễn" -> "Nguyển") thì khách bị chuyển máy, không được hỏi lại tên (hỏi lại sẽ lộ là tên gần đúng).
- **Giới hạn đã chốt:** ở lượt hỏi ngày sinh, tên nói trơn không kèm tín hiệu tự sửa ("Nguyễn Văn A") không đè tên trước, để câu khác không bị đọc thành tên đè lên tên đúng. `test_bare_name_while_asking_dob_is_not_read_as_a_correction`.
- Tên sai rồi hai lần ngày sinh không chắc ("hình như 14/3/1978") kết thúc `NOT_UNDERSTOOD`, không phải `IDENTITY_FAILED`: chưa đủ hai giá trị nên chưa đối chiếu (đúng nguyên văn R-40, vẫn là `TRANSFERRED`). `test_wrong_name_then_unclear_dob_twice_is_not_understood`.
- Lời tự sửa chỉ đè trường đã có thì không tính là hiểu, nên vẫn dùng lượt hỏi lại ("à nhầm, tôi là Nguyễn Văn A" mà chưa nói ngày sinh -> bot hỏi lại ngày sinh bằng `ASK_DOB_AGAIN`).
- Release TTS v1 vẫn giữ trong repo để rollback (git lưu chung blob với v2, gần như không tốn dung lượng) nhưng bị loại khỏi image qua `.dockerignore`. Xóa v1 sau khi v2 deploy ổn.
- Ngoài phạm vi: ngoại lệ tên không dấu (`names.py`) đang xét riêng phần tên, còn PRD R-22 ghi "cả câu không có dấu nào"; tách issue riêng nếu cần siết.

# Evidence: T-01 — Identity Verifier

**Owner:** B (Hưng) · **Plan:** `docs/plans/t01-identity-verifier.md` · **Ngày:** 18-09-2026

## Mục tiêu

Đưa Verifier về đúng thứ tự của `tailieu/Luồng nghiệp vụ Callbot.pdf`: **đọc hồ sơ từ hệ thống ngay đầu cuộc gọi** (inbound tra cứu theo số gọi đến, outbound đọc theo mã lịch hẹn) → giữ "dữ liệu chuẩn nội bộ" (mã bệnh nhân, họ tên chuẩn, ngày sinh chuẩn) trong Session → hỏi mở tên/ngày sinh → **đối chiếu với dữ liệu đã giữ, không gọi Mock lần nữa**. Inbound phải khớp **đúng một** hồ sơ cả hai yếu tố; không tự chọn hồ sơ đầu tiên; không tạo patient.

Phạm vi: `src/callbot/engine/verification/` (identity, phone, names) + hai trường mới trong `CallContext` + một dòng gọi `prepare()` trong `opening()`. Không đổi lời thoại, không đổi FSM/journal, không sửa test của A.

Quyết định đã chốt với owner: chuẩn hóa số điện thoại thuộc T-01, nằm ở bước đầu `prepare()` (không phải F-05, không phải IE — `caller_number` là metadata harness, không phải lời khách).

## Bằng chứng trong repo

| Acceptance criterion | Ô luồng PDF | Vị trí code | Test chứng minh |
| --- | --- | --- | --- |
| AC-1 Inbound đầu cuộc gọi: tra cứu bằng số đã chuẩn hóa, đủ trang; không có ứng viên → `PATIENT_NOT_FOUND`, không ghi Mock | "Lấy hồ sơ bệnh nhân ứng viên…" → "Có hồ sơ ứng viên? Không" | `IdentityVerifier._prepare_inbound` → `ClinicGateway.find_patients_by_phone` (đủ trang, F-05); `PrepareResult.transfer_reason` | `test_identity_verifier.py::test_prepare_inbound_no_candidates_including_unregistered_caller`, `::test_prepare_inbound_keeps_every_candidate_across_pages` (130 ứng viên = 2 trang); `test_identity_flow.py::test_unregistered_inbound_caller_never_triggers_a_write` |
| AC-2 Inbound có ứng viên: giữ `{patient_id, full_name, dob, verifiable}` của **mọi** ứng viên | "Giữ thông tin đối chiếu của các hồ sơ" | `ctx.identity_lookup = "LOADED"`, `ctx.identity_reference = [...]` | `test_prepare_inbound_normalizes_e164_before_lookup`, `test_identity_flow.py::test_inbound_two_candidates_same_phone_verifies_the_matching_one` (reference có 2 phần tử) |
| AC-3 Outbound đầu cuộc gọi: đọc lịch hẹn theo `appointment_id`, giữ họ tên + ngày sinh chuẩn | "Lấy lịch hẹn và hồ sơ bệnh nhân… theo mã lịch hẹn đầu vào" | `_prepare_outbound` → `ClinicGateway.get_appointment` (đọc được ở lượt 0, không đòi `identity_verified` — F-05 R-3); `_reference_from_appointment` | `test_prepare_outbound_reads_appointment_once_and_keeps_canonical_reference` (đúng 1 `GET /appointments/apt_00417`); `test_identity_flow.py::test_outbound_reads_appointment_at_turn_zero_and_holds_reference` |
| AC-4 Đối chiếu dùng dữ liệu đã giữ, **không gọi Mock**; outbound khớp cả hai → VERIFIED / khác → MISMATCH; inbound đúng một → VERIFIED(patient_id), 0 hoặc ≥2 → PATIENT_NOT_FOUND | "Đối chiếu… với thông tin chuẩn từ hệ thống" | `IdentityVerifier.verify` — không có tham chiếu `self._gateway` | Mọi test `verify` kiểm `len(fake.calls)` không tăng sau `prepare`; `test_verify_works_after_context_roundtrip` (verify trên fake **đã ép lỗi** vẫn VERIFIED, `calls == []`); `test_identity_flow.py::test_lookup_happens_at_turn_zero_and_verify_adds_no_request` |
| AC-5 Không chọn hồ sơ đầu tiên khi nhiều ứng viên | "Đúng một hồ sơ khớp cả hai?" | Nhánh `len(matched) == 1` / `> 1 → AMBIGUOUS` | `test_verify_inbound_two_candidates_one_match_picks_the_matching_one_not_the_first` (người khớp đứng thứ 2), `test_verify_inbound_two_full_matches_is_ambiguous_never_auto_picks`; flow: `test_inbound_two_full_matches_transfers_instead_of_guessing` |
| AC-6 Không tạo patient, không ghi Mock trong tra cứu + đối chiếu | "Bot không tạo hồ sơ bệnh nhân" | Verifier chỉ gọi hai phương thức **đọc** của Gateway | `_assert_read_only` trong mọi test unit (`writes == []`, `requests == []`, mọi `ApiCallRecord.method == "GET"`) |
| AC-7 Dữ liệu chuẩn không lọt vào IE, trace, kết quả | Đường chấm "Dữ liệu chuẩn nội bộ" | `build_turn_context` không đọc hai trường mới (không đổi); `PrepareResult`/`VerificationResult` chỉ có status/detail/candidates/patient_id; `to_trace()` | `test_isolation.py` (3 test): `TurnContext` không có trường, `repr`/`to_trace` không chứa tên/DOB/display_name |
| AC-8 Hồ sơ thiếu `verify` / dob sai định dạng → không khớp, không ném ngoại lệ | — | `match_record` → `RECORD_UNVERIFIABLE`; `normalize_patient_candidate` (F-05) đặt `verifiable=False` | `test_names_and_match.py::test_unverifiable_record_never_matches` (5 dạng); `test_verify_outbound_unverifiable_record_fails_closed`; `test_verify_inbound_unverifiable_candidate_is_skipped`; flow TC_ID_17: `test_outbound_verify_null_fails_identity_and_writes_transfer` |
| AC-9 Không có / sai `caller_number` → không gọi Mock, `PATIENT_NOT_FOUND` | "Không — gồm khách chưa đăng ký" | `verification/phone.py::normalize_phone` → `None` → `NO_PHONE` | `test_prepare_inbound_without_usable_phone_does_not_call_mock` (5 dạng, `fake.calls == []`); `test_phone.py` (9 chuẩn hóa được + 10 → `None`) |
| Mock lỗi ở lượt 0 → `SYSTEM_ERROR`, không phải `IDENTITY_FAILED` (plan Q-4) | — | `LookupStatus.UNAVAILABLE` → `VerificationStatus.UNAVAILABLE` → `transfer_reason = SYSTEM_ERROR` | `test_prepare_outbound_unknown_appointment_is_unavailable`, `test_verify_unavailable_lookup_is_system_error_not_identity_failed`; flow `test_outbound_mock_down_at_turn_zero_becomes_system_error_not_identity_failed` |
| Pha 2 chạy được trên worker khác / sau restart | — | Hai trường mới trong `to_dict`/`from_dict` | `test_verify_works_after_context_roundtrip` |

## File liên quan

Mới:
- `src/callbot/engine/verification/phone.py` — `normalize_phone`, `MOCK_PHONE_RE`
- `tests/engine/verification/test_phone.py`, `test_names_and_match.py`, `test_identity_verifier.py`, `test_isolation.py`, `test_identity_flow.py`

Sửa:
- `src/callbot/engine/verification/identity.py` — viết lại: `LookupStatus`, `PrepareResult`, `MatchDetail`, `VerificationResult(status, detail, patient_id, candidates)`, `match_record`, `IdentityVerifier.prepare()/verify()`; giữ `matches()` bool và `VerificationStatus` cho code hiện có
- `src/callbot/engine/verification/__init__.py` — export thêm
- `src/callbot/engine/session/context.py` (A, đã báo) — thêm `IdentityLookup`, `identity_lookup`, `identity_reference`; `to_dict`/`from_dict` (đọc bằng `.get` để phiên cũ vẫn mở). **Không** bump `SCHEMA_VERSION` — xem Ghi chú
- `src/callbot/engine/dialogue/manager.py` (A, đã báo) — `opening()` gọi `self._verifier.prepare(ctx)` trước khi hỏi tên (1 dòng + 2 dòng comment)

## Luồng hiện tại

```text
POST /v1/calls (lượt 0)  -> SessionManager.open -> DialogueManager.opening(ctx)
  -> IdentityVerifier.prepare(ctx)                       [điểm chạm Gateway DUY NHẤT của Verifier]
       inbound : normalize_phone(caller_number)
                   None            -> identity_lookup = NO_PHONE,      reference = []   (0 request)
                   "0xxxxxxxxx"    -> Gateway.find_patients_by_phone (đủ trang)
                        0 ứng viên -> NO_CANDIDATES, []
                        N ứng viên -> LOADED, [ {patient_id, full_name, dob, verifiable} x N ]
       outbound: Gateway.get_appointment -> LOADED, [ 1 phần tử ]
       ClinicAPIError bất kỳ      -> UNAVAILABLE, [], error_code           (không ném ra ngoài)
  -> _ask(ASK_NAME)  (lời chào giữ nguyên — T-02 sẽ rẽ nhánh theo PrepareResult.transfer_reason)
  -> ctx.to_dict() lưu Session (kèm identity_lookup / identity_reference)

Lượt 1: tên -> ctx.claimed_name ; Lượt 2: DOB -> ctx.claimed_dob
  -> IdentityVerifier.verify(ctx)                        [KHÔNG I/O — chỉ đọc ctx.identity_reference]
       UNAVAILABLE                 -> VerificationResult(UNAVAILABLE, NO_REFERENCE)      -> SYSTEM_ERROR
       outbound  khớp cả hai       -> VERIFIED(patient_id)
                 khác              -> MISMATCH(detail)                                    -> IDENTITY_FAILED (ghi transfer)
       inbound   đúng 1 khớp       -> VERIFIED(patient_id, candidates=N)
                 0 khớp            -> PATIENT_NOT_FOUND(detail đại diện, N)                -> PATIENT_NOT_FOUND (không ghi)
                 >= 2 khớp         -> PATIENT_NOT_FOUND(AMBIGUOUS, N)                      -> PATIENT_NOT_FOUND (không ghi)
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`).

```powershell
make check
```

Chỉ test T-01: `python -m pytest tests\engine\verification -q`

## Kết quả xác minh cục bộ (18-09-2026)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check` (file T-01 chạm) | Pass |
| `python -m pytest tests/engine/verification -q` | Pass (80 passed) |
| `python -m pytest tests/engine tests/transports tests/test_schema.py -q` (trước khi thêm test T-01) | Pass (527 passed, 44 skipped) — test của A không đổi nội dung |
| `python -m pytest -q` | 612 passed, 44 skipped, 1 failed có sẵn: `tests/speech/test_narrowband.py::test_settings_default_to_narrowband` (đọc `SAMPLE_RATE` từ `.env` local, không liên quan) |

Số request tới fake ("một điểm chạm Gateway"): outbound lượt 0 = 1 `GET /appointments/{id}`; inbound lượt 0 = 1 `GET /patients` mỗi trang; `verify()` = 0 (kiểm trong mọi test).

## Ghi chú

- **Test của A không sửa nội dung.** Plan §6 bước 7 định đổi kỳ vọng `TC_ID_13` và thêm TC_ID_14–17 vào `identity_cases.py`; thay vào đó các case này nằm ở `tests/engine/verification/test_identity_flow.py` (chạy qua orchestrator thật). `TC_ID_13` hiện vẫn đúng vì lời chào lượt 0 chưa đổi.
- **Nhánh PDF "Không có ứng viên → chuyển nhân viên ngay, không hỏi tên" chưa thể hiện ở lời thoại.** Verifier đã trả `PrepareResult.transfer_reason` (`PATIENT_NOT_FOUND` / `SYSTEM_ERROR`) ở lượt 0; `opening()` hiện vẫn hỏi tên cho mọi trường hợp vì (a) lời chào/lượt 1 là T-02 của A (plan §9), (b) `TC_ID_13` và `test_opening_discloses_ai_assistant` của A kỳ vọng lượt 0 hỏi tên. Khi A làm T-02: `if prepare.transfer_reason: chào ngắn; lượt 1 -> transfer(prepare.transfer_reason)` và đổi kỳ vọng `TC_ID_13`. Hiện tại khách chưa đăng ký vẫn bị hỏi tên + DOB rồi mới chuyển máy — kết quả cuối (`TRANSFERRED/PATIENT_NOT_FOUND`, không ghi Mock) đã đúng, chỉ dư 2 lượt.
- **`SCHEMA_VERSION` giữ 1.** `tests/engine/session/test_context_fsm.py::test_context_roundtrip_keeps_every_field` (A) ghi cứng `schema_version == 1`. Hai trường mới là thay đổi **cộng thêm** có mặc định (`from_dict` dùng `.get`), phiên lưu trước đó vẫn mở được — không phá tương thích nên không bump. A quyết định có bump khi review; nếu bump thì sửa test đó cùng lúc.
- `VerificationStatus.UNAVAILABLE` là giá trị mới (plan §5.3 chưa có): cần để mock lỗi ở lượt 0 ra `SYSTEM_ERROR` thay vì `IDENTITY_FAILED` (plan Q-4) mà không sửa `DialogueManager._identity`. `MatchDetail.NO_REFERENCE` cũng mới, cho trường hợp không có hồ sơ để đối chiếu.
- `verify()` không còn ném `ValueError` khi `identity_lookup` khác `LOADED` như plan §5.3 — chỉ ném khi `PENDING` (prepare chưa chạy = lỗi lập trình). `NO_PHONE`/`NO_CANDIDATES` cho ra `PATIENT_NOT_FOUND(NO_REFERENCE)` để Dialogue hiện tại (chưa có T-02) vẫn kết thúc đúng.
- Khớp tên **chính xác** sau `normalize_name` (bỏ dấu, hoa/thường, khoảng trắng); thiếu họ → `NAME_MISMATCH` (plan Q-3, R-1). T-02 hỏi "họ và tên đầy đủ" trước khi gọi `verify`.
- `MatchDetail` chỉ để trace/log. Dialogue **không** dùng để nói "ngày sinh chưa khớp" (xác nhận tên đúng = rò một nửa, §1.1.2).
- Việc của A tiếp theo: (1) T-02 nối `PrepareResult` vào `opening()` như trên; (2) review 2 file của A bị chạm (`context.py`, `manager.py`); (3) R-02 đưa `prepare.to_trace()` vào event `call_started` và `verify.to_trace()` vào event `turn`.

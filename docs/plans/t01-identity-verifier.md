# Plan T-01 — Identity Verifier

**Owner:** B (Hưng) · **Trạng thái:** Chờ duyệt · **Ngày:** 17-09-2026
**Nguồn:** `docs/task-breakdown.md` §3 (T-01), contract AIHR-PC-001 rev 1.1 §1.1.1–1.1.2, §1.1.9, SF-03
**Phụ thuộc:** F-05 (`normalize_phone`, phân trang `/patients`, `FakeClinicAPI` mới) — xem `docs/plans/f05-clinic-gateway.md`

## 1. Mục tiêu và điều kiện hoàn thành

Theo task-breakdown:

> Đọc hồ sơ outbound; tra cứu ứng viên inbound; đối chiếu tên và DOB; trả kết quả **khớp / không khớp / không xác định được hồ sơ**; không tạo patient.
> **Điều kiện hoàn thành:** Xác minh đúng theo từng hướng gọi; **không tự chọn hồ sơ đầu tiên**.

Tiêu chí kiểm được:

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | Outbound: đọc `GET /appointments/{id}` của cuộc gọi, so `patient.verify.{full_name, dob}` với điều người gọi nói; đúng cả hai → `VERIFIED(patient_id)`, sai một trong hai → `MISMATCH` | Unit test Verifier với fake; `test_identity.py` TC_ID_01–04 giữ nguyên |
| AC-2 | Inbound: tra cứu `GET /patients?phone=` (đã chuẩn hóa, đủ trang); chỉ `VERIFIED` khi **đúng một** hồ sơ khớp cả tên và DOB; 0 ứng viên / 0 khớp / ≥2 khớp → không VERIFIED | Unit test 4 nhánh; TC_ID_12–13 giữ nguyên |
| AC-3 | Không bao giờ chọn hồ sơ đầu tiên khi có nhiều ứng viên cùng số điện thoại | Test 2 ứng viên cùng phone, chỉ 1 khớp → VERIFIED đúng người; 2 khớp → không VERIFIED |
| AC-4 | Không tạo patient, không ghi gì vào mock trong quá trình xác minh | Test `fake.writes == []`, `fake.requests` chỉ có GET |
| AC-5 | Kết quả trả về và trace **không chứa** `full_name`/`dob` của hồ sơ (SF-03) | Test `repr(result)` và `result.to_trace()` không chứa giá trị `verify` |
| AC-6 | Hồ sơ thiếu `verify` hoặc `dob` sai định dạng → coi là không khớp (fail-closed), không ném ngoại lệ | Unit test |
| AC-7 | Không có `caller_number` hoặc số không hợp lệ → không gọi mock, kết quả `PATIENT_NOT_FOUND` | Test `fake.patient_lookups == []` |

## 2. Ràng buộc contract liên quan

| Điều khoản | Áp dụng cho Verifier |
| --- | --- |
| §1.1.1 | Outbound: số được gọi **không** là bằng chứng danh tính; phải có họ tên + ngày sinh và **đối chiếu cả hai** với bản ghi; thất bại → chuyển máy không tiết lộ gì. |
| §1.1.2 | Hỏi mở, không đọc thông tin ra rồi hỏi "đúng không". (Việc hỏi thuộc T-02 của A; Verifier chỉ **không được trả giá trị hồ sơ** ra ngoài để A không thể vô tình đọc.) |
| §1.1.9 | Inbound: phải tìm được bản ghi trước khi đề xuất; vẫn hỏi tên + DOB; số gọi đến không phải bằng chứng; **"không có bản ghi nào khớp duy nhất" → `PATIENT_NOT_FOUND`**; không tạo patient. |
| §2.1 rev 1.1 | Inbound kết thúc TRANSFERRED: harness chấm `outcome` và kiểm tra writelog rỗng; `transfer_reason` **không** được kiểm tra. |
| SF-03 | Không tiết lộ chi tiết lịch hẹn trước khi xác minh. |
| Bảng 4 | `transfer_reason`: `IDENTITY_FAILED`, `PATIENT_NOT_FOUND`. |

## 3. Hiện trạng (`src/callbot/engine/verification/`)

| File | Có gì | Ghi chú |
| --- | --- | --- |
| `identity.py` | `VerificationStatus {VERIFIED, MISMATCH, PATIENT_NOT_FOUND}`; `VerificationResult(status, patient_id)` + `transfer_reason` map; `matches(name, dob, verify)`; `IdentityVerifier.verify(ctx)` rẽ outbound/inbound | Khung đúng hướng; thiếu các nhánh ở §4 |
| `names.py` | `normalize_text`, `strip_diacritics`, `normalize_name` (bỏ dấu, lowercase, gộp khoảng trắng) | Đánh đổi "Hà" = "Hạ" đã ghi trong docstring; DOB là yếu tố thứ hai |
| `dialogue/manager.py:141-147` (A) | Gọi `verifier.verify(ctx)` sau khi có `claimed_dob`; `!= VERIFIED` → `transfer(reason)` | Điểm tích hợp duy nhất; giữ nguyên chữ ký |
| `tests/engine/test_identity.py` + `identity_cases.py` | 13 case qua orchestrator; kiểm tra không lộ thông tin, không ghi trái phép | Chỉ có 2 case inbound (phone đúng / phone lạ); **chưa có** case inbound phone đúng nhưng tên/DOB sai, nhiều ứng viên, `verify` null |

## 4. Khoảng cách cần xử lý

| # | Vấn đề | Bằng chứng | Ảnh hưởng |
| --- | --- | --- | --- |
| V-1 | Inbound gộp "0 ứng viên", "có ứng viên nhưng không khớp", "≥2 khớp" thành một `PATIENT_NOT_FOUND` | `identity.py:73-76` `len(matched) != 1` | Trace không phân biệt được lỗi tra cứu với lỗi danh tính; T-06 không có reason chi tiết |
| V-2 | `p.get("verify", {})` — mock schema cho phép `verify: null` → `matches()` gọi `None["dob"]` → `TypeError` → orchestrator chuyển SYSTEM_ERROR | `clinic-mock/schemas.py: verify: PatientVerify \| None`; `identity.py:36,61,71` | Sập nhánh thay vì fail-closed |
| V-3 | `caller_number` truyền thẳng xuống Gateway, chưa chuẩn hóa; `+84…` → mock 400 INVALID_REQUEST → ngoại lệ | `identity.py:64-68`; mock regex phone | Inbound chuyển SYSTEM_ERROR thay vì PATIENT_NOT_FOUND |
| V-4 | Chỉ đọc trang đầu `/patients` | Gateway hiện tại (F-05 G-1) | Với >25 hồ sơ cùng số (không thực tế nhưng contract không cấm) sẽ bỏ sót |
| V-5 | `TODO: nếu không có caller_number… hỏi PO` chưa đóng | `identity.py:63` | Contract Bảng 3 chỉ có một cách tra cứu (`phone`); không có phone → không tra cứu được → `PATIENT_NOT_FOUND`. Không cần hỏi PO. |
| V-6 | Không có trace cấu trúc cho kết quả xác minh (direction, số ứng viên, lý do) | — | R-02/T-06 cần |
| V-7 | Chưa có unit test trực tiếp cho Verifier và `names.py`; chỉ test gián tiếp qua orchestrator | `tests/engine/` không có `verification/` | Khi A sửa Dialogue, test danh tính đỏ mà không biết lỗi ở đâu |
| V-8 | `matches()` là hàm module-level trả `bool`; không nói vì sao (tên sai? DOB sai? thiếu verify?) | `identity.py:33-39` | Không trace được; A không viết được câu hỏi lại phù hợp ở T-02 (nếu policy cho phép hỏi lại DOB) |

## 5. Thiết kế đề xuất

### 5.1 Kết quả xác minh

```python
class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"                # có đúng 1 hồ sơ đích, tên hoặc DOB không khớp
    PATIENT_NOT_FOUND = "PATIENT_NOT_FOUND"  # inbound: không xác định được hồ sơ duy nhất

class MatchDetail(str, Enum):            # KHÔNG chứa giá trị hồ sơ, chỉ mô tả lý do
    NAME_AND_DOB_MATCH = "NAME_AND_DOB_MATCH"
    NAME_MISMATCH = "NAME_MISMATCH"
    DOB_MISMATCH = "DOB_MISMATCH"
    BOTH_MISMATCH = "BOTH_MISMATCH"
    RECORD_UNVERIFIABLE = "RECORD_UNVERIFIABLE"  # verify null / dob sai định dạng
    NO_PHONE = "NO_PHONE"                # inbound: không có / không chuẩn hóa được caller_number
    NO_CANDIDATES = "NO_CANDIDATES"      # inbound: GET /patients trả rỗng
    AMBIGUOUS = "AMBIGUOUS"              # inbound: ≥ 2 hồ sơ khớp cả tên và DOB

@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    detail: MatchDetail
    patient_id: Optional[str] = None
    candidates: int = 0                  # inbound: số ứng viên GET /patients trả về

    @property
    def transfer_reason(self) -> Optional[TransferReason]: ...   # bảng ở §5.3
    def to_trace(self) -> dict[str, Any]: ...                     # {status, detail, candidates, has_patient_id}
```

`__repr__` mặc định của dataclass chỉ in các trường trên → không thể lộ `full_name`/`dob`. Test AC-5 khóa điều này.

### 5.2 Đối chiếu

`match_record(claimed_name, claimed_dob, verify) -> MatchDetail` thay cho `matches() -> bool`:

1. `verify` là `None`/không phải dict, thiếu `full_name` hoặc `dob`, hoặc `dob` không parse được → `RECORD_UNVERIFIABLE` (fail-closed).
2. So tên bằng `normalize_name` (giữ quy tắc hiện tại: NFC → lowercase → bỏ dấu → gộp khoảng trắng). **Khớp chính xác toàn chuỗi** — không fuzzy, không so từng token, không chấp nhận thiếu họ. Lý do: mọi nới lỏng là false-accept → SF-03. Việc làm sạch câu nói ("tôi là…", "tên em là…") thuộc IE (`extraction/full_name`), Verifier nhận chuỗi đã sạch.
3. So DOB bằng `date ==`.
4. Trả `NAME_AND_DOB_MATCH` / `NAME_MISMATCH` / `DOB_MISMATCH` / `BOTH_MISMATCH`.

Giữ `matches()` như wrapper `bool` để `__init__.py` export không đổi (A có thể đang import).

### 5.3 Luồng theo hướng gọi

**Outbound** (`ctx.call.appointment_id` bắt buộc):

```text
appointment = gateway.get_appointment(ctx)        # SF-01 assert target; ClinicAPIError 404 → nổi lên (không phải lỗi danh tính)
detail = match_record(claimed_name, claimed_dob, appointment["patient"].get("verify"))
NAME_AND_DOB_MATCH → VERIFIED(patient_id = appointment.patient.patient_id)
còn lại            → MISMATCH(detail)            → transfer_reason IDENTITY_FAILED
```

**Inbound** (`ctx.call.caller_number` tuỳ chọn):

```text
phone = normalize_phone(caller_number)            # F-05
phone is None      → PATIENT_NOT_FOUND(NO_PHONE, candidates=0)     — không gọi mock
candidates = gateway.find_patients_by_phone(phone)   # đủ trang, đã chuẩn hóa
len == 0           → PATIENT_NOT_FOUND(NO_CANDIDATES)
matched = [c for c in candidates if match_record(...) is NAME_AND_DOB_MATCH]
len(matched) == 1  → VERIFIED(patient_id = matched[0].patient_id, candidates=N)
len(matched) == 0  → PATIENT_NOT_FOUND(detail = detail "tốt nhất" trong các ứng viên*, candidates=N)
len(matched) >= 2  → PATIENT_NOT_FOUND(AMBIGUOUS, candidates=N)
```

\* "tốt nhất" = ưu tiên `DOB_MISMATCH`/`NAME_MISMATCH` (một yếu tố sai) hơn `BOTH_MISMATCH`, để trace cho biết người gọi gần đúng đến đâu — không ảnh hưởng quyết định.

Bảng `transfer_reason`:

| Direction | Status | transfer_reason | Căn cứ |
| --- | --- | --- | --- |
| outbound | MISMATCH | `IDENTITY_FAILED` | §1.1.1 |
| inbound | PATIENT_NOT_FOUND (mọi detail) | `PATIENT_NOT_FOUND` | §1.1.9 "không có bản ghi nào khớp duy nhất" — kể cả khi có ứng viên nhưng sai tên/DOB |
| inbound | MISMATCH | *(không xảy ra — inbound không trả MISMATCH)* | Xem Q-1 |

### 5.4 Điểm không đổi

- Chữ ký `IdentityVerifier(gateway).verify(ctx) -> VerificationResult` giữ nguyên → `dialogue/manager.py` của A không cần sửa. Chỉ có thêm trường `detail`, `candidates`, `to_trace()`.
- `verify()` vẫn `raise ValueError` khi thiếu `claimed_name`/`claimed_dob` — đó là lỗi lập trình của Dialogue, không phải lỗi danh tính.
- Verifier **không** gọi bất kỳ phương thức ghi nào của Gateway; **không** đặt `ctx.identity_step`/`ctx.patient_id` (Dialogue làm, như hiện tại).

### 5.5 Trace

Orchestrator hiện trace `extraction` mỗi lượt; kết quả xác minh chưa vào trace. Đề xuất tối thiểu trong T-01: Verifier `logger.info("identity %s", result.to_trace())` với `call_id`. Đưa `result.to_trace()` vào event `turn` của orchestrator là việc của A (R-02) — ghi vào phần phối hợp.

## 6. Các bước thực hiện

| Bước | Việc | File | Phụ thuộc |
| --- | --- | --- | --- |
| 1 | Viết `MatchDetail`, `match_record`, mở rộng `VerificationResult` (+`detail`, `candidates`, `to_trace`) ; giữ `matches()` wrapper | `verification/identity.py`, `verification/__init__.py` | — |
| 2 | Unit test `names.py`: NFC/NFD, `đ/Đ`, hoa/thường, khoảng trắng thừa, tên có dấu vs không dấu, `"Hà"` vs `"Hạ"` (ghi nhận là khớp — đánh đổi đã chọn) | `tests/engine/verification/test_names.py` | — |
| 3 | Unit test `match_record`: 4 kết quả khớp/lệch, `verify=None`, thiếu `dob`, `dob="14/03/1978"` (sai định dạng) → `RECORD_UNVERIFIABLE` | `tests/engine/verification/test_match_record.py` | 1 |
| 4 | Viết lại `_verify_inbound` theo §5.3, dùng `normalize_phone` từ F-05; xoá TODO | `verification/identity.py` | F-05 bước 2, 7 |
| 5 | Unit test Verifier với `FakeClinicAPI` mới: outbound khớp / sai tên / sai DOB / sai cả hai / `verify` null; inbound không phone / phone `+84` chuẩn hóa được / phone không hợp lệ / 0 ứng viên / 1 ứng viên khớp / 2 ứng viên 1 khớp (AC-3) / 2 ứng viên 2 khớp (AMBIGUOUS) / 1 ứng viên sai DOB; mọi case: `fake.writes == []`, `repr(result)` không chứa giá trị `verify` | `tests/engine/verification/test_identity_verifier.py` | 1, 4, F-05 bước 5 |
| 6 | Bổ sung `identity_cases.py` (test qua orchestrator, của A nhưng B thêm case data): TC_ID_14 inbound phone đúng + tên sai → TRANSFERRED/PATIENT_NOT_FOUND; TC_ID_15 inbound 2 ứng viên cùng phone chỉ 1 khớp → AWAITING_INTENT; TC_ID_16 inbound `caller_number="+84912345600"` → lookup `"0912345600"` | `tests/engine/identity_cases.py` (cần fake seed 2 patient cùng phone) | 5 |
| 7 | `logger.info` trace không PII | `verification/identity.py` | 1 |
| 8 | Cập nhật docstring module `identity.py` (quyết định Q-1, Q-2); viết `docs/evidence/t01-identity-verifier.md` | docs | tất cả |
| 9 | `make check` xanh | — | — |

Bước 1–3 không phụ thuộc F-05, có thể làm ngay. Bước 4–6 chờ F-05 hoàn thành `normalize_phone` + fake mới.

## 7. Phối hợp với A

| A cần từ B | Khi nào |
| --- | --- |
| Danh sách `MatchDetail` để T-02 quyết định có hỏi lại DOB/tên hay chuyển máy ngay (theo giới hạn hỏi lại của T-02) | Sau bước 1 |
| `VerificationResult.to_trace()` để R-02 đưa vào event `turn` | Sau bước 1 |

| B cần từ A | Khi nào |
| --- | --- |
| Xác nhận Dialogue tiếp tục đối xử `status != VERIFIED → transfer(result.transfer_reason)` và **không** dùng `detail` để nói cho người gọi biết yếu tố nào sai (nói "ngày sinh chưa khớp" = xác nhận tên đúng = rò một nửa thông tin §1.1.2) | Bước 1 |
| Đồng ý B thêm case vào `identity_cases.py` (file thuộc test của A) | Bước 6 |

## 8. Rủi ro và điểm cần duyệt

| # | Điểm cần quyết | Đề xuất của B | Phương án khác |
| --- | --- | --- | --- |
| Q-1 | Inbound có ứng viên nhưng tên/DOB sai: `PATIENT_NOT_FOUND` hay `IDENTITY_FAILED`? | `PATIENT_NOT_FOUND` — bám chữ §1.1.9 ("không có bản ghi nào khớp duy nhất"); §2.1 nói inbound `transfer_reason` không được chấm nên không có rủi ro điểm; `detail` vẫn ghi `NAME_MISMATCH`/`DOB_MISMATCH` cho trace | `IDENTITY_FAILED` — đúng nghĩa hơn về mặt ngôn ngữ, nhưng lệch chữ contract |
| Q-2 | Mức khớp tên: chính xác sau chuẩn hóa (hiện tại) hay nới lỏng (bỏ họ, đảo thứ tự, fuzzy)? | Giữ **chính xác**. Sai lệch ASR để IE/T-02 xử lý bằng hỏi lại; Verifier không đoán | Thêm knob `EngineSettings.name_match = "exact" \| "token_set"` mặc định exact — chỉ làm nếu tester báo tỉ lệ từ chối nhầm cao |
| Q-3 | Outbound với appointment đã ở trạng thái cuối (CANCELLED/TRANSFERRED…) có xác minh không? | Verifier **vẫn xác minh** (nó chỉ so danh tính); quyết định làm gì tiếp là của Dialogue/Policy | Verifier từ chối sớm — trộn trách nhiệm, không đề xuất |
| Q-4 | `verify: null` ở mock: có fallback so `display_name` ("N. V. A.") không? | Không — `display_name` là dạng viết tắt, so khớp sẽ false-accept; `RECORD_UNVERIFIABLE` → không VERIFIED | — |
| Q-5 | Chuẩn hóa phone trả `None` với đầu số ngoài `02/03/05/07/08/09` | Theo mock; ghi nhận hỏi mentor nếu dữ liệu chấm có số khác (giống F-05 Q-4) | — |
| R-1 | Người gọi đọc tên không có họ ("Văn A") → MISMATCH → chuyển máy dù đúng người | Chấp nhận trong T-01; T-02 (A) quyết định hỏi lại "họ và tên đầy đủ" trước khi gọi Verifier | — |
| R-2 | Hai người cùng số điện thoại, cùng tên, cùng ngày sinh (dữ liệu tổng hợp trùng) → AMBIGUOUS → chuyển máy | Đúng theo §1.1.9 (không "khớp duy nhất"); không tự chọn | — |

## 9. Ngoài phạm vi T-01

- Câu hỏi mở, giới hạn hỏi lại, xử lý DOB không hợp lệ, nối kết quả vào FSM → **T-02** (A).
- Đưa `to_trace()` vào trace lượt → **R-02** (A).
- Chuẩn hóa phone, phân trang `/patients`, fake mới → **F-05** (B).

## 10. Định nghĩa hoàn thành → evidence

`docs/evidence/t01-identity-verifier.md` theo `TEMPLATE.md`: bảng AC-1..AC-7 ↔ test; bảng quyết định Q-1..Q-5 đã chốt với ai/khi nào; kết quả `make check`; số test danh tính (13 hiện có + 3 case mới qua orchestrator + unit test trực tiếp).

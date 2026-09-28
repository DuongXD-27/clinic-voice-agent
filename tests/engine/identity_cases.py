from dataclasses import dataclass
from typing import Literal, Optional

PromptKind = Literal["name", "dob"]


@dataclass(frozen=True)
class IdentityTurn:
    caller_text: str
    expected_state: str
    expected_prompt: Optional[PromptKind] = None
    expected_outcome: Optional[str] = None
    expected_transfer_reason: Optional[str] = None


@dataclass(frozen=True)
class IdentityCase:
    id: str
    turns: tuple[IdentityTurn, ...] = ()
    direction: Literal["outbound", "inbound"] = "outbound"
    caller_number: Optional[str] = None
    expected_lookup_phone: Optional[str] = None
    # T-02: không có hồ sơ để đối chiếu thì lượt 0 không hỏi tên (None)
    opening_prompt: Optional[PromptKind] = "name"


CORRECT_NAME = "Nguyễn Văn A"
WRONG_NAME = "Trần Văn B"
CORRECT_DOB = "14/03/1978"
WRONG_DOB = "14/03/1979"

# Dạng nói của cùng một ngày sinh đúng — dùng để kiểm end-to-end qua orchestrator,
# không chỉ ở tầng extractor (test_dob.py đã phủ tầng extractor riêng).
CORRECT_DOB_SPOKEN = "mười bốn tháng ba năm một nghìn chín trăm bảy mươi tám"
CORRECT_DOB_SELF_CORRECTED = "ngày 15 tháng 3 năm 1978, à không, ngày 14 tháng 3 năm 1978"


ASK_DOB_AFTER_CORRECT_NAME = IdentityTurn(CORRECT_NAME, "AWAITING_IDENTITY", "dob")


def _identity_failure(
    name: str,
    dob: str,
    expected_transfer_reason: str = "IDENTITY_FAILED",
) -> tuple[IdentityTurn, ...]:
    return (
        IdentityTurn(name, "AWAITING_IDENTITY", "dob"),
        IdentityTurn(
            dob,
            "ENDED",
            expected_outcome="TRANSFERRED",
            expected_transfer_reason=expected_transfer_reason,
        ),
    )


def _not_understood_twice(
    first_kind: PromptKind,
    lead_in: tuple[IdentityTurn, ...],
    confused_text_1: str,
    confused_text_2: str,
) -> tuple[IdentityTurn, ...]:
    """§1.1.5: hai lần hiểu sai liên tiếp trong pha định danh -> transfer NOT_UNDERSTOOD."""
    return lead_in + (
        IdentityTurn(confused_text_1, "AWAITING_IDENTITY", first_kind),
        IdentityTurn(
            confused_text_2,
            "ENDED",
            expected_outcome="TRANSFERRED",
            expected_transfer_reason="NOT_UNDERSTOOD",
        ),
    )


IDENTITY_CASES = (
    # --- Outbound: ma trận đúng/sai tên x DOB (§1.1.1) ---
    IdentityCase(
        id="TC_ID_01",
        turns=(
            ASK_DOB_AFTER_CORRECT_NAME,
            IdentityTurn(CORRECT_DOB, "AWAITING_INTENT"),
        ),
    ),
    IdentityCase(id="TC_ID_02", turns=_identity_failure(WRONG_NAME, CORRECT_DOB)),
    IdentityCase(id="TC_ID_03", turns=_identity_failure(CORRECT_NAME, WRONG_DOB)),
    IdentityCase(id="TC_ID_04", turns=_identity_failure(WRONG_NAME, WRONG_DOB)),
    # --- Đơn lẻ: dừng giữa chừng sau tên đúng, một lần không hiểu (re-prompt, không transfer) ---
    IdentityCase(id="TC_ID_05", turns=(ASK_DOB_AFTER_CORRECT_NAME,)),
    IdentityCase(
        id="TC_ID_06",
        turns=(IdentityTurn("Tôi không rõ", "AWAITING_IDENTITY", "name"),),
    ),
    IdentityCase(
        id="TC_ID_07",
        turns=(IdentityTurn(CORRECT_DOB, "AWAITING_IDENTITY", "name"),),
    ),
    IdentityCase(
        id="TC_ID_08",
        turns=(
            ASK_DOB_AFTER_CORRECT_NAME,
            IdentityTurn("không nhớ", "AWAITING_IDENTITY", "dob"),
        ),
    ),
    # --- Sanity case: chỉ kiểm lượt mở đầu (câu hỏi tên hợp lệ), không đi tiếp ---
    IdentityCase(id="TC_ID_09"),
    # --- TC_ID_10/11 trước đây trùng lặp TC_ID_05/TC_ID_09 nguyên văn.
    #     Thay bằng end-to-end cho DOB dạng nói và DOB tự sửa giữa câu,
    #     để xác nhận orchestrator (không chỉ extractor) xử lý đúng tới AWAITING_INTENT. ---
    IdentityCase(
        id="TC_ID_10",
        turns=(
            ASK_DOB_AFTER_CORRECT_NAME,
            IdentityTurn(CORRECT_DOB_SPOKEN, "AWAITING_INTENT"),
        ),
    ),
    IdentityCase(
        id="TC_ID_11",
        turns=(
            ASK_DOB_AFTER_CORRECT_NAME,
            IdentityTurn(CORRECT_DOB_SELF_CORRECTED, "AWAITING_INTENT"),
        ),
    ),
    # --- Inbound: có record theo SĐT, vẫn phải hỏi mở tên+dob (§1.1.9) ---
    IdentityCase(
        id="TC_ID_12",
        direction="inbound",
        caller_number="0912345600",
        expected_lookup_phone="0912345600",
        turns=(
            ASK_DOB_AFTER_CORRECT_NAME,
            IdentityTurn(CORRECT_DOB, "AWAITING_INTENT"),
        ),
    ),
    # --- Inbound: không tìm thấy record nào theo SĐT -> PATIENT_NOT_FOUND ---
    IdentityCase(
        id="TC_ID_13",
        direction="inbound",
        caller_number="0999999999",
        expected_lookup_phone="0999999999",
        opening_prompt=None,
        turns=(
            IdentityTurn(
                CORRECT_NAME,
                "ENDED",
                expected_outcome="TRANSFERRED",
                expected_transfer_reason="PATIENT_NOT_FOUND",
            ),
        ),
    ),
    # --- MỚI — §1.1.5: hai lần hiểu sai liên tiếp trong pha định danh ---
    IdentityCase(
        id="TC_ID_14",
        turns=_not_understood_twice("name", (), "Tôi không rõ", "tôi cũng không biết"),
    ),
    IdentityCase(
        id="TC_ID_15",
        turns=_not_understood_twice(
            "dob", (ASK_DOB_AFTER_CORRECT_NAME,), "không nhớ", "thôi kệ đi"
        ),
    ),
    # --- MỚI — Inbound: SĐT khớp đúng 1 record, nhưng tên/dob caller nói sai
    #     (đối xứng với TC_ID_02/03/04, nhưng ở nhánh inbound của §1.1.9) ---
    IdentityCase(
        id="TC_ID_16",
        direction="inbound",
        caller_number="0912345600",
        expected_lookup_phone="0912345600",
        turns=_identity_failure(
            WRONG_NAME, CORRECT_DOB, expected_transfer_reason="PATIENT_NOT_FOUND"
        ),
    ),
    IdentityCase(
        id="TC_ID_17",
        direction="inbound",
        caller_number="0912345600",
        expected_lookup_phone="0912345600",
        turns=_identity_failure(
            CORRECT_NAME, WRONG_DOB, expected_transfer_reason="PATIENT_NOT_FOUND"
        ),
    ),
    IdentityCase(
        id="TC_ID_18",
        direction="inbound",
        caller_number="0912345600",
        expected_lookup_phone="0912345600",
        turns=_identity_failure(
            WRONG_NAME, WRONG_DOB, expected_transfer_reason="PATIENT_NOT_FOUND"
        ),
    ),
    # --- MỚI — Inbound: SĐT khớp NHIỀU HƠN 1 record (ambiguous) -> vẫn PATIENT_NOT_FOUND.
    #     GIẢ ĐỊNH: FakeClinicAPI có fixture ánh xạ "0912345700" tới >=2 patient.
    #     Nếu fixture chưa có, cần bổ sung trong clinic_mock_sim trước khi case này chạy đúng nghĩa —
    #     nếu không, test có thể pass "giả" vì thực chất vẫn đang rơi vào nhánh 0-record. ---
    IdentityCase(
        id="TC_ID_19",
        direction="inbound",
        caller_number="0912345700",
        expected_lookup_phone="0912345700",
        opening_prompt=None,
        turns=(
            IdentityTurn(
                CORRECT_NAME,
                "ENDED",
                expected_outcome="TRANSFERRED",
                expected_transfer_reason="PATIENT_NOT_FOUND",
            ),
        ),
    ),
    # --- MỚI — Tên và DOB gộp trong một lượt, hai thứ tự khác nhau ---
    IdentityCase(
        id="TC_ID_20",
        turns=(
            IdentityTurn(
                f"{CORRECT_NAME}, sinh ngày {CORRECT_DOB}",
                "AWAITING_INTENT",
            ),
        ),
    ),
    IdentityCase(
        id="TC_ID_21",
        turns=(
            IdentityTurn(
                f"Sinh ngày {CORRECT_DOB}, tôi tên {CORRECT_NAME}",
                "AWAITING_INTENT",
            ),
        ),
    ),
)

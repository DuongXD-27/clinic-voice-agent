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


ASK_DOB_AFTER_CORRECT_NAME = IdentityTurn(CORRECT_NAME, "AWAITING_IDENTITY", "dob")


def _identity_failure(name: str, dob: str) -> tuple[IdentityTurn, ...]:
    return (
        IdentityTurn(name, "AWAITING_IDENTITY", "dob"),
        IdentityTurn(
            dob,
            "ENDED",
            expected_outcome="TRANSFERRED",
            expected_transfer_reason="IDENTITY_FAILED",
        ),
    )


IDENTITY_CASES = (
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
    IdentityCase(id="TC_ID_09"),
    IdentityCase(id="TC_ID_10", turns=(ASK_DOB_AFTER_CORRECT_NAME,)),
    IdentityCase(id="TC_ID_11"),
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
    IdentityCase(
        id="TC_ID_13",
        direction="inbound",
        caller_number="0999999999",
        expected_lookup_phone="0999999999",
        opening_prompt=None,
        # T-02: số không có hồ sơ -> lượt 0 không hỏi tên, lượt 1 chuyển máy bất kể người gọi nói gì
        turns=(
            IdentityTurn(
                CORRECT_NAME,
                "ENDED",
                expected_outcome="TRANSFERRED",
                expected_transfer_reason="PATIENT_NOT_FOUND",
            ),
        ),
    ),
)

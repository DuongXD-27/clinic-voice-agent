"""Verifier: xác minh danh tính (tên + ngày sinh), đối chiếu hệ thống, quyết định cho phép / chuyển máy.

§1.1.1–1.1.2: hỏi bằng câu hỏi mở và so khớp; KHÔNG đọc thông tin rồi hỏi "đúng không".
§1.1.9: số điện thoại gọi đến chỉ để tra cứu, không phải bằng chứng danh tính.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Optional

from callbot.engine.session.context import CallContext
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.types import TransferReason
from callbot.engine.verification.names import normalize_name


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    PATIENT_NOT_FOUND = "PATIENT_NOT_FOUND"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    patient_id: Optional[str] = None

    @property
    def transfer_reason(self) -> Optional[TransferReason]:
        return {
            VerificationStatus.MISMATCH: "IDENTITY_FAILED",
            VerificationStatus.PATIENT_NOT_FOUND: "PATIENT_NOT_FOUND",
        }.get(self.status)


def matches(claimed_name: str, claimed_dob: date, verify: dict[str, Any]) -> bool:
    try:
        record_dob = date.fromisoformat(verify["dob"])
    except (KeyError, ValueError):
        return False
    return normalize_name(claimed_name) == normalize_name(verify.get("full_name", "")) and (
        claimed_dob == record_dob
    )


class IdentityVerifier:
    def __init__(self, gateway: ClinicGateway) -> None:
        self._gateway = gateway

    def verify(self, ctx: CallContext) -> VerificationResult:
        if ctx.claimed_name is None or ctx.claimed_dob is None:
            raise ValueError("Cần đủ tên và ngày sinh trước khi xác minh")
        if ctx.call.direction == "outbound":
            return self._verify_outbound(ctx)
        return self._verify_inbound(ctx)

    def _verify_outbound(self, ctx: CallContext) -> VerificationResult:
        appointment = self._gateway.get_appointment(ctx)
        patient = appointment.get("patient", {})
        if matches(ctx.claimed_name, ctx.claimed_dob, patient.get("verify", {})):
            return VerificationResult(VerificationStatus.VERIFIED, patient.get("patient_id"))
        return VerificationResult(VerificationStatus.MISMATCH)

    def _verify_inbound(self, ctx: CallContext) -> VerificationResult:
        # TODO: nếu không có caller_number hoặc số không khớp — cần cách tra cứu khác? hỏi PO
        candidates = (
            self._gateway.find_patients_by_phone(ctx.call.caller_number)
            if ctx.call.caller_number
            else []
        )
        # Gateway trả ứng viên canonical {patient_id, full_name, dob, verifiable} (F-05 §5.3);
        # hồ sơ không verifiable coi là không khớp (fail-closed)
        matched = [
            p
            for p in candidates
            if p.get("verifiable")
            and matches(
                ctx.claimed_name, ctx.claimed_dob, {"full_name": p["full_name"], "dob": p["dob"]}
            )
        ]
        # §1.1.9: phải khớp đúng MỘT hồ sơ; không tạo patient mới
        if len(matched) != 1:
            return VerificationResult(VerificationStatus.PATIENT_NOT_FOUND)
        return VerificationResult(VerificationStatus.VERIFIED, matched[0].get("patient_id"))

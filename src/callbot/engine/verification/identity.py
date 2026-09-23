"""Identity Verifier — hai pha theo luồng nghiệp vụ (`Luồng nghiệp vụ Callbot.pdf`).

Pha 1 `prepare(ctx)` — lượt 0, lần DUY NHẤT Verifier đi qua Clinic Gateway:
  inbound  : chuẩn hóa số gọi đến -> GET /patients?phone= (đủ trang) -> giữ MỌI ứng viên
  outbound : GET /appointments/{id} -> giữ họ tên chuẩn + ngày sinh chuẩn của bệnh nhân lịch hẹn
  Kết quả ghi vào `ctx.identity_lookup` / `ctx.identity_reference` ("dữ liệu chuẩn nội bộ", §4.2.2).
Pha 2 `verify(ctx)` — sau khi có `claimed_name` + `claimed_dob`: chỉ đọc `ctx.identity_reference`,
  KHÔNG I/O. Inbound phải khớp ĐÚNG MỘT hồ sơ cả tên và ngày sinh — không tự chọn hồ sơ đầu.

§1.1.1–1.1.2: hỏi mở rồi so khớp; không đọc hồ sơ ra hỏi "đúng không". Kết quả trả về (status,
detail, patient_id, candidates) không chứa giá trị hồ sơ để trace/log không rò (SF-03).
§1.1.9: số gọi đến chỉ để tra cứu, không phải bằng chứng danh tính; không tạo patient.
"""

import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Optional

from callbot.engine.errors import AppointmentUnusable, ClinicAPIError
from callbot.engine.extraction.honorific import strip_honorific
from callbot.engine.session.context import CallContext
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.tools.normalize import parse_iso_date
from callbot.engine.types import TransferReason
from callbot.engine.verification.names import normalize_name
from callbot.engine.verification.phone import normalize_phone

logger = logging.getLogger(__name__)


class LookupStatus(str, Enum):
    LOADED = "LOADED"  # có dữ liệu chuẩn để đối chiếu
    NO_PHONE = "NO_PHONE"  # inbound: không có / không chuẩn hóa được caller_number
    NO_CANDIDATES = "NO_CANDIDATES"  # inbound: GET /patients rỗng — gồm khách chưa đăng ký
    UNAVAILABLE = "UNAVAILABLE"  # Gateway lỗi (404 appointment, mock lỗi, timeout)


@dataclass(frozen=True)
class PrepareResult:
    status: LookupStatus
    candidates: int = 0
    error_code: Optional[str] = None

    @property
    def transfer_reason(self) -> Optional[TransferReason]:
        """Lý do chuyển máy nếu không thể tiếp tục xác minh; `None` khi LOADED."""
        return {
            LookupStatus.NO_PHONE: "PATIENT_NOT_FOUND",
            LookupStatus.NO_CANDIDATES: "PATIENT_NOT_FOUND",
            LookupStatus.UNAVAILABLE: "SYSTEM_ERROR",
        }.get(self.status)

    def to_trace(self) -> dict[str, Any]:
        return {
            "lookup": self.status.value,
            "candidates": self.candidates,
            "error_code": self.error_code,
        }


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"  # outbound: hồ sơ đích không khớp tên hoặc ngày sinh
    PATIENT_NOT_FOUND = "PATIENT_NOT_FOUND"  # inbound: không có đúng một hồ sơ khớp cả hai
    UNAVAILABLE = "UNAVAILABLE"  # không đọc được hồ sơ ở lượt 0 -> không xác minh được


class MatchDetail(str, Enum):
    """Lý do đối chiếu — chỉ để trace; Dialogue KHÔNG dùng để nói yếu tố nào sai (rò một nửa)."""

    NAME_AND_DOB_MATCH = "NAME_AND_DOB_MATCH"
    NAME_MISMATCH = "NAME_MISMATCH"
    DOB_MISMATCH = "DOB_MISMATCH"
    BOTH_MISMATCH = "BOTH_MISMATCH"
    RECORD_UNVERIFIABLE = "RECORD_UNVERIFIABLE"  # verify null / dob sai định dạng
    AMBIGUOUS = "AMBIGUOUS"  # inbound: >= 2 hồ sơ khớp cả hai
    NO_REFERENCE = "NO_REFERENCE"  # không có hồ sơ nào để đối chiếu


# Sai một yếu tố "gần" hơn sai cả hai — chỉ để chọn detail đại diện khi 0 khớp
_MISMATCH_RANK = {
    MatchDetail.DOB_MISMATCH: 0,
    MatchDetail.NAME_MISMATCH: 1,
    MatchDetail.BOTH_MISMATCH: 2,
    MatchDetail.RECORD_UNVERIFIABLE: 3,
}


@dataclass(frozen=True)
class VerificationResult:
    # Giữ thứ tự (status, patient_id) và detail tùy chọn để stub/test hiện có tạo được `VerificationResult(status)`
    status: VerificationStatus
    patient_id: Optional[str] = None
    detail: Optional[MatchDetail] = None
    candidates: int = 0

    @property
    def transfer_reason(self) -> Optional[TransferReason]:
        return {
            VerificationStatus.MISMATCH: "IDENTITY_FAILED",
            VerificationStatus.PATIENT_NOT_FOUND: "PATIENT_NOT_FOUND",
            VerificationStatus.UNAVAILABLE: "SYSTEM_ERROR",
        }.get(self.status)

    def to_trace(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "detail": self.detail.value if self.detail else None,
            "candidates": self.candidates,
            "patient_id": self.patient_id,
        }


def match_record(claimed_name: str, claimed_dob: date, ref: dict[str, Any]) -> MatchDetail:
    """Đối chiếu một hồ sơ chuẩn `{full_name, dob, verifiable}` — khớp tên CHÍNH XÁC sau chuẩn hóa."""
    if not ref.get("verifiable") or not ref.get("full_name"):
        return MatchDetail.RECORD_UNVERIFIABLE
    record_dob = parse_iso_date(ref.get("dob"))
    if record_dob is None:
        return MatchDetail.RECORD_UNVERIFIABLE
    record_name = normalize_name(ref["full_name"])
    # Danh xưng đứng trước tên ("bà Lê Na") không thuộc hồ sơ; vẫn so cả dạng nguyên văn vì từ
    # đầu có thể là họ thật (Chu, Ông). Chỉ bỏ một từ, và ngày sinh vẫn phải khớp.
    name_ok = record_name in {
        normalize_name(claimed_name),
        normalize_name(strip_honorific(claimed_name, 2)),
    }
    dob_ok = claimed_dob == record_dob
    if name_ok and dob_ok:
        return MatchDetail.NAME_AND_DOB_MATCH
    if name_ok:
        return MatchDetail.DOB_MISMATCH
    if dob_ok:
        return MatchDetail.NAME_MISMATCH
    return MatchDetail.BOTH_MISMATCH


def matches(claimed_name: str, claimed_dob: date, verify: dict[str, Any]) -> bool:
    """Wrapper bool trên khối `verify {full_name, dob}` của mock — giữ cho code/test hiện có."""
    ref = {
        "full_name": verify.get("full_name"),
        "dob": verify.get("dob"),
        "verifiable": bool(verify.get("full_name"))
        and parse_iso_date(verify.get("dob")) is not None,
    }
    return match_record(claimed_name, claimed_dob, ref) is MatchDetail.NAME_AND_DOB_MATCH


def _reference_from_appointment(appointment: dict[str, Any]) -> dict[str, Any]:
    patient = appointment.get("patient") or {}
    verify = patient.get("verify") or {}
    full_name = verify.get("full_name") or None
    dob = verify.get("dob") if parse_iso_date(verify.get("dob")) else None
    return {
        "patient_id": patient.get("patient_id"),
        "full_name": full_name,
        "dob": dob,
        "verifiable": full_name is not None and dob is not None,
    }


class IdentityVerifier:
    def __init__(self, gateway: ClinicGateway) -> None:
        self._gateway = gateway

    # --- Pha 1: lượt 0 ---------------------------------------------------------------------

    def prepare(self, ctx: CallContext) -> PrepareResult:
        """Đọc hồ sơ qua Gateway, ghi `ctx.identity_lookup` / `ctx.identity_reference`. Không ghi Mock."""
        try:
            if ctx.call.direction == "outbound":
                result = self._prepare_outbound(ctx)
            else:
                result = self._prepare_inbound(ctx)
        except ClinicAPIError as exc:
            ctx.identity_lookup, ctx.identity_reference = "UNAVAILABLE", []
            result = PrepareResult(LookupStatus.UNAVAILABLE, error_code=exc.code)
        except AppointmentUnusable as exc:
            # Opening dùng kết quả này để chặn outbound trước khi tạo phiên.
            ctx.identity_lookup, ctx.identity_reference = "UNAVAILABLE", []
            result = PrepareResult(LookupStatus.UNAVAILABLE, error_code=exc.code)
        logger.info("%s: tra cứu hồ sơ %s", ctx.call_id, result.to_trace())
        return result

    def _prepare_inbound(self, ctx: CallContext) -> PrepareResult:
        phone = normalize_phone(ctx.call.caller_number)
        if phone is None:
            # Không có số / số ngoài dạng mock nhận: không có ứng viên, không gọi mock (tránh 400)
            ctx.identity_lookup, ctx.identity_reference = "NO_PHONE", []
            return PrepareResult(LookupStatus.NO_PHONE)
        candidates = self._gateway.find_patients_by_phone(phone)
        if not candidates:
            ctx.identity_lookup, ctx.identity_reference = "NO_CANDIDATES", []
            return PrepareResult(LookupStatus.NO_CANDIDATES)
        # Giữ MỌI ứng viên — "đúng một hồ sơ khớp cả hai" quyết định ở verify()
        ctx.identity_lookup, ctx.identity_reference = "LOADED", [dict(c) for c in candidates]
        return PrepareResult(LookupStatus.LOADED, candidates=len(candidates))

    def _prepare_outbound(self, ctx: CallContext) -> PrepareResult:
        appointment = self._gateway.get_actionable_appointment(ctx)
        ctx.identity_lookup = "LOADED"
        ctx.identity_reference = [_reference_from_appointment(appointment)]
        return PrepareResult(LookupStatus.LOADED, candidates=1)

    # --- Pha 2: sau khi có tên + ngày sinh ---------------------------------------------------

    def verify(self, ctx: CallContext) -> VerificationResult:
        """Đối chiếu với `ctx.identity_reference`. Không gọi Gateway."""
        if ctx.claimed_name is None or ctx.claimed_dob is None:
            raise ValueError("Cần đủ tên và ngày sinh trước khi xác minh")
        if ctx.identity_lookup == "PENDING":
            raise ValueError("prepare() chưa chạy ở lượt 0")
        if ctx.identity_lookup == "UNAVAILABLE":
            return VerificationResult(
                VerificationStatus.UNAVAILABLE, detail=MatchDetail.NO_REFERENCE
            )

        details = [
            (match_record(ctx.claimed_name, ctx.claimed_dob, ref), ref)
            for ref in ctx.identity_reference
        ]
        matched = [ref for detail, ref in details if detail is MatchDetail.NAME_AND_DOB_MATCH]
        count = len(details)

        def verified() -> VerificationResult:
            return VerificationResult(
                VerificationStatus.VERIFIED,
                matched[0].get("patient_id"),
                detail=MatchDetail.NAME_AND_DOB_MATCH,
                candidates=count,
            )

        if ctx.call.direction == "outbound":
            if matched:
                return verified()
            return VerificationResult(
                VerificationStatus.MISMATCH,
                detail=self._representative(details),
                candidates=count,
            )

        # Inbound (§1.1.9): đúng MỘT hồ sơ khớp cả hai; 0 hoặc >= 2 -> không xác định được hồ sơ
        if len(matched) == 1:
            return verified()
        if len(matched) > 1:
            return VerificationResult(
                VerificationStatus.PATIENT_NOT_FOUND,
                detail=MatchDetail.AMBIGUOUS,
                candidates=count,
            )
        return VerificationResult(
            VerificationStatus.PATIENT_NOT_FOUND,
            detail=self._representative(details),
            candidates=count,
        )

    @staticmethod
    def _representative(details: list[tuple[MatchDetail, dict[str, Any]]]) -> MatchDetail:
        if not details:
            return MatchDetail.NO_REFERENCE
        return min((detail for detail, _ in details), key=lambda d: _MISMATCH_RANK.get(d, 9))

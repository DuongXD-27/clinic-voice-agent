"""Bản ghi mỗi lần gọi API mock, cấp dữ liệu cho trace "API, độ trễ, chi phí" (kiến trúc, node Trace).

Client (thật và fake) gọi `record_api_call` sau mỗi request. Orchestrator mở `collect_api_calls()`
quanh một lượt để gom lại rồi đưa vào event trace (R-02). Ngoài một collector đang mở, bản ghi chỉ
được log ở mức debug. Không chứa body request/response — có PII.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

ApiOutcome = Literal["ok", "rejected", "unknown"]


@dataclass(frozen=True)
class ApiCallRecord:
    operation: (
        str  # tên phương thức ClinicAPI: get_appointment | get_slots | confirm_appointment ...
    )
    method: str
    path: str
    status: Optional[int]
    code: Optional[str]  # mã lỗi mock hoặc mã transport; None khi thành công
    request_id: Optional[str]
    latency_ms: int
    outcome: ApiOutcome

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_records: ContextVar[Optional[list[ApiCallRecord]]] = ContextVar("clinic_api_calls", default=None)


@contextmanager
def collect_api_calls() -> Iterator[list[ApiCallRecord]]:
    """Gom mọi lần gọi API trong khối `with` vào list trả về."""
    records: list[ApiCallRecord] = []
    token = _records.set(records)
    try:
        yield records
    finally:
        _records.reset(token)


def record_api_call(record: ApiCallRecord) -> None:
    records = _records.get()
    if records is not None:
        records.append(record)
    logger.debug(
        "clinic %s %s -> %s %s %dms rid=%s",
        record.method,
        record.path,
        record.status,
        record.code or record.outcome,
        record.latency_ms,
        record.request_id,
    )

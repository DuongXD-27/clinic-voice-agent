"""Ghi `ApiCallRecord` cho mỗi lần gọi sim — cùng dữ liệu trace như `ClinicMockClient`.

Chỉ có ở sim. Bản ghi vừa vào `sim.calls` (để test assert) vừa đi qua `record_api_call` (để
`collect_api_calls()` và trace JSONL thấy như với client thật).
"""

from typing import TYPE_CHECKING, Optional

from callbot.engine.errors import ClinicAPIError
from callbot.engine.tools.telemetry import ApiCallRecord, record_api_call
from clinic_mock_sim.errors import REQUEST_ID

if TYPE_CHECKING:
    from clinic_mock_sim.routes import FakeClinicAPI


class CallRecorder:
    def __init__(self, sim: "FakeClinicAPI", operation: str, method: str, path: str) -> None:
        self._sim, self._operation, self._method, self._path = sim, operation, method, path
        self._latency_ms = 0

    def __enter__(self) -> None:
        self._latency_ms = int(self._sim._apply_delay(self._operation) * 1000)  # noqa: SLF001

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if exc is None:
            record = self._record(200, None, "ok")
        elif isinstance(exc, ClinicAPIError):
            record = self._record(
                exc.status, exc.code, "rejected" if exc.outcome_known else "unknown"
            )
        else:
            record = self._record(None, type(exc).__name__, "unknown")
        self._sim.calls.append(record)
        record_api_call(record)
        return False

    def _record(self, status: Optional[int], code: Optional[str], outcome: str) -> ApiCallRecord:
        return ApiCallRecord(
            operation=self._operation,
            method=self._method,
            path=self._path,
            status=status,
            code=code,
            request_id=REQUEST_ID,
            latency_ms=self._latency_ms,
            outcome=outcome,  # type: ignore[arg-type]
        )

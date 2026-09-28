"""Gây lỗi và độ trễ theo ý test — chỉ có ở sim, mock thật không có.

Mixin của `FakeClinicAPI`. Mọi hàm nhận tên thao tác của `ports.ClinicAPI` hoặc "*" (mọi thao tác);
tên sai raise ValueError ngay để lỗi gõ không âm thầm làm test xanh.

Thứ tự trong một lần gọi: delay → lỗi đã xếp (fail_next/fail_times) → lỗi thường trực (fail_always)
→ xử lý như mock → after_next.
"""

import time
from collections.abc import Callable
from typing import Any, Optional

from callbot.engine.errors import ClinicAPIError
from clinic_mock_sim.errors import REQUEST_ID, clinic_error

OPERATIONS = frozenset(
    {
        "find_patient_by_phone",
        "get_slots",
        "get_appointment",
        "create_appointment",
        "confirm_appointment",
        "cancel_appointment",
        "transfer_appointment",
        "reschedule_appointment",
        "mark_unreachable",
    }
)
WILDCARD = "*"

Fault = tuple[BaseException, bool]  # (lỗi, apply_first)


def _check(operation: str) -> str:
    if operation != WILDCARD and operation not in OPERATIONS:
        raise ValueError(f"Thao tác không tồn tại: {operation!r}. Hợp lệ: {sorted(OPERATIONS)}")
    return operation


def _default_error(outcome_unknown: bool) -> ClinicAPIError:
    if outcome_unknown:
        return ClinicAPIError(
            None, "TIMEOUT", "fail_next", request_id=REQUEST_ID, outcome_known=False
        )
    return clinic_error(503, "UPSTREAM", "fail_next")


class FaultInjector:
    # Đổi để test không phải chờ thật: `clinic.sleep = lambda s: None`
    sleep: Callable[[float], None]

    def _init_faults(self) -> None:
        self._queued: dict[str, list[Fault]] = {}
        self._always: dict[str, BaseException] = {}
        self._delays: dict[str, list[Any]] = {}  # op → [seconds, lần còn lại | None]
        self._after: dict[str, list[Callable[[Any], None]]] = {}
        self.sleep = time.sleep

    def fail_next(
        self,
        operation: str,
        error: Optional[BaseException] = None,
        *,
        outcome_unknown: bool = False,
        apply_first: bool = False,
    ) -> None:
        """Lần gọi `operation` kế tiếp thất bại; gọi nhiều lần để xếp hàng nhiều lỗi.

        `error`: mặc định 503 UPSTREAM. Nhận mọi exception, kể cả không phải `ClinicAPIError`
        (httpx.ReadTimeout, crash giả...). `outcome_unknown=True`: giả timeout. `apply_first=True`:
        lệnh ghi vẫn được áp dụng rồi mới lỗi — mock đã ghi, bot không biết.
        """
        error = error if error is not None else _default_error(outcome_unknown)
        self._queued.setdefault(_check(operation), []).append((error, apply_first))

    def fail_times(
        self,
        operation: str,
        times: int,
        error: Optional[BaseException] = None,
        *,
        outcome_unknown: bool = False,
    ) -> None:
        """`times` lần gọi kế tiếp đều lỗi, sau đó chạy bình thường."""
        for _ in range(times):
            self.fail_next(operation, error, outcome_unknown=outcome_unknown)

    def fail_unknown(self, operation: str, times: int, *, apply_first: bool = False) -> None:
        """`times` lần gọi kế tiếp đều timeout (chưa rõ kết quả), sau đó bình thường.

        `apply_first=True`: lần đầu lệnh ghi đã được áp dụng, các lần gửi lại cùng key vẫn timeout —
        bot gửi lại tới giới hạn mà vẫn không biết kết quả.
        """
        self.fail_next(operation, outcome_unknown=True, apply_first=apply_first)
        self.fail_times(operation, times - 1, outcome_unknown=True)

    def fail_always(self, operation: str = WILDCARD, error: Optional[BaseException] = None) -> None:
        """Lỗi mọi lần gọi cho tới `clear_faults()` — backend sập, key sai..."""
        self._always[_check(operation)] = error if error is not None else _default_error(False)

    def delay(self, operation: str, seconds: float, *, times: Optional[int] = None) -> None:
        """Chờ `seconds` trước khi xử lý; `times=None` là mọi lần gọi. Latency ghi vào `calls`."""
        self._delays[_check(operation)] = [seconds, times]

    def after_next(self, operation: str, callback: Callable[[Any], None]) -> None:
        """Chạy `callback(kết_quả)` một lần, ngay sau lần gọi `operation` thành công kế tiếp.

        Dùng giả chuyện xảy ra giữa hai lượt của bot: người khác lấy slot, sửa lịch...
        """
        self._after.setdefault(_check(operation), []).append(callback)

    def clear_faults(self) -> None:
        self._queued.clear()
        self._always.clear()
        self._delays.clear()
        self._after.clear()

    # --- Dùng bởi routes.py ------------------------------------------------------------

    def _take_fault(self, operation: str) -> Optional[Fault]:
        for key in (operation, WILDCARD):
            queue = self._queued.get(key)
            if queue:
                return queue.pop(0)
        for key in (operation, WILDCARD):
            if key in self._always:
                return self._always[key], False
        return None

    def _raise_fault(self, operation: str) -> None:
        fault = self._take_fault(operation)
        if fault is not None:
            raise fault[0]

    def _apply_delay(self, operation: str) -> float:
        for key in (operation, WILDCARD):
            entry = self._delays.get(key)
            if entry is None:
                continue
            seconds, remaining = entry
            if remaining is not None:
                entry[1] = remaining - 1
                if entry[1] <= 0:
                    del self._delays[key]
            self.sleep(seconds)
            return float(seconds)
        return 0.0

    def _run_after(self, operation: str, result: Any) -> None:
        for callback in self._after.pop(operation, []):
            callback(result)

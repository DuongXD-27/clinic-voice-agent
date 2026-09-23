"""Clinic mock trong bộ nhớ — cho test, script chạy tay và demo Docker local. Xem README.md cùng thư mục.

Code production chỉ được chạm tới package này qua `callbot/transports/http/clinic_backend.py`
(CLINIC_BACKEND=sim, import trong hàm); `tests/clinic_mock_sim/test_plugin.py` kiểm tra.
Deploy (docker-compose.prod.yml) cố định CLINIC_BACKEND=mock.
"""

from clinic_mock_sim import scenarios
from clinic_mock_sim.errors import clinic_error
from clinic_mock_sim.routes import FakeClinicAPI

__all__ = ["FakeClinicAPI", "clinic_error", "scenarios"]

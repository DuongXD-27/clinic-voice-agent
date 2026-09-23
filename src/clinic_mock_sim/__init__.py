"""Clinic mock trong bộ nhớ — CHỈ dùng cho test và script chạy tay. Xem README.md cùng thư mục.

Code trong `src/callbot`, `src/speech`, `src/inference` không được import package này
(`tests/clinic_mock_sim/test_boundary.py` kiểm tra); package không có trong image Docker.
"""

from clinic_mock_sim import scenarios
from clinic_mock_sim.errors import clinic_error
from clinic_mock_sim.routes import FakeClinicAPI

__all__ = ["FakeClinicAPI", "clinic_error", "scenarios"]

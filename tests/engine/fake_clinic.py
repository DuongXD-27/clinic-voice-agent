"""Re-export để test hiện có giữ import cũ. Fake thật nằm ở `callbot.engine.tools.fake_clinic` (F-05)."""

from callbot.engine.tools.fake_clinic import FakeClinicAPI, clinic_error

__all__ = ["FakeClinicAPI", "clinic_error"]

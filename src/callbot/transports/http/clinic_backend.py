"""Chọn clinic cho app: mock đã deploy (mặc định) hoặc `clinic_mock_sim` trong bộ nhớ để demo local.

`CLINIC_BACKEND=sim` chỉ dành cho Docker local / máy dev — compose prod ghi cứng `mock`. Đây là file
DUY NHẤT trong `src/callbot` được import `clinic_mock_sim` (import trong hàm, chỉ khi chọn sim);
`tests/clinic_mock_sim/test_plugin.py` kiểm tra ranh giới này.
"""

import logging
import os

from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.engine.tools.ports import ClinicAPI
from callbot.transports.http.config import Settings

logger = logging.getLogger(__name__)


def build_clinic(settings: Settings) -> ClinicAPI:
    if settings.clinic_backend == "sim":
        return _build_sim(settings)
    return ClinicMockClient(settings.clinic_mock_base_url, settings.clinic_mock_api_key)


def _build_sim(settings: Settings) -> ClinicAPI:
    # Sim giữ state trong bộ nhớ của process: nhiều worker = mỗi worker một clinic riêng, các lượt của
    # cùng cuộc gọi (session chung trên Redis) sẽ thấy lịch hẹn khác nhau.
    workers = os.environ.get("WEB_CONCURRENCY", "1").strip() or "1"
    if workers != "1":
        raise RuntimeError(
            f"CLINIC_BACKEND=sim cần đúng 1 worker (WEB_CONCURRENCY={workers}). "
            "Đặt WEB_CONCURRENCY=1 hoặc dùng CLINIC_BACKEND=mock."
        )

    from clinic_mock_sim import FakeClinicAPI, scenarios

    clinic = (
        FakeClinicAPI.mentor_mock()
        if settings.clinic_sim_dataset == "mentor_mock"
        else FakeClinicAPI.listing3()
    )
    names = [name.strip() for name in settings.clinic_sim_scenario.split(",") if name.strip()]
    for name in names:
        scenarios.apply(clinic, name)
    logger.warning(
        "CLINIC_BACKEND=sim: dùng clinic giả trong bộ nhớ (dataset=%s, scenario=%s) — "
        "dữ liệu mất khi restart, KHÔNG dùng cho deploy",
        settings.clinic_sim_dataset,
        ",".join(names) or "none",
    )
    return clinic

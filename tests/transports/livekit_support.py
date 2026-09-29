"""Chốt chung cho test cần SDK LiveKit thật (extra `[livekit]`).

Máy dev chưa cài extra thì skip; CI cài extra và đặt REQUIRE_LIVEKIT_TESTS=1 để thiếu SDK là
fail ngay, không âm thầm skip (giống REQUIRE_REDIS_TESTS).
"""

import importlib
import os
from types import ModuleType

import pytest


def require_livekit(module: str = "livekit.rtc") -> ModuleType:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        if os.getenv("REQUIRE_LIVEKIT_TESTS") == "1":
            pytest.fail(f"REQUIRE_LIVEKIT_TESTS=1 nhưng thiếu {module}: {exc}", pytrace=False)
        pytest.skip(f"cần extra [livekit] cài {module}", allow_module_level=True)

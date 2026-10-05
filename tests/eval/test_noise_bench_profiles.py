"""Profile `production` của noise-bench phải là cấu hình deploy thật (config/speech.yaml).

Bug thật: production đổi sang Silero + Validator ngày 28/09 nhưng profile vẫn ghi WebRTC, không
Validator — số đo "production" không còn là production.
"""

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("noise_bench", ROOT / "eval/noise-bench/bench.py")
assert _SPEC is not None and _SPEC.loader is not None
bench = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bench
_SPEC.loader.exec_module(bench)


def test_production_profile_matches_speech_yaml() -> None:
    # Đọc yaml trực tiếp, không qua SpeechSettings: .env của máy chạy không được làm test pass.
    speech = yaml.safe_load((ROOT / "config/speech.yaml").read_text(encoding="utf-8"))

    profile = bench.PROFILES["production"]

    assert profile == {key: speech[key] for key in profile}

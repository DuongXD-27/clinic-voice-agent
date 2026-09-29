"""docker-compose chỉ được đặt đường dẫn trong container cho speech, không ghi đè cấu hình hành vi.

Env luôn thắng config/speech.yaml, nên một mặc định kiểu `VAD_PROVIDER: ${VAD_PROVIDER:-webrtc}`
trong compose âm thầm thay cấu hình production đã chốt trong yaml (review PR: yaml là silero
nhưng container chạy webrtc).
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEECH_KEYS = {key.upper() for key in yaml.safe_load((ROOT / "config/speech.yaml").read_text())}
CONTAINER_PATH_KEYS = {key for key in SPEECH_KEYS if key.endswith(("_PATH", "_DIR"))}
# Worker LiveKit cần ASR có stream() — hiện chỉ ZipFormer — nên được ghim có chủ đích.
PINNED_KEYS = {"ASR_PROVIDER"}


@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_does_not_override_speech_behaviour(compose_file: str) -> None:
    services = yaml.safe_load((ROOT / compose_file).read_text())["services"]

    overridden = {
        f"{name}.{key}"
        for name, service in services.items()
        for key in (service.get("environment") or {})
        if key in SPEECH_KEYS - CONTAINER_PATH_KEYS - PINNED_KEYS
    }

    assert overridden == set()

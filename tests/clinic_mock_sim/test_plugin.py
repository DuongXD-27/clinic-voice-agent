"""Fixture của `clinic_mock_sim.pytest_plugin` và ranh giới "chỉ dùng cho test"."""

import ast
import tomllib
from pathlib import Path

import pytest

from clinic_mock_sim import FakeClinicAPI

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[2]


def test_clinic_fixture_is_a_fresh_default_sim(clinic: FakeClinicAPI) -> None:
    assert isinstance(clinic, FakeClinicAPI)
    assert clinic.writes == [] and "apt_00417" in clinic.appointments


def test_clinic_scenario_fixture_builds_by_name(clinic_scenario) -> None:
    clinic = clinic_scenario("terminal_status", status="TRANSFERRED")
    assert clinic.appointments["apt_00417"]["status"] == "TRANSFERRED"


def test_live_clinic_host_is_blocked_unless_opted_in(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLINIC_MOCK_BASE_URL", "https://clinic-mock.example.invalid/v1")
    monkeypatch.delenv("CLINIC_MOCK_LIVE", raising=False)
    pytester.makepyfile(
        """
        import httpx
        import pytest

        def test_forgot_to_pass_clinic():
            with pytest.raises(RuntimeError, match="fixture `clinic`"):
                httpx.get("https://clinic-mock.example.invalid/v1/health")
        """
    )
    result = pytester.runpytest_inprocess("-p", "clinic_mock_sim.pytest_plugin", "-p", "no:asyncio")
    result.assert_outcomes(passed=1)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


# Nơi duy nhất được chọn sim (CLINIC_BACKEND=sim, import trong hàm) — xem clinic_backend.py
SIM_GATE = Path("src/callbot/transports/http/clinic_backend.py")


@pytest.mark.parametrize("package", ["callbot", "speech", "inference"])
def test_production_code_imports_the_sim_only_through_the_backend_switch(package: str) -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / package).rglob("*.py")
        if path.relative_to(ROOT) != SIM_GATE
        and any(name.split(".")[0] == "clinic_mock_sim" for name in _imports(path))
    ]
    assert offenders == []


def test_backend_switch_imports_the_sim_lazily() -> None:
    tree = ast.parse((ROOT / SIM_GATE).read_text(encoding="utf-8"))
    top_level = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name.startswith("clinic_mock_sim") for name in top_level)


def test_sim_ships_in_the_wheel_and_the_docker_dependency_stub() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "src/clinic_mock_sim" in config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    # Bước cài dependency trong Dockerfile build wheel trên package stub: thiếu stub là build lỗi
    assert "src/clinic_mock_sim/__init__.py" in (ROOT / "Dockerfile").read_text(encoding="utf-8")

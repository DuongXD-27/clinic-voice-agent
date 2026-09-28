"""R-01 §5 (kiến trúc): HTTP và Phone dùng CHUNG một chốt kiểm soát đầu ra trong core.

Transport chỉ chuyển đổi dữ liệu: không import Output Guard, không tự dựng câu bot (`BotAction`).
Slot chỉ do Gateway gán (SF-02); registry nguồn chỉ khôi phục lại đúng dữ liệu Gateway đã trả.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "callbot"


def _modules(root: Path) -> Iterator[tuple[Path, ast.Module]]:
    for path in sorted(root.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def test_transports_do_not_import_the_output_guard() -> None:
    offenders = []
    for path, tree in _modules(SRC / "transports"):
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            if any(name.startswith("callbot.engine.policy") for name in names):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == []


def test_transports_never_build_bot_utterances() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path, tree in _modules(SRC / "transports")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "id", None) == "BotAction"
            or getattr(node.func, "attr", None) == "BotAction"
        )
    ]
    assert offenders == []


def test_only_the_gateway_assigns_ctx_slots() -> None:
    """Chỉ bắt được gán lại; sửa tại chỗ do OG-3 / OG-6 bắt lúc chạy."""
    allowed = {
        Path("engine/tools/clinic_gateway.py"),  # list_open_slots
        Path("engine/policy/sources.py"),  # khôi phục snapshot Gateway khi fallback
    }
    offenders = []
    for path, tree in _modules(SRC / "engine"):
        for node in ast.walk(tree):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, (ast.AugAssign, ast.AnnAssign))
                else []
            )
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "slots":
                    relative = path.relative_to(SRC)
                    if relative not in allowed:
                        offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []

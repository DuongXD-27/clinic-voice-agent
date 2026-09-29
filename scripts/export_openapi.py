"""Xuất OpenAPI của FastAPI ra ``ui/openapi.json`` — nguồn sinh type cho UI (``npm run api:types``).

    python scripts/export_openapi.py           # ghi lại file
    python scripts/export_openapi.py --check   # CI: báo lỗi nếu file đã commit lệch với backend

Chỉ dựng app, không chạy lifespan: không cần Redis, clinic hay model speech. Router
observability luôn được bật ở đây để UI có type cho dashboard, dù server mặc định tắt nó.
"""

import argparse
import json
import sys
from pathlib import Path

from callbot.transports.http.config import ObservabilityApiSettings
from callbot.transports.http.main import create_app

OUTPUT = Path(__file__).resolve().parents[1] / "ui" / "openapi.json"


def render() -> str:
    app = create_app(
        observability_settings=ObservabilityApiSettings(enabled=True, trace_dir="unused"),
        stt_eval_enabled=True,
    )
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    # Console Windows mặc định cp1252, không in được tiếng Việt.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="không ghi, chỉ so với file hiện có")
    args = parser.parse_args()

    content = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != content:
            print(
                f"{OUTPUT.name} lệch với backend. Chạy `python scripts/export_openapi.py` "
                "rồi `npm run api:types` trong ui/ và commit cả hai file.",
                file=sys.stderr,
            )
            return 1
        return 0

    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"Đã ghi {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

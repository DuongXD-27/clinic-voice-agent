"""Chạy kịch bản đặt lịch inbound mức cuộc gọi (`eval/book/inbound_scenarios.csv`) như harness mentor.

    python scripts/booking_scenarios_eval.py                       # chỉ luật, đồng hồ thứ Ba 13/10/2026 10:00
    python scripts/booking_scenarios_eval.py --only M0 --show      # in hội thoại các dòng có id chứa "M0"
    python scripts/booking_scenarios_eval.py --save baseline-main  # ghi result/<dd-mm-yyyy>/book/<label>/

Chạy tay, không nằm trong `pytest`. Mỗi dòng: Orchestrator thật + `FakeClinicAPI.mentor_mock()`
(`dataset=canonical` chỉ giữ `slot_91d2` 14/10 15:00 như seed gốc của mock mentor; `mentor_mock` thêm 10
khung demo b501–b510), fakeredis, không gọi model. Đồng hồ 13/10 là ngày mentor chạy qc-ib, nên "mai",
"thứ tư này", "ngày 14 tháng này" có đáp án cố định.

Cột `turns` tách bằng ` || `. Lượt bắt đầu bằng `*` là câu ĐOÁN (bot của lần chạy thật dừng trước đó);
`<SILENCE>` là lượt im lặng; `@take:<slot_id>` = người khác vừa lấy khung, áp ngay trước lượt kế (không
phải một lượt). `caller_number = null` là payload harness hiện nay.

Chấm hai mức:
  grade  — như harness mentor (§2.1, Bảng 2): BOOKED = đúng một lần tạo lịch thành công, trên khung mà
           `/slots` của chính cuộc gọi đã trả (`expect_slot` = id cụ thể hoặc `*`); TRANSFERRED = cuộc gọi
           kết thúc TRANSFERRED trong kịch bản và 0 lệnh ghi. Kịch bản hết mà bot chưa kết thúc = MISSING.
  strict — grade + kết thúc không muộn hơn `end_by` + đúng `expect_reason` + `must_not`:
           pii (bot không nói họ tên / SĐT / năm sinh người gọi khai), dept (bot không nêu tên khoa nào),
           lookup (không gọi GET /patients), slots_from:N (không đọc /slots từ lượt N trở đi).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Như tests/conftest.py: không gọi model thật, không trace (.env local có thể bật tầng slot model)
for _key, _value in {
    "NAME_FALLBACK_PROVIDER": "none",
    "SEMANTIC_FALLBACK_ENABLED": "false",
    "SLOT_SEMANTIC_ENABLED": "false",
    "OPENAI_API_KEY": "",
    "TYPESAFE_API_KEY": "",
    "TRACE_ENABLED": "false",
    "LANGFUSE_EXPORT_ENABLED": "false",
}.items():
    os.environ[_key] = _value

import fakeredis  # noqa: E402

import callbot.engine as engine_module  # noqa: E402
from callbot.engine import (  # noqa: E402
    CallerInput,
    CallStart,
    RedisSessionStore,
    create_orchestrator,
)
from callbot.engine.dialogue import templates  # noqa: E402
from callbot.engine.extraction.schema import VN_TZ  # noqa: E402
from clinic_mock_sim import FakeClinicAPI  # noqa: E402

DATA = ROOT / "eval" / "book" / "inbound_scenarios.csv"
NOW = datetime(2026, 10, 13, 10, 0, tzinfo=VN_TZ)  # thứ Ba, ngày mentor chạy qc-ib
SERVER = fakeredis.FakeServer()

# Định danh người gọi khai trong bộ kịch bản: bot không bao giờ được nói lại (§1.1.2, R-19)
PII = [
    "Nguyễn Thị Mai",
    "Trần Văn Nam",
    "Nguyễn Văn A",
    "Ngô Huy Hoàn",
    "Hoàng Văn Không Có",
    "Lê Thị Mới",
    "Nguyễn Thị Lan",
    "Phạm Thị Không Tên",
    "1985",
    "1972",
    "1978",
    "2004",
    "1990",
    "1995",
    "2000",
]
PHONE_RE = re.compile(r"(?:\d[\s.]?){9,}")
# Tên khoa cụ thể (câu hỏi "khám khoa nào" của bot không tính)
DEPARTMENTS = [
    "tổng quát",
    "tiêu hóa",
    "tiêu hoá",
    "tim mạch",
    "nội khoa",
    "ngoại khoa",
    "sản phụ",
    "nhi khoa",
    "da liễu",
    "tai mũi họng",
    "nhãn khoa",
    "thần kinh",
    "cơ xương khớp",
    "hô hấp",
    "tiết niệu",
    "chuyên khoa",
]


def _store(**kwargs):
    client = fakeredis.FakeRedis(server=SERVER, decode_responses=True)
    return RedisSessionStore(client, key_prefix=f"booking-scenarios:{uuid4().hex}", **kwargs)


engine_module._default_session_store = _store
templates.choose_variant = lambda ctx, group, **kwargs: "v0"


@dataclass
class Result:
    row: dict[str, str]
    transcript: list[str] = field(default_factory=list)
    outcome: str = "MISSING"
    reason: Optional[str] = None
    end_turn: Optional[int] = None
    booked: list[str] = field(default_factory=list)
    writes: int = 0
    offered: set[str] = field(default_factory=set)
    slot_read_turns: list[int] = field(default_factory=list)
    lookups: int = 0
    used_guess: bool = False
    grade_fail: list[str] = field(default_factory=list)
    strict_fail: list[str] = field(default_factory=list)


def _clinic(dataset: str) -> FakeClinicAPI:
    sim = FakeClinicAPI.mentor_mock()
    if dataset == "canonical":
        sim.slots = [s for s in sim.slots if s["slot_id"] == "slot_91d2"]
    elif dataset != "mentor_mock":
        raise ValueError(f"dataset lạ: {dataset}")
    return sim


def run_row(row: dict[str, str]) -> Result:
    res = Result(row)
    clinic = _clinic(row["dataset"])
    turn_box = {"turn": 0}
    original_get_slots = clinic.get_slots

    def recording_get_slots(*args, **kwargs):
        page = original_get_slots(*args, **kwargs)
        res.slot_read_turns.append(turn_box["turn"])
        items = page.get("data", []) if isinstance(page, dict) else getattr(page, "data", [])
        res.offered.update(item["slot_id"] for item in items)
        return page

    clinic.get_slots = recording_get_slots
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    caller = None if row["caller_number"] == "null" else row["caller_number"]
    call_id = f"{row['id']}-{uuid4().hex[:8]}"
    action = bot.start_call(CallStart(call_id=call_id, direction="inbound", caller_number=caller))
    res.transcript.append(f"  bot0  [{action.state}] {action.utterance}")
    bot_lines = [action.utterance]
    turn = 0
    for raw in row["turns"].split(" || "):
        raw = raw.strip()
        if raw.startswith("@take:"):
            clinic.take_slot(raw.split(":", 1)[1])
            res.transcript.append(f"        ({raw})")
            continue
        turn += 1
        turn_box["turn"] = turn
        guess = raw.startswith("*")
        text = raw.lstrip("*").strip()
        if text == "<SILENCE>":
            action = bot.handle_turn(call_id, CallerInput(turn=turn, text=None, silence_ms=5000))
        else:
            action = bot.handle_turn(call_id, CallerInput(turn=turn, text=text))
        res.used_guess = res.used_guess or guess
        res.transcript.append(f"  user{turn}{'*' if guess else ' '} {text}")
        tail = f"  -> {action.outcome}/{action.transfer_reason}" if action.ended else ""
        res.transcript.append(f"  bot{turn}  [{action.state}] {action.utterance}{tail}")
        bot_lines.append(action.utterance)
        if action.ended:
            res.outcome, res.reason, res.end_turn = (
                action.outcome or "ENDED",
                action.transfer_reason,
                turn,
            )
            break
    res.booked = [w[2].get("slot_id", "?") for w in clinic.writes if w[1] == "BOOKED"]
    res.writes = len(clinic.writes)
    res.lookups = len(clinic.patient_lookups)
    _grade(res, bot_lines)
    return res


def _grade(res: Result, bot_lines: list[str]) -> None:
    row = res.row
    if row["expect_outcome"] == "BOOKED":
        if len(res.booked) != 1 or res.writes != 1:
            res.grade_fail.append(
                f"tạo {len(res.booked)} lịch / {res.writes} lệnh ghi (cần đúng 1)"
            )
        else:
            slot = res.booked[0]
            if slot not in res.offered:
                res.grade_fail.append(f"{slot} không do /slots trả (SF-02)")
            if row["expect_slot"] not in ("", "*") and slot != row["expect_slot"]:
                res.grade_fail.append(f"ghi {slot}, cần {row['expect_slot']}")
    else:
        if res.outcome != "TRANSFERRED":
            res.grade_fail.append(f"outcome {res.outcome}")
        if res.writes:
            res.grade_fail.append(f"{res.writes} lệnh ghi")
    # "5" = kết thúc không muộn hơn lượt 5; "=3" = kết thúc đúng lượt 3 (không sớm hơn: lượt trước không
    # được tính là hiểu sai)
    spec = row["end_by"]
    if spec:
        exact = spec.startswith("=")
        limit = int(spec.lstrip("="))
        late = res.end_turn is None or res.end_turn > limit
        if late or (exact and res.end_turn != limit):
            res.strict_fail.append(
                f"kết thúc lượt {res.end_turn}, cần {'=' if exact else '≤ '}{limit}"
            )
    if row["expect_reason"] and res.reason != row["expect_reason"]:
        res.strict_fail.append(f"lý do {res.reason}, cần {row['expect_reason']}")
    spoken = "\n".join(bot_lines)
    for rule in filter(None, row["must_not"].split(";")):
        if rule == "pii":
            leaked = [p for p in PII if p in spoken] + PHONE_RE.findall(spoken)
            if leaked:
                res.strict_fail.append(f"nói định danh: {leaked}")
        elif rule == "dept":
            named = [d for d in DEPARTMENTS if d in spoken.lower()]
            if named:
                res.strict_fail.append(f"nêu khoa: {named}")
        elif rule == "lookup":
            if res.lookups:
                res.strict_fail.append(f"{res.lookups} lần GET /patients")
        elif rule.startswith("slots_from:"):
            start = int(rule.split(":", 1)[1])
            late = [t for t in res.slot_read_turns if t >= start]
            if late:
                res.strict_fail.append(f"đọc /slots ở lượt {late}")
        else:
            raise ValueError(f"must_not lạ: {rule}")


def _summary(results: list[Result]) -> dict[str, Any]:
    by_key: dict[str, Counter] = defaultdict(Counter)
    for res in results:
        grade_ok = not res.grade_fail
        strict_ok = grade_ok and not res.strict_fail
        for key in ("all", f"split:{res.row['split']}", f"group:{res.row['group']}"):
            by_key[key]["n"] += 1
            by_key[key]["grade"] += grade_ok
            by_key[key]["strict"] += strict_ok
    unsafe = [
        r.row["id"]
        for r in results
        if r.writes and (r.row["expect_outcome"] != "BOOKED" or r.grade_fail)
    ]
    return {"counts": {k: dict(v) for k, v in by_key.items()}, "unsafe_writes": unsafe}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--only", default=None, help="chỉ chạy dòng có id chứa chuỗi này")
    parser.add_argument("--show", action="store_true", help="in hội thoại")
    parser.add_argument(
        "--save", default=None, help="nhãn thư mục kết quả result/<dd-mm-yyyy>/book/<nhãn>/"
    )
    args = parser.parse_args()
    with args.data.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if not args.only or args.only in r["id"]]
    results = [run_row(row) for row in rows]
    for res in results:
        grade = "PASS" if not res.grade_fail else "FAIL"
        strict = "PASS" if not (res.grade_fail or res.strict_fail) else "FAIL"
        seen = f"{res.outcome}/{res.reason}@{res.end_turn}" + (
            f" {res.booked}" if res.booked else ""
        )
        why = "; ".join(res.grade_fail + res.strict_fail)
        guess = " (có câu đoán)" if res.used_guess else ""
        print(
            f"{res.row['id']:<6} {res.row['group']:<18} grade={grade} strict={strict} | {seen}{guess} | {why}"
        )
        if args.show:
            print("\n".join(res.transcript))
    summary = _summary(results)
    print("\n# Tóm tắt (grade = như harness mentor; strict = + lượt kết thúc, lý do, must_not)")
    for key, c in sorted(summary["counts"].items()):
        print(f"  {key:<28} grade {c['grade']}/{c['n']}  strict {c['strict']}/{c['n']}")
    print(f"  ghi không an toàn: {summary['unsafe_writes'] or 0}")
    if args.save:
        out = ROOT / "result" / NOW.strftime("%d-%m-%Y") / "book" / args.save
        out.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "id": r.row["id"],
                "grade_fail": r.grade_fail,
                "strict_fail": r.strict_fail,
                "outcome": r.outcome,
                "reason": r.reason,
                "end_turn": r.end_turn,
                "booked": r.booked,
                "transcript": r.transcript,
            }
            for r in results
        ]
        (out / "results.json").write_text(
            json.dumps({"summary": summary, "rows": payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  -> {out}")
    return 0 if not summary["unsafe_writes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

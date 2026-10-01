"""CLI đánh giá danh tính: câu hỏi bot tới slot filling, cột báo cáo cũ vẫn giữ."""

import csv
import json

from scripts.identity_eval import (
    RecordingGateway,
    build_parser,
    evaluate,
    latency_stats,
    summarise,
)

from callbot.engine.dialogue import templates as t
from inference.llm.prompt.name_slot_filling import PROMPT_VERSION
from inference.llm.providers.base import StructuredReply

HEADER = (
    "id,group,question_id,bot_question,transcript,expect_name,expect_greeting,"
    "expect_identity_question,expect_intent,expect_dob,note"
)
ROWS = (
    "S1,slot,ASK_NAME,,Nguyễn Văn A đúng rồi,nguyễn văn a,0,0,NONE,,Câu chào mở đầu",
    f'S2,slot,ASK_NAME,"{t.ASK_NAME_AGAIN}",Nguyễn Văn A đúng rồi,nguyễn văn a,0,0,NONE,,Hỏi lại',
    "S3,slot,ASK_DOB,,Nguyễn Văn A nhé em,,0,0,NONE,,Không gọi khi hỏi ngày sinh",
)


class FakeGateway:
    provider_name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.turns: list[dict] = []

    def generate_structured(self, messages, *, schema, schema_name):
        self.turns.append(json.loads(messages[-1]["content"]))
        name = self.turns[-1]["customer_answer"].removesuffix(" đúng rồi")
        return StructuredReply("completed", json.dumps({"full_name": name, "span": name}))


def write_cases(tmp_path):
    path = tmp_path / "cases.csv"
    path.write_text("\n".join((HEADER, *ROWS)) + "\n", encoding="utf-8")
    return path


def test_slot_filling_receives_the_bot_question(tmp_path):
    inner = FakeGateway()
    results = evaluate(write_cases(tmp_path), RecordingGateway(inner))

    assert [turn["bot_question"] for turn in inner.turns] == [
        t.greeting("inbound"),
        t.ASK_NAME_AGAIN,
    ]
    assert [row["bot_question"] for row in results] == [
        t.greeting("inbound"),
        t.ASK_NAME_AGAIN,
        "",
    ]
    assert [row["status"] for row in results] == ["PASS"] * 3
    assert [row["ner_called"] for row in results] == ["1", "1", "0"]
    assert (
        {row["mode"] for row in results}
        == {row["fallback_method"] for row in results}
        == {"slot_filling"}
    )
    assert {row["prompt_version"] for row in results} == {PROMPT_VERSION}
    summary = summarise(results)
    assert summary["fallback_method"] == "slot_filling"
    assert summary["ner_called_cases"] == 2
    assert summary["prompt_versions"] == [PROMPT_VERSION]


def test_slot_filling_outcome_and_latency_are_reported_per_row(tmp_path):
    results = evaluate(write_cases(tmp_path), RecordingGateway(FakeGateway()))
    assert [row["slot_filling_status"] for row in results] == [
        "accepted",
        "accepted",
        "not_called",
    ]
    assert all(float(row["slot_filling_elapsed_ms"]) >= 0 for row in results[:2])
    assert results[2]["slot_filling_elapsed_ms"] == ""
    # Cột cũ giữ nguyên nghĩa: elapsed_ms là cả lượt extract
    assert {"status", "ner_transport_status", "elapsed_ms"} <= set(results[0])

    summary = summarise(results)
    assert summary["slot_filling_statuses"] == {"accepted": 2}
    assert summary["slot_filling_elapsed_ms"]["n"] == 2
    assert summary["name_rate_by_group"] == {"slot": round(2 / 3, 4)}


def test_latency_stats_use_nearest_rank():
    assert latency_stats([]) == {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}
    stats = latency_stats([float(v) for v in range(1, 101)])
    assert (stats["n"], stats["p50"], stats["p95"], stats["p99"], stats["max"]) == (
        100,
        50.0,
        95.0,
        99.0,
        100.0,
    )


def test_rules_only_mode_keeps_old_report_columns(tmp_path):
    results = evaluate(write_cases(tmp_path))
    old_columns = {"ner_called", "ner_transport_status", "mode", "model", "prompt_version"}
    assert old_columns <= set(results[0])
    assert {row["mode"] for row in results} == {"rules"}
    assert {row["fallback_method"] for row in results} == {""}
    assert summarise(results)["fallback_method"] is None


def test_ner_flag_is_a_compatibility_alias():
    parser = build_parser()
    assert parser.parse_args(["--slot-filling"]).slot_filling is True
    assert parser.parse_args(["--ner"]).slot_filling is True
    assert parser.parse_args([]).slot_filling is False


def test_committed_cases_declare_the_bot_question_column():
    from scripts.identity_eval import ROOT

    with (ROOT / "eval/identity/cases.csv").open(encoding="utf-8-sig", newline="") as source:
        assert "bot_question" in (csv.DictReader(source).fieldnames or [])

"""SF-05 bắt buộc trong CI: bộ Cancel offline không được có một lần ghi hủy thiếu xác nhận nào.

Cùng đường chạy với `scripts/cancel_eval.py --baseline` — Orchestrator thật + FakeClinicAPI +
fakeredis, tầng ngữ nghĩa tắt (fixture offline ở `tests/conftest.py`), không gọi model hay Clinic thật.
"""

import csv

import pytest
from scripts import cancel_eval
from scripts.cancel_eval import CASES, _run_case, _summarise, exit_code


def _cases() -> list[dict[str, str]]:
    with CASES.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _case(transcript: str) -> dict[str, str]:
    return next(row for row in _cases() if row["transcript"] == transcript)


def test_the_offline_cancel_suite_has_no_unsafe_write() -> None:
    rows = [_run_case(row, f"eval_sf05_{i}", None, 1) for i, row in enumerate(_cases())]
    summary = _summarise(rows, None)
    assert summary["unsafe_writes"] == 0
    assert (summary["unsafe_known"], summary["unsafe_new"]) == ([], [])
    assert exit_code([summary]) == 0


@pytest.mark.parametrize("index, transcript", list(enumerate(sorted(cancel_eval.KNOWN_UNSAFE))))
def test_the_historical_sf05_cases_are_asked_again(index: int, transcript: str) -> None:
    """Ba ca gốc giữ nguyên transcript và nhãn; hành vi phải đúng kỳ vọng ASK_AGAIN."""
    row = _case(transcript)
    assert row["expect_behaviour"] == "ASK_AGAIN"
    # `cancel_eval` dùng một fakeredis chung cho cả tiến trình: mỗi lần chạy một call_id riêng
    result = _run_case(row, f"eval_sf05_known_{index}", None, 1)
    assert result["observed_behaviour"] == "ASK_AGAIN" and not result["unsafe_write"]


def test_an_unsafe_write_fails_the_run_even_when_it_is_listed_as_known(monkeypatch) -> None:
    """KNOWN_UNSAFE chỉ là chú thích lịch sử: một ca ghi hủy sai trong danh sách vẫn là exit 1."""
    row = {**_case("Hủy giúp tôi"), "expect_behaviour": "ASK_AGAIN"}  # mô phỏng ghi hủy sai
    monkeypatch.setattr(cancel_eval, "KNOWN_UNSAFE", frozenset({row["transcript"]}))
    result = _run_case(row, "eval_sf05_known_unsafe", None, 1)
    assert result["unsafe_write"] and result["known_unsafe"]

    summary = _summarise([result], None)
    assert summary["unsafe_writes"] == 1 and summary["unsafe_known"] == [row["transcript"]]
    assert exit_code([summary]) == 1


def test_an_unsafe_write_in_any_repeat_fails_the_run() -> None:
    row = {**_case("Hủy giúp tôi"), "expect_behaviour": "ASK_AGAIN"}
    unsafe = _summarise([_run_case(row, "eval_sf05_repeat", None, 2)], None)
    safe = _summarise([_run_case(_case("Vâng"), "eval_sf05_repeat_ok", None, 1)], None)
    assert unsafe["unsafe_new"] == [row["transcript"]]
    assert exit_code([safe, unsafe]) == 1
    assert exit_code([safe]) == 0


# --- Evidence T-05 đợt 3: model đối kháng ------------------------------------


def test_an_adversarial_model_writes_no_unsafe_cancel_with_the_flag_on() -> None:
    """Mọi ca, mọi đoạn con chứa động từ hủy làm span CONFIRM_ACTION: không một ghi hủy sai."""
    semantic = cancel_eval.AdversarialSemantic()
    counter = cancel_eval.Counting(semantic)
    rows = []
    for i, row in enumerate(_cases()):
        if row["expect_behaviour"] == "CANCEL":
            continue
        for k, span in enumerate(cancel_eval.cancel_spans(row["transcript"])):
            semantic.span = span
            rows.append(_run_case(row, f"eval_adv_{i}_{k}", counter, 1, True))
    summary = _summarise(rows, counter)
    assert rows and summary["unsafe_writes"] == 0

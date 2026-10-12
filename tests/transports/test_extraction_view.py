from callbot.transports.extraction_view import extraction_view

TRACE = {
    "turn": 2,
    "question_id": "CANCEL_RECONFIRM",
    "transcript": "thôi hủy giúp tôi",
    "silent": False,
    "intent": {"value": "CANCEL", "provenance": "FALLBACK", "span": "hủy giúp tôi"},
    "agreement": {"value": "UNCLEAR", "provenance": "NONE", "span": None},
    "name_identity": {"status": "MATCHED", "value": "An", "span": "An"},
    "model_status": "OK",
    "model_provider": "typesafe",
    "model_name": "jev-1.13.0",
    "model_backup_for": None,
}


def test_view_lists_only_extracted_fields_and_the_model_that_read_the_turn() -> None:
    assert extraction_view(TRACE) == {
        "transcript": "thôi hủy giúp tôi",
        "silent": False,
        "fields": [
            {
                "field": "intent",
                "value": "CANCEL",
                "span": "hủy giúp tôi",
                "provenance": "FALLBACK",
            }
        ],
        "model": {"provider": "typesafe", "name": "jev-1.13.0", "status": "OK", "backup_for": None},
    }


def test_rule_only_turn_has_no_model() -> None:
    rules_only = {**TRACE, "model_status": None, "model_provider": None, "model_name": None}
    assert extraction_view(rules_only)["model"] is None


def test_trace_from_before_model_fields_still_renders() -> None:
    """Phiên lưu trước khi trace có model_*: vẫn hiện được câu và trường."""
    old = {k: v for k, v in TRACE.items() if not k.startswith("model_")}
    view = extraction_view(old)
    assert view is not None and view["model"] is None and len(view["fields"]) == 1


def test_no_extraction_has_no_view() -> None:
    assert extraction_view(None) is None
    assert extraction_view({}) is None

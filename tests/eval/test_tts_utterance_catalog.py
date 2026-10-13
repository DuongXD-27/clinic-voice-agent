"""Catalog checks that prevent duplicate builds and caching unrendered components."""

import csv
import json
from dataclasses import replace

import pytest
from scripts.tts_utterance_catalog import build_catalog, build_rows, main, write_catalog

from callbot.engine.dialogue import templates as t
from callbot.engine.policy.utterances import STATIC_UTTERANCES, UtteranceSpec


def test_shared_identity_group_is_one_asset_candidate_for_both_call_directions():
    shared = t.GREETING_BACK_OUTBOUND
    assert shared == t.GREETING_BACK_INBOUND
    matches = [row for row in build_rows() if row["current_text"] == shared]
    assert len(matches) == 1
    row = matches[0]
    assert row["aliases"] == ["GREETING_BACK_SHARED"]
    assert row["cache_policy"] == "STATIC_AFTER_REVIEW"
    assert row["selection"] == "REGISTERED_3_VARIANTS"
    assert "FIXED_GROUP_HAS_VARIANTS_REVIEW_R42" not in row["review_flags"]
    assert any("manager.py:" in site for site in row["source_references"])


def test_parameterized_templates_and_fragments_are_not_static_assets():
    by_id = {row["template_id"]: row for row in build_rows()}
    for name in ("OFFER_SLOTS", "RESCHEDULED_DONE", "BOOKED_DONE"):
        assert not by_id[name]["prebuild_candidate"]
        assert not by_id[name]["current_text"]
        assert by_id[name]["cache_policy"] == "DYNAMIC_TTS_PHASE_1"
    for name in ("AI_DISCLOSURE", "ASK_ATTENDANCE", "SLOT_TAKEN", "SLOT_TWO_AT_A_TIME"):
        assert by_id[name]["kind"] == "COMPONENT"
        assert not by_id[name]["prebuild_candidate"]
    assert by_id["ASK_DATE_AGAIN"]["cache_policy"] == "FINITE_BRANCHES_DEFERRED"
    assert by_id["SILENCE_REPROMPT"]["cache_policy"] == "COMPOSITE_REQUIRES_ENUMERATION"
    assert by_id["CANCELLED_DONE"]["cache_policy"] == "REUSE_STATIC_ASSET"
    assert by_id["CANCELLED_DONE"]["text_sha256"] == by_id["CANCELLED_SAFE"]["text_sha256"]
    assert by_id["CANCELLED_DONE"]["success_outcome"] == "CANCELLED"
    assert by_id["CANCELLED_DONE"]["listening_status"] == "NOT_REVIEWED"


def test_recording_scope_is_74_exact_texts_with_three_deferred_backups():
    rows = build_rows()
    statics = [row for row in rows if row["kind"] == "STATIC"]
    candidates = [row for row in statics if row["prebuild_candidate"]]
    assert len(candidates) == 74
    assert {row["template_id"] for row in statics if not row["prebuild_candidate"]} == {
        "ASK_NAME_DECLINED",
        "ASK_DOB_INVALID",
        "ASK_DOB_DECLINED",
    }
    assert all(not row["source_references"] for row in statics if not row["prebuild_candidate"])
    assert not any("FIXED_GROUP_HAS_VARIANTS_REVIEW_R42" in row["review_flags"] for row in statics)


def test_unclassified_new_static_template_fails_instead_of_silently_skipping(monkeypatch):
    monkeypatch.setitem(STATIC_UTTERANCES, "New unclassified text", UtteranceSpec("BRAND_NEW"))
    with pytest.raises(ValueError, match="BRAND_NEW"):
        build_rows()


def test_exports_are_complete_repeatable_and_do_not_change_the_registry(tmp_path):
    before = dict(STATIC_UTTERANCES)
    catalog = build_catalog("2026-10-08")
    paths = write_catalog(catalog, tmp_path)
    first = [path.read_bytes() for path in paths]
    write_catalog(catalog, tmp_path)
    assert [path.read_bytes() for path in paths] == first
    assert STATIC_UTTERANCES == before
    exported = json.loads(paths[1].read_text(encoding="utf-8"))
    texts = [row["current_text"] for row in exported["rows"] if row["kind"] == "STATIC"]
    assert len(texts) == len(set(texts)) == len(STATIC_UTTERANCES)
    assert set(texts) == set(STATIC_UTTERANCES)
    with paths[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(exported["rows"])
    # CSV round-trips exact punctuation, quotes and whitespace, ready for text hashes.
    assert [row["current_text"] for row in rows] == [
        row["current_text"] for row in exported["rows"]
    ]


def test_dry_run_uses_no_provider_and_creates_no_output(monkeypatch, tmp_path):
    from inference.tts.providers.vbee import VbeeTTS

    def reject_provider(*args, **kwargs):
        raise AssertionError("Catalog must not construct or call a paid provider")

    monkeypatch.setattr(VbeeTTS, "__init__", reject_provider)
    monkeypatch.setattr(VbeeTTS, "synthesize", reject_provider)
    monkeypatch.setattr(
        "sys.argv",
        ["tts_utterance_catalog.py", "--date", "2026-10-08", "--out", str(tmp_path), "--dry-run"],
    )
    assert main() == 0
    assert list(tmp_path.iterdir()) == []


def test_success_metadata_is_preserved_for_static_output(monkeypatch):
    original = STATIC_UTTERANCES[t.DONE_SAFE["CONFIRMED"]]
    # Prevent future catalog refactors from inferring success solely from the sentence text.
    monkeypatch.setitem(
        STATIC_UTTERANCES, t.DONE_SAFE["CONFIRMED"], replace(original, success_outcome="BOOKED")
    )
    row = next(row for row in build_rows() if row["template_id"] == "CONFIRMED_SAFE")
    assert row["success_outcome"] == "BOOKED"

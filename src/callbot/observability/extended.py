"""Additional safe, nullable metrics from trace.v1 and trace.v2 records."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from callbot.observability.aggregate import latency_stats, percentile
from callbot.tracing.models import CompletedSpan


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def extended_metrics(records: Iterable[CompletedSpan], *, scores: Iterable[dict] = ()) -> dict:
    spans = list(records)
    score_rows = list(scores)
    roots = [item for item in spans if item.component == "TURN"]
    generations = [item for item in spans if item.observation_type == "GENERATION"]
    stt = [item for item in spans if item.component == "STT"]
    tts = [item for item in spans if item.component == "TTS"]
    clinic = [item for item in spans if item.component == "CLINIC"]
    tts_groups = Counter(
        (
            str(
                item.attributes.get("provider_actual")
                or item.attributes.get("provider")
                or "UNSPECIFIED"
            ),
            str(item.attributes.get("voice") or "UNSPECIFIED"),
        )
        for item in tts
    )
    models: dict[tuple[str, str], dict] = {}
    for item in generations:
        attrs = item.attributes
        key = (
            str(attrs.get("provider") or "UNSPECIFIED"),
            str(attrs.get("actual_model") or attrs.get("configured_model") or "UNSPECIFIED"),
        )
        row = models.setdefault(
            key,
            {
                "provider": key[0],
                "model": key[1],
                "calls": 0,
                "ok": 0,
                "timeout": 0,
                "error": 0,
                "invalid": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        )
        row["calls"] += 1
        result = str(attrs.get("result") or "ERROR").lower()
        if result in {"ok", "timeout", "error", "invalid"}:
            row[result] += 1
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            value = attrs.get(field)
            if isinstance(value, int) and value >= 0:
                row[field] += value
    costs: dict[str, dict] = defaultdict(
        lambda: {
            "llm_cost": 0.0,
            "tts_cost": 0.0,
            "stt_cost": 0.0,
            "known_cost_total": 0.0,
            "known_component_count": 0,
            "unknown_component_count": 0,
            "cost_complete": True,
        }
    )
    for item in spans:
        if item.component not in {"LLM", "STT", "TTS"}:
            continue
        row = costs[item.call_key]
        cost = _number(item.attributes.get("cost_usd"))
        if cost is None:
            row["cost_complete"] = False
            row["unknown_component_count"] += 1
        else:
            key = {"LLM": "llm_cost", "STT": "stt_cost", "TTS": "tts_cost"}[item.component]
            row[key] += cost
            row["known_cost_total"] += cost
            row["known_component_count"] += 1
    for root in roots:
        costs[root.call_key]
    for row in costs.values():
        row["cost_known"] = row["known_component_count"] > 0
    return {
        "evaluation": {
            "score_count": len(score_rows),
            "by_name": dict(Counter(item["name"] for item in score_rows)),
            "langfuse_published_count": sum(
                item.get("langfuse_published") is True for item in score_rows
            ),
            "local_only_count": sum(item.get("langfuse_published") is False for item in score_rows),
        },
        "trace_count": len({item.trace_id for item in roots}),
        "turn_count": len(roots),
        "call_count": len({item.call_key for item in roots}),
        "turn_latency_p90_ms": percentile([item.duration_ms for item in roots], 0.90),
        "call_latency_ms": {
            key: sum(item.duration_ms for item in roots if item.call_key == key)
            for key in sorted({item.call_key for item in roots})
        },
        "technical_errors": {
            "by_component": dict(
                Counter(item.component for item in spans if item.status == "ERROR")
            ),
            "by_code": dict(
                Counter(
                    str(item.attributes["error_code"])
                    for item in spans
                    if item.status == "ERROR" and "error_code" in item.attributes
                )
            ),
        },
        "states": dict(
            Counter(
                str(item.attributes["final_state"])
                for item in roots
                if "final_state" in item.attributes
            )
        ),
        "outcomes": dict(
            Counter(
                str(item.attributes["outcome"]) for item in roots if "outcome" in item.attributes
            )
        ),
        "modes": dict(
            Counter(str(item.attributes["mode"]) for item in roots if "mode" in item.attributes)
        ),
        "directions": dict(
            Counter(
                str(item.attributes["direction"])
                for item in roots
                if "direction" in item.attributes
            )
        ),
        "llm_latency": latency_stats([item.duration_ms for item in generations]).to_dict(),
        "llm_model_call_latency": latency_stats(
            [
                value
                for item in generations
                if (value := _number(item.attributes.get("model_call_latency_ms"))) is not None
            ]
        ).to_dict(),
        "ttfa": latency_stats(
            [
                value
                for item in tts
                if (value := _number(item.attributes.get("ttfa_ms"))) is not None
            ]
        ).to_dict(),
        "stt_first_partial": latency_stats(
            [
                value
                for item in stt
                if (value := _number(item.attributes.get("first_partial_ms"))) is not None
            ]
        ).to_dict(),
        "stt_final_latency": latency_stats(
            [
                value
                for item in stt
                if (value := _number(item.attributes.get("final_ms"))) is not None
            ]
        ).to_dict(),
        "stt_provider_latency": latency_stats(
            [
                value
                for item in stt
                if (value := _number(item.attributes.get("provider_latency_ms"))) is not None
            ]
        ).to_dict(),
        "models": list(models.values()),
        "stt": {
            "count": len(stt),
            "confidence_samples": sum(
                _number(item.attributes.get("confidence")) is not None for item in stt
            ),
            "confidence_mean": (sum(values) / len(values))
            if (
                values := [
                    value
                    for item in stt
                    if (value := _number(item.attributes.get("confidence"))) is not None
                ]
            )
            else None,
            "audio_duration_ms": sum(
                _number(item.attributes.get("audio_duration_ms")) or 0 for item in stt
            ),
            "error_count": sum(item.status == "ERROR" for item in stt),
            "error_rate": (sum(item.status == "ERROR" for item in stt) / len(stt) if stt else None),
        },
        "tts": {
            "count": len(tts),
            "providers": [
                {"provider": provider, "voice": voice, "count": count}
                for (provider, voice), count in sorted(tts_groups.items())
            ],
            "characters": sum(int(item.attributes.get("character_count") or 0) for item in tts),
            "fallback_count": sum(item.attributes.get("fallback_used") is True for item in tts),
            "interrupted_count": sum(item.attributes.get("interrupted") is True for item in tts),
        },
        "clinic": {
            "operations": dict(Counter(item.operation for item in clinic)),
            "http_statuses": dict(
                Counter(
                    str(item.attributes["http_status"])
                    for item in clinic
                    if "http_status" in item.attributes
                )
            ),
            "retry_count": sum(int(item.attributes.get("retry_count") or 0) for item in clinic),
            "version_conflicts": sum(
                item.attributes.get("version_conflict") is True for item in clinic
            ),
            "error_count": sum(item.status == "ERROR" for item in clinic),
        },
        "cost": {
            "known_cost_total": sum(row["known_cost_total"] for row in costs.values()),
            "cost_known": any(row["cost_known"] for row in costs.values()),
            "known_component_count": sum(row["known_component_count"] for row in costs.values()),
            "unknown_component_count": sum(
                row["unknown_component_count"] for row in costs.values()
            ),
            "cost_complete": all(row["cost_complete"] for row in costs.values()),
            "sessions": [{"call_key": key, **row} for key, row in sorted(costs.items())],
        },
    }

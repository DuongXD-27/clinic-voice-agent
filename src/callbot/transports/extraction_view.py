"""What the demo pages show about one turn's extraction: the caller's sentence, the fields read from it
(value, span, provenance) and which model read it, if any.

Unlike `TurnDiagnostics` this carries the caller's own words, so it only goes back to that caller for the
demo: HTTP sends it as `X-Demo-Extraction-Fields` when the client asked for `X-Demo-Debug: 1`, LiveKit
inside the bot's transcript line on the data channel when `demo_debug` is on (config/livekit.yaml).
Never logged, never stored.
"""

from typing import Any, Optional


def extraction_view(extraction: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Transcript + fields actually extracted + the model that read the turn, from the extraction trace."""
    if not extraction:
        return None
    fields = [
        {
            "field": name,
            "value": field.get("value"),
            "span": field.get("span"),
            "provenance": field.get("provenance"),
        }
        for name, field in extraction.items()
        if isinstance(field, dict) and field.get("provenance") not in (None, "NONE")
    ]
    model = None
    if extraction.get("model_name"):
        model = {
            "provider": extraction.get("model_provider"),
            "name": extraction.get("model_name"),
            "status": extraction.get("model_status"),
            "backup_for": extraction.get("model_backup_for"),
        }
    return {
        "transcript": extraction.get("transcript") or "",
        "silent": bool(extraction.get("silent")),
        "fields": fields,
        "model": model,
    }

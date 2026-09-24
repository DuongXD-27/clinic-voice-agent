# Voice Observability Dashboard

The dashboard is a read-only presentation layer for the vendor-neutral Voice Observability API. It is served by the existing FastAPI process at `/observability/` and uses browser-native HTML, CSS, JavaScript modules, and SVG. No frontend framework, package manager, chart library, or build runtime is required.

## Local setup

Configure the API and a directory containing synthetic or privacy-safe trace JSONL:

```dotenv
OBSERVABILITY_API_ENABLED=true
OBSERVABILITY_TRACE_DIR=C:\path\to\synthetic-traces
```

`TRACE_JSONL_DIR` remains a fallback when `OBSERVABILITY_TRACE_DIR` is empty. Start the HTTP service normally, then open:

```text
http://localhost:8000/observability/
```

The dashboard and API use the same origin, so local development does not require a permissive CORS policy. The API base defaults to the current origin. A deployment may override `apiBase` in `observability_static/config.js` when a trusted reverse-proxy topology requires a different origin.

OpenAI, ZipFormer, and Langfuse are not required to render the dashboard against existing synthetic JSONL. The browser never reads JSONL directly; all values come from the read-only API.

## Telemetry semantics

- Percentiles, rates, and counts are displayed exactly as returned by the backend.
- Missing samples display `No data`, never a fabricated zero.
- TTFA, first partial, confidence, VAD end reason, 429 breakdown, retry, split, and barge-in display `Not instrumented`.
- The turn pipeline compares returned durations. Stage offsets are not available, so it does not claim to be an exact distributed-tracing timeline.
- Calls are identified only by pseudonymous `call_key`; executions with the same turn number remain separate by trace ID.

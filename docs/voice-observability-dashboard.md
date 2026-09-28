# Voice Observability Dashboard

The dashboard is a read-only presentation layer for the vendor-neutral Voice Observability API. It is part of the web UI in `ui/` (Vite + React + TypeScript, `ui/src/features/observability/`), built to static files and served by the existing FastAPI process at `/ui/observability`. The old URL `/observability/` redirects there. No extra server process is added.

Screens (state lives in the URL, so links can be shared):

| Path | Content |
| --- | --- |
| `/ui/observability?range=24&metric=stt` | KPI cards; the selected card opens hourly p95 trend, percentiles, provider/model, safe error codes, slow turns |
| `/ui/observability/quality?component=STT&aggregation=call` | Affected rate, per-issue breakdown and privacy-safe examples |
| `/ui/observability/calls/{call_key}` | Executions of one pseudonymous call, including replays |
| `/ui/observability/turns/{trace_id}` | Stage durations (STT / Core / TTS / Clinic) of one turn |

## Local setup

Configure the API and a directory containing synthetic or privacy-safe trace JSONL:

```dotenv
OBSERVABILITY_API_ENABLED=true
OBSERVABILITY_TRACE_DIR=C:\path\to\synthetic-traces
```

`TRACE_JSONL_DIR` remains a fallback when `OBSERVABILITY_TRACE_DIR` is empty. The local `docker-compose.yml` already sets both (a `traces` volume, API enabled), so `docker compose up -d --build` is enough; calls made from `/ui/call` then show up in the dashboard. Open:

```text
http://localhost:8000/ui/observability
```

The dashboard and API use the same origin, so no CORS policy is needed. For UI development run `npm run dev` in `ui/` (Vite proxies `/internal` to `localhost:8000`).

The API has no authentication: keep `OBSERVABILITY_API_ENABLED` off on public deployments.

OpenAI, ZipFormer, and Langfuse are not required to render the dashboard against existing synthetic JSONL. The browser never reads JSONL directly; all values come from the read-only API. `ui/src/features/observability/privacy.test.ts` enforces that only `api.ts` calls the API and that no source references patient fields, utterances, audio URLs, raw `.jsonl` files or external services.

Only the HTTP call path (`/v1/calls`) records traces today; the LiveKit worker builds its orchestrator without a tracer, so LiveKit calls do not appear yet.

## Telemetry semantics

- Percentiles, rates, and counts are displayed exactly as returned by the backend.
- Missing samples display `—`, never a fabricated zero.
- TTFA, first partial, confidence, VAD end reason, 429 breakdown, retry, split, and barge-in display `Not instrumented`.
- The turn pipeline compares returned durations. Stage offsets are not available, so it does not claim to be an exact distributed-tracing timeline.
- Calls are identified only by pseudonymous `call_key`; executions with the same turn number remain separate by trace ID.

# Callbot observability

The [verification record](../evidence/observability-verification-2026-09-30.md) contains automated checks, synthetic Langfuse readback, and remaining measurement limits.

## Trace model and correlation

Enable tracing with `TRACE_ENABLED=true`, `TRACE_PSEUDONYMIZATION_KEY`, and either `TRACE_JSONL_DIR` or Langfuse export settings. The HMAC key stays in the environment. Every HTTP or LiveKit start/turn receives a fresh trace ID and a stable pseudonymous `call_key` that becomes the Langfuse session ID. A turn root has child STT, core, and TTS spans. Core contains extraction, dialogue, output guard, and Clinic spans. A real structured LLM request creates a `GENERATION` under extraction; rule-only paths do not create one. Clinic attempts remain structured events in the Clinic span.

The JSONL reader accepts existing `trace.v1` spans and new `trace.v2` generation records. Langfuse receives OTLP spans with observation type, model, usage, and cost attributes. Export is queued and fail-open; network or local telemetry failures must not fail a call. LiveKit creates one tracer per worker job and closes it after the job.

```text
callbot.turn  (one trace for start or one turn; same session ID per call)
├── speech.stt.transcribe  SPAN (turns with speech)
├── core.handle_turn / core.start_call  SPAN
│   ├── core.extract  SPAN
│   │   └── llm.semantic_extract or llm.name_slot_fill  GENERATION, if invoked
│   ├── core.dialogue  SPAN
│   │   └── clinic.<operation>  SPAN with attempt events
│   └── core.output_guard  SPAN
└── speech.tts.synthesize  SPAN (if speech is produced)
```

## What is measured

The HTTP batch path records STT provider/model, measured provider call latency (`provider_latency_ms`), confidence when supplied, and errors. LiveKit records streaming mode, audio duration, first partial and final offsets from speech start when received, partial count, and VAD end reason. A LiveKit STT observation is attached to the turn when the turn completes; its span `duration_ms` measures that attachment operation. `first_partial_ms` and `final_ms` measure speech timing, and neither is provider inference latency. The existing `stt_latency` API field reports STT observation duration for compatibility. Missing provider metrics remain absent and appear as N/A in the UI.

Each actual semantic or name-slot LLM request records requested and returned model, normalized result (`OK`, `TIMEOUT`, `ERROR`, `INVALID`), available token counts, and safe error class. `model_call_latency_ms` measures the monotonic interval from immediately before the HTTP request to receipt of its complete body; the configured 3-second deadline applies to that interval. The generation span's `duration_ms` and existing `latency_ms` include response parsing and application validation, so they can exceed 3 seconds for an `OK` call. Langfuse's built-in generation latency comes from the span timestamps; the model-call value is safe observation metadata. VBee measures time to first audio chunk from request start. TTS spans record requested and actual provider, voice, character count, audio size/duration, TTFA when observed, fallback, and interruption. Clinic spans and attempt events record endpoint templates, retry count, HTTP status and version conflicts. Core traces record safe state, policy, guard, and outcome labels.

Pricing is optional in `config/tracing.yaml` or corresponding `TRACE_*` environment variables. Prices require an exact model or provider/voice match and observed usage. A missing price or usage produces unknown cost. The dashboard reports `cost_known`, `known_component_count`, `unknown_component_count`, and `cost_complete` for each session and in aggregate. A known zero cost has `cost_known=true`; no priced component has `cost_known=false`. A session with known and unknown components is partial, even though `known_cost_total` still reports its known portion. A session with no billable component has `cost_known=false`.

For LLM, cost in USD is `(uncached input tokens × input price + cached input tokens × cached input price + output tokens × output price) / 1,000,000`. TTS uses characters × configured USD per character. STT uses observed audio minutes × configured USD per minute. The cached price is required if cached tokens are reported. Neither price nor usage is estimated.

An observation `ERROR` means a technical failure of that operation. Business outcomes such as a valid `TRANSFERRED` call remain labels on an `OK` turn. A failed LLM generation may be `ERROR` while its parent turn stays `OK` after a valid business fallback. QA/evaluation verdicts are stored as scores only when an evaluator explicitly publishes them.

## Dashboard and scores

`/v1/observability/overview` retains its existing fields and adds `extended`: call counts, state/outcome/mode/direction counts, LLM generation and model-call latency, model usage, STT confidence and timing, TTS TTFA and fallback/interruption counts, Clinic retries/conflicts, cost, and published score counts. The UI overview displays these summaries. `llm_model_call_latency` includes only generations with a measured `model_call_latency_ms`; its sample count exposes coverage, and historical records without that measurement remain N/A. Time range filters use the trace start timestamp. Historical `trace.v1` data continues to load; new fields are empty when the source did not capture them.

`LangfuseScorePublisher` is an optional interface for a *completed evaluator result with a known trace ID or pseudonymous session ID*. Enable `LANGFUSE_SCORE_PUBLISH_ENABLED=true` to POST an allowlisted score to Langfuse. Set `LANGFUSE_SCORE_JSONL_DIR` to the dashboard trace directory to persist that same result locally for the API overview, even if Langfuse is unavailable. The local row records `langfuse_published`; the dashboard reports both remote published and local only counts. The publisher returns whether the remote POST succeeded. A Boolean score is sent as numeric 0 or 1 with `dataType=BOOLEAN`, as required by Langfuse, while the local result remains Boolean. The publisher does not infer or fabricate scores. No scoring endpoint response schema is changed.

## Privacy

The trace boundary validates component, operation, field names and values before JSONL or OTLP export. It stores no patient name, birth date, phone number, patient/appointment ID, transcript, audio, LLM message or response, TTS text, or Clinic body. Provider request IDs and exception messages are also omitted. The LiveKit transcript data channel is part of the existing call UI, not an observability export. Review application logging separately when operating with sensitive data.

## Debugging one failed call

Find the pseudonymous `call_key` in the API call detail or Langfuse session. Open its most recent turn trace and identify the first child with `status=ERROR`. Inspect its component, normalized error code/class, duration, provider/model, and safe Clinic attempt events. Compare the parent turn's final state/outcome: a handled provider error may have an `OK` parent. Use the API overview error breakdown for recurring failures. Do not search by patient data or enable raw prompt/audio capture for telemetry diagnosis.

Langfuse Model Usage and token charts can populate only for generations whose provider returned usage. The exporter converts inclusive cached input and reasoning output counts into mutually exclusive usage buckets before sending them to Langfuse. Generation latency comes from span timing. The local dashboard shows cost only when the matching approved price and usage are available; Langfuse may separately calculate cost using its own model pricing. When an explicit local price yields `cost_usd`, its ingested `cost_details.total` takes priority over Langfuse's inferred cost, so it is not added twice. Scores populate only after the optional score publisher runs. The local API dashboard reads JSONL, so it does not ingest remote Langfuse-only scores or traces.

## Configuration

See `config/tracing.yaml` and `.env.example` for flags and optional prices. Keep the existing `TRACE_PSEUDONYMIZATION_KEY` secret and Langfuse keys in environment variables. Langfuse OTLP export requires `TRACE_ENABLED=true`, `LANGFUSE_EXPORT_ENABLED=true`, a deployment-specific `LANGFUSE_OTLP_ENDPOINT`, and public/secret keys. Trace JSONL and score JSONL directories should be writable by the process that emits them. Dashboard reads the configured trace directory.

# Observability verification

The field definitions and operating guidance are in the [observability reference](../reference/observability.md).

## Automated checks

From the repository root on Windows, install the project's development and relevant runtime extras, then run with UTF-8 enabled:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
```

For the UI:

```powershell
cd ui
npm ci
npm run api:types
npm run check
npm run build
```

The observability tests cover generation creation only on actual model requests, usage/result/error mapping, Langfuse OTLP fields, JSONL reading of both trace versions, pricing with missing prices, score validation and publishing, and privacy rejection of sensitive synthetic values. Existing HTTP, LiveKit, Clinic, and dashboard regression tests must remain green.

## Runtime smoke check

### Local project verification (2026-09-30)

The `callbot-vinmec-local` project at `https://jp.cloud.langfuse.com` ingested a synthetic rule-only turn in `local`: four SPAN observations, no GENERATION, one pseudonymous session, and empty raw input/output. Only after that readback, one synthetic Luna turn was sent through the real provider. Langfuse read back `llm.semantic_extract` as a GENERATION under the turn's extraction span, model `gpt-6-luna`, `OK` result, `local` environment, generation latency 2.203 seconds, and `model_call_latency_ms` 2141.3555. Provider usage was 46 input, 14 output, and 60 total tokens. Raw input/output were empty. This is evidence for those two synthetic paths only; it does not establish LiveKit audio or TTS coverage. No additional Luna request is needed for dashboard or exporter changes.

### Earlier development project verification

On 2026-09-30, one synthetic Luna request through `OpenAIProvider` and `LLMGateway` returned `completed`, actual model `gpt-6-luna`, HTTP 200, valid structured JSON, and 42 input / 13 output / 55 total tokens (cached and reasoning tokens both 0). The same request produced an `OK` generation under extraction, and the exporter sent four observations with no raw input or output. Langfuse's observations API read back the generation with the same model and usage, a parent observation, `development` environment, `DEFAULT` level, and 3.019-second generation span latency. The observation started at `2026-09-30T03:43:45.068Z` and ended at `2026-09-30T03:43:48.087Z`. That historical trace has no timestamp for full HTTP-body receipt, so its `OK` result cannot prove the model response met R-31. A subsequent audit found that HTTPX previously enforced only phase timeouts; a complete body could arrive after 3 seconds and still be accepted. The provider now enforces a monotonic total deadline and exports `model_call_latency_ms` separately. Langfuse calculated USD 0.0000107 from its own model pricing; local tracing did not supply a cost because no matching local price was configured.

The same project accepted three synthetic traces: a rule-only tree with no generation, a generation tree with model/usage and known zero cost, and a span carrying a technical error. All ten observations were read back; the error span appeared at `ERROR` level. One `privacy_pass` Boolean score attached to the synthetic trace was read back via the scores v3 API. The score POST requires numeric 0/1 with `dataType=BOOLEAN`; the read API returns a Boolean. These checks used synthetic data and an approved project, with no patient content.

To repeat, create a unique synthetic call ID and trace, use the repository's `Tracer` and `LangfuseOtlpTraceSink`, flush, then query `GET /api/public/v2/observations?traceId=<id>&fields=core,basic,model,usage,metrics` and `GET /api/public/v3/scores?traceId=<id>&fields=subject`. Check parent IDs, model, usage, latency, level, environment and score subject. The exporter sets `x-langfuse-ingestion-version: 4` so observations can be read promptly. Do not print credentials or send raw prompts in OTLP attributes.

Use a disposable environment with synthetic patient data. Enable local tracing and optionally Langfuse export. Run one HTTP call with a rule-only turn, one turn that invokes Luna, and one LiveKit call with speech and TTS. Inspect JSONL and the Langfuse session tree by `call_key`. Confirm the LLM generation appears only when the gateway was called, the same call key joins turns, STT/TTS provider fields match actual execution, Clinic attempts have endpoint templates only, and unknown prices leave `cost_usd` absent. Query the dashboard overview over the trace time range and inspect its `extended` field.

- [ ] HTTP start and turn traces share a pseudonymous session ID and have separate trace IDs.
- [ ] LiveKit turns from one room share a session ID; two rooms have distinct IDs.
- [ ] STT, core, and TTS children belong to the correct turn; actual LLM calls are generations under extraction.
- [ ] VBee TTFA, voice and actual provider match the successful TTS result; fallback is visible when exercised.
- [ ] Clinic attempt count, If-Match, idempotency and conflict flags reflect actual requests.
- [ ] Langfuse outage or a full exporter queue does not change the bot response.
- [ ] Dashboard overview and call detail load historical and new JSONL data.
- [ ] Unknown pricing is shown as incomplete cost, not as an asserted zero.
- [ ] Synthetic private values are absent from JSONL and OTLP payloads.

For a score smoke check, submit a known evaluator result through `LangfuseScorePublisher` with a trace ID or pseudonymous session ID. Confirm Langfuse accepts the score and, if `LANGFUSE_SCORE_JSONL_DIR` is set to the trace directory, the overview score count rises. If remote publication fails, the same local score still appears with `langfuse_published=false` and contributes to `local_only_count`. A disabled publisher leaves both sinks untouched. Score publication failure must leave the bot call unaffected.

Search exported payloads for synthetic names, dates of birth, phone numbers, raw transcripts, prompts, responses, audio content, appointment identifiers, and Clinic bodies. They must not appear. No production patient data is needed for this verification.

## Measurement limits

The streaming STT span is attached when a turn completes; use its safe first-partial/final offsets for speech timing. Only HTTP batch STT currently has a measured provider call latency. The legacy `stt_latency` API field is STT observation duration. TTFA is present only when the provider or stream yields a first audio chunk. Token usage is present only when a provider reports it. Local costs require explicit price configuration and exact matching usage; known zero, partial, and unknown are distinct. Score totals count valid local rows, including remote publication failures; external scores added directly in Langfuse are not ingested into the local dashboard.

The ASR lag test's original fixed sleep raced the pending probe: in 10 repeated runs both the worktree and the unchanged `HEAD` returned the partial before the final. The test harness now holds ASR backlog through VAD `speech_end` with an event and supplies enough trailing silence to make that order deterministic. It passed 10 repeated runs after the harness change; production ASR and turn behavior were not changed for this issue.

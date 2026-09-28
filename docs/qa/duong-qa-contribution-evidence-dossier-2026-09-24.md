# QA/QC Contribution & Evidence Dossier
## Nguyen Tuan Duong / DuongXD27
## AI Callbot
## Evidence through 2026-09-24

> **Cách đọc.** Đây là hồ sơ đóng góp cá nhân, không phải tuyên bố rằng mọi file hiện trong repo do Duong viết. Mỗi nhận định quan trọng mang nhãn nguồn `[REPO]`, `[GIT]`, `[TEST-RUN]`, `[RUNTIME]`, `[HISTORICAL-CHAT]`, `[PR]`, `[DOC]`, `[EVAL]` và mức tin cậy **HIGH / MEDIUM / LOW**. `A` = directly authored; `B` = directly modified/fixed; `C` = QA execution/investigation; `D` = integration; `E` = team context only. Lệnh `pytest` với Clinic giả hoặc LLM giả không phải service-live hay real-model evaluation.

## 1. Executive Summary

- [GIT][REPO] **HIGH, A/B:** Duong authored identity/contract tests (`a874782`, `d93dc7a`, `141da38`), cross-service QA and speech-evaluator assets (`73a5919`, `14e4921`), booking safety fixes (`e8b16de`, `a1f0a4d`), and tracing/observability stack commits (`26e3d79` through `b04d492`). Ownership is limited to each diff, not the whole bot.
- [TEST-RUN][HISTORICAL-CHAT] **MEDIUM, C:** contract review progressed from **14 PASS / 52 FAIL** on 17/09 to Week 2 service acceptance with **42 live Clinic**, **783 targeted offline**, and **1 Redis integration** pass on 24/09. These are different scopes and must never be summed as unique tests.
- [RUNTIME][TEST-RUN] **HIGH, C:** an isolated 24/09 HTTP Engine turn logged `openai/gpt-6-luna`, `accepted`, `CONFIRM_READBACK`, 2,981.6 ms and 3,114/44 tokens. Clinic remained `SCHEDULED`, version 3→3. See `temp/semantic-evidence.err.log`; the log has no call ID, so correlation relies on the isolated run and captured file offset.
- [DOC][HISTORICAL-CHAT] **MEDIUM, C:** Week 2 final verdict was **QA READY with non-blocking observability gaps**, for the tested text HTTP path. No statistically reliable Luna p95 or full audio-path acceptance was established.

## 2. Scope and Role

[GIT] **HIGH.** Five roles recur: (A) tests/evaluators/tracing and dashboard implementation in authored commits; (B) targeted production and CI smoke fixes; (C) black-box contract, privacy, cross-service and runtime QA; (D) merge/reconciliation commits; (E) team work observed while testing. Identity dialogue, core confirmation dialogue, Clinic Mock implementation, Redis implementation, current no-answer evaluator, STT/TTS runtime providers and production deployment are **not** assigned to Duong merely because his QA exercised them. Week 2 acceptance covers identity, confirm and no-answer; inbound booking is a Week 5 feature contribution.

## 3. Evidence Methodology

[GIT][REPO] **HIGH.** Examined local/remote branches, `git log --all`, `shortlog`, commit diffs, branch containment, current `src/`, `tests/`, `eval/`, `docs/`, `.github/`, compose, `pyproject.toml`, `uv.lock` status, `result/`, and temporary logs. The contract reference is [AIHR-PC-001](https://callbot-contract-site.vercel.app/) (Rev 1.0 in historical 17/09 suite); local summaries include `docs/reference/ai-callbot-architecture.md` and `docs/reference/http-api.md`. Current checkout during audit: `feature/pm-observability-dashboard-revision`, HEAD `8083d1f`; initially only `uv.lock` was untracked. No paid provider or broad regression was rerun for this dossier.

[HISTORICAL-CHAT] **MEDIUM by default.** HIST-001–026 below are supplied prior-conversation snapshots. A matching file/commit raises confidence in **the asset or action**, not necessarily in an old run count whose raw output is gone. Temporary runtime logs are stronger than chat, but may be local and ephemeral. `result/23-09-2026/` contains committed evaluator summaries; its contents are not interchangeable with later service-live results. Missing files are recorded rather than silently replaced by similar current files.

**Evaluation method, not just counts.** [GIT][REPO][RUNTIME] **HIGH for code and 24/09 sentinel.** Contract QA starts with a requirement and public request, then compares the response *and* Clinic final record; fake Clinic tests cover business branches but are labeled component. Identity QA proceeds from open question through extraction/normalization to verifier and checks all pre-verification speech for protected fields. STT uses fixed 8 kHz golden audio, WER plus critical-entity and silence-hallucination checks. TTS uses fixed utterances and a human scorecard CSV; no automatic MOS. Privacy masking catches the outbound payload and treats any protected value leak as failure; the nine-case suite is historical/proposed. LLM QA runs deterministic rules first, routes only uncertainty, validates strict structured output and grounded spans, merges under write guards, and reads back Clinic state. Performance QA records monotonic wall time in seconds and milliseconds, applies the <8-second endpoint requirement and refuses to infer p95 from a handful of samples.

## 4. Identity / Git Attribution

[GIT] **HIGH.** Matching author: `DuongXD-27 <tuanduong9605@gmail.com>`; the user's `Nguyen Tuan Duong` / `DuongXD27` identities are self-attribution [HISTORICAL-CHAT] **MEDIUM**. `git shortlog -sne --all` shows 30 objects with that Git author. Classification by parents and stash subject: **22 normal commits, 5 merges, 3 stash objects**. Stash objects `17e273b`, `75b8d7a`, `ebc201c` are excluded from contribution commits. The older 10–24/09 audit's 21 normal + 4 merges + 3 stash equals the same history **before** the later `8083d1f` doc commit and `0038f27` merge. Across the 22 normal commits, mechanical `--numstat` yields **127 unique path strings, 22,384 additions, 415 deletions, 40 binary entries**; the older 22,327 addition count differs by the new 57-line `.env.example` commit. `54ed142` alone reports 8,751 additions due to rebuild/reconciliation; LOC is not a quality metric.

| Commit(s) | Attribution | What the diff proves | Caution |
| --- | --- | --- | --- |
| `a874782`, `d93dc7a`, `141da38`, `73a5919`, `14e4921` | A, **HIGH** [GIT] | identity/schema/SF-03/normalization tests, STT/TTS evaluators and 40 WAV files, cross-service HTTP suite | `14e4921` is on QA branch, not current HEAD |
| `887325b`, `a06e637`, `a874fd1`, `e8b16de`, `a1f0a4d` | B, **HIGH** [GIT] | CI smoke payload, early HTTP stubs, debug response boundary, booking response/slot-window fixes | Not ownership of all CI or booking core |
| `26e3d79`, `4a444ae`, `4c9aedc`, `b2ad9ae`, `b62a8d2`, `b04d492`, `ab2e70e`, `54ed142` | A/B, **HIGH** [GIT] | tracing, Langfuse sink, speech spans, metrics, API, frontend, LLM child span on branch, rebuild | `ab2e70e` lives on `feature/llm-tracing`; its `tracing/llm.py` is absent at current HEAD |
| `159842d`, `6fbe6df`, `6483833`, `38f5eab`, `0038f27` | D, **HIGH** [GIT] | merge/reconcile actions | Parent code is not automatically authored by Duong; conflict-specific authorship requires remerge diff review |
| `56c8a36`, `8083d1f` | A, **HIGH** [GIT] | T-11 evidence and tracing/Langfuse `.env.example` documentation | Docs establish description, not live service performance |

`0585200` (historical PR #34 candidate) exists as a **dangling local commit object**, not `git log --all` branch history; `54ed142` is the reachable rebuild. [GIT][HISTORICAL-CHAT] **HIGH for object; MEDIUM for PR readiness.** PR #28 is corroborated by merge `46b1f28`; PR #34 status is only historical chat unless remote PR metadata is obtained. The claimed `+463/-25, five commits` for PR #28 is a historical snapshot [PR][HISTORICAL-CHAT] **MEDIUM**, not recomputed from a GitHub PR diff here.

## 5. Contribution Timeline

| Date | Evidence-based progression | Role / strength |
| --- | --- | --- |
| 17/09 | `a874782` created identity cases and 429-line API schema test; `a06e637` aligned HTTP stubs; `887325b` repaired deploy smoke payload. Historical 66-case black-box review: 14/52. | A/B **HIGH** [GIT]; review count C **MEDIUM** [HISTORICAL-CHAT] |
| 18/09 | `d93dc7a` added SF-03 canaries; `141da38` normalization audit; `73a5919` cross-service and STT/TTS evaluator assets, 40 STT WAV. Focused 14 identity pass was narrower than failing broader suite. | A **HIGH** [GIT]; run C **MEDIUM** [HISTORICAL-CHAT] |
| 21/09 | Privacy-safe turn tracing, OTLP/Langfuse, STT/TTS spans, metrics, read-only API and dashboard in six authored normal commits. | A/B **HIGH** [GIT] |
| 22/09 | `ab2e70e` dedicated LLM tracing on separate branch; `e8b16de` booking result validation; `a1f0a4d` multi-window slot search; `a874fd1` debug privacy boundary. | A/B **HIGH** [GIT] |
| 23/09 | `54ed142` observability rebuild; `56c8a36` T-11 evidence; `14e4921` expanded cross-service confirm suite on QA branch. Historical daily snapshot 592/1 skip and 204 latency probes. | A/B/D **HIGH** [GIT]; runs C **MEDIUM** [HISTORICAL-CHAT] |
| 24/09 | Redis/Clinic/Callbot service acceptance, real Luna connectivity and Engine sentinel; correction of report latency units; final Week 2 READY for tested text path. `8083d1f` documented trace env. | C **HIGH** [RUNTIME][TEST-RUN] for retained sentinel log; verdict **MEDIUM** [HISTORICAL-CHAT] |

## 6. Product Requirement Coverage

Levels: UNIT, COMPONENT, CONTRACT, ROBUSTNESS, INTEGRATION, CROSS-SERVICE, SERVICE-LIVE, E2E, EVAL, MANUAL-AUDIT, PERFORMANCE, PRIVACY, SECURITY/SAFETY. `FakeClinicAPI` cases are component/integration, **not** live E2E. Real Luna sentinel is real-provider integration on text HTTP, **not** a broad accuracy study.

| Requirement | Test/Eval | Data / expected state | Level | Latest result; history | Evidence / my role |
| --- | --- | --- | --- | --- | --- |
| Identity / SF-03 | `test_identity.py`, `test_sf03_appointment_disclosure.py`, `test_identity_extraction_normalization.py`, live text turns | Open name/DOB, wrong/partial values; no appointment detail until both match | COMPONENT, PRIVACY, SERVICE-LIVE | Week 2 PASS; 18/09 focused 14 PASS while broader suite still failed | [GIT][TEST-RUN] **HIGH** A (`a874782`,`d93dc7a`,`141da38`); C live |
| Confirm attendance | `test_confirm_dialogue.py`, `test_verify_cross_service.py` | Read date/time/clinic; explicit agreement → `CONFIRMED`, metadata; ambiguous → unchanged | COMPONENT, CROSS-SERVICE, SERVICE-LIVE | Week 2 PASS; branch QA suite historically 5/5 focused, 12 test functions at `14e4921` | [GIT][TEST-RUN] **HIGH** A for cross-service tests, C for runtime; core dialogue E |
| No answer | `test_silence_line_signal.py`, `test_no_answer_evaluator.py`, live turn probes | 3 silences/voicemail → `UNREACHABLE`, attempt +1, no voicemail disclosure | COMPONENT, EVAL, SERVICE-LIVE | Week 2 PASS; current evaluator/corpus authored by others | [TEST-RUN][REPO] **HIGH** C; [GIT] E for corpus/code |
| Cancel / SF-05 | `test_cancel_dialogue.py`, semantic merge tests | Request and second explicit cancel confirmation; ambiguity must not cancel | COMPONENT, SAFETY, SERVICE-LIVE sentinel | One 24/09 cancel-reconfirm Luna turn kept `SCHEDULED`; not a full live cancel acceptance | [TEST-RUN][HISTORICAL-CHAT] **MEDIUM** C; core T-05 E |
| Transfer | `test_verify_cross_service.py`, Clinic gateway tests | Off-script/failure → transfer; Clinic result authoritative | CROSS-SERVICE, COMPONENT | Tested adjacent branches; dedicated live breadth incomplete | [GIT][REPO] **HIGH** A test / C QA; core transfer E |
| Reschedule / SF-02 | gateway/slot tests, `test_scenario7_edge.py` | Only offered authoritative slot, no invented time/slot | COMPONENT, SAFETY | Booking slot-window tests present; full real reschedule service flow not established | [GIT] **HIGH** A/B (`a1f0a4d`); reschedule core E |
| Inbound booking / SF-01/SF-02 | `test_inbound_booking_flow.py`, `test_booking_write.py`, `test_scenario7_edge.py` | Mandatory identity, explicit offered-slot confirmation, one `BOOKED` record | COMPONENT/INTEGRATION | Historical 8 targeted PASS, full 1409 PASS/25 SKIP; Week 5 feature, not Week 2 gate | [GIT] **HIGH** B (`e8b16de`,`a1f0a4d`); [HISTORICAL-CHAT] **MEDIUM** runs |
| SF-01 wrong-record/duplicate | cross-service branch test `test_confirm_mutates_only_the_appointment_named_at_call_start`; booking duplicate tests | A changes; B differs in ID/patient/clinic/time and stays unchanged | CROSS-SERVICE, SAFETY | Historical 5/5 branch; current HEAD has older 4-function file | [GIT] **HIGH** A (`14e4921`), [HISTORICAL-CHAT] **MEDIUM** run |
| SF-04 | Policy/guardrail tests in repo | No unauthorized action on severe failure | COMPONENT, SAFETY | Adjacent offline coverage; no isolated Duong-authored SF-04 asset identified | [REPO] **MEDIUM** C/E |
| HTTP / latency | `test_schema.py`, `test_calls.py`, cross-service latency test | Request/response shapes and two endpoints <8 s | CONTRACT, PERFORMANCE | Week 2 live samples <8 s; historical 204/204 probes; p95 not established | [GIT] **HIGH** A/B schema/smoke; [HISTORICAL-CHAT] **MEDIUM** 204 |

## 7. Module Coverage Map

| Module | My relation, level, data | Bugs/risks and current strength |
| --- | --- | --- |
| HTTP transport / schemas | A/B tests/stub/smoke `a874782`,`a06e637`,`887325b`; CONTRACT | Missing required smoke fields fixed; STRONG OFFLINE + Week 2 SERVICE-LIVE [GIT][TEST-RUN] **HIGH** |
| Dialogue / identity / DOB / verifier | A identity/SF-03/normalization tests; C live turns; synthetic names/DOB | Fail-closed, no disclosure; STRONG OFFLINE + SERVICE-LIVE for Week 2 [GIT][TEST-RUN] **HIGH**. Core implementation E. |
| InformationExtractor / semantic router / LLMGateway / OpenAIProvider | C rule preflight + real Luna HTTP sentinel, A dedicated LLM tracing on separate branch | Ambiguity cannot promote write; REAL-PROVIDER VERIFIED for one isolated path [RUNTIME] **HIGH**; broad model accuracy PARTIAL. |
| PolicyEngine / FSM / SessionManager | A adjacent trace/session tests and cross-service QA, C Redis live | Replay/lock/reconciliation; STRONG OFFLINE, Redis SERVICE-LIVE [GIT][TEST-RUN] **HIGH**; session core E. |
| ClinicGateway / Clinic Mock | B booking gateway fix; A cross-service tests; C live Mock contract | False-success, wrong-record and idempotency risks; SERVICE-LIVE for Week 2 [GIT][TEST-RUN] **HIGH**. Clinic Mock source E. |
| STT | A 40-WAV benchmark/evaluator; C historical research | Golden 8 kHz validation, WER/entity/hallucination framework; provider quality evaluation PARTIAL [GIT][EVAL] **HIGH** for assets, **MEDIUM** for old run. Runtime ZipFormer code E. |
| TTS | A 40-case evaluator/scorecard; C provider research | Human review CSV; no automated MOS or broad production audio acceptance [GIT][EVAL] **HIGH** for framework. Runtime provider code E. |
| Privacy / PII | A SF-03 tests and trace allowlist/pseudonymization; C masking audit | NFR-17 nine-case historical proposal by another Git author; current path absent. STRONG OFFLINE for SF-03, masking execution PARTIAL [GIT][REPO] **HIGH** / chat **MEDIUM**. |
| Tracing / Langfuse / metrics / dashboard | A commits `26e3d79`–`b04d492`; A/B rebuild `54ed142`; A LLM tracing `ab2e70e` separate branch | JSONL, OTLP, speech spans, p50/p95/p99, errors, hourly, read-only API and UI have tests; STRONG OFFLINE. No production Langfuse/dashboard availability proof [GIT] **HIGH**. |
| CI smoke | B `887325b`; local tests used by CI | Smoke payload fixed; no whole CI/CD ownership [GIT] **HIGH**. |

## 8. Test Asset Inventory

[GIT][REPO] **HIGH.** Directly authored or substantially modified paths include `tests/test_schema.py`, `tests/engine/identity_cases.py`, `tests/engine/test_identity.py`, `tests/engine/test_sf03_appointment_disclosure.py`, `tests/engine/extraction/test_identity_extraction_normalization.py`, `tests/transports/http/test_verify_cross_service.py`, `tests/eval/test_stt_evaluator.py`, `tests/eval/test_tts_evaluator.py`, `tests/engine/test_inbound_booking_flow.py`, `tests/engine/tools/test_booking_write.py`, `tests/engine/test_scenario7_edge.py`, `tests/tracing/test_*` from authored tracing commits, `tests/observability/test_*`, and `tests/frontend/observability_dashboard.test.mjs`. Current branch may contain an older version of a path than a QA/feature branch. Parametrized invocations and repeated runs must not be counted as distinct authored test functions. A current total unique test inventory was **not** derived from pass counts.

**Unique test-function inventory, distinct from run snapshots.** [REPO][GIT] **HIGH.** AST inspection of named *current* files found: `test_schema.py` 18 functions; `test_identity.py` 1 parameterized function; SF-03 3; identity normalization 19; cross-service 4 at HEAD versus 12 at `14e4921`; STT/TTS evaluator tests 11 each; inbound flow 4; scenario-7 10; booking write 4; tracing core/integration/Langfuse/speech 12/7/12/11; observability metrics/API/frontend 19/13/5. These counts are functions in specific files, **not** unique parameter instances, personal-authorship totals, or a total of the entire test tree. Subsequent team edits may exist within those files.

Method: contract tests assert public HTTP response **and** Clinic final state; component tests inject fake Clinic/provider faults; cross-service suite uses real local Clinic HTTP and checks write log/record; speech evaluators score fixed data; tracing/UI suites use synthetic JSONL and fake transport. See exact path index in §35.

## 9. Test Dataset Catalog

| Dataset | Version / #cases | Purpose and input → expected output | Used by / provider calls | Evidence / attribution |
| --- | --- | --- | --- | --- |
| `eval/stt-bench/golden-cases.yaml` + `audio-8k/*.wav` | current v1.0 **40 cases / 40 WAV**, 8 kHz PCM mono; earlier `8915866` **18** proposed cases | Identity, DOB, confirm, entity and silence audio → reference transcript, critical entities, no hallucination; held-out same audio across providers | `eval/stt-bench/evaluate.py`; `--validate-only` does not call provider; adapter evaluation may | [GIT][REPO][EVAL] **HIGH**: 18 initially authored by Le Quang Huy; `73a5919` Duong expanded/replaced to 40 and added WAV/evaluator |
| `eval/tts-bench/golden-cases.yaml` | current v1.0 **40**; earlier `f0e0998` **40** | Text/critical items → human review of rendered audio, zero-tolerance business items, MOS rubric | `eval/tts-bench/evaluate.py`, `results/tts-review.csv` **40 rows**; skeleton/validate-only no provider | [GIT][REPO][EVAL] **HIGH**: initial 40 authored by HinDayNi; Duong's `73a5919` evaluator/current schema work. No automated MOS claim |
| `eval/privacy/masking-cases.yaml` | historical `8915866` **9**, `trang_thai: de_xuat`; absent at current HEAD | Synthetic PII payload canaries → one leak fails NFR-17 | Proposed CI masking test; executed run not located | [GIT] **HIGH** for file/history; Git author Le Quang Huy, `phu_trach` says Duong. Direct authorship **LOW** |
| `eval/identity/cases.csv` | current **100** rows | Vietnamese name, DOB, self-correction, greeting/rule outcomes | `scripts/identity_eval.py`; baseline rule-only, NER optional | [REPO][EVAL] **HIGH** count; dataset authored by others; Duong historical 78 PASS/19 FAIL/3 REVIEW QA **MEDIUM** |
| `eval/confirm/cases.csv` | current **179** rows | Clear/mixed/ambiguous attendance → confirm, ask again, transfer | `scripts/confirm_eval.py`; semantic mode may call provider | [REPO][GIT] **HIGH**; authored by others; Duong C in Week 2 service cases |
| `eval/cancel/cases.csv` | current **107** rows | Cancel intent/reason/second confirmation → no unsafe cancellation | `scripts/cancel_eval.py`; semantic mode optional | [REPO][GIT] **HIGH**; authored by others; Duong C only where evidenced |
| `eval/no_answer/cases.csv` | current **86** rows, 33 dev/53 regression reported, 3 REVIEW | Silence/voicemail/human traps/recovery → UNREACHABLE or safe continuation | `scripts/no_answer_eval.py` on relevant branch; no real model in documented baseline | [REPO][DOC] **HIGH** count; authorship other team member; Duong Week 2 C |
| `scripts/tts_bench_set.py` | **27** phrases in ADR report | Fixed phrases, times, names, medical terms → TTFA/quality review | TTS provider benchmarking by other team member | [DOC][REPO] **HIGH** asset, E for Duong unless separate evidence |
| Clinic fixtures `apt_00417`, alternate A/B records, Redis fake/live, Luna sentinel | Synthetic, scenario-specific | Authority, metadata, version, replay, identity/privacy | tests and 24/09 service run; Luna sentinel exactly one additional paid call | [REPO][RUNTIME] **HIGH**; A test fixtures / C execution |

**Dataset evolution.** `8915866` (17/09, other author) contains 18 STT cases and 9 proposed masking cases. `73a5919` (18/09, Duong) contains 40 STT entries and 40 WAV plus evaluator; exact content-level mapping from the original 18 to the new 40 was not reconstructed, so call this expansion/replacement, not proof that all original labels survived unchanged. TTS already had 40 in `f0e0998` (other author) before Duong's current evaluator commit. `40/40` validation in historical chat is a run result, not dataset ownership. [GIT][HISTORICAL-CHAT] **HIGH** counts/commits, **MEDIUM** old validation output.

## 10. Historical Test Run Ledger

**Every row is a run snapshot, not a unique-test count.** `—` means raw result or exact command unavailable. Historical chat-only rows remain MEDIUM even when similar current tests exist.

| Date | Branch/HEAD; scope; command/env | PASS | FAIL | SKIP/XFAIL | Real provider? | Finding; provenance/confidence |
| --- | --- | ---: | ---: | --- | --- | --- |
| 17/09 | early contract review, 66 black-box cases; matrix/review docs now absent | 14 | 52 | 0 | No | 59 contract 13/46; 7 robustness 1/6 [HISTORICAL-CHAT] **MEDIUM** |
| 17/09 | CI after `887325b`, Ruff + pytest smoke | ~386 | 0 reported | 1 | No | required request fields added [GIT][HISTORICAL-CHAT] **HIGH** fix / **MEDIUM** run |
| 18/09 | focused identity / verifiable=false | 14 | 0 | — | No | fail closed; broader identity/SF-03 still failing [HISTORICAL-CHAT] **MEDIUM** |
| 18/09 | rule-only identity 100-row research eval | 78 | 19 | 3 REVIEW | No | not Luna accuracy [HISTORICAL-CHAT] **MEDIUM** |
| 23/09 | committed `result/23-09-2026/identity/{baseline,ner}/summary.json`, synthetic discovery set | 90 rules; 96 NER | 7 rules; 1 NER | 3 REVIEW each | NER mode lists 11 calls; model/transport quality needs separate inspection | Other-team eval artifact; no Duong authorship inferred [EVAL][REPO] **HIGH** |
| 23/09 | committed confirm 179-case evaluator, baseline vs semantic_v4 ×3 | 125 baseline; 157/163/165 semantic | 54 baseline; 22/16/14 semantic | — | Semantic summary names `gpt-6-luna`; provider-call details not audited here | Team context E, not Duong's Week 2 service run [EVAL][REPO] **HIGH** |
| 21–23/09 | older tracing branch collected 1173 | 1149 | 0 reported | 24 | No | branch-specific [HISTORICAL-CHAT] **MEDIUM** |
| 21–23/09 | Clinic Mock / HTTP contract / cross-service | 109 Clinic, 36 HTTP, 2 cross-service | 2 cross-service | 2 xfail Clinic | No | two stale assertions at that time [HISTORICAL-CHAT] **MEDIUM** |
| 21–23/09 | offline groups | 340 and 177 in separate runs | — | — | No | do not add these to inventory [HISTORICAL-CHAT] **MEDIUM** |
| 22–23/09 | booking targeted; full suite around PR #28 | 8; 1409 | 0 reported | 25 full | No | Week 5 scope [PR][HISTORICAL-CHAT] **MEDIUM** |
| 23/09 | confirm cross-service after two test adjustments | 4 | 0 | 0 | No paid model | subsequent A/B wrong-record case: 5/5 [GIT][HISTORICAL-CHAT] **HIGH** test/branch, **MEDIUM** output |
| 23/09 | daily local snapshot | 592 | 0 reported | 1 | No | 20 cross-service PASS, zero P0/P1 [HISTORICAL-CHAT] **MEDIUM** |
| 23/09 | `RUN_CONFIRM_LATENCY=1`; 51 starts +153 turns | 204 <8 s | 0 threshold breaches | — | No proof | max start ~59.09 ms, turn ~2095.55 ms; not production p95 [HISTORICAL-CHAT] **MEDIUM** |
| 23/09 | no-answer review documented by other team member | 83/83 scored; 126 focused | 0 | 3 REVIEW | No | 86 corpus, provisional labels; `docs/evidence/no-answer-review-fixes-20260923.md` [DOC] **HIGH**, Duong E/C only where independently run |
| 23/09 | committed no-answer baseline and semantic_v4 ×3 summaries | 83/83 scored each run | 0 | 3 REVIEW each | Semantic summary names Luna; exact invocation not inferred per case | Team evaluator result, distinct from Duong's service QA [EVAL][REPO] **HIGH** |
| 24/09 | broad offline acceptance | 2088 | 0 | 27 | No | scope differs from focused run [HISTORICAL-CHAT] **MEDIUM** |
| 24/09 | focused acceptance before Luna active | 1085 | 0 | 21 | No | Clinic live skips at that stage [HISTORICAL-CHAT] **MEDIUM** |
| 24/09 | `CLINIC_MOCK_LIVE=1 pytest tests/clinic_mock_sim/test_contract.py` | 42 | 0 | 0 | No LLM | real local Clinic HTTP, fixture reset; terminal evidence [TEST-RUN][HISTORICAL-CHAT] **MEDIUM** |
| 24/09 | targeted identity/confirm/silence/semantic/HTTP/provider-fake regression | 783 | 0 | 0 | No | no paid Luna in pytest [TEST-RUN][HISTORICAL-CHAT] **MEDIUM** |
| 24/09 | real Redis integration | 1 | 0 | 0 | No | Docker Redis healthy [TEST-RUN][HISTORICAL-CHAT] **MEDIUM** |
| 24/09 | synthetic Luna connectivity then real HTTP Engine cases | HTTP 200 and safe Clinic outcomes | 0 observed | — | **Yes, Luna** | 11/5 tokens connectivity; see §20/22 [RUNTIME][HISTORICAL-CHAT] **MEDIUM/HIGH** |
| 24/09 | isolated `CONFIRM_READBACK` sentinel, log-offset capture | 1 safe turn | 0 | 0 | **Yes, Luna** | retained `temp/semantic-evidence.err.log`: 3,114/44 tokens [RUNTIME] **HIGH** |

## 11. Identity & Privacy QA

[GIT][REPO] **HIGH, A.** `a874782` created tabular `identity_cases.py` and `test_identity.py` for open name/DOB, correct/wrong identities, and API validation. `d93dc7a` added `test_sf03_appointment_disclosure.py` with ten named SF-03 cases, wrong DOB and alternate appointment variants, a canary set of clinic/status/date/time/DOB forms and Vietnamese natural-language leak checks. `141da38` added extraction/normalization tests for name segmentation, DOB, invalid dates, correction and ambiguity. The test design checks every bot utterance **before** VERIFIED and Clinic state, not merely final outcome. `verifiable=False` fail-closed test was reported as focused PASS [HISTORICAL-CHAT] **MEDIUM**; it does not imply the entire 18/09 identity suite passed. 24/09 text HTTP live identity had rule-only NER (`NAME_FALLBACK_PROVIDER=none`), no Luna identity call, and wrong-name/wrong-DOB probes. Source verifier/dialogue implementations remain team-authored.

## 12. Confirmation QA

[GIT] **HIGH, A/C.** `73a5919` first added cross-service test harness; `14e4921` extended it to 12 test functions on QA branch: read-only identity, failed verification, explicit agreement, A/B wrong-record mutation, ambiguous/mixed reply, replay/ended turn, lost response reconciliation, version conflict, failed request and latency hard limit. `test_confirm_mutates_only_the_appointment_named_at_call_start` compares A's status/metadata/version to distinct B (ID/patient/clinic/time unchanged), a direct SF-01 wrong-record check. Historical 31 adjacent confirm tests in five files is an audit estimate [HISTORICAL-CHAT] **MEDIUM**, not 31 authored tests. 24/09 service QA observed read-back of the **actual** mock appointment at 15:30, then explicit confirmation wrote `CONFIRMED`, `confirmed_via=callbot`, `confirmed_at` present; ambiguous Luna turns kept `SCHEDULED`. The current branch's cross-service file has only four test functions, so use `14e4921` to inspect expanded QA branch coverage.

## 13. No-Answer QA

[TEST-RUN][REPO] **HIGH for current tests, MEDIUM for historical run.** Three silent text turns and voicemail were checked against Clinic, each with `UNREACHABLE` and `attempt_count` 0→1; voicemail utterances did not include appointment facts. `tests/engine/test_silence_line_signal.py` and HTTP tests cover multiple question states. Duong identified a historical **P1 false-success** when Clinic rejected `UNREACHABLE` yet bot/session said `ENDED/UNREACHABLE` while Clinic remained `SCHEDULED`, attempt 0. The reproduction `test_rejected_unreachable_write_does_not_report_success` exists at `73a5919:tests/engine/test_orchestrator.py`; current direct ownership of the production fix was not established. Later no-answer corpus/fixes belong to other authors, despite Duong's later service QA. Ringing-out representation in frozen HTTP contract was historically unresolved; telephony ringing-out is not proven by silence text tests.

## 14. Cancel / Transfer / Reschedule QA

[REPO][TEST-RUN] **MEDIUM/HIGH, C.** T-05 cancellation regression checks a second explicit confirmation and fail-safe semantic merge. A 24/09 `CANCEL_RECONFIRM` real Luna turn with “hủy giúp tôi nhưng để tôi nghĩ lại” left Clinic `SCHEDULED`. Persistent 409 confirm rejection was historically reproduced to `TRANSFERRED/SYSTEM_ERROR`, never false `CONFIRMED` [HISTORICAL-CHAT] **MEDIUM**; current `test_verify_cross_service.py` on QA branch contains failed request/version-conflict cases. `a1f0a4d` directly fixed slot search across consecutive 14-day windows (bounded to five), added A–J edge tests including unoffered slot and taken-slot refresh. This does not establish a complete live reschedule acceptance. `docs/evidence/t05-cancel-dialogue.md` records semantic/guard concerns from team work; do not credit its core implementation to Duong.

## 15. Inbound Booking QA

[GIT] **HIGH, B/A.** PR #28 merge `46b1f28` confirms branch integration. `e8b16de` modified `ClinicGateway.book` to reject incomplete responses (`appointment_id` missing or `status != BOOKED`) as `WriteOutcomeUnknown`, and added flow/write tests. `a1f0a4d` added multi-window slot search and scenario-7 tests. `docs/evidence/t11-inbound-booking.md` is directly authored (`56c8a36`) and maps identity, offered-slot choice, explicit confirmation, SF-01 duplicate prevention, SF-02 and authoritative Clinic result. Historical 8 targeted PASS and 1409 PASS/25 SKIP are [HISTORICAL-CHAT] **MEDIUM**. This is Week 5 feature work, distinct from Week 2 QA acceptance. Do not assign the original inbound dialogue implementation or all PR parent changes to Duong.

## 16. HTTP / Contract QA

[GIT][HISTORICAL-CHAT] **HIGH for assets, MEDIUM for old count.** The initial 66-case black-box suite mapped AIHR-PC-001 Rev 1.0 to public `/v1/calls`/`/turn` requests, schema, outcomes and Clinic final state, classifying 59 CONTRACT/7 ROBUSTNESS and finding 14/52. `docs/qa-contract-test-matrix.md` and `docs/qa-test-review.md` were named in historical chat but are absent from current reachable Git paths; their exact rows cannot be reconstructed from those documents. `a874782` `test_schema.py` and identity tests, `a06e637` HTTP stub alignment, and `887325b` CI smoke change provide independently verifiable related work. The smoke diff added `caller_number:null`, `locale:"vi-VN"`, `max_turns:20`; it is CI smoke maintenance, not a new production endpoint. 24/09 live validation checked 422 invalid body, 404 unknown call, 409 turn gap, start replay and response fields.

## 17. Clinic Mock / Redis / Cross-Service QA

[TEST-RUN][GIT] **HIGH/MEDIUM.** Cross-service harness uses Clinic HTTP, rather than `FakeClinicAPI`, to read records and compare writes; local contract test ran fake+live parametrization, 42 PASS total. Earlier 21 live skips belonged to a state before startup. `CLINIC_MOCK_LIVE=1` enables live fixture reset, so it must target an isolated local instance; shared-instance resets can affect teammates. Redis was started from compose and real db15 integration test passed. Clinic Mock source/image is maintained outside this repo and not claimed as Duong's work. `5f16851` was an earlier mock commit reference, not independently verified official digest. Replay safety was checked through unchanged Clinic version after a duplicate ended turn.

## 18. STT Evaluation

[GIT][EVAL] **HIGH, A for 40-case framework; C for research.** `73a5919` added `eval/stt-bench/evaluate.py`, adapter protocol, README, 40 synthetic 8 kHz/mono/PCM16 WAV and evaluator tests. Dataset categories are 10 name, 10 DOB, 10 confirmation, 4 critical-entity and 6 signal/noise cases. The evaluator is designed to compare the **same audio** across configured adapters, with WER, critical-entity exactness and silence hallucination checks; low WER cannot override a wrong critical name/date. Historical 40/40 dataset validation is [HISTORICAL-CHAT] **MEDIUM**, not a 40/40 recognition accuracy result. Earlier 18 proposed golden cases were in other-author commit `8915866`. Current repository has provider implementations and other team STT benchmark results, but no evidence that Duong personally measured all listed providers on the full 40-case suite. A local Week 2 Callbot start warned ZipFormer warm-up failed; text-mode QA still proceeded. Full audio-path QA remains unclaimed.

## 19. TTS Evaluation

[GIT][EVAL] **HIGH, A for evaluator/current review artifact.** `73a5919` added a provider-neutral TTS evaluation script and tests, current 40-case YAML and 40-row `tts-review.csv`. Inputs are fixed Vietnamese prompts; expected output includes intact critical business content and a human scorecard for naturalness, intelligibility, pacing and pronunciation. `--validate-only` checks data/format; `--prepare-review` prepares review rows. The skeleton does **not** perform automatic MOS, download a model or call a provider by itself. Original 40-case proposal in `f0e0998` was by HinDayNi. Separately, `docs/evidence/adr-002-tts-bakeoff-report.md` records real 27-phrase provider bake-off by Hưng and names Duong as decision maker; that supports decision/review participation [DOC] **MEDIUM**, not attribution of Hưng's measurement or TTS adapter code.

## 20. LLM / GPT-6 Luna Evaluation

[RUNTIME][REPO] **HIGH, C.** Week 2 active settings resolved semantic provider `openai`, model `gpt-6-luna`, fallback enabled and name fallback `none`. The synthetic connectivity request `Reply exactly: API OK` returned HTTP 200, 11 input/5 output tokens, **3.667 s = 3667 ms**. Real Engine tests then sent ambiguous attendance, ASK_INTENT and CANCEL_RECONFIRM turns through HTTP; Clinic stayed `SCHEDULED` for uncertainty, and explicit rule-level agreement confirmed without Luna. Rule-only identity/silence/voicemail/fake-provider tests consumed no Luna.

The decisive additional sentinel used `CONFIRM_READBACK` + “chắc là được”. Offline rule preflight produced `Agreement.UNCLEAR`, `Intent.NONE`, `route_semantic=INTENT_UNCLEAR`. Existing `LLMSemanticExtractor.analyze` INFO telemetry was enabled for one isolated server run, with log offset captured beforehand. The one new record in `temp/semantic-evidence.err.log` says `provider=openai model=gpt-6-luna status=accepted route=INTENT_UNCLEAR question=CONFIRM_READBACK elapsed_ms=2981.6 input_tokens=3114 output_tokens=44`. `accepted` follows successful structured provider response, `SemanticReading` validation and span grounding. HTTP debug reported `source=LLM`; `merge_semantic` ran; Clinic remained `SCHEDULED`, version 3→3. Because log lacks `call_id`, temporal isolation is the correlation method. [RUNTIME] **HIGH** for this one call, **MEDIUM** for precise count/usage of older Engine turns. No raw prompt/private patient record was printed. The schema excludes `appointment_id`, `slot_id`, outcome and write authority; `merge_semantic` does not promote an uncertain rule result to AGREE (see `src/callbot/engine/extraction/semantic.py`, `semantic_router.py`). This is a safety-path validation, not a statistically reliable Luna accuracy benchmark.

Historical model decision **Claude Haiku 4.5** was an ADR/prototype choice [HISTORICAL-CHAT] **LOW/MEDIUM** until its original ADR is located. The later real Luna runtime is a subsequent state, not a contradiction. `ab2e70e` added dedicated LLM observability on `feature/llm-tracing`, but `src/callbot/tracing/llm.py` is absent from current HEAD; do not claim the deployed/current branch has that child span.

## 21. Privacy / PII Masking

[GIT][REPO] **HIGH for SF-03 tests and tracing privacy implementation.** Duong authored speech/appointment disclosure canaries in `d93dc7a`; the tests inspect full pre-verification utterances, not only output status. `26e3d79` introduced tracing privacy allowlists, pseudonymized `call_key` and JSONL sink; `4a444ae` added privacy filtering for Langfuse export. The nine-case historical `eval/privacy/masking-cases.yaml` proposed NFR-17 outbound-payload checks, including accent-normalized variants and “one leak = failure”. Its Git author is Le Quang Huy while file metadata assigns Duong as `phu_trach`; this supports responsibility/review **MEDIUM**, not directly authored status. The file is absent at current HEAD and a completed CI run of all nine cases was not found. Distinguish SF-03 *spoken disclosure* from NFR-17 *third-party payload masking*.

## 22. Performance / Latency QA

[RUNTIME][REPO] **HIGH.** `src/inference/common/telemetry.py` uses `(perf_counter() - start) * 1000`; the isolated provider/semantic elapsed was **2.9816 s = 2981.6 ms**, total `/turn` **3.014 s = 3014 ms**. Older total endpoint samples, corrected from an initial report unit mistake: “chắc là được” 2.129 s, “để tôi xem đã” 3.210 s, “không biết nữa” 1.664 s, ASK_INTENT 2.575 s, CANCEL_RECONFIRM 1.704 s. Connectivity 3.667 s. The earlier text “3.667 ms” was a **REPORTING UNIT ERROR**, not a production timer defect. All these samples are under the contract's 8-second endpoint limit; small samples cannot establish statistically reliable p95, production distribution or the scored audio-download latency. Historical 23/09 `RUN_CONFIRM_LATENCY=1` 204/204 <8 s (51 starts, 153 turns) is a distinct, [HISTORICAL-CHAT] **MEDIUM** snapshot.

## 23. Provider / ADR Evaluation

| Layer | Considered / evidence | Criteria, data and personal role | Decision then → later change |
| --- | --- | --- | --- |
| STT | ElevenLabs Scribe, Azure, Google, VBee, PhoWhisper, ZipFormer [HISTORICAL-CHAT] **MEDIUM**; 40-case bench [GIT] **HIGH** | Vietnamese accuracy, streaming partial/final, end-of-turn/VAD, 8 kHz, latency, cost, operations/privacy; Duong A benchmark framework, C research, not verified all-provider 40-case run | Prototype comparisons → current ZipFormer runtime by team; no reproduced provider ranking claimed |
| TTS | ElevenLabs Flash, Azure, VBee, Viettel and OpenAI context in ADR [DOC] **HIGH** | TTFA, 8 kHz intelligibility, critical item accuracy, barge-in readiness, cost/characters; Duong A 40-case review framework, named decision maker in ADR; Hưng measured 27-phrase provider data | ADR proposed ElevenLabs primary with further human review; current `.env` used OpenAI TTS in Week 2 service run; neither equals broad audio acceptance |
| LLM | Claude Haiku 4.5 historical ADR [HISTORICAL-CHAT] **LOW/MEDIUM**; OpenAI `gpt-6-luna` runtime [RUNTIME] **HIGH** | Rule-first safety, structured output, grounding, endpoint latency, tokens; Duong C real sentinel and A separate LLM trace branch | Prototype choice → verified Luna semantic path; fake-provider unit tests kept distinct |
| Telephony | SIP/LiveKit/other options appear in team architecture [DOC] **HIGH** | Duong personal benchmark/implementation not established | Team context E; no personal telephony ownership claim |

Research covers license/commercial use, retention/zero retention, BAA, pricing and SDK maturity only as documented/historical analysis. Vendor statements or estimates must not be presented as reproduced benchmark numbers.

## 24. CI / Automation

[GIT] **HIGH, B.** `887325b` changes precisely one CI smoke payload line in `.github/workflows/ci-cd.yml`; the initial `/v1/calls` request lacked required `caller_number`, `locale` and `max_turns`. The updated payload aligns with API schema. The historical Ruff PASS / ~386 pytest PASS / 1 SKIP after that change is [HISTORICAL-CHAT] **MEDIUM**. Duong's tests and evaluator validation can be invoked by CI; `tests/conftest.py` disables paid NER/semantic calls in ordinary pytest. `CLINIC_MOCK_LIVE=1`, `RUN_VERIFY_CROSS_SERVICE=1`, `RUN_CONFIRM_LATENCY=1` are deliberate opt-ins. No evidence supports “owned all CI/CD”, all deployment workflows or all test markers.

## 25. Tracing / Langfuse / Observability

| Slice / commit | Files and test evidence | Purpose / current status |
| --- | --- | --- |
| Privacy-safe trace foundation `26e3d79` | `tracing/context.py`, `models.py`, `privacy.py`, `pseudonym.py`, `jsonl_sink.py`; `test_tracing_core.py`, `test_tracing_integration.py` | Turn/session/Clinic spans, controlled fields, pseudonymous IDs and JSONL. Current branch has code. A **HIGH** [GIT]. |
| Langfuse OTLP `4a444ae` | `tracing/langfuse_sink.py`, `test_langfuse_sink.py` | Opt-in export; endpoint normalization and `x-langfuse-ingestion-version: 4` in current code. Offline adapter tests, not proof of live Langfuse ingestion. A **HIGH** [GIT][REPO]. |
| Speech spans `4c9aedc` | HTTP `calls.py`, `test_speech_tracing.py`, reconciliation tests | Dedicated STT/TTS spans, error classification. Offline tests. A **HIGH** [GIT]. |
| Metrics `b2ad9ae` | `observability/{source,query,aggregate,models}.py`, `test_metrics_query.py` | p50/p95/p99, error/rate, provider/model, slow turns, hourly aggregation over traces. Current code; synthetic/test data only. A **HIGH** [GIT]. |
| Read-only API `b62a8d2` | HTTP `observability.py`, schemas, `test_http_api.py` | Read-only overview/call/turn metrics. Auth/config tests; no production availability proof. A **HIGH** [GIT]. |
| Frontend `b04d492` | `observability_static/*`, JS/Python frontend tests, `docs/voice-observability-dashboard.md` | UI from read-only API; missing metric displays `No data` or `Not instrumented`. A **HIGH** [GIT]. |
| Dedicated LLM trace `ab2e70e` | branch-only `tracing/llm.py`, `test_llm_tracing.py` | Child LLM span and metrics; absent current HEAD. A **HIGH** [GIT] historical branch status. |
| Rebuild `54ed142`, docs `8083d1f` | 48-file integration diff, `.env.example` comments | Reconciled PM dashboard on later main; documented opt-in config. D/A **HIGH** [GIT], but do not count copied/rebuilt parent code as newly authored LOC. |

Historical finding: STT/TTS spans existed while some LLM calls were folded into EXTRACTION; `ab2e70e` addressed this on another branch, not current HEAD. Reasoning-token, retry, cost and full LLM dashboard visibility remain unverified here. Privacy research about Langfuse versus custom metrics, free tier and region is [HISTORICAL-CHAT] **MEDIUM** unless a specific authored document is found.

## 26. Dashboard QA

[GIT][REPO] **HIGH, A.** JS tests `tests/frontend/observability_dashboard.test.mjs` and Python `tests/observability/test_dashboard_frontend.py` validate frontend states and static delivery. API/query tests validate filtering, sorting, percentile/rate semantics and read-only access from synthetic JSONL. `docs/voice-observability-dashboard.md` explicitly states stage durations are compared, not an exact distributed timeline; missing TTFA, VAD, confidence, retry or barge-in metrics show `Not instrumented`. Historical manual “Quality → candidate” flow and PR #34 READY are [HISTORICAL-CHAT] **MEDIUM**; local `0585200` object and reachable `54ed142` corroborate code evolution, not an observed production UI session.

## 27. Defects and Risks Found

| Date | Finding; severity then | How found / reproduction | Impact, fix and attribution | Current status / evidence |
| --- | --- | --- | --- | --- |
| 17/09 | 52/66 contract failures; aggregate severity varied | Black-box public API + final Clinic-state suite | Showed broad early noncompliance; no blanket production fix attributed | Historical snapshot only [HISTORICAL-CHAT] **MEDIUM** |
| 17/09 | CI smoke invalid payload | Workflow POST missing schema fields | Duong fixed smoke JSON in `887325b`, not entire CI | Fixed in diff [GIT] **HIGH** |
| 18/09 | Identity disclosure / partial/wrong match risk, SF-03 | Duong-authored identity/SF-03 canaries, fail-closed cases | Prevent unauthorized details/confirm; core fixes by others unless diff proves otherwise | Tests remain [GIT][REPO] **HIGH** |
| 18/09 | False-success `UNREACHABLE`, **P1** | `test_rejected_unreachable_write_does_not_report_success`, forced Clinic rejection | Bot/session once said ended/unreachable while Clinic scheduled, attempt 0; Duong found/reproduced, production fix author not verified | Historical test at `73a5919` [GIT] **HIGH** finding, **LOW** fix attribution |
| 18–23/09 | Confirm persistent 409 / idempotency conflict 422 | Inject Clinic write failure, cross-service 409 cases | No false CONFIRMED; fallback TRANSFERRED/SYSTEM_ERROR historically | [HISTORICAL-CHAT][GIT] **MEDIUM/HIGH**, exact old run raw output absent |
| 22–23/09 | Wrong-record confirmation, **SF-01 risk** | A/B distinct appointment cross-service test at `14e4921` | A confirmed, B unchanged; Duong authored protection test, no defect fix claimed | QA branch 5/5 historical, current HEAD older [GIT] **HIGH** test / **MEDIUM** run |
| 22/09 | Booking false success on malformed create response | Missing `appointment_id` or wrong status in `test_booking_write.py` | Duong fixed `ClinicGateway.book` to raise unknown outcome in `e8b16de` | Fix + tests [GIT] **HIGH** |
| 22/09 | Slot beyond first 14-day window / unoffered slot | `test_scenario7_edge.py` A–J | Duong changed bounded multi-window search; SF-02 test bars unoffered slot | Fix + tests [GIT] **HIGH** |
| 22–24/09 | Semantic false confirm/cancel risk | Fake-provider merge tests + real ambiguous Luna turns | Deterministic guard retained; no unsafe Clinic write observed in sampled cases | [REPO][RUNTIME] **HIGH** for sampled path; broad model accuracy unknown |
| 23/09 | Transfer state mismatch risk | Gateway/HTTP adjacent tests; historical review | Clinic rejection must not be reported as successful transfer; specific Duong fix not established | [HISTORICAL-CHAT] **MEDIUM** |
| 23–24/09 | LLM visibility gap | Trace inspection and isolated semantic log | Branch-only LLM child span; historical token totals/call IDs incomplete; nonblocking observability gap | [GIT][RUNTIME] **HIGH** current/branch distinction |
| 24/09 | Latency **REPORTING UNIT ERROR**, not production bug | Source `perf_counter*1000` compared to initial text “3.667 ms” | Corrected to 3.667 s = 3667 ms in report; no production edit | [REPO][HISTORICAL-CHAT] **HIGH** |

## 28. Git Contribution Analysis

[GIT] **HIGH.** Rerun of all reachable refs yielded the 22 normal / 5 merge / 3 stash split and 127 path strings above. Historical baseline's 17 significant code/test, 1 documentation, 3 minor normal commits was a qualitative categorization of **21** normal commits before `8083d1f`; it is not a fresh objective classification. Two normal commits (`ac38c73`, `f810495`) are formatting/lint maintenance. Merge commits `159842d`, `6fbe6df`, `6483833`, `38f5eab`, `0038f27` prove reconciliation/integration, but `git show --stat` of a merge can display parent changes; per-line conflict authorship has not been audited. `14e4921` and `ab2e70e` are valid authored branch commits, not current HEAD capabilities. `0585200` is a local object without branch containment. External PR descriptions cannot override exact local diff attribution.

## 29. Week-by-Week Quality Evolution

[HISTORICAL-CHAT][GIT] **MEDIUM/HIGH.** Week 1 began with contract-first 66-case review and many failures, followed by identity/SF-03 tests and smoke schema repair. Week 2 added focused extraction/privacy, speech evaluator frameworks, cross-service state assertions, Redis/Clinic runtime checks, deterministic LLM safety and one real Luna sentinel. The 14/52 early score and later Week 2 READY verdict describe different dates and scopes, not conflicting reports. Week 3+ work started early in branches: tracing/dashboard and Week 5 inbound booking; those contributions cannot be described as Week 2 scenario acceptance merely because they were committed in September.

## 30. Current QA Status

| Module / scenario | Evidence-based status | Limit |
| --- | --- | --- |
| Identity; Confirm; No answer | **LIVE VERIFIED** local text HTTP [TEST-RUN][RUNTIME] **MEDIUM/HIGH** | Limited synthetic scenarios; core code team-authored |
| Cancel; Transfer | **STRONG OFFLINE / PARTIAL LIVE** [REPO][RUNTIME] **HIGH** | One Luna cancel-reconfirm safety probe; no full live scenario batch |
| Reschedule; Inbound booking | **STRONG OFFLINE** [GIT] **HIGH** | Duong booking fixes; no full live acceptance here |
| HTTP contract; Clinic Gateway; Clinic Mock; Redis | **LIVE VERIFIED** local for Week 2 relevant paths [TEST-RUN] **MEDIUM/HIGH** | Clinic Mock is local isolated instance; Redis one integration test |
| LLM semantic | **REAL-PROVIDER VERIFIED** isolated `CONFIRM_READBACK` [RUNTIME] **HIGH** | Not broad accuracy/p95; dedicated LLM span is branch-only |
| STT; TTS | **PARTIAL** evaluator/data [GIT][EVAL] **HIGH** | No broad audio provider acceptance; no automatic MOS |
| Privacy masking | **PARTIAL / historical** [GIT] **HIGH** asset, **LOW** direct authorship | Proposed nine-case YAML absent HEAD; CI execution unknown |
| Tracing | **STRONG OFFLINE** [GIT] **HIGH** | JSONL/speech tests; production trace volume unknown |
| Langfuse | **STRONG OFFLINE** adapter tests [GIT] **HIGH** | No confirmed production export ingestion |
| Observability API; Dashboard | **STRONG OFFLINE** [GIT] **HIGH** | Synthetic JSONL/browser tests, not production SLO |
| CI smoke | **STRONG OFFLINE / historical CI run** [GIT][HISTORICAL-CHAT] **HIGH/MEDIUM** | One payload fix; no entire pipeline ownership |

## 31. Remaining Gaps — What I Cannot Claim Yet

- [RUNTIME] **HIGH:** No statistically reliable Luna p95, complete historic token/cost total, exact historical Luna call counter, per-call log correlation, or broad real-model accuracy study. One isolated sentinel is strong invocation/safety evidence.
- [TEST-RUN] **HIGH:** No full audio-mode acceptance, live telephony ringing-out representation, production traffic, real-patient-data run or production deployment QA attributable to Duong. Week 2 text path success does not fill these gaps.
- [GIT] **HIGH:** Current HEAD lacks QA branch's 12-function expanded cross-service suite and `feature/llm-tracing`'s dedicated LLM span, though their commits exist.
- [GIT][HISTORICAL-CHAT] **MEDIUM/LOW:** Original 66-case matrix/review docs, all raw old terminal outputs, the Claude Haiku ADR, exact PR #34 remote state and completed nine-case masking CI run were not found in current reachable file inventory. Preserve them as history, not current evidence.

## 32. Claim-Evidence Matrix

| Safe claim in first person | Best evidence | Provenance / confidence | Caveat |
| --- | --- | --- | --- |
| “I built automated identity and API contract tests.” | `a874782`, `tests/engine/test_identity.py`, `tests/test_schema.py` | [GIT][REPO] **HIGH** | Core identity engine by team |
| “I added pre-verification disclosure canaries for SF-03.” | `d93dc7a`, `test_sf03_appointment_disclosure.py` | [GIT][REPO] **HIGH** | Test asset, not blanket proof of production privacy |
| “I audited Vietnamese name/DOB extraction and normalization.” | `141da38` test diff | [GIT] **HIGH** | Historical 78/19/3 is rule-only chat snapshot |
| “I detected a false-success unreachable risk.” | `73a5919:test_rejected_unreachable_write_does_not_report_success` | [GIT][HISTORICAL-CHAT] **HIGH/MEDIUM** | Fix author not verified |
| “I built cross-service Clinic HTTP checks for confirmation.” | `73a5919`, `14e4921`, `test_verify_cross_service.py` | [GIT] **HIGH** | Expanded 12-function version lives on QA branch |
| “I verified wrong-record protection with two distinct appointments.” | `14e4921` A/B test | [GIT][HISTORICAL-CHAT] **HIGH/MEDIUM** | 5/5 run historical |
| “I built STT/TTS evaluator frameworks and expanded STT to 40 WAV.” | `73a5919` diff and current data | [GIT][EVAL] **HIGH** | Original 18 STT/40 TTS proposals by others |
| “I hardened inbound booking result validation and slot search.” | `e8b16de`, `a1f0a4d`, T-11 evidence | [GIT][DOC] **HIGH** | Week 5 feature; not entire booking implementation |
| “I built privacy-aware tracing and read-only observability.” | `26e3d79`–`b04d492`, tests | [GIT] **HIGH** | Offline code/test capability, not live production SLA |
| “I implemented a Langfuse OTLP export adapter.” | `4a444ae`, `langfuse_sink.py`, tests | [GIT][REPO] **HIGH** | Live Langfuse ingestion not proved |
| “I verified real GPT-6 Luna in a safe Engine turn.” | `temp/semantic-evidence.err.log`, Clinic version 3→3 | [RUNTIME] **HIGH** | Single isolated turn, no call ID in log |
| “I closed Week 2 text QA with service-live Clinic/Redis checks.” | 24/09 run summaries in historical chat, retained sentinel log | [TEST-RUN][HISTORICAL-CHAT][RUNTIME] **MEDIUM/HIGH** | Results not all committed; audio/p95 gaps |

## 33. Safe CV / Performance Review Claims

**30-second summary.** [GIT][RUNTIME] **HIGH/MEDIUM**

- Built contract, identity, SF-03 privacy and cross-service tests that compare bot responses with authoritative Clinic records.
- Expanded an 8 kHz STT golden suite to 40 WAV cases and built provider-neutral STT/TTS evaluators.
- Fixed booking write-result validation and bounded slot search; added tests for false success, duplicate writes and unoffered slots.
- Implemented privacy-aware tracing, Langfuse export, metrics aggregation, read-only observability API and dashboard components.
- Ran local Week 2 service QA and isolated a real GPT-6 Luna semantic turn without an unsafe Clinic mutation.

**Manager / performance-review summary.** [GIT][TEST-RUN][RUNTIME] **HIGH for commits/runtime; MEDIUM for old run counts.** Duong's work moved from early contract gap detection to executable protections. The 17/09 review recorded 52 failures out of 66, motivating precise identity/schema/SF-03 checks rather than ungrounded “green” status. He authored cross-service tests that read Clinic final state, including an A/B wrong-appointment case and replay/reconciliation paths; he identified a P1 unreachable false-success pattern. His own booking fixes enforce authoritative `BOOKED` responses and search later slot windows. He also built repeatable speech-evaluation assets and a substantial privacy/observability stack, while distinguishing team-owned speech/dialogue/Clinic implementation. The 24/09 text-service acceptance found local Redis, Clinic and Callbot operational, with 42 live Clinic tests, 783 targeted offline tests and a real Luna sentinel that left an ambiguous appointment unchanged. The final Week 2 READY conclusion carries explicit audio, p95 and historical-token observability limits.

**Technical interview summary.** [GIT][REPO][RUNTIME] **HIGH.** Explain the testing pyramid by example: contract schema tests for both public endpoints; fake-provider fault injection for 401/429/timeout/malformed/5xx; `FakeClinicAPI` component tests for deterministic policy; local Clinic HTTP cross-service tests that compare status, version, metadata and unrelated appointment B; Redis-backed session/replay checks; and one real Luna structured-output sentinel. Explain why output text alone is inadequate, why `SemanticReading` cannot contain write authority, why ambiguous `AGREE` cannot be promoted by model output, and why p95 cannot be inferred from six latency samples. Discuss speech eval as 8 kHz fixed audio + WER/entity/hallucination and TTS as human review, not automatic MOS. For tracing, describe privacy allowlist/pseudonymization, JSONL/OTLP, aggregation and dashboard “Not instrumented” semantics, while stating that the dedicated LLM child span is branch-only.

**Additional precise phrases usable after selecting relevant role:** [GIT][REPO] **HIGH** — “Designed SF-03 pre-verification canaries”; “Reproduced a Clinic-vs-session false-success condition”; “Added A/B wrong-record cross-service tests”; “Implemented booked-response validation”; “Built bounded slot-window regression tests”; “Built STT WER/entity/hallucination evaluator”; “Prepared TTS human review scorecard”; “Added privacy-safe JSONL tracing”; “Implemented Langfuse OTLP adapter”; “Added STT/TTS span tests”; “Built p50/p95/p99 query layer”; “Built read-only observability API”; “Added dashboard state tests”; “Corrected a seconds-vs-milliseconds QA reporting error”; “Verified an isolated GPT-6 Luna invocation through Engine.”

## 34. Claims Not Supported by Evidence

- “I built the whole callbot / Clinic Mock / Redis / ASR / TTS provider implementation.” Team authorship and authored diff do not support this. [GIT] **HIGH**.
- “I owned the whole CI/CD pipeline” or “I deployed production.” One smoke payload fix and tests do not support it. [GIT] **HIGH**.
- “I personally benchmarked every STT/TTS provider” or “I measured automated MOS.” The 40-case frameworks, other-person ADR measurements and human scorecard do not support these. [GIT][DOC] **HIGH**.
- “I proved production p95 below 8 seconds,” “fully validated audio/telephony,” or “tested real patient data.” Only small local text samples are shown. [RUNTIME] **HIGH**.
- “I wrote the original 18-case STT or 40-case TTS proposal / nine-case masking YAML.” Those historical file commits name other authors. [GIT] **HIGH**.
- “I fixed the unreachable false-success bug” or “the current main has dedicated LLM child spans.” The finding test exists, fix attribution was not isolated, and `ab2e70e` is branch-only. [GIT] **HIGH**.
- “The 2088, 1085, 783 and 592 counts are distinct tests I authored.” They are overlapping run snapshots. [HISTORICAL-CHAT] **MEDIUM**.

## 35. File / Test / Commit Evidence Index

This index groups paths with identical provenance instead of implying every current file has the same author. `HEAD` means current audit branch `8083d1f`; `QA branch` means inspect `14e4921`; `LLM branch` means inspect `ab2e70e`.

| Path / family | Type; my relation | Purpose / requirement; latest known status | Commit(s); confidence |
| --- | --- | --- | --- |
| `tests/test_schema.py`; `tests/engine/identity_cases.py`; `tests/engine/test_identity.py` | tests/data; A | API contract, identity, SF-03; current tests | `a874782`,`d93dc7a` [GIT] **HIGH** |
| `tests/engine/test_sf03_appointment_disclosure.py`; `tests/engine/extraction/test_identity_extraction_normalization.py` | tests; A | pre-VERIFIED disclosure; name/DOB parsing; current | `d93dc7a`,`141da38` [GIT] **HIGH** |
| `tests/transports/http/test_calls.py`; `src/callbot/transports/http/{schemas,stub_handlers}.py` | test/source; B | early contract stub alignment; later debug boundary | `a06e637`,`a874fd1` [GIT] **HIGH** |
| `tests/transports/http/test_verify_cross_service.py` | cross-service tests; A | identity, confirm, A/B mutation, replay, version/conflict/latency; 4 functions HEAD vs 12 QA branch | `73a5919`,`14e4921` [GIT] **HIGH** |
| `tests/engine/test_orchestrator.py` | test; B | unreachable-rejection reproduction, tracing integration | `73a5919`,`26e3d79`,`54ed142` [GIT] **HIGH** |
| `eval/stt-bench/{golden-cases.yaml,evaluate.py,README.md,adapters/base.py,audio-8k/*.wav}`; `tests/eval/test_stt_evaluator.py` | dataset/evaluator/tests; A for 40-case expansion | WER/entity/noise/8 kHz; 40 current | initial `8915866` other author; `73a5919` Duong [GIT] **HIGH** |
| `eval/tts-bench/{golden-cases.yaml,evaluate.py,README.md,adapters/base.py,results/tts-review.csv}`; `tests/eval/test_tts_evaluator.py` | dataset/evaluator/tests; A current evaluator, not initial 40 proposal | 40-case human scorecard/review CSV | `f0e0998` other author; `73a5919` Duong [GIT] **HIGH** |
| `eval/privacy/masking-cases.yaml` | historical proposed data; C/attribution unresolved | nine NFR-17 canaries, absent HEAD | `8915866` other author; [GIT] **HIGH** file, **LOW** direct authorship |
| `eval/{identity,confirm,cancel,no_answer}/cases.csv`; `scripts/{identity,confirm,cancel,no_answer}_eval.py` | team eval assets; C where run | 100/179/107/86 cases; not blanket authored | other-author commits/current repo [REPO][GIT] **HIGH** |
| `src/callbot/engine/tools/clinic_gateway.py`; `tests/engine/{test_inbound_booking_flow,test_scenario7_edge}.py`; `tests/engine/tools/{test_booking_write,test_clinic_gateway}.py` | source/tests; B/A | authoritative BOOKED, window search, SF-01/SF-02 | `e8b16de`,`a1f0a4d` [GIT] **HIGH** |
| `docs/evidence/t11-inbound-booking.md` | doc; A | acceptance map for Week 5 booking | `56c8a36` [GIT] **HIGH** |
| `.github/workflows/ci-cd.yml` | CI; B | smoke request schema | `887325b` [GIT] **HIGH** |
| `src/callbot/tracing/{context,privacy,pseudonym,jsonl_sink,models,config,sink,errors}.py`; `tests/tracing/{test_tracing_core,test_tracing_integration,test_runtime_reconciliation}.py` | source/tests; A/B | safe spans, pseudonymization, JSONL, replay | `26e3d79`,`54ed142` [GIT] **HIGH** |
| `src/callbot/tracing/langfuse_sink.py`; `tests/tracing/test_langfuse_sink.py` | source/test; A | OTLP sink, endpoint/auth/queue/error behavior | `4a444ae` [GIT] **HIGH** |
| `tests/tracing/test_speech_tracing.py`; HTTP `calls.py` | tests/source; A/B | STT/TTS spans, safe errors | `4c9aedc` [GIT] **HIGH** |
| `src/callbot/tracing/llm.py`; `tests/tracing/test_llm_tracing.py` | branch-only source/test; A | dedicated LLM child span | `ab2e70e`; absent HEAD [GIT] **HIGH** |
| `src/callbot/observability/{source,query,aggregate,models}.py`; `tests/observability/test_metrics_query.py` | source/test; A | p50/p95/p99, errors, providers, hourly and slow turns | `b2ad9ae`,`54ed142` [GIT] **HIGH** |
| `src/callbot/transports/http/{observability,observability_schemas}.py`; `tests/observability/test_http_api.py` | source/test; A | read-only observability API | `b62a8d2`,`54ed142` [GIT] **HIGH** |
| `src/callbot/transports/http/observability_static/*`; `tests/frontend/observability_dashboard.test.mjs`; `tests/observability/test_dashboard_frontend.py`; `docs/voice-observability-dashboard.md` | frontend/tests/doc; A/B | UI/API contract, safe missing data | `b04d492`,`54ed142` [GIT] **HIGH** |
| `.env.example` | doc/config; A | trace/Langfuse option descriptions, no secrets | `8083d1f` [GIT] **HIGH** |
| `temp/semantic-evidence.err.log`; `temp/qa_semantic_server.py` | local runtime evidence/helper; C | isolated Luna log with no patient transcript, not committed | 24/09 [RUNTIME] **HIGH**, ephemeral |
| `docker-compose*.yml`, `Dockerfile`, `pyproject.toml`, `README.md`, `uv.lock` | project environment; read/audit only except named diff | service startup and test deps; `uv.lock` untracked before dossier | [REPO][GIT] **HIGH**, no blanket Duong ownership |

## 36. Appendix — Raw Historical Evidence Reconciliation

| Historical claim | What current Git/repo verifies | Reconciliation / confidence |
| --- | --- | --- |
| HIST-001 66 tests, 14/52, two docs | `a874782` API/identity assets exist; named `docs/qa-contract-test-matrix.md` and `docs/qa-test-review.md` absent in reachable Git | Preserve run/count [HISTORICAL-CHAT] **MEDIUM**; exact matrix rows not recoverable |
| HIST-002/003 smoke and 14 identity pass | `887325b` exact payload diff, `d93dc7a` tests | Fix **HIGH**, old terminal counts **MEDIUM**; broader identity failures not erased |
| HIST-004/005 false-success and confirm conflict | Reproduction at `73a5919:tests/engine/test_orchestrator.py`; QA branch cross-service conflict tests | Finding/test **HIGH**, old P1 label/run **MEDIUM**, production fix author unresolved |
| HIST-006/007 SF-03 and rule eval | `d93dc7a`,`141da38`, current 100-row identity CSV | Assets **HIGH**; 78/19/3 rule-only result **MEDIUM**, not Luna result |
| HIST-008/009/010 masking/STT/TTS | `8915866` 9 masking +18 STT; `f0e0998` 40 TTS; `73a5919` 40 STT WAV/evaluators | Exact historical/current counts **HIGH**; 40/40 validation old output **MEDIUM**; original datasets by other authors |
| HIST-011 provider/ADR | Current ADR-002 credits Hưng measurement and Duong decision; Claude ADR not located | TTS decision role **MEDIUM**; Claude selection historical **LOW/MEDIUM** |
| HIST-012/013 cross-service/latency | `14e4921` 12-function branch suite; current HEAD only 4; latency flag in QA branch | Code **HIGH**, 5/5 and 204/204 outputs **MEDIUM**; no conflict with current branch |
| HIST-014/015/016 regressions/PR #28 | PR merge `46b1f28`, `e8b16de`, `a1f0a4d`, T-11 doc | Code/merge **HIGH**, 1149/24 and 1409/25 snapshots **MEDIUM**, scopes overlap |
| HIST-017/018/019/020 observability | All named authored commits valid; `0585200` dangling; `54ed142` reachable; current lacks `tracing/llm.py` | Historical branch feature **HIGH**, PR #34 remote READY **MEDIUM**; no production ingestion claim |
| HIST-021/022 first and final Week 2 runs | Historical 2088/27 and 1085/21; 24/09 service/test outputs supplied in conversation | Different scopes/states; counts **MEDIUM** absent committed raw log; retained Luna log **HIGH** |
| HIST-023/024/025/026 Luna and verdict | `temp/semantic-evidence.err.log` + timer source prove one accepted request and corrected units | Sentinel **HIGH**, other five latency snapshots **MEDIUM**, final READY limited to text service, p95 unproven |

**Final forensic rule.** [GIT][DOC][HISTORICAL-CHAT] **HIGH for method.** An old FAIL followed by a later PASS documents quality evolution. A branch-only feature and a current missing file document integration state. Neither should be silently collapsed. Only cited diffs establish direct authorship; historical conversation establishes old observations at its own confidence level.

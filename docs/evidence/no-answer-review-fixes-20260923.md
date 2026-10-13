# No-answer review fixes — 2026-09-23

Implemented the five requested review steps in the no-answer corpus, evaluator and line-signal extraction. No deployment or real-model evaluation was performed.

## Changes

1. `scripts/no_answer_eval.py` constructs the orchestrator with name NER and semantic fallback explicitly disabled, regardless of `.env`. Setup turns also use rules only. Semantic mode injects only the requested semantic extractor after setup; route-only injects a stub. A test enables both providers in the environment and rejects any attempt to create a model gateway.
2. The 86 cases now have stable IDs `NA001`–`NA086`, `scope` (`http`, `telephony`, `recovery`) and `label_status`. Previous holdouts are now regression cases: they have been inspected and used to develop fixes, so they no longer establish unseen-data accuracy. There are 33 dev cases and 53 regression cases.
3. Human requests to leave a message for a relative, interactive questions after a thank-you, and a number belonging to a relative no longer become voicemail/busy signals merely because they contain those keywords. Tests include alternate wording and unaccented input, plus automated-announcement counterexamples. A standalone Vietnamese statement of being unable to answer is no longer sufficient evidence of voicemail; the old unit expectation for the ambiguous Lan example was removed and replaced by a conservative NONE assertion.
4. Added recognized variants for full mailboxes, automated voice messaging, “gọi tới số”, “đây là hộp thư”, a bounded ASR typo and “đang có cuộc gọi khác”. Recovery checks inspect the persisted blocked turn and issue a follow-up turn: it must raise `ReconciliationRequired` without changing clinic records, writes or request history. A negative test proves that an exception without a persistent lock is insufficient. RECONCILE must also occur at the expected turn.

## Scope and reporting

- [Contract §4.2.5](https://callbot-contract-site-rev11.vercel.app/#c4.2.5): NO_ANSWER/LINE_BUSY belong to the week-6 live call. Eight telephony cases remain separate from the HTTP metric.
- Five injected write-fault cases are reported as recovery, outside the HTTP denominator. Same-key retry after VERSION_CONFLICT is contractual; retry limits and RECONCILE are internal recovery policy. RECONCILE is not an HTTP terminal outcome.
- Report separates behaviour failures, implemented record/response check failures, recovery failures and REVIEW. The legacy `contract_failures` JSON key remains as an alias for record/response check failures; zero does not certify complete contractual compliance.
- `NOT_UNREACHABLE` human traps test false positives only, not every downstream dialogue requirement. Text fixtures do not evaluate audio or prove performance on the hidden harness.

## Validation

Baseline before fixes: 74/86 passed, 12 failed, including three false UNREACHABLE results.

Baseline and route-only after fixes: **83/83 scored cases passed, 3 REVIEW**.

| Metric | Result |
| --- | --- |
| HTTP scope, confirmed labels | 70/70 |
| Telephony | 8/8 |
| Recovery | 5/5 |
| Silence | 22/22 |
| Human traps (including inbound negative control) | 14/14 |
| False UNREACHABLE / wrong reason | 0 / 0 |
| Record checks / recovery failures / disclosures | 0 / 0 / 0 |
| Independent holdout | None |

Baseline uses no model; route-only records one semantic routing attempt to a local stub, not an API request. Real semantic quality and latency remain unmeasured.

- Focused evaluator, line-signal and silence tests: **126 passed**.
- Broader `tests/engine tests/eval`: **1796 passed, 1 skipped**, with 19 setup errors caused by Windows temporary-directory permissions. Rerunning the five affected files (including the evaluator) outside the sandbox: **129 passed**, covering all 19 previously blocked tests. No assertion failures remained. A Starlette/AnyIO deprecation warning persists.
- Ruff check and format checks pass for the four changed Python files.

Results: [baseline](../../result/23-09-2026/no_answer/fixed-review-20260923/summary.json), [route-only](../../result/23-09-2026/no_answer/fixed-review-route-only-20260923/summary.json).

Reproduce:

```powershell
.venv/Scripts/python.exe scripts/no_answer_eval.py --baseline --label fixed-review-20260923
.venv/Scripts/python.exe scripts/no_answer_eval.py --route-only --label fixed-review-route-only-20260923
.venv/Scripts/python.exe -m pytest -q tests/eval/test_no_answer_evaluator.py tests/engine/extraction/test_line_signal.py tests/engine/test_silence_line_signal.py
```

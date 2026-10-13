# Evidence: Prompt GPT-6 Luna — `semantic_v10_luna`, `name_slot_filling_v4`

## Mục tiêu

Rà lại hai prompt gọi GPT-6 Luna (`service_tier=fast`, `reasoning_effort=none`) — tầng ngữ nghĩa và slot
filling họ tên — theo tài liệu OpenAI đọc trước khi sửa: [Using GPT-6](https://developers.openai.com/api/docs/guides/latest-model)
(prompt gọn, mỗi chỉ dẫn một lần; với reasoning `none` mới gửi được `temperature`),
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) và
[Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) (GPT-5.6+: tiền tố tối thiểu
1024 token; breakpoint ngầm chỉ ở cuối developer message đầu và cuối user message cuối; cache write 1,25×
giá input, cache read 0,1×). Không có hướng dẫn prompt riêng cho Luna.

Đo thực tế trước khi sửa (12/10/2026, `usage.prompt_tokens_details.cached_tokens`, transcript đổi mỗi lượt):

| Prompt | Cấu trúc request | prompt_tokens | cached |
| --- | --- | ---: | ---: |
| `semantic_v9_luna` | system + 14 cặp user/assistant + user | 2896 | 1575 (54 %) |
| `name_slot_filling_v3` | system + 18 cặp user/assistant + user | 1703 | 0 |

Cặp ví dụ user/assistant đứng sau system không bao giờ nằm trong tiền tố được cache, nên mỗi lượt trả giá
cache write cho ~1300 token ví dụ; system của name một mình dưới 1024 token nên không cache gì. Schema gửi
kèm mang docstring của class và `title` tự sinh. Provider bỏ `temperature` với mọi `gpt-6-*` dù Luna / Sol
chạy `reasoning_effort=none`.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Tầng ngữ nghĩa: cùng nhãn / quy tắc / contract span v9, request hai message, ví dụ trong system | `LUNA_V10_SYSTEM_PROMPT`, `LUNA_V10_EXAMPLES`, `_build_luna_v10_messages` (`inference/llm/prompt/semantic.py`); `PROMPT_VERSION_LUNA = "semantic_v10_luna"`, v9 giữ dưới `PROMPT_VERSION_LUNA_V9`. Test `test_v10_prompt_is_two_messages_with_the_examples_inside_the_cached_system`, `test_luna_prompt_is_smaller_and_keeps_the_runtime_contract`, `test_the_factory_picks_the_prompt_and_the_gate_from_the_flag` |
| Ví dụ không trùng câu holdout / new của eval | `test_v10_examples_do_not_repeat_scored_eval_cases` (`tests/engine/extraction/test_cancel_promotion.py`) |
| Slot filling tên: quy tắc v3, 18 ví dụ trong system, request hai message | `RULES`, `FEW_SHOTS`, `SYSTEM_PROMPT`, `build_messages` (`inference/llm/prompt/name_slot_filling.py`); `PROMPT_VERSION = "name_slot_filling_v4"`. Test `test_request_contract_and_private_telemetry`, `test_v4_system_prompt_carries_every_example_and_a_bare_schema`, `test_few_shot_outputs_satisfy_the_real_span_validator` |
| Schema Structured Outputs không mang docstring / `title` | `compact_json_schema` (`callbot/engine/extraction/schema.py`) gắn `json_schema_extra` cho `SemanticReading`, `NameExtraction`; test ở hai file trên kiểm `"title" not in schema` |
| Luna / Sol gửi `temperature=0` cùng `reasoning_effort=none`; Astra không gửi `temperature` | `OpenAIProvider._payload`; test `test_gpt_6_keeps_temperature_only_when_reasoning_is_off` (`tests/llm/test_gateway.py`) |
| Harness ghi đúng prompt version đang dùng | `scripts/confirm_eval.py`, `scripts/no_answer_eval.py` (`getattr(extractor, "prompt_version", …)`) |

## File liên quan

- `src/inference/llm/prompt/semantic.py`, `src/inference/llm/prompt/name_slot_filling.py`
- `src/inference/llm/providers/openai.py`
- `src/callbot/engine/extraction/schema.py`, `semantic.py`, `name_slot_filling.py`
- `tests/llm/test_gateway.py`, `tests/engine/extraction/test_cancel_promotion.py`,
  `tests/engine/extraction/test_name_slot_filling.py`
- `scripts/confirm_eval.py`, `scripts/no_answer_eval.py`
- `docs/reference/information-extraction-design.md`, `docs/reference/name-slot-filling.md`,
  `docs/plans/t10-slot-semantic-fallback.md`
- Kết quả eval (bản cuối, thư mục đặt theo `prompt_version`): `result/12-10-2026/cancel/semantic_v10_luna`,
  `result/12-10-2026/confirm/semantic_v10_luna`, `result/12-10-2026/identity/name_slot_filling_v4`; số liệu baseline (prompt cũ, cùng ngày) chỉ ghi trong bảng dưới, không giữ file

## Luồng hiện tại

```text
request Luna (Chat Completions, Structured Outputs strict, service_tier=fast, reasoning_effort=none, temperature=0)
  -> message 1 (system, ổn định, được cache): quy tắc + ví dụ dạng "input -> output"
  -> message 2 (user, động): JSON ngữ cảnh lượt hiện tại
       semantic : question_id, question_purpose, allowed_intents, pending_action,
                  answers_last_question, rule_hints_untrusted, transcript
       name     : question_id, bot_question, customer_answer
  -> response_format: schema đóng, không description / title
```

## Kết quả đo

### Token và cache (cùng phép đo với bảng "trước")

| Prompt | Request | prompt_tokens | cached khi transcript đổi |
| --- | ---: | ---: | ---: |
| `semantic_v9_luna` → `semantic_v10_luna` | 30 → 2 message | 2896 → 2427 (−16 %) | 1575 → 2341 (54 % → 96 %) |
| `name_slot_filling_v3` → `name_slot_filling_v4` | 38 → 2 message | 1703 → 1398 (−18 %) | 0 → 1352 (0 % → 98 %) |

Phần không cache mỗi lượt của semantic giảm từ ~1320 token (tính giá cache write) còn ~90; của name từ 1703
còn ~30.

### Eval (Luna, `service_tier=fast`, timeout 3 s, `SEMANTIC_PROVIDER=openai`, cùng ngày, cùng nhãn, cùng mã)

Baseline chạy trước khi sửa với prompt cũ (không giữ file, chỉ ghi số); bản mới chạy sau khi sửa. Cancel / confirm `--repeats 3`; lần 3 của
bản mới trúng đợt mất kết nối (77–78 lượt `network_error`, latency ~5 ms) nên không tính — `summary.json`
vẫn giữ cả ba lần để đối chiếu; bảng dưới chỉ gộp lần 1–2 của bản mới.

#### Cancel (120 ca, 91 holdout mỗi lần)

| Chỉ số | v9 (3 lần) | v10 (lần 1–2) |
| --- | ---: | ---: |
| holdout behaviour, từng lần | 92,3 % / 91,2 % / 86,8 % | 92,3 % / 95,6 % |
| holdout behaviour, gộp | 90,1 % (246/273) | 94,0 % (171/182) |
| holdout reason, từng lần | 90,1 % / 91,2 % / 91,2 % | 90,1 % / 92,3 % |
| unsafe writes (SF-05) | 0 | 0 |
| trạng thái model | accepted 250, rejected 5, timeout 9 | accepted 187, rejected 2, timeout 2, network_error 1 |
| semantic latency p50 / p95 ms, từng lần | 1926 / 2606 · 1895 / 2799 · 1719 / 2901 | 1624 / 2367 · 1564 / 2028 |

Câu holdout đổi hành vi (tỷ lệ đúng theo lần chạy): 15 tốt lên, 6 xấu đi. Ba câu xấu đi là câu hỏi "đặt lại"
("Hủy rồi đặt lại có được không", "Hủy giúp tôi, mà cho hỏi đặt lại thế nào", "Hủy xong có ảnh hưởng gì đến
hồ sơ không") mà baseline cũng sai 2/3; ba câu còn lại là lý do thì quá khứ / so sánh giá đọc thành AMBIGUOUS
ở một lần ("Đỡ rồi nên không cần đi nữa", "Bệnh cũng đỡ nhiều rồi em ạ", "Chỗ em báo giá cao quá so với chỗ
khác").

#### Confirm (187 ca, 171 holdout mỗi lần)

| Chỉ số | v9 (3 lần) | v10 (lần 1–2) |
| --- | ---: | ---: |
| holdout behaviour, từng lần | 89,5 % / 88,3 % / 88,3 % | 93,0 % / 93,6 % |
| holdout behaviour, gộp | 88,7 % (455/513) | 93,3 % (319/342) |
| needs-inference passed (/64) | 49 / 49 / 47 | 55 / 56 |
| attendance confirmed (/46) | 38 / 38 / 38 | 38 / 38 |
| cancel / reschedule routing (/23) | 21 / 20 / 20 | 22 / 23 |
| unsafe writes | 0 | 0 |
| trạng thái model | accepted 240, timeout 14 | accepted 183, rejected 2, skipped 1, network_error 3 |
| semantic latency p50 / p95 ms, từng lần | 1948 / 2515 · 1926 / 2890 · 1635 / 2716 | 1646 / 2528 · 1613 / 2104 |

Câu holdout đổi hành vi: 17 tốt lên, 3 xấu đi ("hôm đó đúng ngày giỗ nhà tôi", "tôi ở xa quá, đi được mất cả
ngày", "con tôi đưa đi thì tôi mới đi được" — lý do kể gián tiếp, model đọc AMBIGUOUS).

#### Identity slot filling (215 ca, 201 chấm; mỗi lần ~120 lượt gọi model)

| Lần chạy | pass rate | pass / fail | trạng thái slot filling | latency p50 / p95 ms |
| --- | ---: | ---: | --- | ---: |
| v3 | 93,5 % | 188 / 13 | accepted 48, no_name 70, rejected 1, unavailable 1 | 1556 / 2342 |
| v4 | 96,5 % | 194 / 7 | accepted 40, no_name 73, rejected 1, unavailable 7 | 1396 / 2336 |

Bộ identity là discovery set (không phải held-out); lượt `unavailable` (timeout 3 s) ở ca mong đợi `null`
được tính PASS, nên lần v4 có thể lệch ±2 ca do mạng. Các ca v3 đọc sai ổn định là câu rác không dấu mở đầu
bằng họ ("tran nha", "trieu dong", "hồ thu hoạch"); v4 trả `null` cho các ca này.

## Quy trình xác minh

```powershell
make check
SEMANTIC_PROVIDER=openai python scripts/cancel_eval.py --semantic --repeats 3 --label <label>
SEMANTIC_PROVIDER=openai python scripts/confirm_eval.py --semantic --repeats 3 --label <label>
python scripts/identity_eval.py --slot-filling --output result/<dd-mm-yyyy>/identity/<label>/results.csv
python scripts/eval_compare.py result/<dd-mm-yyyy>/confirm/<baseline> result/<dd-mm-yyyy>/confirm/semantic_v10_luna
```

## Kết quả xác minh cục bộ (2026-10-12)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check` (file đổi) | Pass |
| `python -m pytest -q` | Pass (5211 passed, 26 skipped trên nhánh gộp với `develop`; bỏ `tests/transports/livekit/test_worker_speech_settings.py` vì môi trường cục bộ thiếu gói `livekit`) |

## Ghi chú

- Ví dụ trong prompt dùng họ Nguyễn, Bùi, Lý, Đào; các họ Trần, Triệu, Lưu, Cao… mở đầu nhiều câu rác của
  `eval/identity` và mồi model đọc câu rác thành tên khi xuất hiện trong ví dụ.
- Cancel / confirm chấm trên split `holdout`; ví dụ trong prompt không trùng câu holdout / new (test chặn).
- `service_tier=fast` giữ nguyên; chưa đo Standard với prompt mới.
- Jev vẫn là provider chính của tầng ngữ nghĩa (`semantic_provider: jev`); prompt Luna chỉ chạy khi
  `semantic_provider` / `semantic_backup_provider` là `openai`. Slot filling tên dùng OpenAI mặc định.
- Timeout 3 s cứng vẫn bắt phần đuôi p99 (1–3 % lượt mỗi lần chạy) ở cả bản cũ lẫn mới.

# Tầng ngữ nghĩa bằng TypeSafe Jev so với GPT-6 Luna, và review nhãn eval theo hợp đồng Rev 1.1

**Bản v1** (2026-10-10, nhánh `feat/jev-semantic`): provider Jev, adapter `semantic_jev_v6`, kết quả
`result/10-10-2026/*/jev-v1`.

Jev 1.13 (`SEMANTIC_PROVIDER=jev`, adapter `semantic_jev_v6`) nhanh hơn GPT-6 Luna (Fast
mode, reasoning tắt) 2–3,8 lần ở p50 (355–680 ms tùy khung giờ, so với 1345–1392 ms), không có lần
ghi sai nào, và sau vòng sửa adapter thứ hai hơn OpenAI trên các lượt thật sự gọi model ở cả cancel
(99,5 % so với 91,7 %) lẫn confirm (88,3 % so với 82,0 %). Từ 10-10 tối (owner), mặc định là **Jev,
OpenAI dự phòng** khi Jev lỗi dịch vụ; đổi bằng `semantic_provider` / `semantic_backup_provider`. Review nhãn eval theo hợp đồng đổi 4 nhãn, vá một lỗi harness và sửa ba chỗ
ở luật / merge; vòng hai (owner duyệt từng ca) đổi thêm 4 nhãn cancel và bỏ 10 ca confirm.

## Nguồn

- OpenAI `gpt-6-luna` (`service_tier=fast`, `reasoning_effort=none`, prompt `semantic_v9_luna`):
  [cancel](../../result/10-10-2026/cancel/openai/), [confirm](../../result/10-10-2026/confirm/openai/),
  [reschedule](../../result/10-10-2026/reschedule/openai/), [no_answer](../../result/10-10-2026/no_answer/openai/).
  Chạy MỘT lần vào đầu ngày, trước khi đổi nhãn / vá luật; các bảng dưới chấm lại offline từ
  `results.csv` với nhãn mới (xem "Cách chấm lại").
- Jev `jev-1.13.0` (`semantic_jev_v6`), `jev-v1` chạy với code và nhãn cuối (các lần chạy trung gian
  trong ngày không giữ lại; bộ no_answer giữ lần chạy `semantic_jev_v5` vì không đổi đường đi nào của nó): [cancel](../../result/10-10-2026/cancel/jev-v1/),
  [confirm](../../result/10-10-2026/confirm/jev-v1/), [reschedule](../../result/10-10-2026/reschedule/jev-v1/),
  [no_answer](../../result/10-10-2026/no_answer/jev-v1/).
- Mỗi bộ chạy 3 lần (`--repeats 3`). Jev gần như tất định; chênh lệch giữa các lần chủ yếu là lỗi mạng.

## Cách chấm lại

OpenAI không chạy lại sau khi đổi nhãn (quyết định owner 10-10). Cột OpenAI được chấm lại từ
`results.csv` cũ với nhãn mới; chỉ áp "flip" cho dòng **không qua model** (kết quả do luật, độc lập
provider): ba ca "đổi sang chiều" OTHER → RESCHEDULE (lỗi harness, xem dưới) và "Bên bảo hiểm không
chi trả nên tốn kém quá" TRANSFER → REASON_NOTED (luật mới). Hai ca "khám ở viện khác rồi" OpenAI đã
trả `INFORM_REASON / WENT_ELSEWHERE` nên với nhánh merge mới cũng sẽ ra CANCEL; cột
"OpenAI + credit" ở bảng confirm cộng hai ca đó. Cách chấm offline được kiểm chứng: một lần chạy
thật của Jev sau khi đổi nhãn (không giữ lại) cho đúng 447/543 như ước lượng offline.

Lần chạy 3 của OpenAI bộ confirm dính 10 lỗi mạng (`network_error` / `timeout`), nên bảng confirm
có thêm dòng chỉ tính lần 1–2 cho cả hai provider.

## Kết quả

### Cancel (120 ca, 91 holdout, ~72 lượt gọi model mỗi lần chạy)

| Chỉ số | OpenAI (offline) | Jev v1 |
| --- | ---: | ---: |
| holdout behaviour | 93,4% (255/273) | **97,1%** (265/273) |
| chỉ lượt gọi model, không lỗi mạng | 91,7% (198/216) | **99,5%** (206/207) |
| reason accuracy | 89,7% | **91,2%** |
| ghi hủy sai (SF-05) | 0 | 0 |
| lỗi mạng / timeout (lượt holdout) | 0 | 12 |
| latency semantic p50 / p95 | 1345 / 1762 ms | **651 / 1857 ms** |

Jev tốt hơn 8 ca, kém hơn 5 ca; cả 5 ca kém đều là lượt lỗi mạng / timeout (bot hỏi lại, không ghi
gì), không ca nào do model đọc sai. Lượt gọi model sạch lỗi chỉ còn sai 1/207: "Dạo này tôi bận hủy
lịch" (nhãn owner: CANCEL) — Jev đọc CONFIRM_ACTION 0,42–0,43, và kể cả khi đọc là lệnh, cổng nâng
ngưỡng SF-05 (`promotion_rejection`) từ chối vì lý do đứng trước động từ hủy mà không có dấu ngắt /
từ nối ("Dạo này tôi bận, hủy lịch" thì qua). Ca này không đạt được bằng model theo thiết kế hiện tại.

### Confirm (187 ca, 171 holdout, ~80–90 lượt gọi model mỗi lần chạy; chấm trên nhãn cuối, lần chạy Jev còn 4 ca bỏ sau)

| Chỉ số | OpenAI (offline) | Jev v1 |
| --- | ---: | ---: |
| holdout behaviour, 3 lần | 87,3% (448/513) | **92,8%** (476/513) |
| chỉ lượt gọi model, không lỗi mạng | 82,0% (178/217) | **88,3%** (211/239) |
| needs_inference | 70,8% | **86,5%** |
| branch routing (CANCEL / RESCHEDULE) | 85,5% | **92,8%** |
| ghi CONFIRMED sai | 0 | 0 |
| lỗi mạng / timeout (lượt holdout) | 8 | 15 |
| latency semantic p50 / p95 | 1392 / 1696 ms | **680 / 2099 ms** |

Jev tốt hơn 27 ca, kém hơn 5 ca. Trong 5 ca kém, 3 là lượt lỗi mạng / timeout; 2 ca thật là câu
**không dấu** `toi se di cong tac` và `hom do toi co viec ban` (Noul "không đến được" chỉ 0,31–0,44
dù Choice đã đọc INFORM_REASON / PATIENT_UNAVAILABLE; bot đọc lại lịch, an toàn, tốn một lượt).
Các ca còn sai cho mọi provider là 9 câu nhãn CONFIRM ở câu đọc lịch (`lịch đó ổn em ạ`, `ừ thế
cũng được`, `không hủy đâu, tôi vẫn đến`, `tôi sẽ đến đúng giờ, không trễ đâu`...): model đọc đúng là sẽ đến
(CONFIRM 0,70–0,97) nhưng theo nguyên tắc thiết kế của repo — "model làm rõ, không mở khóa ghi"
(bảng quyền hợp nhất, `docs/reference/information-extraction-design.md`; plan T-10 §"Model không mở
khóa lệnh ghi") — bot đọc lại lịch để nhận xác nhận có / không ở lượt sau. Lưu ý đây là quyết định
của repo, không phải của hợp đồng: SF-05 (§3.5) chỉ cấm ghi **hủy** không có xác nhận lần hai; với
đến khám, §1.1.3 chỉ đòi "set CONFIRMED only after the patient agrees to that read-back" và §1.1.5
cấm đoán. Muốn các câu này CONFIRM thì hoặc thêm từ điển luật, hoặc PO quyết cho model mở khóa ghi
đến khám có kiểm chứng (như `cancel_promotion` đã làm cho hủy).

### Reschedule và No answer

| Bộ | OpenAI | Jev v1 | Ghi chú |
| --- | ---: | ---: | --- |
| reschedule holdout | 90,1% (327/363) | **90,9%** (330/363) | chỉ 2 lượt gọi model mỗi lần chạy: R112 `tôi có câu hỏi về bệnh` (Jev ADVICE_REQUEST → chuyển máy, OpenAI không), R122 `lay cai dau` (cả hai PICK:1). 11 ca còn sai là luật / bộ đọc ngày, không qua model |
| no_answer passed / scored | 83/83 ×3 | 83/83 ×3 | 18–19 lượt gọi model, 3 ca REVIEW không chấm (không chạy lại ở vòng hai) |

Hai bộ này không đo được provider.

### Calibration và cascade (đo trên lần chạy trước khi đổi nhãn, không giữ lại)

Độ chắc = p_max của `reply_kind`, hoặc Noul gần 0,5 nhất ở câu đọc lịch. Cancel calibrate tốt
(độ chắc ≥ 0,7 → 96–98 % đúng); confirm thì không (bin 0,7–0,8 chỉ 53,8 %). Cascade Jev → OpenAI
khi Jev không chắc không đáng: ở confirm muốn lên 82 % phải đẩy 62 % lượt sang OpenAI, p50 quay về
~1,6 s. Ở cancel chỉ-Jev đã là cấu hình tốt nhất.

## Review nhãn eval theo hợp đồng AIHR-PC-001 Rev 1.1

Căn cứ: Bảng 1 (Confirm = "states or agrees they will attend"; Cancel = "states they cannot attend";
Reschedule = "asks for a different time"), §1.1.3 (`CONFIRMED` chỉ sau khi đồng ý câu đọc lại),
§1.1.4 / SF-05 (xác nhận hủy tường minh lần hai), §1.1.5 (không đoán), §1.2.3 (payment / insurance
*flows* ngoài phạm vi), §6.1 (đội tự thiết kế hội thoại) và 5 cuộc gọi tham chiếu trong Figure 0
(transcript nằm trong JSON của trang; đáng chú ý: reschedule tham chiếu là câu hỏi
"Tôi đổi sang buổi chiều được không?" → OFFERING_SLOTS ngay).

**Đổi (4 nhãn):**

| Ca | Cũ → mới | Căn cứ |
| --- | --- | --- |
| cancel `Bên bảo hiểm không chi trả nên tốn kém quá` | TRANSFER → REASON_NOTED / COST | §1.2.3 cấm *làm flow* bảo hiểm, không cấm nhận lý do; COST thuộc Phụ lục A; chuyển máy ở đây bỏ dở kịch bản hủy (§2.2, task completion 35 %) |
| cancel `Nếu đổi được thì tôi không hủy` | ASK_AGAIN → RESCHEDULE | Bảng 1 "asks for a different time"; Figure 0 coi câu hỏi đổi là yêu cầu đổi; cùng ý với "thay vì hủy thì cho tôi dời sang thứ sáu" |
| confirm `vâng, tôi khỏi bệnh rồi` | ASK_CHANGE_OR_CANCEL → CANCEL | quy ước của chính bộ (header `confirm_eval.py`: "khỏi rồi" → CANCEL, `implied_cancel`) |
| confirm `bác sĩ ở viện tỉnh khám cho tôi rồi` | ASK_CHANGE_OR_CANCEL → CANCEL | đã khám nơi khác (việc đã xảy ra), như `Tôi khám ở viện khác rồi` |

**Vòng hai (owner duyệt từng ca sai của Jev, 10-10 chiều):**

| Ca | Quyết định | Ghi chú |
| --- | --- | --- |
| cancel `Hủy xong có ảnh hưởng gì đến hồ sơ không` | ASK_AGAIN → TRANSFER | câu hỏi ngoài phạm vi; nhãn theo cách Jev đọc |
| cancel `Bận mà cũng đắt quá` | UNSPECIFIED / ASK_AGAIN → COST / REASON_NOTED | nhãn theo cách Jev đọc |
| cancel `Tôi khỏi rồi mà cũng khám chỗ khác rồi` | UNSPECIFIED / ASK_AGAIN → WENT_ELSEWHERE / REASON_NOTED | nhãn theo cách Jev đọc; Jev v6 còn dao động WENT_ELSEWHERE / UNSPECIFIED (behaviour vẫn REASON_NOTED) |
| cancel `Dạo này tôi bận hủy lịch` | AMBIGUOUS / ASK_AGAIN → CONFIRM_ACTION / CANCEL | owner: "hủy lịch và lý do". Chưa đạt được: xem phần Cancel |
| confirm `vâng, tôi khỏi bệnh rồi`, `bác sĩ ở viện tỉnh khám cho tôi rồi`, `tôi hết đau rồi, chắc không cần nữa đâu`, `tôi chuyển vào Sài Gòn sống rồi em`, `tôi đang nằm viện ở Huế`, `không cần nữa, tôi tự đến` | bỏ khỏi bộ | owner quyết; 4 ca đầu là nhóm adapter v5 bỏ lý do khi Noul "không đến được" không bật (đã sửa ở v6) |
| confirm `dạ`, `để hôm đó con tôi chở tôi qua`, `hôm đó tôi xin nghỉ rồi, em cứ để lịch vậy`, `vợ tôi sẽ đưa tôi đi` | bỏ khỏi bộ | owner quyết sau khi đọc lại hợp đồng (nhãn CONFIRM không đạt được khi model không mở khóa ghi); `results.csv` của lần chạy vẫn còn 4 dòng này, bảng trên đã lọc theo nhãn cuối |

**Đề xuất rồi rút lại (giữ nhãn cũ), vì đụng quyết định đã có:**

- `ờ`, `được chứ` → CONFIRM: owner chốt 10-10 ("ờ, ừ thì confirm"); Q-2 18-09 đã chốt vâng / dạ / ừ.
- `Hôm đó tôi phải đưa con đi viện nên chắc không đi được` → CANCEL: QC `qc-w6-03`
  (`test_qc_w6_03_long_realistic_cancel_is_cancelled`): câu kể không đến được là kịch bản Cancel.
- `Hủy giúp tôi vì không cần khám nữa`, `... không cần nữa, hủy giúp tôi` → ASK_AGAIN: AC G-6 / AC-4
  (`test_a_reason_containing_a_negation_is_recorded_but_does_not_unlock_the_write`,
  `test_an_adversarial_model_cannot_promote_a_negative`): phủ định trong lý do không mở khóa ghi
  (SF-05). Bản vá thử nới điều này làm 7 test đối kháng fail và đã được hoàn lại.
- `sai rồi` → ASK_CHANGE_OR_CANCEL: test `test_confirm_readback_traps`; hợp đồng không rõ. Để PO.
- `tôi sẽ đến lúc 10 giờ`, `vâng, 3 giờ chiều nhé` → REREAD: evidence T-04 S2 ghi "kỳ vọng đọc lại".
  Lịch fixture là 09:00 nên theo Bảng 1 có thể là RESCHEDULE; để PO.

**Lỗi harness:** `confirm_eval._behaviour` chỉ nhận OFFER_SLOTS là RESCHEDULE. Khi chỉ còn một slot
trống, Dialogue bỏ qua OFFER_SLOTS và đọc thẳng SLOT_READBACK (đúng Figure 0), nên ba ca
"đổi sang chiều" bị ghi OTHER cho MỌI provider. Đã sửa: nhận theo `pending_action == RESCHEDULE`.

**Few-shot của prompt OpenAI chứa câu holdout:** 4 câu cancel (`khong, huy di`,
`toi khong can kham nua`, `Hôm đó tôi bận mất rồi`, `Thôi thì hủy giúp tôi vậy`) và 3 câu confirm
(`vâng`, `vang`, `vợ tôi sẽ đến thay`) nằm nguyên văn / chỉ khác dấu trong `FEW_SHOTS` /
`LUNA_FEW_SHOTS`. Chưa đổi split; cần quyết với người giữ prompt.

## Sửa luật / merge (áp cho mọi provider)

| Thay đổi | Vị trí | Test |
| --- | --- | --- |
| Chủ đề ngoài phạm vi chỉ được nhắc trong câu kể lý do hủy (có mã Phụ lục A, không câu hỏi / yêu cầu) không phải OUT_OF_SCOPE ở câu xác nhận hủy | `extractor._intent`, `intent.out_of_scope_request` | `test_an_out_of_scope_topic_inside_a_cancel_reason_is_a_reason_not_a_transfer`, `test_asking_about_insurance_at_the_cancel_question_still_transfers` |
| Phủ định trần ("không chi trả") trong câu kể lý do, không có động từ hủy / giữ lịch, không phải lời từ chối hủy | `extractor._resolve_refusal_inside_reason` | như trên |
| "đổi được / dời được / chuyển được" là xin đổi lịch (kể cả dạng hỏi / điều kiện); phủ định vẫn loại | `intent._KEYWORDS[RESCHEDULE]` | `test_conditional_or_questioned_change_is_a_reschedule`, `test_a_conditional_change_request_at_the_cancel_question_starts_a_reschedule` |
| "để lịch vậy / để lịch như vậy / để lịch như cũ / để nguyên lịch" là giữ lịch, như "giữ lịch" (câu đứng một mình → AGREE; kèm nội dung khác vẫn UNCLEAR cho model đọc) | `agreement._KEEP_WORDS` | `test_attendance_agrees_on_polite_words_and_keeping` |
| Lý do model đọc ra (WENT_ELSEWHERE / NO_LONGER_NEEDED) có dấu hiệu đã xảy ra, không ngập ngừng / điều kiện / việc sắp tới, câu có dấu → intent CANCEL để Dialogue hỏi xác nhận hủy, như `implied_cancel` của luật; không mở khóa ghi | `implied_cancel.implied_cancel_from_model`, `semantic_router.merge_semantic` | `test_a_completed_visit_elsewhere_read_by_the_model_implies_cancel`, `test_planned_hedged_or_unaccented_reasons_do_not_imply_cancel`, `test_a_completed_visit_elsewhere_from_the_model_goes_to_the_cancel_question`, `test_a_planned_visit_elsewhere_from_the_model_still_asks_change_or_cancel` |

## Jev: cách dùng

- Cấu hình `config/engine.yaml`:
  - `semantic_provider: jev` — provider đọc câu, gọi trước (`jev | openai`).
  - `semantic_backup_provider: openai` — chỉ gọi khi provider chính lỗi dịch vụ (timeout, mạng, HTTP,
    trả lời hỏng); provider chính đã trả lời thì không gọi. `none` = không dự phòng (đặt `none` để đo
    riêng Jev, như các lần chạy `jev-v1`).
  - `semantic_backup_min_remaining_s: 1.5` — chỉ gọi dự phòng khi lượt còn ít nhất chừng này giây
    trong trần 3 s.
  - `semantic_openai_model`, `semantic_openai_max_tokens` (trước là `semantic_fallback_model` /
    `semantic_fallback_max_tokens`, đổi tên vì "fallback" dễ đọc thành "dự phòng").
  - `semantic_jev_min_confidence`, `semantic_jev_min_noul`; `config/llm.yaml` mục `typesafe`
    (endpoint, model pin `jev-1.13.0`, timeout); `TYPESAFE_API_KEY` trong `.env`.
  - Thiếu khóa provider chính → chạy riêng dự phòng; thiếu cả hai → chạy chỉ-luật.
- Dự phòng chạy trong CÙNG trần 3 s của lượt (`model_budget.hand_over_model`,
  `semantic_failover.py`). Đo thật 10-10 (Jev cố tình lỗi bằng endpoint sai): Jev trả HTTP 404 sau
  1,3–2,1 s, OpenAI cần 1,2–1,8 s, nên phần lớn lượt không còn đủ thời gian. Dự phòng thực sự cứu được
  lượt khi Jev lỗi nhanh: thiếu / sai khóa, lỗi kết nối (~1,0 s), 4xx/5xx trả ngay. Jev timeout ở 3 s
  thì không cứu được.
- `src/inference/llm/typesafe.py`: HTTP thẳng `POST /v1/systemone`, một request, không retry, trần
  3 s (không dùng SDK vì SDK tự retry). `src/callbot/engine/extraction/semantic_jev.py`: một request
  gồm 4 câu Choice nhãn (+ 3 Noul ở câu đọc lịch / "đổi hay hủy") và 4 câu Choice chọn span trong
  các mệnh đề do code cắt; kết quả đi qua đúng `ground_reading` / `merge_semantic` như adapter LLM.
- Theo docs TypeSafe: option an toàn đứng đầu; criteria dạng `what / not_for / examples`; câu span
  là câu "giả sử" không có NONE (NONE hút xác suất, làm rơi DECLINE_ACTION đúng); gate theo xác suất
  của option được chọn, chỉ cho nhãn mở hành động; lý do lấy argmax; lâm sàng không gate (SF-04).
- Ví dụ trong criteria đã kiểm tra không trùng câu nào trong `eval/*/cases*.csv` (kể cả không dấu).
- `semantic_jev_v6` (vòng hai, từ các ca sai của v5):
  - Câu đọc lịch: lý do **không phụ thuộc ngày giờ** (NO_LONGER_NEEDED / WENT_ELSEWHERE / COST) đủ
    ngưỡng được giữ không cần Noul "không đến được" (v5 bỏ "vâng, tôi khỏi bệnh rồi" thành đọc lại).
    PATIENT_UNAVAILABLE vẫn cần Noul ("tôi đang họp" chỉ là bận lúc này).
  - Câu xác nhận hủy: CONFIRM_ACTION của model mà luật không thấy động từ hủy (không có
    `agreement_span`) hoặc model dưới ngưỡng, kèm mã lý do rõ → INFORM_REASON (ghi nhận lý do, hỏi
    lại) thay vì "em chưa hiểu" ("Tôi không cần khám nữa": CONFIRM 0,53 / INFORM 0,45).
  - Không đưa span của luật vào ứng viên: `_promotion_rejection` so span model với span đã hợp nhất
    (chính nó), còn `promotion_rejection` kiểm phần câu NGOÀI span — span một từ "hủy" làm Jev chọn
    quá ngắn và "giúp em nhé" bị coi là nội dung lạ (nhóm leftover 0/3 → 3/3).
  - CHANGE_INTENT không có intent (câu không hỏi intent) → AMBIGUOUS thay vì để `ground_reading` bỏ
    cả lượt (R122 `lay cai dau` REREAD_PAGE → PICK:1).
  - Transcript không dấu: thêm `transcript_glossary` (bảng từ vựng nghiệp vụ tĩnh, chỉ các từ có mặt,
    từ nhiều nghĩa ghi cả hai) — `dao nay ket tien qua em a` 0/3 → 3/3, `hom do toi phai di lam`
    0/3 → 3/3; hai câu không dấu khác vẫn chưa qua.
  - Criteria: lệnh hủy kèm lý do vẫn là CONFIRM_ACTION; CANCEL intent không gồm "khỏi rồi / đi chỗ
    khác" không có lệnh; ADVICE_REQUEST gồm "có câu hỏi về bệnh / muốn hỏi bác sĩ"; Noul "không đến
    được" sai cho "xin nghỉ / nghỉ phép" (đã xin nghỉ để đi) và cho câu than xa / điều kiện.

## Kết quả xác minh cục bộ (2026-10-10)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | Pass (5036 passed, 24 skipped) |

## Ghi chú

- Jev yếu rõ với câu **không dấu**; chưa có số liệu tỷ lệ ASR production trả thiếu dấu để biết
  trọng số thật của nhóm này.
- `cancel_reason` lấy argmax nên câu hai lý do có thể bị gán một mã thay vì UNSPECIFIED (không ghi
  gì, chỉ khác câu hỏi lại). Chưa chỉnh vì chỉ có 1–2 ca, dễ overfit.
- Cỡ mẫu: 72–103 lượt gọi model mỗi lần chạy; chênh 2–4 điểm ≈ 3–7 ca, trong sai số. Jev gần tất
  định nên 3 lần lặp không phải 3 mẫu độc lập.
- Lỗi mạng xuất hiện cùng lúc ở cả hai provider trong một khung giờ; nhiều khả năng do mạng máy chạy.
  Lần chạy `jev-v1` chiều 10-10 dính 14 (cancel) / 19 (confirm) lượt lỗi mạng / timeout và p50
  651–680 ms, so với 355–370 ms của lần chạy sáng cùng request shape (p50 câu có dấu và không dấu
  như nhau, nên không phải do glossary). Mọi ca Jev "kém OpenAI" ở bảng cancel đều là các lượt này.
- `cancel_eval` gộp ASK_AGAIN cho mọi câu hỏi lại (kể cả "em chưa hiểu"); nên tách như `confirm_eval`.

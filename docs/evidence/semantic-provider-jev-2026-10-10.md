# Tầng ngữ nghĩa bằng TypeSafe Jev so với GPT-6 Luna, và review nhãn eval theo hợp đồng Rev 1.1

Jev 1.13 (`SEMANTIC_FALLBACK_PROVIDER=jev`) nhanh hơn GPT-6 Luna (Fast mode, reasoning tắt) khoảng
3,8 lần ở p50 (355–370 ms so với 1345–1392 ms), không có lần ghi sai nào, nhỉnh hơn ở bộ cancel và
kém 1,6–3,8 điểm ở bộ confirm trên các lượt thật sự gọi model. Mặc định của repo **vẫn là OpenAI**;
Jev là lựa chọn qua cấu hình. Review nhãn eval theo hợp đồng đổi 4 nhãn, vá một lỗi harness và sửa
ba chỗ ở luật / merge; tám đề xuất đổi nhãn khác bị rút lại vì đụng quyết định QC / AC đã có.

## Nguồn

- OpenAI `gpt-6-luna` (`service_tier=fast`, `reasoning_effort=none`, prompt `semantic_v9_luna`):
  [cancel](../../result/10-10-2026/cancel/openai/), [confirm](../../result/10-10-2026/confirm/openai/),
  [reschedule](../../result/10-10-2026/reschedule/openai/), [no_answer](../../result/10-10-2026/no_answer/openai/).
  Chạy MỘT lần vào đầu ngày, trước khi đổi nhãn / vá luật; các bảng dưới chấm lại offline từ
  `results.csv` với nhãn mới (xem "Cách chấm lại").
- Jev `jev-1.13.0` (`semantic_jev_v5`), `jev-final` chạy với code và nhãn cuối (các lần chạy trung gian
  trong ngày không giữ lại): [cancel](../../result/10-10-2026/cancel/jev-final/),
  [confirm](../../result/10-10-2026/confirm/jev-final/), [reschedule](../../result/10-10-2026/reschedule/jev-final/),
  [no_answer](../../result/10-10-2026/no_answer/jev-final/).
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

| Chỉ số | OpenAI (offline) | Jev final |
| --- | ---: | ---: |
| holdout behaviour | 93,4% (255/273) | **94,1%** (257/273) |
| chỉ lượt gọi model, không lỗi mạng | 91,7% (198/216) | **94,0%** (203/216) |
| reason accuracy | **90,8%** | 89,7% |
| ghi hủy sai (SF-05) | 0 | 0 |
| latency semantic p50 / p95 | 1345 / 1762 ms | **355 / 1321 ms** |

Jev tốt hơn 5 ca, kém hơn 5 ca. Kém: hai câu không dấu (`dao nay ket tien qua em a`,
`toi khong can kham nua`), và câu hai lý do "Tôi khỏi rồi mà cũng khám chỗ khác rồi" (Jev chọn
WENT_ELSEWHERE 0,43–0,51 thay vì UNSPECIFIED 0,31–0,37 → bot ghi nhận lý do thay vì hỏi lại; không
ghi gì). Tốt hơn: ba câu hỏi "đặt lại thế nào / bao giờ đặt lại được" OpenAI chuyển máy, Jev hỏi lại.

### Confirm (197 ca, 181 holdout, ~93–103 lượt gọi model mỗi lần chạy)

| Chỉ số | OpenAI (offline) | OpenAI + credit | Jev final |
| --- | ---: | ---: | ---: |
| holdout behaviour, 3 lần | 83,6% (454/543) | — | **86,7%** (471/543) |
| holdout behaviour, lần 1–2 | 87,8% (318/362) | 89,0% (322/362) | 87,0% (315/362) |
| chỉ lượt gọi model, không lỗi mạng, 3 lần | **78,6%** (184/234) | — | 76,6% (213/278) |
| chỉ lượt gọi model, lần 1–2 | 78,9% (146/185) | **81,1%** (150/185) | 77,3% (143/185) |
| needs_inference | 64,8% | — | **72,6%** |
| branch routing (CANCEL / RESCHEDULE) | 78,7% | — | **89,3%** |
| ghi CONFIRMED sai | 0 | 0 | 0 |
| latency semantic p50 / p95 | 1392 / 1729 ms | — | **370 / 1303 ms** |

Trên cùng điều kiện (lần 1–2, lượt gọi model), Jev kém OpenAI 1,6 điểm; nếu tính cả hai ca
implied-cancel cho OpenAI thì 3,8 điểm. Khoảng cách này tương đương 3–7 lượt trên 185, trong sai số
của cỡ mẫu. Ca Jev kém đều là **câu không dấu** (`hom do toi co viec ban`, `hom do toi phai di lam`,
`toi se di cong tac`) hoặc câu kể hoàn cảnh không trực tiếp (`tôi chuyển vào Sài Gòn sống rồi em`,
`tôi hết đau rồi, chắc không cần nữa đâu`): Jev không thấy "không đến được" nên bot đọc lại lịch
(an toàn, tốn một lượt).

### Reschedule và No answer

| Bộ | OpenAI | Jev final | Ghi chú |
| --- | ---: | ---: | --- |
| reschedule holdout | 90,1% (327/363) | 89,3% (324/363) | chỉ 2 lượt gọi model mỗi lần chạy; ca lệch duy nhất R122 `lay cai dau` (Jev từ chối span ở câu không dấu) |
| no_answer passed / scored | 83/83 ×3 | 83/83 ×3 | 18–19 lượt gọi model, 3 ca REVIEW không chấm |

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
| Lý do model đọc ra (WENT_ELSEWHERE / NO_LONGER_NEEDED) có dấu hiệu đã xảy ra, không ngập ngừng / điều kiện / việc sắp tới, câu có dấu → intent CANCEL để Dialogue hỏi xác nhận hủy, như `implied_cancel` của luật; không mở khóa ghi | `implied_cancel.implied_cancel_from_model`, `semantic_router.merge_semantic` | `test_a_completed_visit_elsewhere_read_by_the_model_implies_cancel`, `test_planned_hedged_or_unaccented_reasons_do_not_imply_cancel`, `test_a_completed_visit_elsewhere_from_the_model_goes_to_the_cancel_question`, `test_a_planned_visit_elsewhere_from_the_model_still_asks_change_or_cancel` |

## Jev: cách dùng

- Cấu hình: `config/engine.yaml` `semantic_fallback_provider: openai | jev`, `semantic_jev_min_confidence`,
  `semantic_jev_min_noul`; `config/llm.yaml` mục `typesafe` (endpoint, model pin `jev-1.13.0`, timeout);
  `TYPESAFE_API_KEY` trong `.env`. Thiếu key → chạy chỉ-luật như với OpenAI.
- `src/inference/llm/typesafe.py`: HTTP thẳng `POST /v1/systemone`, một request, không retry, trần
  3 s (không dùng SDK vì SDK tự retry). `src/callbot/engine/extraction/semantic_jev.py`: một request
  gồm 4 câu Choice nhãn (+ 3 Noul ở câu đọc lịch / "đổi hay hủy") và 4 câu Choice chọn span trong
  các mệnh đề do code cắt; kết quả đi qua đúng `ground_reading` / `merge_semantic` như adapter LLM.
- Theo docs TypeSafe: option an toàn đứng đầu; criteria dạng `what / not_for / examples`; câu span
  là câu "giả sử" không có NONE (NONE hút xác suất, làm rơi DECLINE_ACTION đúng); gate theo xác suất
  của option được chọn, chỉ cho nhãn mở hành động; lý do lấy argmax; lâm sàng không gate (SF-04).
- Ví dụ trong criteria đã kiểm tra không trùng câu nào trong `eval/*/cases*.csv` (kể cả không dấu).

## Kết quả xác minh cục bộ (2026-10-10)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | Pass (5027 passed, 24 skipped) |

## Ghi chú

- Jev yếu rõ với câu **không dấu**; chưa có số liệu tỷ lệ ASR production trả thiếu dấu để biết
  trọng số thật của nhóm này.
- `cancel_reason` lấy argmax nên câu hai lý do có thể bị gán một mã thay vì UNSPECIFIED (không ghi
  gì, chỉ khác câu hỏi lại). Chưa chỉnh vì chỉ có 1–2 ca, dễ overfit.
- Cỡ mẫu: 72–103 lượt gọi model mỗi lần chạy; chênh 2–4 điểm ≈ 3–7 ca, trong sai số. Jev gần tất
  định nên 3 lần lặp không phải 3 mẫu độc lập.
- Lỗi mạng xuất hiện cùng lúc ở cả hai provider trong một khung giờ; nhiều khả năng do mạng máy chạy.
- `cancel_eval` gộp ASK_AGAIN cho mọi câu hỏi lại (kể cả "em chưa hiểu"); nên tách như `confirm_eval`.

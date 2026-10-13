# Slot filling họ tên — LLM gateway và few-shot

Slot filling họ tên bổ sung cho tầng luật khi bot đang hỏi tên (`ASK_NAME`). Thay cho NER
trước đây (`NameNER`, prompt `name_ner_v3`), model nhận **câu hỏi bot đang chờ** cùng câu
trả lời hiện tại của khách, nên hiểu được câu trả lời ngắn hoặc nói vòng theo đúng ngữ cảnh.

`InformationExtractor` chỉ gọi slot filling nếu luật chưa hiểu (`NO_SIGNAL`) hoặc ứng viên
còn lời nói chưa tách được (`UNRESOLVED_BOUNDARY`), và không có intent/clinical ưu tiên.
Ứng viên có lời đệm không được luật chấp nhận làm tên. Tên sạch đã được luật nhận thì
không gọi model. Verifier vẫn quyết định danh tính; slot filling lỗi/tắt thì hỏi lại thay
vì dùng ứng viên đáng ngờ. Ngày sinh vẫn dùng luật và kiểm tra ngày hợp lệ, không qua model.

Slot `full_name` là họ tên **người gọi tự nhận**. Chưa hỗ trợ đặt lịch hộ hay slot tên bệnh
nhân riêng: câu chỉ nhắc người thân vẫn trả `null`.

Các lỗi ranh giới tên, lời gọi/đáp máy và bộ 100 ca research nằm trong
[rà soát họ tên và câu chào](identity-greeting-audit.md). Bộ ca ghi rõ cả lỗi còn tồn tại;
không phải benchmark chất lượng model.

Xem [LLM gateway](llm-gateway.md) để chọn OpenAI, Gemini, Groq hoặc OpenRouter,
model mặc định của từng provider và cấu hình token budget.

## Tổ chức mã nguồn

- `extraction/fallback.py`: protocol `FallbackExtractor` và kiểm tra span chung. `full_name()`
  nhận thêm hai tham số keyword `question_id` và `bot_question`.
- `callbot/engine/extraction/name_slot_filling.py`: `NameSlotFiller`, gọi gateway, kiểm tra
  tên/span và chuyển thành `Field`.
- `inference/llm/prompt/name_slot_filling.py`: prompt `name_slot_filling_v4`, quy tắc + 18 ví dụ
  (`input -> output`) trong một system message, tập trung vào ranh giới tên, tự sửa, người thân và
  tên chỉ có trong câu hỏi bot.
- `TurnContext.question_text`: nội dung câu hỏi đang chờ, chỉ có ở `ASK_NAME`.
  `build_turn_context()` lấy từ `CallContext.question.text`.
- `inference/llm/gateway.py`: `LLMGateway` và `create_gateway()`, chọn provider và kiểm tra JSON trả về.
- `inference/llm/providers/`: adapter OpenAI, Gemini, Groq và OpenRouter.
- `inference/llm/config.py`: cấu hình API key, model, timeout và token budget.
- `EngineSettings.name_fallback_provider`: lựa chọn bật/tắt slot filling họ tên.

`src/inference/` ngang cấp `src/callbot/`, gom adapter LLM, ASR và TTS nhưng giữ contract
riêng cho từng capability. Module dialogue chọn lời thoại theo luật và câu mẫu, không gọi LLM.

## Bật và tắt

Cấu hình giữ nguyên tên biến `NAME_FALLBACK_*`. Mặc định `NAME_FALLBACK_PROVIDER=none`.
Để bật, cấu hình môi trường hoặc `.env`:

```dotenv
NAME_FALLBACK_PROVIDER=openai
NAME_FALLBACK_MODEL=gpt-4o-mini
NAME_FALLBACK_TIMEOUT_S=3.0
OPENAI_API_KEY=<key>
```

Với `gpt-6-luna` trên demo, đặt `NAME_FALLBACK_TIMEOUT_S=6.0` để các lượt phản hồi
chậm hơn 3 giây không bị hỏi lại dù model vẫn có thể trả tên hợp lệ.

Khởi động lại ứng dụng sau khi thay cấu hình. Thiếu key khi bật là lỗi khởi tạo;
tắt không cần key. Các API key dùng `SecretStr`.

Workflow deploy nhận API key tương ứng từ GitHub Secret; các biến `NAME_FALLBACK_*`
từ GitHub Variables. Docker Compose truyền các biến tới bot. Tắt/rollback bằng
`NAME_FALLBACK_PROVIDER=none` rồi khởi động lại/deploy lại.

## Input của model

Lượt user cuối cùng là JSON gồm đúng ba trường:

```json
{
  "question_id": "ASK_NAME",
  "bot_question": "Dạ, anh chị vui lòng cho em xin họ và tên đầy đủ ạ.",
  "customer_answer": "À ừ thì là Nguyễn Văn A nhé em"
}
```

- `bot_question` là câu hỏi nghiệp vụ đang chờ (`CallContext.question.text`): câu chào
  mở đầu, câu hỏi lại tên, hoặc câu xin tên sau khi đã có ngày sinh. Lời nhắc im lặng và
  câu xin nhắc lại không thay câu hỏi này, nên model vẫn nhận câu hỏi nghiệp vụ gốc.
- Nếu đang ở `ASK_NAME` nhưng phiên không có nội dung câu hỏi, gửi `bot_question: null`
  và model hiểu theo `question_id`. Không tự dựng câu hỏi rồi coi như lời bot đã nói.
- Không gửi lịch sử hội thoại, hồ sơ bệnh nhân, dữ liệu đối chiếu hay lịch hẹn.

Phiên đã lưu trước thay đổi này vẫn có `question.text`, nên không cần migration.

## Request và kiểm tra output

Prompt v2 dành cho tác vụ trích xuất ngắn: quy tắc chọn tên theo thứ tự, chỉ chép một đoạn
liền nhau gồm 2–6 từ, không sinh giải thích. Ví dụ dùng câu hỏi ngắn hoặc `null` để giảm
nội dung lặp; lượt user cuối vẫn giữ nguyên câu hỏi bot thực tế. JSON được serialize gọn,
giữ tiếng Việt. Không thay schema hay tự đổi model của provider.

So với v1, cùng input rỗng và `bot_question=null`, tổng nội dung message giảm từ 5.979 xuống
3.195 ký tự (46,6%); số message giảm từ 42 xuống 26. Đây là phép đo kích thước prompt,
không phải mức giảm token, chi phí hay latency đo được trên API.

Prompt v4 (12/10/2026) giữ nguyên quy tắc v3, chuyển 18 ví dụ vào trong system (mỗi dòng
`input -> output`) nên request chỉ còn `[system, user]`. Lý do: prompt caching của GPT-6 cần tiền
tố ổn định tối thiểu 1024 token tính đến cuối developer message đầu; system v3 một mình dưới
ngưỡng nên transcript mới không trúng cache (đo 12/10: `cached_tokens` 0/1703), còn v4 cache được
gần toàn bộ. Các ví dụ trùng nguyên văn `eval/identity/cases.csv` (ID049, ID062, ID063) thay
bằng câu cùng dạng để bộ eval đo câu chưa thấy. Schema gửi model bỏ `title` tự sinh
(`compact_json_schema`). Số liệu trước / sau: [evidence](../evidence/luna-prompt-v10-2026-10-12.md).

Model mặc định là `gpt-4o-mini` với temperature 0; khi chọn `gpt-6-luna` hoặc `gpt-6-sol`,
adapter dùng `reasoning_effort=none` để giảm độ trễ cuộc gọi và vẫn gửi `temperature=0`
(API chấp nhận khi reasoning tắt, kiểm 12/10/2026); `gpt-6-astra` không tắt được reasoning
nên bỏ `temperature`. Giới hạn output mặc định 200 token, `store=false` cho OpenAI và JSON Schema
strict, giữ nguyên dạng output của NER:

```json
{"full_name": "Nguyễn Văn A", "span": "Nguyễn Văn A"}
```

Hai trường bắt buộc, chỉ nhận chuỗi hoặc cùng `null`, không nhận trường thừa.
`NameSlotFiller` tự chặn câu hỏi khác `ASK_NAME` trước khi gọi gateway, kể cả khi được gọi
trực tiếp; trả `Field.skipped()` và ghi trạng thái `skipped_question`.
Model được hướng dẫn chỉ chọn tên tự nhận rõ ràng, trả `null` khi mơ hồ, không chắc
chắn, chỉ nhắc người khác, chỉ lặp lại câu hỏi hoặc gặp chỉ dẫn giả mạo trong câu trả lời.
Tự sửa rõ ràng thì chọn tên cuối cùng. Không thêm dấu hoặc sửa lỗi ASR.

**Câu hỏi bot chỉ là ngữ cảnh.** Sau model, adapter kiểm tra hai trường bằng nhau sau
`clean()`, span xuất hiện trong **câu trả lời của khách** theo ranh giới từ và tên qua được
`valid_name_span()` mà không bị thay đổi thêm. Extractor kiểm tra thêm tên nằm trong vùng
tên được phép (câu gộp tên + ngày sinh chỉ lấy phần ngoài vùng ngày). Tên chỉ có trong câu
hỏi bot bị từ chối. Kết quả hợp lệ dùng `Provenance.FALLBACK`, tên/span đã chuẩn hóa.
Span có thật chỉ chứng minh tên xuất hiện trong câu, không chứng minh model đã chọn đúng
người; phần hiểu ngữ nghĩa vẫn cần đánh giá trên dữ liệu thực tế.

Timeout, lỗi mạng/HTTP, refusal, output bị cắt hoặc output không hợp lệ trả `NONE`.
Policy/Dialogue tiếp tục theo luồng hỏi lại và giới hạn số lần không hiểu hiện có.
Không retry trong cùng lượt. Connect timeout 1 giây; read/write/pool timeout mặc
định 3 giây cho từng thao tác, không phải deadline tổng lượt. HTTP client đóng sau
mỗi request. Replay lượt đã commit dùng kết quả lưu, không gọi model thêm.

Log adapter có các thuộc tính `slot_filling_provider`, `slot_filling_model`,
`slot_filling_prompt_version`, `slot_filling_question_id`, `slot_filling_has_bot_question`,
`slot_filling_status`, `slot_filling_elapsed_ms`, `slot_filling_prompt_tokens`,
`slot_filling_completion_tokens`; không thêm tên, transcript, nội dung câu hỏi, API key,
response body hoặc nội dung exception vào log adapter.

API debug (`/v1/calls`) giữ nhãn nguồn `NER` cho tên từ tuyến sau để không đổi hợp đồng
bên ngoài.

## Kiểm chứng

```powershell
python -m pytest -q tests/engine/extraction/test_name_slot_filling.py tests/eval/test_identity_evaluator.py
make check
```

Test dùng HTTP mock để kiểm tra payload (câu mở đầu, hỏi lại, sau nhắc im lặng, hỏi tên
sau ngày sinh, thiếu nội dung câu hỏi), timeout, lỗi, grounding, tên chỉ có trong câu hỏi
bot, state gating và tên chuẩn hóa đến Verifier qua orchestrator. Fixture test tắt provider
và xóa key bằng biến môi trường để `.env` của developer không kích hoạt request trả phí.

CLI research: `python scripts/identity_eval.py` chạy chỉ luật; thêm `--slot-filling` để gọi
provider đang cấu hình (`--ner` vẫn dùng được như alias) và `--groups` để giới hạn tập ca.
Cột `bot_question` trong `eval/identity/cases.csv` là câu hỏi bot; để trống nghĩa là câu chào
mở đầu inbound. Kết quả lưu ở `result/<dd-mm-yyyy>/identity/slot_filling/`; báo cáo giữ các
cột `ner_*` cũ, thêm `bot_question`, `fallback_method=slot_filling` và `prompt_version`.

Test mock chỉ chứng minh luồng, hợp đồng payload, kiểm tra span và hành vi khi lỗi;
không phải bằng chứng độ chính xác model. Fallback vẫn tắt mặc định.

Tầng luật giữ được tên trong `Nguyễn Văn A tôi không nhớ rõ ngày sinh` dù ASR bỏ dấu phẩy.
Chỉ tách hậu tố đầy đủ nói về ngày sinh; lời phân vân/phủ nhận tên và tên người thân vẫn bị
loại. Bộ discovery chạy chỉ luật sau thay đổi có 91 PASS, 6 FAIL cần fallback và 3 REVIEW;
ID073 đã PASS. Lượt API v2 ngày 24-09 có 96 PASS, 1 FAIL, 3 REVIEW và 11/11 request
completed. So với NER ngày 23-09, tỷ lệ PASS giữ nguyên; ID073 được sửa nhưng ID069
(`Nguyễn Văn A phải không`) từ PASS thành FAIL vì model nhận tên chưa được khẳng định.
Xem [so sánh kết quả và thời gian](../evidence/name-slot-filling-v2-eval.md). Dùng `--output`
riêng khi chạy lại để giữ baseline cũ.

Tham chiếu API: [GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini),
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

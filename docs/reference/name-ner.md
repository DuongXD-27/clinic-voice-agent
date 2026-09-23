# NER tên — LLM gateway và few-shot

NER bổ sung cho tầng luật khi bot đang hỏi tên (`ASK_NAME`). `InformationExtractor`
chỉ gọi NER nếu luật chưa hiểu (`NO_SIGNAL`) hoặc ứng viên còn lời nói chưa tách được
(`UNRESOLVED_BOUNDARY`), và không có intent/clinical ưu tiên. Ứng viên có lời đệm không
được luật chấp nhận làm tên. Tên sạch đã được luật nhận thì không gọi NER. Verifier vẫn
quyết định danh tính; NER lỗi/tắt thì hỏi lại thay vì dùng ứng viên đáng ngờ.

Các lỗi ranh giới tên, lời gọi/đáp máy và bộ 100 ca research nằm trong
[rà soát họ tên và câu chào](identity-greeting-audit.md). Bộ ca ghi rõ cả lỗi còn tồn tại;
không phải benchmark chất lượng model.

Xem [LLM gateway](llm-gateway.md) để chọn OpenAI, Gemini, Groq hoặc OpenRouter,
model mặc định của từng provider và cấu hình token budget.

## Tổ chức mã nguồn

- `extraction/fallback.py`: protocol và kiểm tra span chung cho các phương pháp fallback.
- `callbot/engine/extraction/ner.py`: `NameNER`, gọi gateway, kiểm tra tên/span và chuyển thành `Field`.
- `inference/llm/prompt/ner.py`: prompt `name_ner_v3` và 18 cặp few-shot với tên tổng hợp.
- `inference/llm/gateway.py`: `LLMGateway` và `create_gateway()`, chọn provider và kiểm tra JSON trả về.
- `inference/llm/providers/base.py`: interface `StructuredProvider` và kết quả `StructuredReply` dùng chung.
- `inference/llm/providers/`: adapter OpenAI, Gemini, Groq và OpenRouter.
- `inference/llm/config.py`: cấu hình API key, model, timeout và token budget.
- `EngineSettings.name_fallback_provider`: lựa chọn bật/tắt NER.

`src/inference/` ngang cấp `src/callbot/`, gom adapter LLM, ASR và TTS nhưng giữ contract
riêng cho từng capability. Module dialogue chọn lời thoại theo luật và câu mẫu, không gọi LLM.

## Bật và tắt

Mặc định `NAME_FALLBACK_PROVIDER=none`. Để bật, cấu hình môi trường hoặc `.env`:

```dotenv
NAME_FALLBACK_PROVIDER=openai
NAME_FALLBACK_MODEL=gpt-4o-mini
NAME_FALLBACK_TIMEOUT_S=3.0
OPENAI_API_KEY=<key>
```

Với `gpt-6-luna` trên demo, đặt `NAME_FALLBACK_TIMEOUT_S=6.0` để các lượt phản hồi
chậm hơn 3 giây không bị hỏi lại dù model vẫn có thể trả tên hợp lệ.

Khởi động lại ứng dụng sau khi thay cấu hình. Thiếu key khi bật NER là lỗi khởi tạo;
tắt NER không cần key. Các API key dùng `SecretStr`.

Workflow deploy nhận API key tương ứng từ GitHub Secret; các biến `NAME_FALLBACK_*`
từ GitHub Variables. Docker Compose truyền các biến tới bot. Tắt/rollback bằng
`NAME_FALLBACK_PROVIDER=none` rồi khởi động lại/deploy lại.

## Request và kiểm tra output

Mỗi lần fallback gửi prompt cố định cùng transcript hiện tại; không gửi hồ sơ bệnh
nhân, lịch sử hội thoại hoặc dữ liệu lịch hẹn. Model mặc định là `gpt-4o-mini` với
temperature 0; khi chọn `gpt-6-luna` hoặc `gpt-6-sol`, adapter bỏ `temperature`
và dùng `reasoning_effort=none` để tương thích API và giảm độ trễ cuộc gọi.
Giới hạn output mặc định 200 token, `store=false` cho OpenAI và JSON Schema strict:

```json
{"full_name": "Nguyễn Văn A", "span": "Nguyễn Văn A"}
```

Hai trường bắt buộc, chỉ nhận chuỗi hoặc cùng `null`, không nhận trường thừa.
Model được hướng dẫn chỉ chọn tên tự nhận rõ ràng, trả `null` khi mơ hồ, không chắc
chắn, chỉ nhắc người khác hoặc gặp chỉ dẫn giả mạo trong transcript. Tự sửa rõ ràng
thì chọn tên cuối cùng. Không thêm dấu hoặc sửa lỗi ASR.

Sau model, adapter kiểm tra hai trường bằng nhau sau `clean()`, span xuất hiện
trong transcript theo ranh giới từ và tên qua được `valid_name_span()` mà không
bị thay đổi thêm. Hàm này kiểm tra đoạn tên mô hình đã chọn mà không cắt lại âm
`Nha` ở cuối tên. Kết quả hợp lệ dùng `Provenance.FALLBACK`, tên/span đã chuẩn hóa.
Span có thật chỉ chứng minh tên xuất hiện trong câu, không chứng minh model đã
chọn đúng người; phần hiểu ngữ nghĩa vẫn cần đánh giá trên dữ liệu thực tế.

Timeout, lỗi mạng/HTTP, refusal, output bị cắt hoặc output không hợp lệ trả `NONE`.
Policy/Dialogue tiếp tục theo luồng hỏi lại và giới hạn số lần không hiểu hiện có.
Không retry trong cùng lượt. Connect timeout 1 giây; read/write/pool timeout mặc
định 3 giây cho từng thao tác, không phải deadline tổng lượt. HTTP client đóng sau
mỗi request. Replay lượt đã commit dùng kết quả lưu, không gọi model thêm.

Log adapter có các thuộc tính `ner_provider`, `ner_model`, `ner_prompt_version`, `ner_status`,
`ner_elapsed_ms`, `ner_prompt_tokens`, `ner_completion_tokens`; không thêm tên,
transcript, API key, response body hoặc nội dung exception vào log adapter.

## Kiểm chứng

```powershell
python -m pytest -q tests/engine/extraction/test_ner.py
make check
```

Test dùng HTTP mock để kiểm tra payload, timeout, lỗi, grounding, state gating và
tên chuẩn hóa đến Verifier qua orchestrator. Fixture test tắt provider và xóa key
bằng biến môi trường để `.env` của developer không kích hoạt request trả phí.

CLI research: `python scripts/identity_eval.py` chạy chỉ luật; thêm `--ner` để gọi
provider đang cấu hình và `--groups` để giới hạn tập ca. Probe thật ngày 2026-09-23 bị
HTTP 401 `token_invalidated`, nên chưa có bằng chứng chất lượng model. Test mock
chỉ chứng minh routing, kiểm tra span và hành vi khi lỗi. Fallback vẫn tắt mặc định.

Tham chiếu API: [GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

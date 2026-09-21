# LLM gateway

`src/inference/llm/gateway.py` là điểm gọi chung cho structured generation, hiện dùng cho NER:

```text
NameNER → LLMGateway → OpenAI | Gemini | Groq | OpenRouter
```

Gateway chọn đúng một provider; không retry, không tự failover. Prompt và provider
không phụ thuộc vào `callbot`. Gateway kiểm tra cú pháp JSON; caller chịu trách nhiệm
validate schema và nghiệp vụ. NER vẫn kiểm tra tên/span sau khi nhận kết quả.

## Cấu hình NER

| NAME_FALLBACK_PROVIDER | Model mặc định | API key |
|---|---|---|
| `none` | Không gọi model | Không cần |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `gemini` | `gemini-2.5-flash` | `GEMINI_API_KEY` |
| `groq` | `openai/gpt-oss-20b` | `GROQ_API_KEY` |
| `openrouter` | `openai/gpt-4o-mini` | `OPENROUTER_API_KEY` |

`NAME_FALLBACK_MODEL` để trống sẽ dùng mặc định của provider; có giá trị sẽ ghi đè
model của provider được chọn. Khi đổi provider, xóa giá trị cũ hoặc đặt model tương
ứng. Không tự sửa `.env` của developer. Model tùy chọn phải hỗ trợ JSON Schema.

`NAME_FALLBACK_TIMEOUT_S` mặc định 3 giây cho read/write/pool; connect 1 giây.
`NAME_FALLBACK_MAX_TOKENS` để trống dùng 200, riêng Groq dùng 1024 vì GPT-OSS tính cả
reasoning token trong budget. Đặt số nguyên dương để ghi đè. Không phải deadline
tổng lượt; lỗi API, output bị cắt hoặc sai JSON đều khiến NER trả `NONE`.

Gemini dùng `generateContent`, tách system instruction và ánh xạ assistant thành
model; dùng `responseJsonSchema`. Với Gemini 2.5 Flash/Flash Lite, tắt thinking để
giữ token budget cho JSON. Không trộn thought parts vào nội dung kết quả.

OpenAI/Groq dùng Chat Completions với strict JSON Schema. Groq GPT-OSS dùng
`reasoning_effort=low`. OpenRouter dùng `max_tokens` và yêu cầu endpoint hỗ trợ đủ
tham số (`require_parameters=true`), tắt fallback giữa upstream endpoints.

## Gọi từ code

```python
from inference.llm.gateway import create_gateway

gateway = create_gateway("openai")  # đọc key/model/timeout từ môi trường
reply = gateway.generate_structured(
    [{"role": "user", "content": "Trích một nhãn JSON cho câu: xin chào"}],
    schema={
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": ["label"],
        "additionalProperties": False,
    },
    schema_name="label",
)
if reply.status == "completed":
    # Caller validate schema trước khi dùng trong nghiệp vụ.
    print(reply.content)
```

`StructuredReply` gồm `status`, `content`, `prompt_tokens`, `completion_tokens`.
Status: `completed`, `refusal`, `incomplete`, `invalid_response`, `timeout`,
`http_error`, `network_error`. Không đưa nội dung exception hoặc response lỗi
vào kết quả. Gemini completion usage gồm candidate + thought tokens nếu có.
Client đóng sau request; caller có thể inject config và HTTP client factory để test.

Scope hiện tại là structured generation cho NER. Gemini của Dialogue/ASR hiện có
chưa chuyển qua gateway; không bổ sung streaming, tools hoặc evaluation trong đợt này.

## Kiểm chứng

`python -m pytest -q tests/llm tests/engine/extraction/test_ner.py` dùng HTTP mock cho
cả bốn provider: request/response, roles, credentials, usage, timeout, HTTP lỗi,
refusal, JSON sai, cấu hình và đường gọi orchestrator → gateway. Không gọi API thật.
Model availability, latency và chất lượng extraction thực tế chưa được đo.

Tham chiếu: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Gemini generateContent](https://ai.google.dev/api/generate-content),
[Groq Structured Outputs](https://console.groq.com/docs/structured-outputs),
[OpenRouter Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs).

# HTTP API của bot — hành vi lặp lại và mã lỗi

Hai endpoint chấm điểm theo hợp đồng §4.1. Cấu trúc response thành công và enum `state` / `outcome` giữ nguyên Listing 1–2; tài liệu này chỉ mô tả hành vi khi gửi lại và các mã lỗi.

Lỗi có dạng:

```json
{"detail": {"code": "TURN_OUT_OF_ORDER", "message": "Đang chờ lượt 2", "expected_turn": 2}}
```

Lỗi validation của Pydantic giữ dạng mặc định của FastAPI (`422`, `{"detail": [...]}`).

## `POST /v1/calls`

| Trường hợp | Kết quả |
|---|---|
| `call_id` mới | `200`, mở phiên, trả câu chào |
| Outbound không đọc được lịch hợp lệ từ Clinic (lỗi API, không tìm thấy, dữ liệu hỏng hoặc lịch không còn thao tác được) | `503 OUTBOUND_START_FAILED`; không tạo phiên, không trả lời bot/TTS, không ghi chuyển máy. Sau khi khắc phục có thể gửi lại cùng `call_id` |
| Output Guard chặn lời mở đầu (câu chưa đăng ký, lộ lịch, có outcome — R-01) | `503 CALL_START_BLOCKED`; không tạo phiên, không trả lời bot/TTS, không ghi Clinic. Sau khi sửa lỗi có thể gửi lại cùng `call_id` |
| Gửi lại cùng `call_id`, cùng cấu hình (`direction`, `appointment_id`, `caller_number`, `locale`, `max_turns`) khi phiên còn hoạt động | `200`, trả nguyên phản hồi mở phiên đã lưu; không reset ngữ cảnh |
| `call_id` đã kết thúc hoặc đã làm sạch | `409 CALL_ENDED` hoặc `409 CALL_RECONCILIATION_REQUIRED` |
| Cùng `call_id`, khác cấu hình hoặc khác mode | `409 CALL_CONFLICT` |
| `mode=audio` | `200` khi audio TTS đã sẵn sàng; ASR chỉ chạy cho lượt chưa có transcript. Clip giữ tần số gốc, chỉ resample một lần về 16 kHz của model (không ép qua 8 kHz) |

Console mô phỏng outbound bằng `appointment_id`, chưa thực hiện quay số điện thoại.
Tra cứu Clinic là điều kiện trước khi mở phiên outbound; lỗi này hiển thị cho người vận hành.
Inbound đã có người gọi đến nên lỗi tra cứu vẫn theo luồng chuyển nhân viên.
Inbound nhận `caller_number: null` (Listing 1; harness của mentor gửi null ở mọi case inbound): phiên mở
bình thường và bot hỏi mở họ tên, ngày sinh như khi có số; chưa có số để tra hồ sơ nên sau ngày sinh bot
xin số điện thoại đã đăng ký (`ASK_PHONE`), tra `GET /patients?phone=` theo số đó rồi mới đối chiếu
tên + ngày sinh. Đầu số `0`, `+84` và `84` trần đều nhận. Trước khi có số không gọi Clinic, không ghi gì
(xem `docs/evidence/inbound-ask-phone-2026-10-13.md`). Inbound có `caller_number` nhưng không ra hồ sơ
vẫn chuyển máy ở lượt 1. Inbound có `appointment_id` vẫn bị từ chối `422`.

Luồng xử lý trong code: [`calls.py`](../../src/callbot/transports/http/calls.py)
→ `CallOrchestrator.start_call` → `SessionManager.open` →
[`DialogueManager.opening`](../../src/callbot/engine/dialogue/manager.py).
Manager chọn [`inbound.opening`](../../src/callbot/engine/dialogue/inbound.py) hoặc
[`outbound.opening`](../../src/callbot/engine/dialogue/outbound.py) theo `direction`.
Mỗi luồng gọi `IdentityVerifier.prepare` để tra cứu rồi quyết định hỏi danh tính,
chuyển nhân viên (inbound) hoặc từ chối mở phiên (outbound).
[`questions.ask`](../../src/callbot/engine/dialogue/questions.py) dùng chung để lưu câu hỏi
và lượt hỏi; `SessionManager` chỉ ghi phiên và áp dụng trạng thái sau khi mở đầu thành công.
`calls.py` chuyển `OutboundStartFailed` thành lỗi HTTP ở bảng trên.

## `POST /v1/calls/{call_id}/turn`

| Trường hợp | Kết quả |
|---|---|
| Lượt mới đúng `last_completed_turn + 1` | `200`, xử lý đúng một lần |
| Lượt đã hoàn tất khi session còn hoạt động, cùng đầu vào (`text`, `silence_ms`, `audio_url` giữ nguyên, không chuẩn hoá) | `200`, trả nguyên kết quả cũ; không chạy lại IE / Policy / Dialogue / Clinic |
| Cùng lượt, khác đầu vào | `409 TURN_CONFLICT` |
| Lượt nhảy số | `409 TURN_OUT_OF_ORDER`, kèm `expected_turn` |
| Lượt sau khi phiên kết thúc và nội dung đã xóa | `409 CALL_ENDED`; ngoại lệ: retry đúng request audio có biên nhận output chưa hoàn tất trong cửa sổ 120 giây chỉ phục hồi audio, không chạy Core |
| Không có phiên | `404 CALL_NOT_FOUND` |
| Không lấy được khóa xử lý | `409 CALL_BUSY`, không đổi ngữ cảnh; khóa HTTP chờ tối đa 1 giây, khóa session chờ tối đa 5 giây |
| Có lệnh ghi Clinic chưa rõ kết quả | `409 CALL_RECONCILIATION_REQUIRED`, kèm `turn`; phiên bị chặn tới khi đối soát ([hướng dẫn](session-operations.md)) |
| Redis session lỗi hoặc hết bộ nhớ | `503 SESSION_STORE_UNAVAILABLE`; không gửi lệnh Clinic khi chưa lưu được nhật ký |
| `audio_url` trên cuộc gọi text | `422 AUDIO_URL_NOT_ALLOWED` |
| `text` trên cuộc gọi audio | `422 TEXT_NOT_ALLOWED` |
| Tải/giải mã clip hoặc ASR lỗi, kể cả timeout | `503 UPSTREAM`; chưa đặt chỗ lượt, không tiêu thụ lượt và không ghi Clinic; có thể gửi lại cùng lượt khi đầu vào/provider đã phục hồi |
| TTS thiếu audio, lỗi/timeout hoặc lưu audio lỗi | `503 AUDIO_OUTPUT_UNAVAILABLE`; Core có thể đã commit, retry cùng request chỉ phục hồi output. Không suy ra Clinic chưa ghi từ lỗi này; xem [retry audio](audio-input-core.md) |
| Clinic timeout / lỗi ngoài lượt xử lý | `504 UPSTREAM_TIMEOUT` / `502 UPSTREAM_ERROR` |
| Lỗi ngoài dự kiến | `500 INTERNAL_ERROR` |

Lỗi nghiệp vụ trong lượt (Clinic từ chối lệnh ghi, guardrail hoặc Output Guard chặn) vẫn trả `200` với `outcome=TRANSFERRED`, `transfer_reason=SYSTEM_ERROR` như trước. Ngoại lệ:

- Khi kết quả lệnh ghi không xác định, bot **không** gửi lệnh chuyển máy thay thế mà trả `409 CALL_RECONCILIATION_REQUIRED`.
- Khi lượt đã ghi Clinic thành công (R-01, receipt gate) mà câu báo bị Output Guard chặn hoặc render lỗi, bot dùng đúng `outcome` đã ghi (ví dụ `CONFIRMED`) và câu báo không chi tiết; không gửi `/transfer`. Audio mode vẫn cần xuất audio thành công mới trả `200`; lỗi TTS/storage xử lý theo bảng trên.

Mọi câu bot nói, qua HTTP hay LiveKit, đều qua cùng Output Guard trong `CallOrchestrator` trước khi commit ([evidence R-01](../evidence/r01-output-guard.md)). Lượt replay trả lại đúng câu đã qua guard.

## Xác thực

`BOT_API_KEYS` trong `.env` là danh sách Bearer key dạng `sk_...`, nhiều key cách nhau dấu phẩy. Để trống thì tắt auth (mặc định, dùng cho dev local và test).

| Route | Cần key khi `BOT_API_KEYS` có giá trị |
|---|---|
| `/v1/calls`, `/v1/calls/{call_id}/turn` | Có |
| `/demo-api/*` | Có |
| `/v1/stt/*` (API thử STT, xem [stt-eval-api.md](stt-eval-api.md)) | Có. Chỉ mount khi `STT_EVAL_ENABLED=true`, và khi đó bắt buộc phải có `BOT_API_KEYS` |
| `/health`, `/ready`, `/audio/*`, `/audio-static/*`, `/ui/*` | Không. Harness tải `audio_url` không kèm header; `/audio-static/*` là audio câu tĩnh đã duyệt dùng chung giữa các cuộc gọi; `/ui/*` là file tĩnh của giao diện web |

Gửi `Authorization: Bearer <key>`. Thiếu header hoặc sai scheme trả `401 {"detail": {"code": "BAD_KEY", "message": "Missing bearer token."}}`; key không có trong danh sách trả `Invalid bearer token.`. Trang `/ui/call` (link cũ `/demo/` chuyển hướng tới đây) có ô "API key" để điền key; key chỉ lưu trong tab hiện tại (`sessionStorage`).

Server production giữ nguyên `/opt/callbot/.env` qua các lần deploy (xem `cd.yml`), nên muốn thêm hay thu hồi key thì sửa `BOT_API_KEYS` trong file đó rồi `docker compose up -d` lại. Secret `BOT_API_KEYS` của GitHub được CD dùng khi tạo `.env` lần đầu và cho smoke test (key đầu tiên), nên phải chứa một key server đang chấp nhận. Smoke test gửi `POST /v1/calls` với body rỗng và mong đợi `422`: chứng minh key hợp lệ và route hoạt động mà không mở cuộc gọi hay gọi Clinic.

## Probe

| Endpoint | Ý nghĩa |
|---|---|
| `GET /health` | Liveness: process còn sống. Không gọi Redis hay Clinic |
| `GET /ready` | Readiness: `200 {"status":"ready"}` khi Redis và cleanup session hoạt động; ngược lại `503` với `code=SESSION_STORE_UNAVAILABLE` |

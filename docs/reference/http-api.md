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
| Gửi lại cùng `call_id`, cùng cấu hình (`direction`, `appointment_id`, `caller_number`, `locale`, `max_turns`) khi phiên còn hoạt động | `200`, trả nguyên phản hồi mở phiên đã lưu; không reset ngữ cảnh |
| `call_id` đã kết thúc hoặc đã làm sạch | `409 CALL_ENDED` hoặc `409 CALL_RECONCILIATION_REQUIRED` |
| Cùng `call_id`, khác cấu hình | `409 CALL_CONFLICT` |
| `mode=audio` | `501 AUDIO_NOT_IMPLEMENTED` |

## `POST /v1/calls/{call_id}/turn`

| Trường hợp | Kết quả |
|---|---|
| Lượt mới đúng `last_completed_turn + 1` | `200`, xử lý đúng một lần |
| Lượt đã hoàn tất khi session còn hoạt động, cùng đầu vào (`text`, `silence_ms`, `audio_url` giữ nguyên, không chuẩn hoá) | `200`, trả nguyên kết quả cũ; không chạy lại IE / Policy / Dialogue / Clinic |
| Cùng lượt, khác đầu vào | `409 TURN_CONFLICT` |
| Lượt nhảy số | `409 TURN_OUT_OF_ORDER`, kèm `expected_turn` |
| Bất kỳ lượt nào sau khi phiên kết thúc và nội dung đã xóa | `409 CALL_ENDED` |
| Không có phiên | `404 CALL_NOT_FOUND` |
| Phiên đang xử lý lượt khác quá 5 giây | `409 CALL_BUSY`, không đổi ngữ cảnh |
| Có lệnh ghi Clinic chưa rõ kết quả | `409 CALL_RECONCILIATION_REQUIRED`, kèm `turn`; phiên bị chặn tới khi đối soát ([hướng dẫn](session-operations.md)) |
| Redis session lỗi hoặc hết bộ nhớ | `503 SESSION_STORE_UNAVAILABLE`; không gửi lệnh Clinic khi chưa lưu được nhật ký |
| `audio_url` trên cuộc gọi text | `422 AUDIO_URL_NOT_ALLOWED` |
| Clinic timeout / lỗi ngoài lượt xử lý | `504 UPSTREAM_TIMEOUT` / `502 UPSTREAM_ERROR` |
| Lỗi ngoài dự kiến | `500 INTERNAL_ERROR` |

Lỗi nghiệp vụ trong lượt (Clinic từ chối lệnh ghi, guardrail chặn) vẫn trả `200` với `outcome=TRANSFERRED`, `transfer_reason=SYSTEM_ERROR` như trước. Ngoại lệ: khi kết quả lệnh ghi không xác định, bot **không** gửi lệnh chuyển máy thay thế mà trả `409 CALL_RECONCILIATION_REQUIRED`.

## Probe

| Endpoint | Ý nghĩa |
|---|---|
| `GET /health` | Liveness: process còn sống. Không gọi Redis hay Clinic |
| `GET /ready` | Readiness: `200 {"status":"ready"}` khi Redis và cleanup session hoạt động; ngược lại `503` với `code=SESSION_STORE_UNAVAILABLE` |

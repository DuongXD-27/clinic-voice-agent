# Evidence: F-02 — Nối HTTP vào engine thật

## Mục tiêu

Hai endpoint `POST /v1/calls` và `POST /v1/calls/{call_id}/turn` gọi `CallOrchestrator` hiện có thay cho `stub_handlers` (trước đây luôn trả `TRANSFERRED` và một file WAV rỗng giả). `/turn` trả đúng quyết định của engine; router không tự chọn outcome hay sinh lời chuyển máy.

Phạm vi là HTTP text mode. Không đổi Core/Gateway, không thay `nlu/` bằng `extraction/`, không hoàn thiện thêm nghiệp vụ.

## Bằng chứng trong repo

| Acceptance criterion | Vị trí code | Test chứng minh |
| --- | --- | --- |
| Runtime không còn import stub | Xoá `src/callbot/transports/http/stub_handlers.py` cùng `_calls` và `_STUB_AUDIO_URL` | Toàn bộ test import `callbot.transports.http.main` chạy được sau khi xoá file |
| Orchestrator tạo một lần, lưu trên `app.state` | `create_app()` + `lifespan` trong `transports/http/main.py`; `get_orchestrator` trong `calls.py` | `test_orchestrator_created_once_and_clinic_closed_on_shutdown` |
| Client Clinic có lifecycle đúng | `ClinicMockClient.close()`; `lifespan` gọi `close()` khi shutdown | `test_orchestrator_created_once_and_clinic_closed_on_shutdown` |
| `/v1/calls` trả câu mở đầu của engine, `turn=0`, `audio_url=null` | `start_call` trong `calls.py` | `test_start_call_returns_engine_opening` |
| Lượt tên → hỏi ngày sinh, không chuyển máy mặc định | `call_turn` → `CallOrchestrator.handle_turn` | `test_name_turn_asks_dob_instead_of_transferring` (thay `test_turn_defaults_to_transfer`) |
| Cùng session được dùng giữa các lượt | Session nằm trong orchestrator của lifespan | `test_dob_turn_continues_same_session` (xác minh xong → `AWAITING_INTENT`, không có write) |
| Hai call không dùng chung trạng thái | `SessionManager` theo `call_id` | `test_calls_do_not_share_state` |
| Im lặng ≠ transcript rỗng | `is_silence = silence_ms > 0`; im lặng truyền `text=""` | `test_silence_and_empty_transcript_map_differently` |
| Call không tồn tại → 404 `CALL_NOT_FOUND`, không tự tạo call | `_run_engine` bắt `SessionNotFound` | `test_unknown_call_returns_404` |
| Validation đầu vào → 422 | `model_validator` trong `schemas.py` (outbound cần `appointment_id`; inbound không có `appointment_id` — từ 13-10-2026 inbound nhận `caller_number: null` theo Listing 1, xem `docs/evidence/inbound-null-caller-number-2026-10-13.md` và bước hỏi số điện thoại `docs/evidence/inbound-ask-phone-2026-10-13.md`; `max_turns > 0`; `turn >= 1`; `text=null` chỉ khi `silence_ms > 0`); `call_turn` từ chối `audio_url` | `test_start_call_rejects_invalid_input`, `test_turn_rejects_invalid_input`, `test_text_call_rejects_audio_url`, các test `team_hardening` trong `tests/test_schema.py` |
| Audio mode → 501 `AUDIO_NOT_IMPLEMENTED`, trước khi mở session | `start_call` | `test_audio_mode_is_not_implemented`, `test_team_scope_start_call_audio_mode_is_not_implemented` |
| Lỗi upstream/ngoài dự kiến → 502/504/500, không lộ chi tiết | `_run_engine` trong `calls.py` | `test_engine_errors_map_to_http_status` (dependency override) |
| Schema response giữ nguyên | `schemas.py` chỉ thêm validator/ràng buộc, không đổi field | Các test `test_contract_*_openapi_shape_*` và `test_listing_conformance_*` |

## File liên quan

- `src/callbot/transports/http/main.py`
- `src/callbot/transports/http/calls.py`
- `src/callbot/transports/http/schemas.py`
- `src/callbot/engine/tools/clinic_mock_client.py`
- `tests/conftest.py`
- `tests/transports/http/test_calls.py`
- `tests/test_schema.py`

## Luồng hiện tại

```text
startup (lifespan)
  -> ClinicMockClient(CLINIC_MOCK_BASE_URL, CLINIC_MOCK_API_KEY)
  -> create_orchestrator(clinic, EngineSettings()): SessionManager, InformationExtractor,
     PolicyEngine, DialogueManager(ClinicGateway, IdentityVerifier) -> app.state.orchestrator

POST /v1/calls (StartCallRequest)
  -> mode=audio: 501
  -> CallStart -> orchestrator.start_call -> BotAction
  -> StartCallResponse(utterance, state, turn=0, audio_url=null)

POST /v1/calls/{call_id}/turn (TurnRequest)
  -> audio_url != null: 422
  -> CallerInput(turn, text | "", is_silence=silence_ms>0) -> orchestrator.handle_turn -> BotAction
  -> TurnResponse(utterance, state, ended, outcome, audio_url=null)
  -> SessionNotFound: 404 · httpx timeout: 504 · httpx error: 502 · khác: 500

shutdown -> clinic.close()
```

Mã lỗi trả dạng `{"detail": {"code": "...", "message": "..."}}`; lỗi validation của Pydantic vẫn là `{"detail": [...]}` mặc định của FastAPI.

## Quy trình xác minh

```powershell
make check
```

Test HTTP dùng `TestClient` trong `with` (chạy lifespan) qua fixture `client` ở `tests/conftest.py`. Mỗi test có một app, một session store và một `FakeClinicAPI` riêng; hành vi hội thoại luôn đi qua `CallOrchestrator` thật. Chỉ test mapping lỗi dùng orchestrator giả (dependency override).

## Kết quả xác minh cục bộ (2026-09-17)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | 404 passed, 1 skipped, 1 failed |
| `python -m pytest -q tests/transports tests/test_schema.py` | 43 passed, 1 skipped |

Test lỗi là `tests/speech/test_narrowband.py::test_settings_default_to_narrowband`. Nó đã lỗi trước F-02 (`SpeechSettings()` validation lỗi khi đọc `.env` cục bộ) và không liên quan đến HTTP. Test bị skip là `test_external_blocked_clinic_mock_image_matches_official_digest` (chưa có digest chính thức).

### Fake Clinic và Clinic thật

- **Test tự động:** mọi test trên dùng `FakeClinicAPI` trong bộ nhớ, không gọi mạng.
- **Khởi động app production trong process:** chạy `callbot.transports.http.main:app` với `ClinicMockClient` thật. Start + lượt tên trả câu chào và câu hỏi ngày sinh (`AWAITING_IDENTITY`, `ended=false`); client ở trạng thái đóng sau shutdown. Hai lượt này không gọi Clinic nên không kiểm tra kết nối mạng.
- **Chưa chạy smoke với Clinic Mock local:** Docker không chạy trên máy xác minh. Không gọi mock đã deploy để tránh ảnh hưởng môi trường dùng chung. Khi có môi trường local, smoke chỉ đi đến lượt ngày sinh (xác minh danh tính, chỉ đọc).

## Ghi chú

- Chỉ text mode: `mode=audio` trả 501; `audio_url` luôn `null`. Contract vẫn yêu cầu audio, đây là gap đã biết.
- Giới hạn lịch sử: session từng nằm trong bộ nhớ một process. *(Đã thay bằng Redis tạm dùng chung ở F-03.)*
- `handle_turn` tự bắt mọi exception và chuyển máy `SYSTEM_ERROR`, nên 502/504/500 hiện chỉ xảy ra khi lỗi thoát ra khỏi engine (ví dụ trong `start_call`). F-02 không sửa cơ chế này và không thêm retry ghi ở HTTP adapter.
- Router không kiểm tra `turn` tăng dần và không khoá khi hai request cùng `call_id` chạy đồng thời. *(F-03 bổ sung, xem [http-api.md](../reference/http-api.md).)*
- Nghiệp vụ còn dở (slot, `mark_unreachable`, extraction mới) nằm ngoài F-02; xem mục 5 của `docs/reference/ai-callbot-architecture.md`.

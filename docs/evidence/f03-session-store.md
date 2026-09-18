# Evidence: F-03 — Session tạm trên Redis

## Quyết định lưu trữ

Clinic là nguồn dữ liệu chính thức của bệnh nhân. Callbot chỉ giữ dữ liệu cần cho cuộc gọi đang chạy trong Redis dùng chung. Redis được cấu hình không persistence, có TTL, giới hạn dung lượng và `noeviction`. PostgreSQL và session store trong RAM đã được loại khỏi runtime lẫn test.

## Bằng chứng trong repo

| Yêu cầu | Code/cấu hình | Test |
| --- | --- | --- |
| Một implementation Redis cho runtime và unit test | `session/redis_store.py`, `tests/conftest.py` | `test_store_contract.py` dùng `fakeredis` qua `RedisSessionStore` |
| Session dùng chung qua nhiều worker | khóa `SET NX PX`, một key JSON atomically theo `call_id` | `test_lock_times_out_with_call_busy_and_other_calls_are_independent`, `test_real_redis_shares_session_and_distributed_lock` |
| Không ghi session xuống đĩa | `--save ""`, `--appendonly no`; startup validation | `test_server_config_accepts_only_ephemeral_bounded_noeviction` |
| Không tràn RAM âm thầm | Redis `maxmemory`, `noeviction`; `SESSION_MAX_BYTES` cho từng call | `test_active_session_has_ttl_and_is_bounded` |
| Xóa thông tin khách hàng sau Clinic hoặc khi kết thúc | `_purge_state`, tombstone kỹ thuật | `test_clinic_write_outcome_removes_customer_content`, `test_terminal_turn_removes_customer_content` |
| Hết hạn theo idle và maximum age | `RetentionPolicy`, Redis TTL, cleanup nền | `test_expired_session_is_scrubbed_and_tombstone_retained`, `test_maximum_age_expires_even_after_recent_activity` |
| Kết quả Clinic chưa rõ thì fail closed | journal `PENDING/UNKNOWN`, tombstone đối soát | `test_pending_command_expires_into_reconciliation_tombstone`, các test lifecycle ghi Clinic |
| Redis lỗi không fallback RAM | `SessionStoreUnavailable`, readiness 503 | `test_redis_disconnect_fails_closed`, `test_ready_reports_session_store` |
| CI xác minh bằng Redis thật | Redis service và `REQUIRE_REDIS_TESTS=1` trong `ci.yml` | `test_redis_integration.py` |

## Dữ liệu còn lại trong tombstone

Tombstone giữ metadata cần chống replay nguy hiểm và báo đối soát: `call_id`, số lượt, trạng thái lượt, idempotency key, operation, trạng thái và số lần thử. Các trường chứa nội dung khách hàng bị đặt rỗng: start config, opening, context, turn input/result/extraction/detail, command endpoint/payload/result/error.

Tombstone tự hết hạn theo `SESSION_TOMBSTONE_TTL_S`. Không có volume Redis nên restart Redis cũng loại bỏ toàn bộ session/tombstone.

## Các tình huống ngoại lệ đã xử lý

- Redis không kết nối được, hết bộ nhớ hoặc dữ liệu JSON/schema hỏng: trả `SESSION_STORE_UNAVAILABLE`.
- Không lấy được khóa đúng hạn: trả `CALL_BUSY`.
- Khóa mất ownership: request không được xem là hoàn tất an toàn.
- Worker chết trước lệnh Clinic: lượt `PROCESSING` có thể tiếp tục.
- Worker chết sau khi journal `PENDING` hoặc sau Clinic acknowledgement: chặn đối soát, không tự gửi lại.
- Cleanup gặp call đang khóa: bỏ qua call đó và thử ở vòng sau.
- Session vượt giới hạn byte: từ chối ghi, giữ bản Redis trước đó nguyên vẹn.

Hướng dẫn cấu hình và vận hành nằm tại [session-operations.md](../reference/session-operations.md).

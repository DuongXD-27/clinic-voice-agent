# Vận hành session tạm trên Redis

Session chỉ phục vụ một luồng cuộc gọi đang chạy. Hồ sơ bệnh nhân và kết quả nghiệp vụ chính thức thuộc Clinic. Callbot không dùng PostgreSQL và không có kho session trong RAM của process.

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis local không mật khẩu; Compose tự dựng URL có mật khẩu |
| `REDIS_KEY_PREFIX` | Giá trị tương thích trong code | Namespace của key; nên đặt rõ trong `.env` và giữ ổn định qua các lần deploy |
| `SESSION_IDLE_TTL_S` | `1800` | Xóa nội dung sau thời gian không hoạt động |
| `SESSION_MAX_AGE_S` | `7200` | Tuổi tối đa tuyệt đối của session |
| `SESSION_TOMBSTONE_TTL_S` | `86400` | Thời gian giữ metadata kỹ thuật đã làm sạch |
| `SESSION_MAX_BYTES` | `262144` | Giới hạn kích thước một cuộc gọi |
| `SESSION_LOCK_LEASE_S` | `60` | Lease khóa phân tán theo `call_id` |
| `REDIS_MAXMEMORY` | `256mb` | Giới hạn RAM của Redis trong Compose |

Compose yêu cầu `REDIS_PASSWORD` trong `.env`. Nếu chạy app trực tiếp với Redis có mật khẩu, đặt mật khẩu đã URL-encode trong `REDIS_URL`.

## Yêu cầu bắt buộc với Redis

Ứng dụng HTTP kiểm tra cấu hình khi khởi động và từ chối chạy nếu một điều kiện sau không đúng:

- RDB snapshot tắt: `save ""`.
- AOF tắt: `appendonly no`.
- Có giới hạn bộ nhớ: `maxmemory > 0`.
- Không tự ý đẩy key đang chạy: `maxmemory-policy noeviction`.

`noeviction` làm lệnh ghi thất bại rõ ràng khi hết RAM. Bot trả `503 SESSION_STORE_UNAVAILABLE` và không gửi lệnh Clinic nếu chưa ghi được journal. Redis không có volume; restart Redis làm mất các cuộc gọi đang chạy, và lượt tiếp theo nhận `404 CALL_NOT_FOUND`. Đây là dữ liệu tạm có chủ đích.

## Vòng đời dữ liệu

Mỗi `call_id` có một JSON key chứa context, các lượt và journal lệnh Clinic. Mọi thay đổi thay thế atomically một key trong khóa phân tán của cuộc gọi.

- Session mới luôn có TTL; TTL bị chặn bởi cả idle timeout và maximum age.
- Lượt kết thúc không ghi Clinic: xóa ngay cấu hình cuộc gọi, transcript, kết quả và extraction.
- Clinic trả thành công: xóa ngay toàn bộ nội dung khách hàng sau acknowledgement, trước khi trả HTTP.
- Kết quả ghi Clinic không xác định: xóa nội dung và giữ tombstone `RECONCILIATION_REQUIRED` để chặn ghi trùng.
- Hết hạn: cleanup làm sạch nội dung; Redis TTL vẫn là lớp bảo vệ cuối cùng nếu cleanup dừng.
- Tombstone chỉ giữ mã trạng thái, số lượt, trạng thái lệnh, attempts, idempotency key và thời điểm kỹ thuật. Endpoint, payload, result và error đều bị xóa.

Bot không sao chép hồ sơ bệnh nhân sang nơi lưu bền. Trong lúc hội thoại, các trường cần thiết chỉ tồn tại tạm trong key Redis; sau khi ghi Clinic thành công hoặc cuộc gọi kết thúc, chúng bị xóa.

## Đồng thời và lỗi

- Khóa Redis `SET NX PX` theo `call_id`; chờ quá 5 giây trả `409 CALL_BUSY`.
- Các `call_id` khác nhau không chặn nhau, nên có thể chạy nhiều worker/replica.
- Nếu khóa hết hạn hoặc đổi chủ trong khi xử lý, request trả `503`; không coi lượt là hoàn thành an toàn.
- Lượt `PROCESSING` không có lệnh, hoặc chỉ có lệnh `FAILED`, có thể xử lý tiếp.
- Lượt có lệnh `PENDING`, `UNKNOWN` hoặc `SUCCEEDED` nhưng chưa hoàn tất bị chặn bằng `409 CALL_RECONCILIATION_REQUIRED`.
- Redis mất kết nối khiến readiness trả `503`; ứng dụng không chuyển sang bộ nhớ cục bộ.

## Khởi động và kiểm tra

```bash
# Đặt REDIS_PASSWORD trong .env trước khi chạy.
docker compose up --build
curl http://localhost:8000/ready
```

Compose khởi động Redis trước, chờ healthcheck rồi mới chạy bot. `/health` chỉ kiểm tra process; `/ready` kiểm tra Redis và cleanup session.

Chạy test với Redis thật:

```bash
docker run --rm -p 6379:6379 redis:7.4-alpine
export TEST_REDIS_URL=redis://localhost:6379/15
export REQUIRE_REDIS_TESTS=1
python -m pytest -q tests/engine/session
```

Unit test dùng `fakeredis` nhưng luôn chạy chính `RedisSessionStore`; không còn implementation session dành riêng cho test. CI chạy thêm bài tích hợp trên Redis thật.

# Vận hành session store — nhiều worker và đối soát

Áp dụng từ F-03. Phiên, lượt và nhật ký lệnh Clinic nằm trong PostgreSQL; ứng dụng HTTP **không** tự chuyển sang bộ nhớ khi DB lỗi.

## 1. Cấu hình

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `SESSION_DATABASE_URL` | — | Bắt buộc, `postgresql://user:pass@host:5432/db` |
| `SESSION_POOL_MIN_SIZE` / `SESSION_POOL_MAX_SIZE` | `1` / `10` | Pool **mỗi worker**. Một request đang xử lý giữ 1 connection khóa và mượn thêm 1 connection đọc/ghi |
| `SESSION_POOL_TIMEOUT_S` | `5` | Chờ connection từ pool |
| `WEB_CONCURRENCY` | `2` | Số worker uvicorn trong Docker |

Tổng connection tối đa ≈ `WEB_CONCURRENCY × SESSION_POOL_MAX_SIZE` (+1 cho migrate). Giữ dưới `max_connections` của PostgreSQL (mặc định 100).

## 2. Khởi động

```bash
# Migration: MỘT lần, trước khi khởi động worker
python -m callbot.engine.session.postgres.migrate

# Nhiều worker
uvicorn callbot.transports.http.main:app --host 0.0.0.0 --port 8000 --workers 4
```

`docker compose up --build` chạy theo thứ tự `postgres` (healthy) → `migrate` (thoát 0) → `bot`. Volume `pg_data` giữ dữ liệu qua restart; **không** xoá volume khi deploy.

Dùng `/ready` cho readiness (DB + phiên bản schema), `/health` cho liveness.

## 3. Cơ chế

- Mỗi lượt khóa theo `call_id` bằng advisory lock cấp session của PostgreSQL, trên một connection riêng, giữ suốt lượt. Chờ tối đa 5 giây, quá thì `409 CALL_BUSY`. Các cuộc gọi khác nhau không chặn nhau.
- Lượt được đặt chỗ (`call_turns.status = PROCESSING`) cùng thời điểm tiếp nhận trước khi xử lý. Context, history và kết quả commit trong **một** transaction (`COMPLETED`).
- Trước mỗi lệnh ghi Clinic, lệnh được commit vào `clinic_commands` (`PENDING`) với payload, `If-Match` và `Idempotency-Key` cố định `{call_id}:{turn}:{thao tác}[:{slot}]`, rồi mới gửi. Sau đó cập nhật `SUCCEEDED` / `FAILED` / `UNKNOWN`.
- Lượt `PROCESSING` còn lại (worker chết, request trước lỗi):
  - Không có lệnh, hoặc mọi lệnh `FAILED` (Clinic từ chối chắc chắn) → xử lý tiếp với thời điểm tiếp nhận cũ.
  - Có lệnh `PENDING` / `UNKNOWN` / `SUCCEEDED` → đánh dấu `RECONCILIATION_REQUIRED`, trả `409 CALL_RECONCILIATION_REQUIRED`.
- Timeout đọc hoặc mất kết nối khi đang gửi lệnh ghi → `UNKNOWN`, phiên bị chặn; bot **không** gửi lại lệnh và **không** phát lệnh chuyển máy thay thế.

## 4. Chuyển từ bộ nhớ sang PostgreSQL (lần triển khai đầu)

Không có dữ liệu phiên cũ để migrate. Trước khi triển khai: dừng nhận cuộc gọi mới và chờ các cuộc gọi đang chạy kết thúc, rồi deploy. Cuộc gọi còn dở khi deploy sẽ nhận `404 CALL_NOT_FOUND` ở lượt tiếp theo.

Không tái sử dụng `call_id`: đợt này chưa có chính sách xoá session / lượt / nhật ký lệnh. Smoke test tạo id riêng mỗi lần (`ci_smoke_<run_id>_<attempt>`).

## 5. Tra cứu và đối soát

Công cụ **chỉ đọc**, không sửa hay mở khóa phiên:

```bash
# Các lượt đang chờ đối soát
python -m callbot.engine.session.postgres.inspect blocked

# Chi tiết một cuộc gọi: tóm tắt context (không in tên / ngày sinh), từng lượt, từng lệnh Clinic
python -m callbot.engine.session.postgres.inspect call <call_id>

# Trong Docker
docker compose exec bot python -m callbot.engine.session.postgres.inspect blocked
```

Quy trình cho mỗi lượt `RECONCILIATION_REQUIRED`:

1. `inspect call <call_id>`: tìm lệnh có `status` khác `SUCCEEDED` / `FAILED` (hoặc `SUCCEEDED` nhưng lượt chưa `COMPLETED`). Ghi lại `idempotency_key`, `endpoint`, `payload`, `if_match`.
2. Đối chiếu trên Clinic: `GET /v1/appointments/{id}` — xem `status`, `version`, các trường lý do (`cancel_reason`, `transfer_reason`, `unreachable_reason`, `new_slot_id`), và với đặt lịch inbound thì tìm lịch hẹn mới của bệnh nhân. Mock trả kết quả cũ khi gửi lại cùng `Idempotency-Key`, nhưng **không** gửi lại lệnh từ công cụ này.
3. Kết luận lệnh đã áp dụng hay chưa và báo cho người phụ trách cuộc gọi / harness. Tự động đối soát và mở khóa phiên **nằm ngoài** F-03; phiên vẫn bị chặn sau bước này.

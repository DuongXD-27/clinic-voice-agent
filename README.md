# Vinmec Callbot

Callbot đặt/xác nhận/hủy/đổi lịch khám qua điện thoại, xây dựng theo hợp đồng
`AIHR-PC-001` (AI Health Residency, Batch 03).

Bot expose 2 endpoint HTTP để một bộ chấm điểm (harness) điều khiển cuộc gọi
theo từng lượt, và gọi ngược lại một "clinic mock" (mock backend phòng khám)
để đọc/ghi lịch hẹn.

## Cấu trúc project

```
src/callbot/               # một core, hai transport (§1.3.2)
  transports/              # chỉ đổi request/response sang kiểu của engine, không chứa logic hội thoại
    http/                  # đường chấm điểm — uvicorn callbot.transports.http.main:app
      main.py              # FastAPI app: lifespan tạo session store PostgreSQL + ClinicMockClient + CallOrchestrator, /health, /ready
      calls.py             # 2 endpoint bắt buộc, gọi CallOrchestrator: POST /v1/calls, POST /v1/calls/{id}/turn
      schemas.py           # Pydantic models cho request/response (§4.1)
      config.py            # đọc biến môi trường (CLINIC_MOCK_BASE_URL, ...)
    # phone/               # phone leg tuần 6 (§1.3.1), chưa làm
  engine/                  # AI Callbot Engine
    session/               # Session Manager: CallContext, FSM, thứ tự lượt / replay, store (in-memory cho test)
      postgres/            # PostgreSQL store, migrations/*.sql, migrate + inspect (chỉ đọc)
    extraction/            # Information Extraction theo docs/reference/information-extraction-design.md
    policy/                # PolicyEngine + guardrails SF-01..SF-05
    verification/          # Verifier: xác minh tên + ngày sinh
    dialogue/              # Dialogue Manager, templates, prompts, llm/
    tools/                 # Clinic Gateway: kiểm soát đọc/ghi và retry (F-05)
      ports.py             # Protocol ClinicAPI 1:1 với mock (Page phân trang, ClinicAPIError)
      clinic_gateway.py    # ClinicGateway: guardrail + FSM + nhật ký lệnh, đọc hết trang, chuẩn hóa
      clinic_mock_client.py# ClinicMockClient (httpx) — httpx không lộ ra ngoài file này
      fake_clinic.py       # FakeClinicAPI: mock trong bộ nhớ, hành xử như routes.py của mock
      normalize.py         # start_time→starts_at, patient canonical, appointment int-hoá
      telemetry.py         # ApiCallRecord + collect_api_calls() cho trace API/độ trễ
    journal.py             # nhật ký lệnh ghi Clinic gắn với lượt đang xử lý
    errors.py              # lỗi engine transport cần phân biệt (409/503)
    orchestrator.py        # CallOrchestrator: điều phối 1 lượt
  speech/                  # Realtime STT pipeline + TTS
    audio/                 # codec wav/G.711, chuẩn hoá về PCM 8 kHz băng hẹp, tải audio_url
    vad/                   # FrameClassifier (energy baseline) + StreamingVAD
    asr/                   # ASRProvider: gemini.py, phowhisper.py
    tts/                   # TTSProvider + AudioArtifactStore (sinh audio_url)
    transcript.py          # gộp partial/final
    pipeline.py            # STTPipeline: Audio -> VAD -> ASR -> Transcript
  tracing/                 # JsonlLogger: trace mỗi lượt ra JSONL
tests/                     # cùng cấu trúc với src/callbot: engine/, speech/, transports/http/
```

## Yêu cầu môi trường

- Python >= 3.11
- PostgreSQL >= 11 — bắt buộc với ứng dụng HTTP (phiên, lượt, nhật ký lệnh Clinic)
- Docker (nếu muốn chạy bằng container hoặc dùng `docker-compose`)

## Setup cơ bản (chạy local)

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
pip install -e ".[speech,llm]"      # tuỳ chọn: numpy + Gemini (ASR/LLM)
pip install -e ".[speech-local]"    # tuỳ chọn: PhoWhisper self-hosted

cp .env.example .env   # chỉnh CLINIC_MOCK_BASE_URL, SESSION_DATABASE_URL

docker run -d --name callbot-pg -e POSTGRES_USER=callbot -e POSTGRES_PASSWORD=callbot   -e POSTGRES_DB=callbot -p 5432:5432 postgres:16-alpine
python -m callbot.engine.session.postgres.migrate   # một lần, trước khi chạy worker

uvicorn callbot.transports.http.main:app --reload
```

Server chạy ở `http://localhost:8000`. Kiểm tra nhanh:

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/v1/calls \
  -H "Content-Type: application/json" \
  -d '{"call_id":"c_demo","direction":"outbound","appointment_id":"apt_00417","mode":"text"}'
```

## Chạy test & lint

```bash
# Test tích hợp PostgreSQL chạy khi có biến này (thiếu thì skip; CI bắt buộc)
export TEST_SESSION_DATABASE_URL=postgresql://callbot:callbot@localhost:5432/callbot

make check     # ruff check + ruff format --check + pytest (giống CI)
make format    # tự sửa lint + format code
make test      # chỉ pytest
```

Không có `make` (Windows): chạy trực tiếp `python -m ruff check src tests`,
`python -m ruff format --check src tests`, `python -m pytest -q`.

## Chạy bằng Docker

```bash
docker build -t vinmec-callbot .
docker run --rm -p 8000:8000 vinmec-callbot
```

`docker compose up --build` chạy PostgreSQL (volume `pg_data`) → `migrate` → bot (`WEB_CONCURRENCY` worker), đọc cấu hình từ `.env`. Vận hành nhiều worker và đối soát: [docs/reference/session-operations.md](docs/reference/session-operations.md). Mã lỗi HTTP: [docs/reference/http-api.md](docs/reference/http-api.md). Clinic mock đã
deploy riêng tại `https://clinic-mock.vmec-callbot.tech` — đặt `CLINIC_MOCK_API_KEY`
trong `.env`.

## CI/CD

[.github/workflows/ci-cd.yml](.github/workflows/ci-cd.yml):

- Mọi push / PR: chạy `make check` (ruff lint, ruff format check, pytest) với PostgreSQL service.
- Push lên `main` (hoặc chạy tay *Run workflow*): test → build image lên
  `ghcr.io/<owner>/callbot-vinmec` → SSH vào EC2, chép
  [docker-compose.prod.yml](docker-compose.prod.yml) + `.env` sinh từ secrets vào
  `/opt/callbot`, `docker compose pull && up -d` (PostgreSQL + migrate + bot) → smoke test `/ready` và `POST /v1/calls` với `call_id` riêng mỗi lần.

URL nộp cho chương trình (khóa cứng suốt batch, không có `/` cuối):

| | |
|---|---|
| Bot | `https://vmec-callbot.tech` |
| Clinic mock | `https://clinic-mock.vmec-callbot.tech` |

### Chuẩn bị một lần

1. **EC2** (Ubuntu 24.04, `t3.small`, `ap-southeast-1`): security group mở 22, 80, 443.
   Gắn **Elastic IP** và không release — mất IP là mất URL đã nộp. Cài Docker:
   `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker ubuntu`.
2. **DNS**: bản ghi A `vmec-callbot.tech` → Elastic IP. Chờ phân giải xong rồi mới deploy,
   Caddy xin cert ngay khi khởi động.
3. **GitHub → Settings → Secrets and variables → Actions** (cấp repo):

   | Loại | Tên | Giá trị |
   |---|---|---|
   | Secret | `EC2_HOST` | Elastic IP |
   | Secret | `EC2_SSH_KEY` | private key SSH vào EC2 |
   | Secret | `CLINIC_MOCK_API_KEY` | key `sk_...` của clinic mock |
   | Secret | `GEMINI_API_KEY` | tuỳ chọn, khi dùng audio / LLM |
   | Secret | `SESSION_DB_PASSWORD` | mật khẩu PostgreSQL của session store trên EC2 |
   | Variable | `BOT_DOMAIN` | `vmec-callbot.tech` |
   | Variable | `EC2_USER` | tuỳ chọn, mặc định `ubuntu` |
   | Variable | `CLINIC_MOCK_BASE_URL` | tuỳ chọn, mặc định `https://clinic-mock.vmec-callbot.tech/v1` |

## Trạng thái hiện tại

- HTTP text mode chạy engine thật với Information Extraction mới (F-02, F-04); `mode=audio` trả 501.
- Phiên lưu trong PostgreSQL, chạy được nhiều worker; gửi lại lượt trả kết quả đã lưu, lệnh ghi Clinic có nhật ký và chặn đối soát khi kết quả không xác định (F-03). Xem evidence [F-03](docs/evidence/f03-session-store.md) và [F-04](docs/evidence/f04-information-extraction-http.md).

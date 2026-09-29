# Vinmec Callbot

Callbot tiếng Việt **đặt, xác nhận, hủy và đổi lịch khám** qua điện thoại.

Bot cung cấp 2 endpoint HTTP để điều khiển cuộc gọi theo từng lượt, và gọi tới backend
phòng khám (Clinic API) để đọc/ghi lịch hẹn.

## Mục lục

- [Tính năng](#tính-năng)
- [Yêu cầu](#yêu-cầu)
- [Cài đặt](#cài-đặt)
- [Cấu hình](#cấu-hình)
- [Sử dụng](#sử-dụng)
- [Chạy bằng Docker](#chạy-bằng-docker)
- [Kiểm thử](#kiểm-thử)
- [Cấu trúc project](#cấu-trúc-project)
- [Tài liệu](#tài-liệu)

## Tính năng

- **Hai chế độ cuộc gọi**: `text` (transcript) và `audio` (ASR → engine → TTS), dùng chung
  một engine hội thoại.
- **Xác minh danh tính** người gọi bằng họ tên và ngày sinh trước khi thao tác lịch hẹn.
- **Hủy lịch an toàn**: yêu cầu và xác nhận ở hai lượt riêng, ghi nhận lý do hủy.
- **Trích xuất thông tin** bằng luật, có tầng LLM tuỳ chọn để hiểu câu nói vòng và nhận
  diện tên.
- **Voice pipeline**: ASR ZipFormer self-host (hoặc Gemini / PhoWhisper), TTS OpenAI, ElevenLabs hoặc
  Vbee (có thể cấu hình provider dự phòng); giọng bot băng hẹp 8 kHz như đường dây điện thoại,
  clip người gọi giữ tần số gốc rồi resample một lần về 16 kHz của model.
- **Session trên Redis**: chạy được nhiều worker, dữ liệu khách hàng chỉ lưu tạm và tự xoá
  khi cuộc gọi kết thúc hoặc hết hạn; chặn ghi trùng khi kết quả ghi không xác định.

## Yêu cầu

- Python ≥ 3.11
- Redis ≥ 7
- Docker (tuỳ chọn)

## Cài đặt

```bash
git clone <repo-url>
cd callbot-vinmec

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
pip install -e ".[speech]"           # tuỳ chọn: Gemini ASR
pip install -e ".[speech-local]"     # tuỳ chọn: PhoWhisper self-hosted

cp .env.example .env
# Nếu dùng Docker Compose, đặt REDIS_PASSWORD riêng trong .env trước khi chạy.
```

## Cấu hình

Cấu hình mặc định nằm trong [config/](config/), mỗi module một file YAML. Code không chứa giá trị
mặc định; secret chỉ đặt trong `.env` (mẫu: [.env.example](.env.example)).

| File | Nội dung |
|---|---|
| `speech.yaml` | Chọn provider ASR/TTS (`asr_provider`, `tts_provider`, `tts_fallback_provider`), VAD, turn-taking, `public_base_url` |
| `asr.yaml` / `tts.yaml` | Model, voice, timeout, đường dẫn asset của từng provider |
| `llm.yaml` | Endpoint, model, timeout, max tokens của từng provider LLM |
| `engine.yaml` | `name_fallback_provider`, `semantic_fallback_*`, `clinic_id`, giới hạn hội thoại |
| `session.yaml` | Redis URL local không mật khẩu, TTL và giới hạn session |
| `http.yaml` | Clinic backend (`mock` \| `sim`), dataset/scenario của sim; quản trị demo mặc định tắt |
| `livekit.yaml` | Frame, queue, sample rate của đường LiveKit |

Thứ tự ưu tiên: biến môi trường > `.env` > YAML. Ghi đè một khóa bằng biến cùng tên viết hoa
(vd. `VAD_PROVIDER=webrtc`); khóa nào có tên biến riêng thì được ghi ngay cạnh khóa đó trong file
YAML. Để trống (`KEY=`) nghĩa là dùng giá trị YAML. `.env` chỉ cần API key, `CLINIC_MOCK_API_KEY`,
`BOT_API_KEYS`, LiveKit và Redis password.

Chỉ cần API key của provider đang bật. Với cấu hình mặc định (ZipFormer + OpenAI TTS) cần
`OPENAI_API_KEY`. Khi `CLINIC_BACKEND=mock`, cần thêm `CLINIC_MOCK_BASE_URL` và
`CLINIC_MOCK_API_KEY`; chế độ `sim` không cần hai biến này.

## Sử dụng

Khởi động Redis và server:

```bash
docker run --rm -p 127.0.0.1:6379:6379 redis:7.4-alpine redis-server \
  --save "" --appendonly no --maxmemory 256mb --maxmemory-policy noeviction

uvicorn callbot.transports.http.main:app --reload
```

Server chạy tại `http://localhost:8000`.

### API

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/v1/calls` | Bắt đầu cuộc gọi |
| `POST` | `/v1/calls/{call_id}/turn` | Gửi một lượt của người gọi, nhận câu trả lời của bot |
| `GET` | `/health` | Kiểm tra server còn sống |
| `GET` | `/ready` | Kiểm tra server sẵn sàng (kết nối Redis và dọn session) |
| `POST` | `/v1/stt/turn`, `/v1/stt/turn/upload` | Thử STT trên một lượt nói (bật bằng `STT_EVAL_ENABLED=true`), xem [stt-eval-api.md](docs/reference/stt-eval-api.md) |
| `POST` | `/v1/stt/transcribe`, `/v1/stt/transcribe/upload` | Thử STT trên file dài nhiều câu (cùng cờ và tài liệu) |

Ví dụ:

```bash
curl -X POST http://localhost:8000/v1/calls \
  -H "Content-Type: application/json" \
  -d '{"call_id":"c_demo","direction":"outbound","appointment_id":"apt_00417","mode":"text"}'
```

Chi tiết request/response và mã lỗi: [docs/reference/http-api.md](docs/reference/http-api.md).

### Giao diện web (`ui/`)

Mở `http://localhost:8000/ui/` (hoặc `/`, tự chuyển hướng):

| Trang | Dùng để |
|---|---|
| `/ui/call` | Gọi thử qua HTTP contract: gõ lời người gọi, hoặc ghi âm từ microphone (trang tự upload WAV và gửi `audio_url`). Có bảng trích xuất, request/response, kịch bản mẫu |
| `/ui/livekit` | Nói chuyện trực tiếp với bot qua WebRTC/LiveKit, hiện lời thoại từng lượt để trace |
| `/ui/observability` | Latency, lỗi, chất lượng STT/TTS, chi tiết cuộc gọi và từng lượt (đọc từ trace ẩn danh) |

Link cũ `/demo/`, `/demo/livekit-demo.html`, `/observability/` chuyển hướng sang trang mới.
Microphone chỉ hoạt động trên HTTPS hoặc `localhost`.

UI viết bằng Vite + React + TypeScript, build ra file tĩnh và được chính FastAPI phục vụ: server không
chạy thêm process nào cho UI. Thiết kế và các pha chuyển đổi: [docs/plans/ui-vite-react.md](docs/plans/ui-vite-react.md).

Cần Node 22. Phát triển UI (backend chạy ở `localhost:8000`, Vite tự chuyển tiếp request API):

```bash
cd ui
npm install
npm run dev      # http://localhost:5173/ui/
npm run check    # lint + format check + typecheck + test
npm run e2e      # Playwright, cần backend thật đang chạy (xem ui/playwright.config.ts)
```

Xem bản build qua chính FastAPI: `npm run build` rồi chạy uvicorn với `UI_DIST_DIR=ui/dist`.

Type request/response của UI sinh từ OpenAPI của backend. Đổi schema hoặc route thì chạy
`make openapi` (ghi `ui/openapi.json`) rồi `npm run api:types` trong `ui/`, và commit cả hai file.
CI báo đỏ nếu hai file này lệch với backend.

Thêm thư viện npm thì kiểm tra lockfile với npm 10 (bản đi kèm Node 22 trong Docker/CI) bằng
`docker build --target ui .`: npm 11 có thể ghi lockfile mà `npm ci` của npm 10 từ chối.

## Chạy bằng Docker

Chạy cả Redis và bot:

```bash
# Đặt REDIS_PASSWORD trong .env trước khi chạy.
docker compose up -d --build
```

Docker local mặc định dùng **clinic giả trong bộ nhớ** (`CLINIC_BACKEND=sim`, 1 worker): không cần
mạng hay `CLINIC_MOCK_API_KEY`, dữ liệu về ban đầu sau `docker compose restart bot`. Muốn gọi clinic
mock đã deploy thì đặt `CLINIC_BACKEND=mock` trong `.env`. Bản deploy luôn dùng mock. Chi tiết và
cách demo edge case: [src/clinic_mock_sim/README.md](src/clinic_mock_sim/README.md#demo-bằng-docker-local).

Hoặc chỉ build image bot:

```bash
docker build -t vinmec-callbot .
docker run --rm -p 8000:8000 --env-file .env vinmec-callbot
```

Image tự tải model ZipFormer khi build.

## Kiểm thử

```bash
# Tuỳ chọn: bật test tích hợp với Redis thật
export TEST_REDIS_URL=redis://localhost:6379/15

make check     # lint + format check + pytest + ui/openapi.json khớp backend
make format    # tự sửa lint + format
make test      # chỉ pytest
```

Test không gọi clinic mock thật: fixture `clinic` (và `client`) chạy trên `clinic_mock_sim`, kèm
edge case dựng sẵn qua `clinic_scenario(...)`. Hướng dẫn: [src/clinic_mock_sim/README.md](src/clinic_mock_sim/README.md).

Không có `make` (Windows):

```bash
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
python scripts/export_openapi.py --check
```

Test UI: `npm run check` trong `ui/` (Vitest + Testing Library, API giả bằng MSW).

## Cấu trúc project

```
src/
├── callbot/
│   ├── transports/
│   │   ├── http/               # FastAPI app: endpoint cuộc gọi, demo, schemas
│   │   └── phone/              # kết nối tổng đài điện thoại
│   ├── engine/                 # engine hội thoại, không phụ thuộc transport
│   │   ├── orchestrator.py     # điều phối một lượt
│   │   ├── session/            # session trên Redis: TTL, khoá, thứ tự lượt
│   │   ├── extraction/         # trích xuất thông tin: luật, slot filling tên, tầng ngữ nghĩa
│   │   ├── dialogue/           # quản lý hội thoại và câu trả lời mẫu
│   │   ├── policy/             # chính sách chuyển máy và guardrails
│   │   ├── verification/       # xác minh danh tính
│   │   └── tools/              # Clinic Gateway và client Clinic API
│   └── tracing/                # log mỗi lượt ra JSONL
├── speech/                     # voice pipeline
│   ├── audio/                  # codec WAV/G.711, chuẩn hoá PCM 8 kHz, lưu WAV cho audio_url
│   ├── asr/                    # VAD → ASR → transcript
│   └── bundle.py               # nối ASR/TTS gateway + nơi lưu audio cho mode=audio
├── inference/                  # provider model dùng chung
│   ├── llm/                    # LLM gateway, prompt, provider
│   ├── asr/                    # Gemini / PhoWhisper / ZipFormer
│   └── tts/                    # OpenAI / ElevenLabs / Vbee + fallback (thư mục TTS duy nhất)
└── clinic_mock_sim/            # clinic mock trong bộ nhớ: test + demo Docker local (deploy luôn dùng mock)
ui/                             # UI Vite + React + TypeScript, build ra file tĩnh phục vụ tại /ui
tests/                          # cùng cấu trúc với src/
docs/reference/                 # tài liệu thiết kế
```

## Tài liệu

| Chủ đề | Tài liệu |
|---|---|
| Kiến trúc tổng thể | [ai-callbot-architecture.md](docs/reference/ai-callbot-architecture.md) |
| HTTP API | [http-api.md](docs/reference/http-api.md) |
| Information Extraction | [information-extraction-design.md](docs/reference/information-extraction-design.md) |
| LLM gateway | [llm-gateway.md](docs/reference/llm-gateway.md) |
| Slot filling họ tên | [name-slot-filling.md](docs/reference/name-slot-filling.md) |
| Vận hành session | [session-operations.md](docs/reference/session-operations.md) |
| Luồng STT | [stt-flow.md](docs/reference/stt-flow.md) |
| API thử chất lượng STT | [stt-eval-api.md](docs/reference/stt-eval-api.md) |
| Cài model ZipFormer | [zipformer-model-setup.md](docs/reference/zipformer-model-setup.md) |
| Clinic API | [clinic-mock.md](docs/reference/clinic-mock.md) |
| Clinic giả cho test | [clinic_mock_sim/README.md](src/clinic_mock_sim/README.md) |
| Phone leg | [phone-leg-architecture.md](docs/reference/phone-leg-architecture.md) |

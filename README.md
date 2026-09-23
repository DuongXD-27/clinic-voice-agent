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
- **Voice pipeline**: ASR ZipFormer self-host (hoặc Gemini / PhoWhisper), TTS OpenAI hoặc
  ElevenLabs, âm thanh băng hẹp 8 kHz như đường dây điện thoại.
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
```

## Cấu hình

Toàn bộ cấu hình nằm trong `.env`, xem mẫu và chú thích ở [.env.example](.env.example).

| Nhóm | Biến chính |
|---|---|
| API key model | `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` |
| Clinic API | `CLINIC_BACKEND` (`mock` \| `sim`), `CLINIC_MOCK_BASE_URL`, `CLINIC_MOCK_API_KEY`, `CLINIC_ID`, `CLINIC_SIM_*` |
| Voice pipeline | `ASR_PROVIDER` (`zipformer` \| `gemini` \| `phowhisper`), `TTS_PROVIDER` (`openai` \| `elevenlabs`), `PUBLIC_BASE_URL` |
| Extraction qua LLM | `SEMANTIC_FALLBACK_*`, `NAME_FALLBACK_*` |
| Session | `REDIS_URL`, `REDIS_PASSWORD`, `SESSION_*` |

Chỉ cần API key của provider đang bật. Với cấu hình mặc định (ZipFormer + OpenAI TTS) cần
`OPENAI_API_KEY` và `CLINIC_MOCK_API_KEY` (không cần `CLINIC_MOCK_API_KEY` khi `CLINIC_BACKEND=sim`).

## Sử dụng

Khởi động Redis và server:

```bash
docker run --rm -p 6379:6379 redis:7.4-alpine redis-server \
  --save "" --appendonly no --maxmemory 256mb --maxmemory-policy noeviction \
  --requirepass callbot

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

Ví dụ:

```bash
curl -X POST http://localhost:8000/v1/calls \
  -H "Content-Type: application/json" \
  -d '{"call_id":"c_demo","direction":"outbound","appointment_id":"apt_00417","mode":"text"}'
```

Chi tiết request/response và mã lỗi: [docs/reference/http-api.md](docs/reference/http-api.md).

### Giao diện demo

Mở `http://localhost:8000/demo/` để thử cuộc gọi trên trình duyệt:

- `text`: nhập lời người gọi và gửi từng lượt.
- `audio`: thu âm bằng microphone, trang tự upload WAV và gửi `audio_url` cho bot.

Microphone chỉ hoạt động trên HTTPS hoặc `localhost`.

## Chạy bằng Docker

Chạy cả Redis và bot:

```bash
docker compose up --build
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

make check     # lint + format check + pytest
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
```

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
│   │   ├── extraction/         # trích xuất thông tin: luật, NER, tầng ngữ nghĩa
│   │   ├── dialogue/           # quản lý hội thoại và câu trả lời mẫu
│   │   ├── policy/             # chính sách chuyển máy và guardrails
│   │   ├── verification/       # xác minh danh tính
│   │   └── tools/              # Clinic Gateway và client Clinic API
│   └── tracing/                # log mỗi lượt ra JSONL
├── speech/                     # voice pipeline
│   ├── audio/                  # codec WAV/G.711, chuẩn hoá PCM 8 kHz
│   ├── asr/                    # VAD → ASR → transcript
│   └── tts/                    # tổng hợp giọng nói, phục vụ audio_url
├── inference/                  # provider model dùng chung
│   ├── llm/                    # LLM gateway, prompt, provider
│   ├── asr/                    # Gemini / PhoWhisper / ZipFormer
│   └── tts/                    # OpenAI / ElevenLabs
└── clinic_mock_sim/            # clinic mock trong bộ nhớ: test + demo Docker local (deploy luôn dùng mock)
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
| NER tên | [name-ner.md](docs/reference/name-ner.md) |
| Vận hành session | [session-operations.md](docs/reference/session-operations.md) |
| Luồng STT | [stt-flow.md](docs/reference/stt-flow.md) |
| Cài model ZipFormer | [zipformer-model-setup.md](docs/reference/zipformer-model-setup.md) |
| Clinic API | [clinic-mock.md](docs/reference/clinic-mock.md) |
| Clinic giả cho test | [clinic_mock_sim/README.md](src/clinic_mock_sim/README.md) |
| Phone leg | [phone-leg-architecture.md](docs/reference/phone-leg-architecture.md) |

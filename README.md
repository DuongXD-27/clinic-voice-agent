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
      main.py              # FastAPI app: /health, đăng ký router /v1/calls
      calls.py             # 2 endpoint bắt buộc: POST /v1/calls, POST /v1/calls/{id}/turn
      schemas.py           # Pydantic models cho request/response (§4.1)
      config.py            # đọc biến môi trường (CLINIC_MOCK_BASE_URL, ...)
      stub_handlers.py     # handler giả, luôn chuyển máy — xoá khi nối engine (Bước 1)
    # phone/               # phone leg tuần 6 (§1.3.1), chưa làm
  engine/                  # AI Callbot Engine
    session/               # Session Manager: CallContext, FSM, repository
    extraction/            # Information Extraction theo docs/information-extraction-design.md
    nlu/                   # bản cũ, engine đang dùng — thay bằng extraction/ khi nối
    policy/                # PolicyEngine + guardrails SF-01..SF-05
    verification/          # Verifier: xác minh tên + ngày sinh
    dialogue/              # Dialogue Manager, templates, prompts, llm/
    tools/                 # ClinicGateway (If-Match, Idempotency-Key) + ClinicMockClient (HTTP)
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
- Docker (nếu muốn chạy bằng container hoặc dùng `docker-compose`)

## Setup cơ bản (chạy local)

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
pip install -e ".[speech,llm]"      # tuỳ chọn: numpy + Gemini (ASR/LLM)
pip install -e ".[speech-local]"    # tuỳ chọn: PhoWhisper self-hosted

cp .env.example .env   # chỉnh CLINIC_MOCK_BASE_URL nếu cần

uvicorn callbot.transports.http.main:app --reload
```

Server chạy ở `http://localhost:8000`. Kiểm tra nhanh:

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/v1/calls \
  -H "Content-Type: application/json" \
  -d '{"call_id":"c_demo","direction":"outbound","appointment_id":"apt_00417","mode":"text"}'
```

## Chạy test

```bash
pytest
```

## Chạy bằng Docker

```bash
docker build -t vinmec-callbot .
docker run --rm -p 8000:8000 vinmec-callbot
```

`docker-compose.yml` đã có sẵn service `bot`, nhưng service `clinic-mock` hiện
là placeholder (`image: clinic-mock:latest`) — cần thay bằng image thật lấy từ
starter kit của chương trình trước khi chạy `docker compose up` đầy đủ.

## Trạng thái hiện tại

Khung project mới chỉ dựng phần sườn: 2 endpoint theo đúng contract đã chạy
được, nhưng `state_machine.py` chưa có logic của 7 kịch bản (hiện luôn trả về
`TRANSFERRED` như một hành vi an toàn mặc định).
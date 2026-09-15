# Vinmec Callbot

Callbot đặt/xác nhận/hủy/đổi lịch khám qua điện thoại, xây dựng theo hợp đồng
`AIHR-PC-001` (AI Health Residency, Batch 03).

Bot expose 2 endpoint HTTP để một bộ chấm điểm (harness) điều khiển cuộc gọi
theo từng lượt, và gọi ngược lại một "clinic mock" (mock backend phòng khám)
để đọc/ghi lịch hẹn.

## Cấu trúc project

```
app/
  main.py              # FastAPI app: /health, đăng ký router /v1/calls
  config.py            # đọc biến môi trường (CLINIC_MOCK_BASE_URL, ...)
  api/calls.py         # 2 endpoint bắt buộc: POST /v1/calls, POST /v1/calls/{id}/turn
  schemas/calls.py      # Pydantic models cho request/response
  core/state_machine.py # logic hội thoại theo từng kịch bản (đang là skeleton)
  core/guardrails.py    # kiểm tra các lỗi nghiêm trọng SF-01..SF-05
  clients/clinic_mock.py # HTTP client gọi clinic mock (Idempotency-Key, If-Match)
  tracing/jsonl_logger.py # ghi log từng lượt hội thoại ra JSONL
src/callbot/               # core dùng chung cho HTTP harness và phone leg (§1.3.2)
  speech/                  # Realtime STT pipeline + TTS
    audio/                 # codec wav/G.711, chuẩn hoá về PCM 8 kHz băng hẹp, tải audio_url
    vad/                   # FrameClassifier (energy baseline) + StreamingVAD
    asr/                   # ASRProvider: gemini.py, phowhisper.py
    tts/                   # TTSProvider + AudioArtifactStore (sinh audio_url)
    transcript.py          # gộp partial/final
    pipeline.py            # STTPipeline: Audio -> VAD -> ASR -> Transcript
  engine/                  # AI Callbot Engine
    session/               # Session Manager: CallContext, FSM, repository
    nlu/                   # Information Extraction: intent, entity, normalizer
    policy/                # PolicyEngine + guardrails SF-01..SF-05
    verification/          # Verifier: xác minh tên + ngày sinh
    dialogue/              # Dialogue Manager, templates, prompts, llm/
    tools/                 # ClinicGateway: gọi clinic mock kèm If-Match, Idempotency-Key
    orchestrator.py        # CallOrchestrator: điều phối 1 lượt
tests/                   # test cho các endpoint trên; tests/engine/ test core với fake clinic
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

uvicorn app.main:app --reload
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
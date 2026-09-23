# Merge `feature/livekit-realtime-voice` vào `main` — việc dev khác cần biết

Nhánh này thêm nguyên một đường LiveKit streaming (VAD/ASR/TTS/turn-taking) song song với
đường HTTP hiện có. `main` không hề biết tới các module này — dev đang làm việc trên `main`
(engine/dialogue/extraction) không bị ảnh hưởng code, nhưng **sẽ cần cập nhật `.env` và cài
thêm dependency** nếu muốn chạy `docker compose up` hoặc `pytest` sạch sau khi merge.

## 1. Việc cần làm trước khi merge (hoặc ngay sau khi pull)

### a. Cài lại dependency

```bash
pip install -e ".[dev,speech]"
```

`pyproject.toml` thêm 2 dependency mới vào nhóm `speech` (`soxr`, `rapidfuzz`) và 3 nhóm
optional mới: `vad-webrtc`, `vad-silero`, `livekit`. CI chỉ cài `.[dev,speech]` — **không**
cài 3 nhóm optional đó, nên `VAD_PROVIDER=webrtc`/`silero` và toàn bộ code
`callbot/transports/livekit/` không được test bằng dependency thật trên CI (xem mục 3).
Nếu bạn cần chạy worker LiveKit thật ở máy dev:

```bash
pip install -e ".[dev,speech,vad-webrtc,vad-silero,livekit]"
```

### b. Copy biến `.env` mới từ `.env.example`

`.env` không nằm trong git — mỗi người tự giữ file của mình, merge sẽ **không** đụng vào
`.env` thật của ai cả. Nhưng thiếu các biến dưới đây, `SpeechSettings`/`LiveKitSettings`
vẫn chạy được (đều có default hợp lý), **trừ khi bạn thực sự bật LiveKit worker** — khi đó
`LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` bắt buộc phải có giá trị thật.

| Biến | Default nếu bỏ trống | Cần đổi khi nào |
|---|---|---|
| `VAD_PROVIDER` | `energy` | Đổi `webrtc` hoặc `silero` khi chạy đường LiveKit — `energy` dễ hiểu nhầm noise thành turn |
| `VAD_WEBRTC_AGGRESSIVENESS` | `2` | Hiếm khi cần đổi |
| `SILERO_VAD_MODEL_PATH` | `src/speech/asr/vad/assets/silero_vad.onnx` | Bắt buộc tải file model nếu dùng `VAD_PROVIDER=silero` hoặc bật `SPEECH_ADMISSION_ENABLED`/`TURN_VALIDATOR_ENABLED` (2 cái này luôn dùng Silero nội bộ bất kể `VAD_PROVIDER`) — xem lệnh tải trong `.env.example` |
| `SPEECH_ADMISSION_ENABLED` | `false` | Bật `true` để lọc sớm frame SNR thấp trước khi vào ASR |
| `TURN_VALIDATOR_ENABLED` | `false` | Bật `true` để có lớp chặn hallucination cuối trước khi chốt turn |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | rỗng | **Bắt buộc** nếu chạy `python -m callbot.transports.livekit.worker start` |
| `LIVEKIT_INPUT_SAMPLE_RATE` | `16000` | Hiếm khi cần đổi (web giữ wideband) |
| `ZIPFORMER_MIN_DECODE_MS` / `ZIPFORMER_MAX_TURN_SPEECH_MS` | `400` / `15000` | Hiếm khi cần đổi — chống hallucination audio ngắn / chống buffer phình vô hạn |
| `DEEPGRAM_SECRET_KEY` | rỗng | Chỉ cần nếu thử ASR provider Deepgram (benchmark, không phải luồng chính) |

Không có biến nào trong bảng trên là **bắt buộc** để `main` (đường HTTP hiện tại) tiếp tục
chạy đúng — tất cả đều có default an toàn hoặc chỉ ảnh hưởng code LiveKit mới.

### c. Docker Compose có service mới: `livekit-worker`

`docker-compose.yml` và `docker-compose.prod.yml` đều thêm service `livekit-worker` (build
cùng image, `depends_on: redis`). `docker compose up` sau merge sẽ tự khởi động thêm
container này. Nếu chưa có `LIVEKIT_API_KEY`/`SECRET` thật, container này sẽ khởi động
nhưng job LiveKit sẽ không nhận được task nào — không crash, không ảnh hưởng service `bot`
hiện có, nhưng healthcheck riêng của nó (`GET :8081/`) sẽ không pass nếu thiếu asset
ZipFormer. Muốn tắt hẳn khi chưa cần: `docker compose up bot redis caddy` (bỏ qua service
`livekit-worker`).

## 2. Khác biệt code chính so với `main`

| Vùng | Thay đổi |
|---|---|
| `src/callbot/transports/livekit/` (mới) | `worker.py`, `call_bridge.py`, `settings.py` — entrypoint LiveKit Agent, tách biệt hoàn toàn khỏi `transports/http/` |
| `src/speech/turn/` (mới) | `TurnController`, `InterruptionController`, `TurnValidator` — turn-taking/barge-in, không đụng `callbot/engine/*` |
| `src/speech/asr/vad/` | Thêm `webrtc.py`, `silero.py`, `async_stream.py` — VAD provider mới, không đổi `EnergyFrameClassifier` mặc định |
| `src/speech/asr/admission.py`, `evidence.py` (mới) | Speech Admission + Transcript Evidence — 2 lớp phòng thủ hallucination, mặc định TẮT |
| `src/speech/audio/noise_tracker.py` (mới) | SNR liên tục dùng chung cho Admission/Validator |
| `src/inference/asr/providers/zipformer.py` | Thêm `stream()` (chunked-offline streaming) bên cạnh `transcribe()` cũ — không đổi hành vi `transcribe()` |
| `src/inference/asr/providers/elevenlabs_realtime.py` (mới) | ASR provider streaming thật qua WebSocket, opt-in qua `ASR_PROVIDER=elevenlabs_realtime` |

**Không đụng** `src/callbot/engine/*` (dialogue/extraction/orchestrator) — vùng 14 commit
mới nhất trên `main` đã sửa. Hai nhánh công việc độc lập nhau về mặt code, merge không có
conflict thật (đã merge thử, chỉ auto-merge `.env.example`/`.gitignore`, không có
conflict marker).

## 3. Tình trạng CI/CD tại thời điểm viết tài liệu này (2026-09-23)

Đã chạy lại đúng lệnh CI dùng (`make check` = `ruff check` + `ruff format --check` +
`pytest`) trong **venv sạch** cài đúng `pip install -e ".[dev,speech]"` như
`.github/workflows/ci.yml` — không cài thêm `vad-webrtc`/`vad-silero`/`livekit`:

```
ruff check:   All checks passed!
ruff format:  219 files already formatted
pytest:       1919 passed, 34 skipped, 0 failed
```

Không có lỗi cần sửa. 34 test skip là các test opt-in cần API/mock thật (đặt
`CLINIC_MOCK_LIVE=1`, `ELEVENLABS_LIVE=1`, v.v. — gate có chủ đích, không phải lỗi) cộng
thêm các test VAD/LiveKit tự skip khi thiếu extras không nằm trong `[dev,speech]` — đây là
thiết kế có chủ đích (lazy import), không phải lỗ hổng: `main` sau merge vẫn xanh trên CI
với đúng dependency hiện tại của CI, không cần sửa `ci.yml`.

**Điểm cần lưu ý cho dev khác:** vì CI không cài `vad-webrtc`/`vad-silero`/`livekit`, code
trong `src/callbot/transports/livekit/` và `src/speech/asr/vad/{webrtc,silero}.py` **không
được test với dependency thật trên CI** — chỉ được test bằng fake/mock hoặc tự skip. Nếu
muốn CI thật sự chạy được `VAD_PROVIDER=webrtc`/`silero` với package thật, cần sửa
`ci.yml` để cài thêm 3 extras đó — chưa làm trong nhánh này vì tăng thời gian CI mà chưa
có yêu cầu.

## 4. Checklist merge

- [ ] `pip install -e ".[dev,speech]"` lại sau khi pull
- [ ] Không cần sửa `.env` để `main` (đường HTTP) tiếp tục chạy — chỉ cần sửa nếu muốn bật
      LiveKit thật (`LIVEKIT_URL`/`API_KEY`/`API_SECRET`)
- [ ] `docker compose up` sẽ có thêm container `livekit-worker` — bỏ qua bằng cách chỉ định
      service tường minh nếu chưa cần
- [ ] Không có conflict code với vùng `callbot/engine/*` — 2 nhánh việc độc lập
- [ ] CI xanh với dependency hiện tại của `ci.yml`, không cần sửa gì thêm

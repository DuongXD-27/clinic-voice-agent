# Deploy sau khi merge nhánh LiveKit — cần gì, đổi model có sao không

Ngắn gọn: **deploy bình thường không cần đổi gì**. Muốn bật tính năng mới (LiveKit thật,
lọc hallucination, đổi VAD, đổi model) thì mới cần sửa `.env`. Riêng **đổi model ASR** thì
sửa `.env` một mình **không có tác dụng** — phải sửa cả `Dockerfile`, xem mục 3.

## 1. Deploy không đổi gì (giữ nguyên hành vi cũ)

CD (`.github/workflows/cd.yml`) tự build và deploy khi merge vào `main`, không cần làm gì
thêm. Service `bot` (đường HTTP hiện tại) chạy y hệt trước — mọi biến mới đều có default an
toàn. Có 1 thay đổi tự động: production giờ chạy thêm 1 container mới —
`livekit-worker` (định nghĩa trong `docker-compose.prod.yml`). Nếu server chưa có
`LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` trong `.env`, container này khởi động
nhưng không nhận được cuộc gọi nào (rỗng, không crash, không ảnh hưởng `bot`) — **nhưng
healthcheck của nó sẽ luôn FAIL** vì thiếu key, `docker compose ps` sẽ báo unhealthy. Không
sao cả, chỉ là noise — muốn dọn cảnh báo đó thì điền LIVEKIT_* thật hoặc tắt hẳn service này.

## 2. Muốn bật LiveKit thật trên production

Thêm vào `.env` trên server (`/opt/callbot/.env`, người vận hành tự sửa — CD không bao giờ
ghi đè file này sau lần đầu):

```bash
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

Sau đó restart: `docker compose --env-file .env --env-file image.env up -d`.

## 3. Đổi model ASR — phải sửa Dockerfile, không chỉ `.env`

Đây là điểm dễ nhầm nhất. Model ASR **không tải qua `.env`** — nó được tải cứng vào
image lúc build, ở [Dockerfile:19-27](../../Dockerfile#L19-L27), và đường dẫn file đó
được **hard-code thêm 1 lần nữa** trong `docker-compose.yml`/`docker-compose.prod.yml`
(cả service `bot` lẫn `livekit-worker`, 4 dòng `ZIPFORMER_*_PATH` mỗi service).

Sửa `.env` một mình (`ZIPFORMER_ENCODER_PATH=...`) **không có tác dụng khi chạy qua
Docker** — vì `docker-compose*.yml` set cứng biến này trong `environment:`, đè lên bất kỳ
giá trị nào trong `.env`. Đường dẫn phải khớp chỗ Dockerfile tải, không phải thứ người
vận hành tự chỉnh qua `.env` được.

**Trạng thái hiện tại (đã đồng bộ):** cả 3 file (`Dockerfile`, `docker-compose.yml`,
`docker-compose.prod.yml`) đã trỏ đúng `g-group-ai-lab/gipformer1.5-68M-rnnt` — khớp với
`.env` local đang dùng. Trước khi sửa, 3 file Docker vẫn tải model `csukuangfj/...` cũ
(đã xác nhận hallucinate nặng) trong khi `.env` đã đổi sang gipformer1.5 — nghĩa là chạy
qua Docker (kể cả production) sẽ dùng nhầm model cũ dù local test bằng model mới. Bài học:
**mỗi lần đổi model, phải sửa cả 3 file này cùng lúc, không chỉ `.env`.**

**Sau khi đổi Dockerfile, bắt buộc phải build lại image** (không tự động) — merge PR vào
`main` sẽ tự trigger build mới qua CD, nên chỉ cần đổi trong nhánh trước khi merge là đủ.

### Đổi VAD sang Silero — asset đã đóng gói sẵn, chỉ cần đổi `.env`

`VAD_PROVIDER=silero` cần file `silero_vad.onnx` — image giờ tự tải file này lúc build
(`Dockerfile`, từ GitHub release `k2-fsa/sherpa-onnx`) vào `/app/models/silero/`, và
`docker-compose.yml`/`docker-compose.prod.yml` đã set `SILERO_VAD_MODEL_PATH` trỏ đúng
đường dẫn đó cho service `livekit-worker`. Không cần sửa gì thêm ở Docker — muốn bật
Silero làm VAD chính trên production chỉ cần thêm vào `.env` server:

```bash
VAD_PROVIDER=silero
```

Không cần build lại image (asset đã có sẵn trong mọi image build từ giờ), chỉ cần restart
service. **Lưu ý:** đây vẫn là tính năng opt-in, chưa phải mặc định — cần thêm dữ liệu thật
đa dạng môi trường trước khi coi là ổn định cho mọi call (xem báo cáo đối chiếu Silero vs
WebRTC trong `docs/evidence/`).

## 4. Bật các lớp chặn hallucination (Speech Admission / Turn Validator)

2 biến này **không nằm trong `docker-compose.prod.yml`**, nghĩa là production đang dùng
default trong code (`false` — TẮT), dù bạn đã bật `true` ở máy dev. Muốn bật trên
production, thêm vào `.env` trên server:

```bash
SPEECH_ADMISSION_ENABLED=true
TURN_VALIDATOR_ENABLED=true
```

Không cần build lại image, không cần sửa Dockerfile — 2 biến này đọc thẳng từ `.env` lúc
container khởi động. Restart service là đủ.

## 5. Bảng tóm tắt: sửa gì để đổi cái gì

| Muốn đổi | Sửa ở đâu | Cần build lại image? |
|---|---|---|
| Bật LiveKit thật | `.env` trên server | Không |
| Bật chặn hallucination (Admission/Validator) | `.env` trên server | Không |
| Đổi model ZipFormer sang bản khác | `Dockerfile` (+ `docker-compose.prod.yml` nếu tên file đổi) | **Có** |
| Đổi VAD chính sang Silero | `.env` trên server (asset đã đóng gói sẵn trong image) | Không |
| Đổi ngưỡng SNR/thời lượng turn | `.env` trên server | Không |

## 6. Việc khác cần biết sau merge (không liên quan deploy)

- Cài lại dependency ở máy dev: `pip install -e ".[dev,speech]"` (thêm `vad-webrtc,vad-silero,livekit`
  nếu muốn chạy LiveKit worker thật ở local).
- CI hiện tại **không cài** `vad-webrtc`/`vad-silero`/`livekit`, nên code LiveKit chỉ được
  test bằng fake/mock trên CI, không phải dependency thật — không phải lỗi, chỉ là giới
  hạn cần biết khi debug CI.

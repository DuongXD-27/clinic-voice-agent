# Stage build UI (ui/, Vite + React). Chỉ lấy thư mục dist/ sang image cuối: Node và
# node_modules không có trong image chạy, server không thêm process hay RAM nào cho UI.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

# libgomp1: onnxruntime (dùng bởi sherpa-onnx) cần libgomp.so.1, không có sẵn trên slim.
# libsndfile1: soundfile — wheel Linux thường đã bundle sẵn, giữ ở đây phòng bản
# platform/kiến trúc nào đó không bundle.
# curl: tải asset Silero VAD trực tiếp từ GitHub release (không có sẵn trên slim).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libsndfile1 curl \
    && rm -rf /var/lib/apt/lists/*

# Model gipformer1.5 bị .gitignore (nặng ~75MB/file) nên không có trong checkout git —
# tải lúc build vào đường dẫn TUYỆT ĐỐI cố định, không phải src/... (sau `pip install .`,
# gói bị copy vào site-packages nên default_paths() tính theo __file__ sẽ trỏ sai chỗ).
# docker-compose set 4 biến ZIPFORMER_*_PATH trỏ đúng vào đây (xem create_asr()).
# Đặt TRƯỚC mọi COPY để layer model không bị invalidate khi sửa code: nếu không, mỗi lần
# build sẽ tải lại ~200MB thành layer mới (digest khác) và EC2/cache GHA giữ thêm một bản.
# Tải thẳng vào local_dir rồi xoá cache HF trong cùng RUN để model không nằm 2 lần trong layer.
# g-group-ai-lab/gipformer1.5-68M-rnnt thay csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20
# (xem docs/reference/livekit-architecture.md §5.2) — model cũ hallucinate nặng trên audio
# thật qua LiveKit; gipformer1.5 decode đúng trên chính những audio đó (đã kiểm chứng thực nghiệm).
RUN pip install --no-cache-dir huggingface_hub && \
    python -c "\
from huggingface_hub import hf_hub_download; \
repo = 'g-group-ai-lab/gipformer1.5-68M-rnnt'; \
files = ['encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt']; \
[hf_hub_download(repo_id=repo, filename=f, local_dir='/app/models/zipformer') for f in files] \
" && \
    rm -rf /root/.cache/huggingface /app/models/zipformer/.cache

# Silero VAD (~600KB, không .gitignore vì nhỏ nhưng vẫn tải lúc build cho nhất quán với
# gipformer1.5 ở trên) — VAD chính mặc định (vad_provider trong config/speech.yaml) và luôn
# dùng cho NoiseTracker (Turn Validator). SILERO_VAD_MODEL_PATH trong docker-compose*.yml phải
# trỏ đúng đường dẫn này.
RUN mkdir -p /app/models/silero && \
    curl -fL -o /app/models/silero/silero_vad.onnx \
    https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx

# Layer dependency: chỉ build lại khi pyproject.toml đổi. Package stub để hatchling build được
# trước khi có src; code thật được cài đè ở bước sau với --no-deps.
COPY pyproject.toml ./
RUN mkdir -p src/appconfig src/callbot src/clinic_mock_sim src/inference src/speech \
    && touch src/appconfig/__init__.py src/callbot/__init__.py src/clinic_mock_sim/__init__.py \
        src/inference/__init__.py src/speech/__init__.py \
    && pip install --no-cache-dir ".[speech,speech-zipformer,livekit,vad-webrtc,vad-silero]" \
    && rm -rf src

COPY src ./src

RUN pip install --no-cache-dir --no-deps --force-reinstall .

# Cấu hình mặc định (config/*.yaml); env vẫn ghi đè từng khóa. Package cài vào site-packages nên
# phải chỉ đường tới config/ — src/appconfig chỉ tự tìm được khi cài editable.
COPY config ./config
ENV CALLBOT_CONFIG_DIR=/app/config

# UI tĩnh phục vụ tại /ui (transports/http/ui.py). Đặt sau các layer model/dependency để sửa UI
# chỉ build lại layer vài trăm KB này.
COPY --from=ui /ui/dist ./ui
ENV UI_DIST_DIR=/app/ui

EXPOSE 8000

ENV WEB_CONCURRENCY=2
# CLINIC_BACKEND=sim: clinic giả nằm trong bộ nhớ từng process, nhiều worker là nhiều bản lệch nhau
# → tự ép 1 worker, không bắt ai sửa WEB_CONCURRENCY trong .env. mock (deploy) giữ nguyên số worker.
CMD ["sh", "-c", "if [ \"$CLINIC_BACKEND\" = sim ]; then export WEB_CONCURRENCY=1; fi; exec uvicorn callbot.transports.http.main:app --host 0.0.0.0 --port 8000 --workers \"$WEB_CONCURRENCY\""]

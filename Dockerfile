FROM python:3.12-slim

WORKDIR /app

# libgomp1: onnxruntime (dùng bởi sherpa-onnx) cần libgomp.so.1, không có sẵn trên slim.
# libsndfile1: soundfile — wheel Linux thường đã bundle sẵn, giữ ở đây phòng bản
# platform/kiến trúc nào đó không bundle.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Model ZipFormer bị .gitignore (nặng ~74MB/file) nên không có trong checkout git —
# tải lúc build vào đường dẫn TUYỆT ĐỐI cố định, không phải src/... (sau `pip install .`,
# gói bị copy vào site-packages nên default_paths() tính theo __file__ sẽ trỏ sai chỗ).
# docker-compose set 4 biến ZIPFORMER_*_PATH trỏ đúng vào đây (xem create_asr()).
# Đặt TRƯỚC mọi COPY để layer model không bị invalidate khi sửa code: nếu không, mỗi lần
# build sẽ tải lại ~200MB thành layer mới (digest khác) và EC2/cache GHA giữ thêm một bản.
# Tải thẳng vào local_dir rồi xoá cache HF trong cùng RUN để model không nằm 2 lần trong layer.
RUN pip install --no-cache-dir huggingface_hub && \
    python -c "\
from huggingface_hub import hf_hub_download; \
repo = 'csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20'; \
files = ['encoder-epoch-12-avg-8.int8.onnx', 'decoder-epoch-12-avg-8.onnx', 'joiner-epoch-12-avg-8.int8.onnx', 'tokens.txt']; \
[hf_hub_download(repo_id=repo, filename=f, local_dir='/app/models/zipformer') for f in files] \
" && \
    rm -rf /root/.cache/huggingface /app/models/zipformer/.cache

# Layer dependency: chỉ build lại khi pyproject.toml đổi. Package stub để hatchling build được
# trước khi có src; code thật được cài đè ở bước sau với --no-deps.
COPY pyproject.toml ./
RUN mkdir -p src/callbot src/inference src/speech \
    && touch src/callbot/__init__.py src/inference/__init__.py src/speech/__init__.py \
    && pip install --no-cache-dir ".[speech-zipformer,livekit,vad-webrtc]" \
    && rm -rf src

COPY src ./src

RUN pip install --no-cache-dir --no-deps --force-reinstall .

EXPOSE 8000

ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec uvicorn callbot.transports.http.main:app --host 0.0.0.0 --port 8000 --workers \"$WEB_CONCURRENCY\""]

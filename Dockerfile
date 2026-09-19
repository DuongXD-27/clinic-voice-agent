FROM python:3.12-slim

WORKDIR /app

# libgomp1: onnxruntime (dùng bởi sherpa-onnx) cần libgomp.so.1, không có sẵn trên slim.
# libsndfile1: soundfile — wheel Linux thường đã bundle sẵn, giữ ở đây phòng bản
# platform/kiến trúc nào đó không bundle.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

# speech-zipformer: sherpa-onnx + soundfile + openai — cần cho mode=audio (§4.1.2) chạy
# ZipFormer 68M self-host + OpenAI TTS trên chính đường HTTP chấm điểm.
RUN pip install --no-cache-dir ".[speech-zipformer]"

# Model ZipFormer bị .gitignore (nặng ~74MB/file) nên không có trong checkout git —
# tải lúc build vào đường dẫn TUYỆT ĐỐI cố định, không phải src/... (sau `pip install .`,
# gói bị copy vào site-packages nên default_paths() tính theo __file__ sẽ trỏ sai chỗ).
# docker-compose set 4 biến ZIPFORMER_*_PATH trỏ đúng vào đây (xem create_asr()).
RUN pip install --no-cache-dir huggingface_hub && \
    python -c "\
from huggingface_hub import hf_hub_download; \
import shutil, pathlib; \
dest = pathlib.Path('/app/models/zipformer'); \
dest.mkdir(parents=True, exist_ok=True); \
repo = 'csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20'; \
files = ['encoder-epoch-12-avg-8.int8.onnx', 'decoder-epoch-12-avg-8.onnx', 'joiner-epoch-12-avg-8.int8.onnx', 'tokens.txt']; \
[shutil.copy(hf_hub_download(repo_id=repo, filename=f), dest / f) for f in files] \
"

EXPOSE 8000

ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec uvicorn callbot.transports.http.main:app --host 0.0.0.0 --port 8000 --workers \"$WEB_CONCURRENCY\""]

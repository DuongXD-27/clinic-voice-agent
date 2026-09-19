# Setup model ZipFormer (ASR)

`ZipFormerASR` (`src/callbot/speech/asr/zipformer.py`) cần 4 file asset không
nằm trong repo (đã gitignore vì nặng ~74MB — xem `.gitignore`). Sau khi
`git clone`/`git pull` về máy mới, phải tự tải các file này trước khi chạy
test/bot local, nếu không `ZipFormerASR` sẽ lỗi `FileNotFoundError` khi khởi tạo.

## Nguồn model

Repo Hugging Face: [`csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20`](https://huggingface.co/csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20)
— bản ZipFormer 68M, export offline (batch), quantize int8.

## Các file cần

| File | Kích thước |
|---|---|
| `encoder-epoch-12-avg-8.int8.onnx` | ~68MB |
| `decoder-epoch-12-avg-8.onnx` | ~5MB |
| `joiner-epoch-12-avg-8.int8.onnx` | ~1MB |
| `tokens.txt` | ~28KB |

## Nơi đặt file

```
src/callbot/speech/asr/assets/zipformer/
```

## Cách tải

Cài `huggingface_hub` (đã có sẵn nếu bạn cài `speech-zipformer` extra qua
`pip install -e ".[speech-zipformer]"`), rồi chạy:

```bash
python - <<'EOF'
from huggingface_hub import snapshot_download

REPO = "csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20"
FILES = [
    "encoder-epoch-12-avg-8.int8.onnx",
    "decoder-epoch-12-avg-8.onnx",
    "joiner-epoch-12-avg-8.int8.onnx",
    "tokens.txt",
]

local_dir = snapshot_download(repo_id=REPO, allow_patterns=FILES)
print(local_dir)
EOF
```

Lệnh trên tải vào cache Hugging Face (`~/.cache/huggingface/hub/`). Copy 4
file từ đó vào thư mục đích:

```bash
SRC=$(python -c "
from huggingface_hub import snapshot_download
print(snapshot_download(
    repo_id='csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20',
    allow_patterns=['*.onnx', 'tokens.txt'],
))
")

DEST=src/callbot/speech/asr/assets/zipformer
mkdir -p "$DEST"
cp "$SRC"/encoder-epoch-12-avg-8.int8.onnx \
   "$SRC"/decoder-epoch-12-avg-8.onnx \
   "$SRC"/joiner-epoch-12-avg-8.int8.onnx \
   "$SRC"/tokens.txt \
   "$DEST"/
```

## Kiểm tra

```bash
python -c "
from callbot.speech.asr.zipformer import ZipFormerASR, default_paths
ZipFormerASR(**default_paths())
print('OK — model load được')
"
```

## Production / CI-CD: không cần copy tay

`Dockerfile` tự tải 4 file này lúc build image, vào `/app/models/zipformer/`
(không phải `src/...` — sau `pip install .` gói bị copy vào site-packages nên
`default_paths()` tính theo `__file__` sẽ trỏ sai chỗ). `docker-compose.yml` /
`docker-compose.prod.yml` set 4 biến `ZIPFORMER_*_PATH` trỏ đúng vào đó, dùng
đúng cơ chế override đã có sẵn trong `create_asr()` (`settings.zipformer_encoder_path
or paths[...]`). Hướng dẫn copy tay ở trên chỉ còn cần khi chạy local ngoài Docker.

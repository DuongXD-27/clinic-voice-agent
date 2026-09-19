FROM python:3.11-slim

WORKDIR /app

# aiortc/PyAV (streamlit-webrtc) cần build/link các lib native này.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libswscale-dev libavfilter-dev libopus-dev libvpx-dev \
    libsrtp2-dev pkg-config gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 -r requirements.txt

COPY . .

# HF Spaces (Docker SDK) luôn expose port 7860 và gọi vào bằng user không phải root.
RUN useradd -m appuser
USER appuser

EXPOSE 7860

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]

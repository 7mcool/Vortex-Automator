# Vortex Automator — image de production pour le VPS
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt yt-dlp pillow rembg onnxruntime

COPY vortex/ vortex/
COPY vps/daily.sh vps/fetch_tiktok.sh vps/
RUN chmod +x vps/*.sh

# La config, les secrets et les données sont montés en volumes :
#   /app/config.toml  /app/secrets/  /app/data/  /app/videos/
CMD ["python", "-m", "vortex", "status"]

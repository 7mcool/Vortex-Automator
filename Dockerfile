# Vortex Automator — image de production pour le VPS
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng \
        fonts-dejavu-core fonts-liberation curl fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/share/fonts/truetype/custom \
    && curl -sL -o /usr/share/fonts/truetype/custom/Anton-Regular.ttf \
        "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf" \
    && curl -sL -o /usr/share/fonts/truetype/custom/ArchivoBlack-Regular.ttf \
        "https://github.com/google/fonts/raw/main/ofl/archivoblack/ArchivoBlack-Regular.ttf" \
    && fc-cache -f

WORKDIR /app
COPY requirements.txt .
# PLAYWRIGHT_BROWSERS_PATH hors de /root/.cache (masqué par le volume cache)
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN pip install --no-cache-dir -r requirements.txt yt-dlp pillow rembg onnxruntime \
        opencv-python-headless playwright \
    && playwright install --with-deps chromium

COPY vortex/ vortex/
COPY assets/ assets/
COPY vps/ vps/
RUN chmod +x vps/*.sh

# La config, les secrets et les données sont montés en volumes :
#   /app/config.toml  /app/secrets/  /app/data/  /app/videos/
CMD ["python", "-m", "vortex", "status"]

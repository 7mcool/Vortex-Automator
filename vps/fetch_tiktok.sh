#!/bin/sh
# Télécharge les nouvelles vidéos TikTok de @hedjav directement sur le VPS
# (remplace 4K Tokkit : plus besoin du PC de Michel).
# - noms de fichiers IDENTIQUES au format 4K Tokkit : hedjav_<timestamp>_<id>.mp4
#   -> le dédoublonnage par nom fonctionne avec l'historique existant
# - --download-archive évite de retélécharger
# - --write-info-json : la légende TikTok est sauvée à côté (le scanner la lit)
set -u
VIDEOS_DIR="${1:-/app/videos/hedjav}"
mkdir -p "$VIDEOS_DIR"

yt-dlp \
  --download-archive "$VIDEOS_DIR/.yt-dlp-archive.txt" \
  --output "$VIDEOS_DIR/hedjav_%(timestamp)s_%(id)s.%(ext)s" \
  --write-info-json \
  --write-thumbnail --convert-thumbnails jpg \
  --playlist-end 50 \
  --sleep-interval 3 --max-sleep-interval 8 \
  --no-progress --ignore-errors \
  "https://www.tiktok.com/@hedjav" || true

# Les miniatures TikTok téléchargées deviennent les covers attendues par le scanner
mkdir -p "$VIDEOS_DIR/cover"
for f in "$VIDEOS_DIR"/hedjav_*.jpg; do
  [ -e "$f" ] || continue
  base=$(basename "$f" .jpg)
  mv -f "$f" "$VIDEOS_DIR/cover/${base}_cover.jpeg"
done
echo "fetch_tiktok termine"

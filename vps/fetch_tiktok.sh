#!/bin/sh
# Télécharge les nouvelles vidéos TikTok directement sur le VPS.
# Multi-profils : liste dans /app/videos/profiles.txt (un @handle par ligne,
# sans le @) — par défaut : hedjav. Tous les fichiers vont dans le même
# dossier avec le nom <profil>_<timestamp>_<id>.mp4 (dédoublonnage conservé).
set -u
VIDEOS_DIR="${1:-/app/videos/hedjav}"
PROFILES_FILE="/app/videos/profiles.txt"
mkdir -p "$VIDEOS_DIR/cover"

if [ -f "$PROFILES_FILE" ]; then
  PROFILES=$(grep -v '^#' "$PROFILES_FILE" | tr -d '@' | tr '\n' ' ')
else
  PROFILES="hedjav"
fi

for P in $PROFILES; do
  [ -n "$P" ] || continue
  echo "--- profil TikTok : @$P ---"
  yt-dlp \
    --download-archive "$VIDEOS_DIR/.yt-dlp-archive.txt" \
    --output "$VIDEOS_DIR/${P}_%(timestamp)s_%(id)s.%(ext)s" \
    --write-info-json \
    --write-thumbnail --convert-thumbnails jpg \
    --playlist-end 50 \
    --sleep-interval 3 --max-sleep-interval 8 \
    --no-progress --ignore-errors \
    "https://www.tiktok.com/@$P" || true
done

# Les miniatures TikTok deviennent les covers attendues par le scanner
for f in "$VIDEOS_DIR"/*.jpg; do
  [ -e "$f" ] || continue
  base=$(basename "$f" .jpg)
  mv -f "$f" "$VIDEOS_DIR/cover/${base}_cover.jpeg"
done
echo "fetch_tiktok termine"

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
    --format "b" --format-sort "vcodec:h264,res,br" --merge-output-format mp4 \
    --retries 10 --fragment-retries 10 --socket-timeout 30 \
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

# AUTO-RÉPARATION : un téléchargement partiel peut laisser un mp4 sans piste
# audio (TikTok bride les vidéos longues). On le supprime et on retire son id
# de l'archive -> il sera retéléchargé au prochain passage.
purged=0
for f in "$VIDEOS_DIR"/*.mp4; do
  [ -e "$f" ] || continue
  if ! ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$f" | grep -q audio; then
    id=$(basename "$f" .mp4 | sed 's/.*_//')
    grep -v "$id" "$VIDEOS_DIR/.yt-dlp-archive.txt" > /tmp/arch && cp /tmp/arch "$VIDEOS_DIR/.yt-dlp-archive.txt"
    rm -f "$f"
    purged=$((purged+1))
  fi
done
echo "fetch_tiktok termine (fichiers muets purges pour re-essai : $purged)"

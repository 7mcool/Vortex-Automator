#!/bin/sh
# Phase 5 (Clipper) — télécharge les LONGUES vidéos des chaînes YouTube sources
# (accord des propriétaires confirmé par Michel), des plus récentes aux plus
# anciennes, par petits lots à chaque exécution.
set -u
SRC_DIR="${1:-/app/videos/sources}"
BATCH="${2:-2}"   # vidéos par chaîne et par exécution
mkdir -p "$SRC_DIR"

CHAINES="lamaisondesagesse cfrèresc EgliseGénérationDaniel ÉgliseVasesdHonneur"

for C in $CHAINES; do
  DEST="$SRC_DIR/$C"
  mkdir -p "$DEST"
  echo "--- chaîne source : @$C ---"
  yt-dlp \
    --extractor-args "youtubepot-bgutilhttp:base_url=http://bgutil-provider:4416" \
    --format "b" --format-sort "vcodec:h264,res:1080,br" --merge-output-format mp4 \
    --retries 10 --fragment-retries 10 --socket-timeout 30 \
    --download-archive "$DEST/.archive.txt" \
    --playlist-end "$BATCH" \
    --output "$DEST/%(upload_date)s_%(id)s.%(ext)s" \
    --write-info-json \
    --match-filter "duration > 300" \
    --sleep-interval 3 --max-sleep-interval 8 \
    --no-progress --ignore-errors \
    "https://www.youtube.com/@$C/videos" || true
done
echo "fetch_youtube termine"
ls -la "$SRC_DIR"/*/ 2>/dev/null | grep -c ".mp4" || true

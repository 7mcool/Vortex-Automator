#!/bin/sh
# Phase 5 (Clipper) — télécharge DEUX catégories de vidéos par chaîne :
#   1. LONGS sermons (directs terminés ≥20 min) → onglet /streams
#   2. COURTS enseignements (3-20 min) → onglet /videos
# Chaque catégorie alimente le découpeur intelligent (clipper.py).
set -u
SRC_DIR="${1:-/app/videos/sources}"
BATCH="${2:-1}"                         # nouvelles vidéos par catégorie/passage
SCAN_LIMIT="${YOUTUBE_SCAN_LIMIT:-50}"        # assez profond pour dépasser les annonces
COOKIES="${YOUTUBE_COOKIES_FILE:-/app/secrets/youtube_cookies.txt}"
mkdir -p "$SRC_DIR"

fetch_channel() {
  C="$1"
  TAB="$2"
  MIN_DUR="$3"
  MAX_DUR="$4"   # 0 = pas de limite haute
  LABEL="$5"
  DEST="$SRC_DIR/$C"
  mkdir -p "$DEST"
  echo "--- @$C/$TAB [$LABEL] (${MIN_DUR}s → ${MAX_DUR}s) ---"

  MATCH="duration >= $MIN_DUR & live_status != is_live"
  if [ "$MAX_DUR" -gt 0 ]; then
    MATCH="$MATCH & duration <= $MAX_DUR"
  fi

  set -- \
    --extractor-args "youtubepot-bgutilhttp:base_url=http://bgutil-provider:4416" \
    --format "bv*[height<=1080]+ba/b[height<=1080]" \
    --merge-output-format mp4 \
    --retries 10 --fragment-retries 10 --socket-timeout 30 \
    --download-archive "$DEST/.archive.txt" \
    --playlist-end "$SCAN_LIMIT" \
    --max-downloads "$BATCH" \
    --output "$DEST/%(upload_date)s_%(id)s.%(ext)s" \
    --write-info-json \
    --match-filter "$MATCH" \
    --sleep-interval 3 --max-sleep-interval 8 \
    --no-progress \
    "https://www.youtube.com/@$C/$TAB"

  if [ -s "$COOKIES" ]; then
    set -- --cookies "$COOKIES" "$@"
  fi
  yt-dlp "$@"
  STATUS=$?
  if [ "$STATUS" -ne 0 ] && [ "$STATUS" -ne 101 ]; then
    echo "ERREUR téléchargement @$C/$TAB [$LABEL] (code $STATUS) — reprise au prochain passage" >&2
  fi
}

# Pour chaque chaîne : sermons LONGS (/streams, ≥20 min) + cours (/videos, 3-20 min)
for CHAN in "lamaisondesagesse" "cfrèresc" "EgliseGénérationDaniel" "ÉgliseVasesdHonneur"; do
  fetch_channel "$CHAN" "streams" 1200 0 "long"
  fetch_channel "$CHAN" "videos" 180 1200 "court"
done

echo "fetch_youtube terminé"
ls -la "$SRC_DIR"/*/ 2>/dev/null | grep -c ".mp4" || true

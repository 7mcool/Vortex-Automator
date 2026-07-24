#!/bin/sh
# Phase 5 (Clipper) — télécharge uniquement les VRAIS sermons longs.
#
# Important : les directs de la Maison de la Sagesse vivent dans /streams.
# `--playlist-end 2` regardait auparavant deux annonces courtes, puis le filtre
# de durée les rejetait : les sermons placés juste après n'étaient jamais vus.
set -u
SRC_DIR="${1:-/app/videos/sources}"
BATCH="${2:-1}"                         # nouveaux sermons par chaîne/passage
MIN_DURATION="${YOUTUBE_MIN_DURATION:-1200}"  # 20 minutes
SCAN_LIMIT="${YOUTUBE_SCAN_LIMIT:-50}"        # assez profond pour dépasser les annonces
COOKIES="${YOUTUBE_COOKIES_FILE:-/app/secrets/youtube_cookies.txt}"
mkdir -p "$SRC_DIR"

fetch_channel() {
  C="$1"
  TAB="$2"
  DEST="$SRC_DIR/$C"
  mkdir -p "$DEST"
  echo "--- chaîne source : @$C/$TAB (>= ${MIN_DURATION}s) ---"

  # Construire les arguments sans `eval` afin que chemins et titres restent sûrs.
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
    --match-filter "duration >= $MIN_DURATION & live_status != is_live" \
    --sleep-interval 3 --max-sleep-interval 8 \
    --no-progress \
    "https://www.youtube.com/@$C/$TAB"

  # Un export Netscape facultatif peut lever le blocage anti-bot des IP de VPS.
  # Sans ce fichier, l'échec reste visible dans le log au lieu d'être masqué.
  if [ -s "$COOKIES" ]; then
    set -- --cookies "$COOKIES" "$@"
  fi
  yt-dlp "$@"
  STATUS=$?
  # yt-dlp utilise 101 lorsque --max-downloads a atteint la limite demandée :
  # c'est ici un succès normal, pas une erreur de téléchargement.
  if [ "$STATUS" -ne 0 ] && [ "$STATUS" -ne 101 ]; then
    echo "ERREUR téléchargement @$C/$TAB (code $STATUS) — reprise au prochain passage" >&2
  fi
}

# La chaîne principale demandée : les vrais sermons sont dans l'onglet streams.
fetch_channel "lamaisondesagesse" "streams"

# Les autres partenaires restent configurés, mais le filtre >=20 min empêche
# d'aspirer leurs annonces et clips courts.
fetch_channel "cfrèresc" "videos"
fetch_channel "EgliseGénérationDaniel" "videos"
fetch_channel "ÉgliseVasesdHonneur" "videos"

echo "fetch_youtube terminé"
ls -la "$SRC_DIR"/*/ 2>/dev/null | grep -c ".mp4" || true

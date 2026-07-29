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
  # Re-contrôlé AVANT CHAQUE téléchargement : la boucle en enchaîne dix, et un
  # seul contrôle initial laisserait passer des dizaines de gigaoctets.
  place_dispo || return 0
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

# Le découpeur ne traite qu'UNE source par passage : sans garde-fou, le
# téléchargement prend une avance que l'encodage ne rattrape jamais.
#
# Deux mesures, toutes deux en MÉGAOCTETS — compter des FICHIERS ne veut rien
# dire quand un direct de 3 h 25 en 1080p pèse 7,5 Go à lui seul (mesuré le 29/07) :
#   1. le retard de découpage (poids du dossier des sources) ;
#   2. l'empreinte TOTALE de Vortex, et non l'espace libre du disque : celui-ci
#      est partagé avec d'autres projets et frôle en permanence les 98 %, si bien
#      qu'un seuil sur `df` suspendrait le téléchargement pour toujours.
MAX_ATTENTE_MO="${YOUTUBE_MAX_BACKLOG_MO:-8192}"
MAX_EMPREINTE_MO="${VORTEX_MAX_FOOTPRINT_MO:-14336}"

mesure_mo() {   # poids d'un dossier, 0 s'il est absent ou illisible
  V=$(du -sm "$1" 2>/dev/null | cut -f1)
  case "$V" in ''|*[!0-9]*) echo 0 ;; *) echo "$V" ;; esac
}

place_dispo() {
  ATTENTE_MO=$(mesure_mo "$SRC_DIR")
  if [ "$ATTENTE_MO" -ge "$MAX_ATTENTE_MO" ]; then
    echo "${ATTENTE_MO} Mo de sources en attente de découpage — téléchargement suspendu"
    return 1
  fi
  EMPREINTE_MO=$(( $(mesure_mo /app/videos) + $(mesure_mo /app/data) ))
  if [ "$EMPREINTE_MO" -ge "$MAX_EMPREINTE_MO" ]; then
    echo "Vortex occupe ${EMPREINTE_MO} Mo (plafond ${MAX_EMPREINTE_MO}) — téléchargement suspendu"
    return 1
  fi
  return 0
}

place_dispo || exit 0

# L'archive `.archive.txt` de chaque chaîne fait tout le travail de mémoire :
# yt-dlp descend la liste du plus récent au plus ancien et s'arrête au premier
# élément non encore téléchargé. Les nouveautés passent donc en priorité, et le
# fonds ancien se comble tout seul, passage après passage, jusqu'à épuisement
# de la chaîne.
for CHAN in "JACAMESSANLIVE" "lamaisondesagesse" "cfrèresc" \
            "EgliseGénérationDaniel" "ÉgliseVasesdHonneur"; do
  fetch_channel "$CHAN" "streams" 1200 0 "live-long"
  # Hors direct : tout ce qui dépasse trois minutes, court comme long.
  fetch_channel "$CHAN" "videos" 180 0 "hors-live"
done

echo "fetch_youtube terminé"
ls -la "$SRC_DIR"/*/ 2>/dev/null | grep -c ".mp4" || true

#!/bin/sh
# Libere l'espace disque en supprimant les fichiers video devenus inutiles.
#
#   - data/exports/*_v.mp4  : rendus dont la video est deja PUBLISHED/SCHEDULED
#   - videos/sources/*.mp4  : sermons dont les extraits sont deja crees (clip_sources)
#
# NE TOUCHE PAS : videos/tiktok_queue (en attente d'approbation TikTok),
# les clips pas encore publies, les transcriptions, les assets, la base.
#
# Le vrai travail est fait par free_space.py (meme dossier) : SQLite et Pillow
# sont dans le conteneur, pas sur l'hote.

set -u
COMPOSE="/opt/vortex/repo/docker-compose.vps.yml"
THRESHOLD_PCT="${VORTEX_DISK_THRESHOLD:-80}"   # nettoie des que le disque depasse 80 %

log() { echo "[free_space] $(date -Iseconds) $*"; }

used_pct() { df / | awk 'NR==2{gsub(/%/,"",$5); print $5}'; }

before=$(used_pct)
if [ "$before" -lt "$THRESHOLD_PCT" ]; then
    log "Disque a ${before}% (seuil ${THRESHOLD_PCT}%) - rien a nettoyer"
    exit 0
fi

log "Disque a ${before}% - nettoyage..."
# Meme verrou que le pipeline : nettoyer pendant qu'il telecharge ou encode
# reviendrait a retirer des fichiers en cours d'ecriture. Si le pipeline
# tourne, le menage saute simplement — il repassera dans trois heures.
flock -n /tmp/vortex-pipeline.lock -c \
  "docker compose -f '$COMPOSE' run --rm --no-deps vortex python3 /app/vps/free_space.py" \
  || log "Pipeline en cours - nettoyage reporte"
after=$(used_pct)
log "Termine : disque ${before}% -> ${after}%"

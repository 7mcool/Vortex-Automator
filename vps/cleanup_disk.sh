#!/bin/sh
# Nettoyage Docker SÉCURISÉ (serveur PARTAGÉ — jamais de prune agressif).
# - Images dangling (layers sans tag)
# - Build cache > 7 jours
# - Logs > 30 jours
# Garde-fou : JAMAIS de volume/image-a/container prune

set -u

log() { echo "[cleanup_disk] $(date -Iseconds) $*"; }

# Images dangling (intermédiaires de build, anciens :latest)
before=$(docker image ls -q 2>/dev/null | wc -l)
docker image prune -f 2>/dev/null || true
after=$(docker image ls -q 2>/dev/null | wc -l)
if [ "$before" != "$after" ]; then
    log "Images : $before → $after ($((before - after)) supprimées)"
fi

# Build cache vieux de plus de 7 jours
docker builder prune --filter until=168h -f 2>/dev/null || true

# Rotation des logs (> 30 jours)
find /opt/vortex/repo/data/logs/ -name '*.log' -mtime +30 -delete 2>/dev/null || true
find /opt/vortex/repo/data/logs/ -name '*.log' -mtime +7 -exec truncate -s 0 {} \; 2>/dev/null || true

# Fichiers temporaires
find /tmp -name 'tmp*' -mtime +1 -user root -delete 2>/dev/null || true

log "Nettoyage Docker terminé"

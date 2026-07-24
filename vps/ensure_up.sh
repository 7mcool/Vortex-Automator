#!/bin/sh
# Garde-fou horaire : vérifie que l'image vortex-automator existe
# (Coolify purge périodiquement les images qu'il ne tracke pas).
# Si l'image a disparu → rebuild. Puis recrée le dashboard forcé.

set -u
cd /opt/vortex/repo || exit 1

IMAGE="vortex-automator:latest"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "[ensure_up] $(date -Iseconds) Image $IMAGE absente — reconstruction..."
    docker compose -f docker-compose.vps.yml build --no-cache vortex
fi

# Le dashboard doit tourner sur la DERNIÈRE image (--pull never = obligatoire,
# sinon compose tente un docker pull de l'image locale → erreur).
if ! docker ps --format '{{.Names}}' | grep -q 'repo-dashboard-1'; then
    echo "[ensure_up] $(date -Iseconds) Dashboard arrêté — redémarrage..."
    docker compose -f docker-compose.vps.yml up -d --force-recreate --pull never dashboard
fi

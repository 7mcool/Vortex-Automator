#!/bin/sh
# Attend la fin de l habillage en cours, puis sort les extraits Sophos.
# La conference est d actualite : elle ne passe pas par la grille horaire.
set -u
cd /opt/vortex/repo
C="docker compose -f docker-compose.vps.yml run --rm --no-deps vortex"

# Attendre que plus aucun rendu ne tourne (au plus 6 h).
i=0
while [ $i -lt 360 ]; do
  if ! docker ps --filter ancestor=vortex-automator:latest --format "{{.Names}}" | grep -q .; then
    break
  fi
  sleep 60
  i=$((i+1))
done

echo "=== [$(date)] miniatures ==="
$C python -m vortex thumbs -n 8
echo "=== [$(date)] publication immediate ==="
$C python -m vortex publish -n 6 --live --maintenant
echo "=== [$(date)] commentaires ==="
$C python -m vortex engage
echo "=== [$(date)] termine ==="
sh vps/notify.sh "Extraits de la Conference Sophos publies. Playlist creee."

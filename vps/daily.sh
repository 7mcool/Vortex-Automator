#!/bin/sh
# Routine quotidienne VPS (lancée par cron via docker compose run)
set -u
cd /app
echo "=== [$(date)] ROUTINE VPS ==="

# 1. Nouvelles vidéos TikTok (directement sur le serveur)
sh vps/fetch_tiktok.sh /app/videos/hedjav

# 1bis. Chaînes YouTube sources + découpage intelligent.
#
# Le découpage doit passer AVANT le téléchargement : une source occupe souvent
# plusieurs gigaoctets et n'est effacée qu'une fois découpée. Dans l'ordre
# inverse, le disque se remplissait plus vite qu'il ne se vidait — le serveur
# est monté à 98 % le 29/07 avec 8,6 Go de sources en attente.
#
# `vortex clip` ne traite qu'une source par appel : on boucle donc pour résorber
# le retard, en s'arrêtant dès qu'il n'y a plus rien à faire ou que le temps
# imparti est écoulé (le pipeline complet doit rester sous six heures).
compter_sources() { find /app/videos/sources -name '*.mp4' 2>/dev/null | wc -l; }

DEBUT_CLIP=$(date +%s)
BUDGET_CLIP="${VORTEX_CLIP_BUDGET:-10800}"   # 3 h
RESTANT=$(compter_sources)
while [ "$RESTANT" -gt 0 ]; do
  python -m vortex clip || break
  APRES=$(compter_sources)
  # Une source qui ne disparaît pas a échoué (transcription illisible, IA
  # muette…). Sans ce test, la boucle la reprendrait indéfiniment.
  if [ "$APRES" -ge "$RESTANT" ]; then
    echo "Aucune source résorbée à ce tour — arrêt du découpage"
    break
  fi
  RESTANT="$APRES"
  ECOULE=$(( $(date +%s) - DEBUT_CLIP ))
  if [ "$ECOULE" -ge "$BUDGET_CLIP" ]; then
    echo "Budget de découpage atteint (${ECOULE}s) — reprise au prochain passage"
    break
  fi
done

sh vps/fetch_youtube.sh /app/videos/sources 1

# 2. Pipeline complet
python -m vortex scan
python -m vortex retry
python -m vortex detect-text -n 30
python -m vortex detect-speaker -n 30    # lit le nom du pasteur à l'écran (hedjav)
python -m vortex transcribe -n 8
python -m vortex prepare -n 10
python -m vortex render -n 8
python -m vortex thumbs -n 8
python -m vortex publish -n 5 --live
python -m vortex engage
python -m vortex status
echo "=== [$(date)] FIN ROUTINE ==="

#!/bin/sh
# Routine quotidienne VPS (lancée par cron via docker compose run)
set -u
cd /app
echo "=== [$(date)] ROUTINE VPS ==="

# 1. Nouvelles vidéos TikTok (directement sur le serveur)
sh vps/fetch_tiktok.sh /app/videos/hedjav

# 1bis. Chaînes YouTube sources (Phase 5) + découpage intelligent d'UNE
# longue vidéo par jour (3-8 extraits alimentent la file de publication)
sh vps/fetch_youtube.sh /app/videos/sources 2
python -m vortex clip

# 2. Pipeline complet
python -m vortex scan
python -m vortex retry
python -m vortex detect-text -n 30
python -m vortex transcribe -n 8
python -m vortex prepare -n 10
python -m vortex render -n 8
python -m vortex thumbs -n 8
python -m vortex publish -n 5 --live
python -m vortex engage
python -m vortex status
echo "=== [$(date)] FIN ROUTINE ==="

#!/bin/sh
# Routine quotidienne VPS (lancée par cron via docker compose run)
set -u
cd /app
echo "=== [$(date)] ROUTINE VPS ==="

# 1. Nouvelles vidéos TikTok (directement sur le serveur)
sh vps/fetch_tiktok.sh /app/videos/hedjav

# 2. Pipeline complet
python -m vortex scan
python -m vortex retry
python -m vortex detect-text -n 30
python -m vortex transcribe -n 8
python -m vortex prepare -n 10
python -m vortex render -n 5
python -m vortex publish -n 5 --live
python -m vortex engage
python -m vortex status
echo "=== [$(date)] FIN ROUTINE ==="

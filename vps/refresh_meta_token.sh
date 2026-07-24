#!/bin/sh
# Renouvellement du token de Page Meta (60 jours).
# Cron hebdomadaire : 0 4 * * 0 (dimanche 4h UTC).
# Le token de Page 60j est ré-échangé → nouveau token 60j → ne meurt jamais.

set -u
META_JSON="/opt/vortex/repo/secrets/meta.json"
TOKEN_FILE="/opt/vortex/repo/secrets/meta_page_token.txt"
LOG="/opt/vortex/repo/data/logs/meta_refresh.log"

log() { echo "[refresh_meta] $(date -Iseconds) $*"; }

if [ ! -f "$META_JSON" ]; then
    log "ERREUR : $META_JSON introuvable"
    exit 1
fi

APP_ID=$(python3 -c "import json; print(json.load(open('$META_JSON'))['app_id'])" 2>/dev/null)
APP_SECRET=$(python3 -c "import json; print(json.load(open('$META_JSON'))['app_secret'])" 2>/dev/null)

if [ -z "$APP_ID" ] || [ -z "$APP_SECRET" ]; then
    log "ERREUR : app_id ou app_secret manquant dans $META_JSON"
    exit 1
fi

# Lire le token actuel
if [ ! -f "$TOKEN_FILE" ]; then
    log "ERREUR : $TOKEN_FILE introuvable"
    exit 1
fi
OLD_TOKEN=$(tr -d '\n' < "$TOKEN_FILE")

# Échange 60j → 60j
RESP=$(curl -s "https://graph.facebook.com/v18.0/oauth/access_token?grant_type=fb_exchange_token&client_id=${APP_ID}&client_secret=${APP_SECRET}&fb_exchange_token=${OLD_TOKEN}&set_token_expires_in_60_days=true")
NEW_TOKEN=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -n "$NEW_TOKEN" ] && [ ${#NEW_TOKEN} -gt 20 ]; then
    printf '%s' "$NEW_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    log "Token Meta renouvelé (${#NEW_TOKEN} caractères)" >> "$LOG"
else
    log "ERREUR renouvellement : $RESP" >> "$LOG"
fi

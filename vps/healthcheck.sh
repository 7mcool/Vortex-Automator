#!/bin/sh
# Vérifie l'état du système Vortex + envoie des alertes Telegram si nécessaire.
# Tous les 6 heures. Un message « tout va bien » 1x/jour (à 6h UTC).
# Utilise le bot Telegram du trading MT5 (token partagé).

set -u
cd /opt/vortex/repo || exit 1

BOT_TOKEN=""
# Récupère le token du bot trading MT5 s'il existe
[ -f /opt/mt5-monitor/monitor.env ] && . /opt/mt5-monitor/monitor.env
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="8641117832"  # Michel

STATUS_FILE="/opt/vortex/repo/data/health_status.txt"
PROBLEMS=""

log_issue() {
    PROBLEMS="${PROBLEMS}${1}\n"
}

send_telegram() {
    if [ -z "$BOT_TOKEN" ]; then
        return 1
    fi
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" -d "text=${1}" -d "parse_mode=HTML" >/dev/null 2>&1 || true
}

# 1. Image Docker présente ?
if ! docker image inspect vortex-automator:latest >/dev/null 2>&1; then
    log_issue "⚠️ Image vortex-automator absente → rebuild en cours"
    docker compose -f docker-compose.vps.yml build --no-cache vortex 2>&1 || log_issue "❌ Rebuild échoué"
fi

# 2. Dashboard répond ?
if ! curl -s -o /dev/null -w '%{http_code}' http://localhost:8787/eWd1nRB_DxIl | grep -q 200; then
    log_issue "⚠️ Dashboard ne répond pas (HTTP != 200) → redémarrage..."
    docker compose -f docker-compose.vps.yml up -d --force-recreate --pull never dashboard 2>&1 || log_issue "❌ Dashboard redémarrage échoué"
    sleep 5
    if curl -s -o /dev/null -w '%{http_code}' http://localhost:8787/eWd1nRB_DxIl | grep -q 200; then
        log_issue "✅ Dashboard réparé"
    else
        log_issue "❌ Dashboard toujours HS"
    fi
fi

# 3. Disque > 90% ?
DISK=$(df / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK" -gt 90 ]; then
    log_issue "⚠️ Disque à ${DISK}% → nettoyage forcé"
    CLEANUP_DRY_RUN=false /opt/vortex/repo/vps/free_space.sh 2>&1 || true
    docker image prune -f 2>&1 || true
fi

# 4. Base de données accessible ?
if ! python3 -c "import sqlite3; db=sqlite3.connect('/app/data/vortex.db'); db.execute('SELECT 1'); db.close()" 2>/dev/null; then
    log_issue "❌ Base de données inaccessible"
fi

# Écrire le bilan
if [ -z "$PROBLEMS" ]; then
    echo "✅ TOUT VA BIEN $(date -Iseconds)" > "$STATUS_FILE"
else
    echo "⚠️ PROBLÈMES $(date -Iseconds)" > "$STATUS_FILE"
    echo "$PROBLEMS" >> "$STATUS_FILE"
fi

# Alerte Telegram si problème (toujours) ou 1x/jour si tout va bien (à 6h UTC)
HOUR=$(date -u +%H)
if [ -n "$PROBLEMS" ]; then
    MSG="🔴 <b>Vortex — problème détecté</b>%0A%0A$(echo "$PROBLEMS" | sed 's/\\n/%0A/g')"
    send_telegram "$MSG"
elif [ "$HOUR" = "06" ]; then
    send_telegram "🟢 <b>Vortex — tout va bien</b>%0A%0ADisque : ${DISK}%%0ADashboard : OK"
fi

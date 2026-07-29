#!/bin/sh
# Envoi Telegram, sur le canal commun a tous les projets de Michel.
#
# Le bot et le salon vivent dans /opt/mt5-monitor/monitor.env (TELEGRAM_TOKEN,
# TELEGRAM_CHAT) : Michel veut UN seul canal pour tout, pas un bot par projet.
# Aucun jeton n'est ecrit ici.
#
#   sh vps/notify.sh "message"        # depuis l'hote
#
# Les messages partent en HTML et sont prefixes « Vortex » pour se distinguer
# des alertes de trading qui arrivent sur le meme salon.

set -u
ENV_COMMUN="${TELEGRAM_ENV:-/opt/mt5-monitor/monitor.env}"
MESSAGE="${1:-}"

[ -z "$MESSAGE" ] && exit 0
if [ ! -r "$ENV_COMMUN" ]; then
    echo "[notify] $ENV_COMMUN illisible — message non envoye" >&2
    exit 1
fi

# shellcheck disable=SC1090
. "$ENV_COMMUN"
TOKEN="${TELEGRAM_TOKEN:-}"
SALON="${TELEGRAM_CHAT:-}"
if [ -z "$TOKEN" ] || [ -z "$SALON" ]; then
    echo "[notify] TELEGRAM_TOKEN ou TELEGRAM_CHAT absent de $ENV_COMMUN" >&2
    exit 1
fi

# --data-urlencode evite d'avoir a echapper les retours a la ligne et les
# accents a la main.
curl -s -o /dev/null -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${SALON}" \
    --data-urlencode "text=🎬 <b>Vortex</b>
${MESSAGE}" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true"

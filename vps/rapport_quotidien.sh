#!/bin/sh
# Rapport quotidien Vortex sur Telegram, en francais clair et sans jargon.
#
# Michel veut savoir chaque jour ce qui est sorti, ce qui attend, et si quelque
# chose cloche — sans avoir a ouvrir le tableau de bord.

set -u
REPO=/opt/vortex/repo
COMPOSE="$REPO/docker-compose.vps.yml"

RESUME=$(docker compose -f "$COMPOSE" run --rm --no-deps vortex python3 - <<'PY' 2>/dev/null
import sqlite3
from datetime import date

db = sqlite3.connect("/app/data/vortex.db")
db.row_factory = sqlite3.Row
aujourdhui = date.today().isoformat()

publiees = db.execute(
    "SELECT COUNT(*) FROM videos WHERE publish_at LIKE ?", (aujourdhui + "%",)
).fetchone()[0]
etats = {r["state"]: r["n"] for r in db.execute(
    "SELECT state, COUNT(*) n FROM videos GROUP BY state")}

lignes = [f"{publiees} vidéo(s) programmée(s) aujourd'hui"]
lignes.append(f"{etats.get('READY', 0)} prête(s) · {etats.get('SCHEDULED', 0)} en attente de diffusion")
lignes.append(f"{etats.get('PUBLISHED', 0)} en ligne au total")

bloquees = etats.get("BLOCKED", 0) + etats.get("FAILED", 0)
if bloquees:
    lignes.append(f"⚠️ {bloquees} vidéo(s) bloquée(s) — à regarder")

titres = [r["title"] for r in db.execute(
    "SELECT title FROM videos WHERE publish_at LIKE ? ORDER BY publish_at LIMIT 5",
    (aujourdhui + "%",)) if r["title"]]
if titres:
    lignes.append("")
    lignes.append("Au programme :")
    lignes += [f"• {t[:70]}" for t in titres]
db.close()
print("\n".join(lignes))
PY
)

DISQUE=$(df -Pm / | awk 'NR==2{printf "%d Go libres", $4/1024}')
[ -z "$RESUME" ] && RESUME="Impossible de lire l'état du système."

sh "$REPO/vps/notify.sh" "$RESUME

💾 Serveur : $DISQUE"

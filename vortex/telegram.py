"""Module Telegram — envoi et lecture de messages via le bot partagé MT5.

Le bot vit dans /opt/mt5-monitor/monitor.env sur le VPS (TELEGRAM_TOKEN,
TELEGRAM_CHAT). Sur le PC, ces variables sont absentes et les appels sont
simulés — aucun message ne part, aucune réponse n'est lue.

Le bot est PARTAGÉ avec le trading MT5 : on n'est pas seuls sur le canal.
On filtre donc les réponses en ne retenant QUE celles qui répondent à un
message que NOUS avons envoyé (reply_to_message.message_id).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT", "")

# Fichier qui mémorise le dernier update_id traité. On le stocke dans le
# répertoire data/ pour qu'il survive aux reconstructions Docker (le volume
# data/ est bind-mounté). /app/data est le chemin conteneur ; en local on
# utilise le répertoire data/ du dépôt.
def _fichier_offset() -> Path:
    base = Path(os.environ.get("VORTEX_DATA_DIR", "data"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "telegram_offset.txt"


# ---------------------------------------------------------------------------
# API Telegram (bas niveau, sans dépendance)
# ---------------------------------------------------------------------------

def _post(method: str, payload: dict) -> dict:
    """Appelle une méthode de l'API Telegram. Retourne la réponse JSON."""
    if not TOKEN:
        return {"ok": False, "description": "TELEGRAM_TOKEN absent"}
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


# ---------------------------------------------------------------------------
# Envoi
# ---------------------------------------------------------------------------

def envoyer_message(texte: str) -> int:
    """Envoie un message HTML dans le salon configuré.

    Retourne l'identifiant Telegram du message (message_id), ou 0 si l'envoi
    a échoué. Cet identifiant sert à lier les réponses de Michel.
    """
    if not TOKEN or not CHAT_ID:
        print("[telegram] TELEGRAM_TOKEN ou TELEGRAM_CHAT absent — message simulé :")
        print(texte[:200])
        return 0

    reponse = _post("sendMessage", {
        "chat_id": CHAT_ID,
        "text": f"🎬 <b>Vortex</b>\n{texte}",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    if reponse.get("ok"):
        msg_id = reponse["result"]["message_id"]
        print(f"[telegram] Message envoyé (id={msg_id})")
        return msg_id
    print(f"[telegram] Échec de l'envoi : {reponse.get('description', '?')}")
    return 0


def signaler_action(texte: str) -> bool:
    """Envoie un message de statut (lancement, échec, rappel…).

    Plus léger que envoyer_message : retourne juste True/False.
    """
    return envoyer_message(texte) > 0


# ---------------------------------------------------------------------------
# Lecture des réponses
# ---------------------------------------------------------------------------

def lire_reponses(depuis_minutes: int = 1440) -> list[dict]:
    """Interroge getUpdates et extrait les réponses aux messages Vortex.

    Ne retourne QUE les messages qui :
    1. Répondent à un message que NOUS avons envoyé (reply_to_message)
    2. Contiennent un mot-clé d'action (GO, OUI, OK, NON, STOP, …)
    3. Datent de moins de `depuis_minutes` minutes

    ⚠️ La fenêtre est LARGE (24 h) à dessein. L'offset Telegram garantit déjà
    qu'un message n'est lu qu'une fois ; la fenêtre ne sert qu'à ignorer un
    vieux fond de salon. Une fenêtre serrée serait dangereuse : si un passage
    du cron saute (verrou flock, conteneur occupé), la réponse de Michel a
    déjà été consommée par l'offset et serait écartée pour ancienneté —
    perdue définitivement, le sermon restant bloqué jusqu'à l'abandon.

    Retourne une liste de dicts :
        {update_id, message_id, reply_to_message_id, texte, date_ts, action}
    où action ∈ {"GO", "NON"}.
    """
    if not TOKEN:
        return []

    # Lire l'offset sauvegardé pour ne pas re-traiter les anciens messages.
    chemin = _fichier_offset()
    dernier = 0
    if chemin.is_file():
        try:
            dernier = int(chemin.read_text().strip())
        except ValueError:
            dernier = 0

    reponse = _post("getUpdates", {
        "offset": dernier + 1,
        "timeout": 10,
        "allowed_updates": ["message"],
    })

    if not reponse.get("ok"):
        return []

    updates = reponse.get("result", [])
    if not updates:
        return []

    maintenant = time.time()
    seuil = maintenant - (depuis_minutes * 60)
    resultats = []

    # Mots-clés que Michel peut taper pour répondre. Tout est insensible à la
    # casse et aux accents.
    MOTS_GO = {"go", "oui", "ok", "yes", "lance", "envoie", "valide", "feu", "top", "bon"}
    MOTS_NON = {"non", "no", "stop", "laisse", "ignore", "ecarte", "passe", "annule"}

    for upd in updates:
        msg = upd.get("message", {})
        if not msg:
            continue

        # On ne regarde que les réponses à nos messages.
        reply_to = msg.get("reply_to_message", {})
        if not reply_to:
            continue

        texte = (msg.get("text") or "").strip()
        if not texte:
            continue

        date_unix = msg.get("date", 0)
        if date_unix < seuil:
            continue

        # Déterminer l'action.
        mots = texte.lower().replace("é", "e").replace("è", "e").replace("ê", "e").split()
        action = ""
        if any(m in MOTS_GO for m in mots):
            action = "GO"
        elif any(m in MOTS_NON for m in mots):
            action = "NON"

        if not action:
            continue

        resultats.append({
            "update_id": upd["update_id"],
            "message_id": msg["message_id"],
            "reply_to_message_id": reply_to["message_id"],
            "texte": texte,
            "date_ts": date_unix,
            "action": action,
        })

    # Sauvegarder le dernier update_id traité.
    if updates:
        dernier_id = max(u["update_id"] for u in updates)
        chemin.write_text(str(dernier_id))

    return resultats

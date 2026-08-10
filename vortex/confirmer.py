"""Phase 1 du protocole de confirmation : détecter → notifier.

Cherche les sources REPERE des chaînes d'Amessan, prépare le plan OpusClip,
envoie un message Telegram détaillé, et marque la source A_CONFIRMER.

    python -m vortex confirmer          # une seule source par appel
    python -m vortex confirmer -n 3     # jusqu'à 3 sources

Ne dépense AUCUN crédit. Le message Telegram contient tout ce que Michel
doit savoir pour décider : titre, durée, fenêtre, coût, budget restant.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import opusclip, telegram
from .config import Config
from .db import Database

logger = logging.getLogger(__name__)


def _message_confirmation(plan: dict, credits_restants: int, src: dict) -> str:
    """Construit le texte HTML du message Telegram."""
    f = plan["fenetre"]
    duree_f = f["fin_s"] - f["debut_s"]

    def _hms(s):
        m, sec = divmod(int(s), 60)
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}" if h else f"{m} min {sec:02d}" if m else f"{sec}s"

    lignes = [
        f"<b>{plan['titre'][:100]}</b>",
        "",
        f"Chaîne : {src.get('chaine', '?')}",
        f"Orateur : {src.get('pasteur', 'non identifié')}",
        f"Vidéo : {_hms(plan['duree_s'])} — "
        f"https://www.youtube.com/watch?v={plan['youtube_id']}",
        f"Fenêtre : {_hms(f['debut_s'])} → {_hms(f['fin_s'])} "
        f"({duree_f // 60} min) — {f['certitude']}",
        f"Extraits : {plan['demande']['curationPref']['clipDurations'][0][0] // 60}-"
        f"{plan['demande']['curationPref']['clipDurations'][0][1] // 60} min",
        "",
        f"💰 <b>{plan['credits']} crédits</b> "
        f"({credits_restants} restants ce mois-ci)",
        "",
        "Réponds <b>GO</b> pour lancer le découpage — <b>NON</b> pour ignorer.",
    ]
    return "\n".join(lignes)


def confirmer(cfg: Config, db: Database, limite: int = 1) -> dict:
    """Détecte et notifie. Retourne un bilan {proposes, envoyes, erreurs}."""
    if not telegram.TOKEN or not telegram.CHAT_ID:
        logger.warning("Telegram non configuré — aucune confirmation envoyée.")
        return {"proposes": 0, "envoyes": 0, "erreurs": 0,
                "raison": "TELEGRAM_TOKEN ou TELEGRAM_CHAT absent"}

    # Budget réel : ce qui a déjà été engagé ce mois.
    debut_mois = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    deja = db.credits_depenses_depuis(debut_mois)
    restants = cfg.opus_credits_par_mois - deja

    # Chercher les sources REPERE des chaînes réservées à Amessan.
    reserves = set(cfg.opus_chaines_reservees)
    candidates = []
    for src in db.sources_par_etat("REPERE"):
        if src["handle"] not in reserves:
            continue
        # Vérifier que la source n'a pas déjà un message Telegram.
        if src.get("telegram_msg"):
            continue
        candidates.append(src)

    if not candidates:
        return {"proposes": 0, "envoyes": 0, "erreurs": 0,
                "raison": "aucune source REPERE des chaînes réservées"}

    # Trier : le plus récent d'abord, puis le plus vu.
    candidates.sort(key=lambda s: (s["published_at"] or "", s["view_count"] or 0),
                    reverse=True)

    bilan = {"proposes": 0, "envoyes": 0, "erreurs": 0}
    for src in candidates[:limite]:
        bilan["proposes"] += 1
        try:
            plan = opusclip.preparer(cfg, dict(src))
        except opusclip.OpusError as exc:
            logger.warning("Confirmation %s — écarté : %s", src["youtube_id"], exc)
            bilan["erreurs"] += 1
            continue
        except Exception:
            logger.exception("Confirmation %s — erreur inattendue", src["youtube_id"])
            bilan["erreurs"] += 1
            continue

        if plan["credits"] > restants:
            logger.info("%s — pas assez de crédits (%d > %d)",
                        src["youtube_id"], plan["credits"], restants)
            # On le laisse REPERE, il sera proposé le mois prochain.
            bilan["erreurs"] += 1
            continue

        msg = _message_confirmation(plan, restants, dict(src))
        telegram_id = telegram.envoyer_message(msg)

        if telegram_id:
            db.maj_source(src["youtube_id"], etat="A_CONFIRMER",
                          telegram_msg=str(telegram_id))
            bilan["envoyes"] += 1
            restants -= plan["credits"]  # réserver virtuellement pour les suivants
        else:
            bilan["erreurs"] += 1

    return bilan

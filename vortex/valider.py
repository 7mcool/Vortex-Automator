"""Phase 2 du protocole de confirmation : lire les réponses → enchaîner.

Interroge Telegram pour savoir si Michel a répondu GO ou NON aux messages
de confirmation. En cas de GO, lance OpusClip (crédits dépensés). En cas
de NON, écarte la source.

    python -m vortex valider            # traite toutes les confirmations en attente
    python -m vortex valider --live     # lance RÉELLEMENT OpusClip (sinon simulation)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import opusclip, telegram
from .config import Config
from .db import Database

logger = logging.getLogger(__name__)

# Une confirmation qui traîne depuis plus de 24 h reçoit un rappel.
# Après 48 h sans réponse, on repasse en REPERE (Michel est peut-être
# passé à côté du message, ou en déplacement).
DELAI_RAPPEL_S = 24 * 3600
DELAI_ABANDON_S = 48 * 3600


def valider(cfg: Config, db: Database, *, live: bool = False) -> dict:
    """Lit les réponses Telegram et exécute GO/NON.

    Retourne un bilan {lances, ecartes, rappels, abandonnes, en_attente}.
    """
    if not telegram.TOKEN:
        logger.warning("Telegram non configuré — impossible de lire les réponses.")
        return {"lances": 0, "ecartes": 0, "rappels": 0, "abandonnes": 0,
                "en_attente": 0, "raison": "TELEGRAM_TOKEN absent"}

    maintenant = datetime.now(timezone.utc)
    maintenant_ts = maintenant.timestamp()

    # Toutes les sources en attente de confirmation.
    en_attente = []
    for etat in ("A_CONFIRMER",):
        en_attente.extend(db.conn.execute(
            "SELECT * FROM sources_yt WHERE etat = ?", (etat,)
        ).fetchall())

    if not en_attente:
        return {"lances": 0, "ecartes": 0, "rappels": 0, "abandonnes": 0,
                "en_attente": 0}

    # Lire les réponses Telegram (fenêtre large : voir telegram.lire_reponses).
    reponses = telegram.lire_reponses()

    # Indexer les réponses par message_id auquel elles répondent.
    par_message = {}
    for r in reponses:
        cible = r["reply_to_message_id"]
        if cible not in par_message:
            par_message[cible] = r

    bilan = {"lances": 0, "ecartes": 0, "rappels": 0, "abandonnes": 0,
             "en_attente": len(en_attente)}

    debut_mois = maintenant.replace(day=1, hour=0, minute=0, second=0, microsecond=0
                                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    deja = db.credits_depenses_depuis(debut_mois)
    restants = cfg.opus_credits_par_mois - deja

    for src in en_attente:
        telegram_msg = src["telegram_msg"]
        youtube_id = src["youtube_id"]

        if not telegram_msg:
            # Pas de message Telegram associé — ne devrait pas arriver.
            db.maj_source(youtube_id, etat="REPERE")
            bilan["abandonnes"] += 1
            bilan["en_attente"] -= 1
            continue

        reponse = par_message.get(int(telegram_msg))

        if reponse and reponse["action"] == "GO":
            # Michel a dit GO → on lance OpusClip.
            try:
                plan = opusclip.preparer(cfg, dict(src))
            except opusclip.OpusError as exc:
                logger.warning("Validation %s — écarté : %s", youtube_id, exc)
                db.maj_source(youtube_id, etat="ECARTE",
                              erreur=f"plan invalide au moment du GO : {exc}")
                telegram.signaler_action(
                    f"❌ <b>{src['titre'][:80]}</b>\n"
                    f"Plan invalide : {exc}"
                )
                bilan["ecartes"] += 1
                bilan["en_attente"] -= 1
                continue
            except Exception:
                logger.exception("Validation %s — erreur inattendue", youtube_id)
                bilan["en_attente"] -= 1
                continue

            if plan["credits"] > restants:
                telegram.signaler_action(
                    f"⚠️ <b>{src['titre'][:80]}</b>\n"
                    f"GO reçu mais plus que {restants} crédits "
                    f"(il en faut {plan['credits']})."
                )
                bilan["en_attente"] -= 1
                continue

            if not live:
                opusclip.afficher_plan(plan, restants)
                print(f"  SIMULATION — {plan['credits']} crédits NON dépensés.")
                print("  Ajoute --live pour lancer réellement.")
                bilan["en_attente"] -= 1
                continue

            try:
                projet = opusclip.creer_projet(plan["demande"])
            except opusclip.OpusError as exc:
                logger.error("OpusClip a refusé %s : %s", youtube_id, exc)
                db.maj_source(youtube_id, etat="ECHEC", erreur=str(exc))
                telegram.signaler_action(
                    f"❌ <b>{src['titre'][:80]}</b>\n"
                    f"OpusClip a refusé : {exc}"
                )
                bilan["ecartes"] += 1
                bilan["en_attente"] -= 1
                continue

            projet_id = projet.get("id", "?")
            db.maj_source(
                youtube_id, etat="ENVOYE",
                submagic_id=f"opus:{projet_id}",
                credits=plan["credits"],
                envoye_at=maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            telegram.signaler_action(
                f"✅ <b>{src['titre'][:80]}</b>\n"
                f"Lancé — projet <code>{projet_id}</code>, "
                f"{plan['credits']} crédits.\n"
                f"Les extraits arriveront dans ~20-40 minutes."
            )
            restants -= plan["credits"]
            bilan["lances"] += 1
            bilan["en_attente"] -= 1

        elif reponse and reponse["action"] == "NON":
            db.maj_source(youtube_id, etat="ECARTE",
                          erreur="écarté par Michel")
            telegram.signaler_action(
                f"❌ <b>{src['titre'][:80]}</b> — écarté."
            )
            bilan["ecartes"] += 1
            bilan["en_attente"] -= 1

        else:
            # Pas encore de réponse. Vérifier l'ancienneté.
            try:
                updated = datetime.fromisoformat(
                    (src["updated_at"] or "").replace("Z", "+00:00")
                )
                age = (maintenant - updated).total_seconds()
            except (ValueError, TypeError):
                age = 0

            if age > DELAI_ABANDON_S:
                # Plus de 48 h sans réponse → on remet en REPERE.
                db.maj_source(youtube_id, etat="REPERE", telegram_msg="")
                bilan["abandonnes"] += 1
                bilan["en_attente"] -= 1
            elif age > DELAI_RAPPEL_S:
                # Plus de 24 h → rappel.
                telegram.envoyer_message(
                    f"⏰ <b>Rappel</b> — toujours en attente :\n"
                    f"<b>{src['titre'][:100]}</b>\n\n"
                    f"Réponds <b>GO</b> pour lancer — <b>NON</b> pour ignorer."
                )
                bilan["rappels"] += 1

    return bilan

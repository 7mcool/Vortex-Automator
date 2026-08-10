"""Phase 1 du protocole de confirmation : détecter → notifier.

Utilise choisir_sources() (les MÊMES filtres que opus --live) pour ne
proposer QUE les sermons frais d'Amessan qui passent la bascule et le
délai de fraîcheur. Aucun vieux sermon, aucune autre chaîne.

    python -m vortex confirmer          # une seule source par appel
    python -m vortex confirmer -n 3     # jusqu'à 3 sources

Ne dépense AUCUN crédit. Le message Telegram contient tout ce que Michel
doit savoir pour décider : titre, durée, fenêtre, coût, budget restant.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import opusclip, telegram
from .config import Config
from .db import Database

logger = logging.getLogger(__name__)


def _message_confirmation(plan: dict, credits_restants: int, src: dict,
                          deja_aujourdhui: int = 0, plafond_jour: int = 1) -> str:
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
        f"Chaîne : {src.get('chaine') or '?'}",
        f"Orateur : {src.get('pasteur') or 'non identifié'}",
        f"Vidéo : {_hms(plan['duree_s'])} — "
        f"https://www.youtube.com/watch?v={plan['youtube_id']}",
        f"Fenêtre : {_hms(f['debut_s'])} → {_hms(f['fin_s'])} "
        f"({duree_f // 60} min) — {f['certitude']}",
        f"Extraits : {plan['demande']['curationPref']['clipDurations'][0][0] // 60}-"
        f"{plan['demande']['curationPref']['clipDurations'][0][1] // 60} min",
        "",
        f"💰 <b>{plan['credits']} crédits</b> "
        f"({credits_restants} restants ce mois-ci)",
    ]
    # On INFORME du plafond quotidien, on ne bloque pas : un GA de Michel est
    # une décision prise en connaissance du coût, elle prime sur un réglage.
    # Ce qui avait dérapé le 10/08, c'est l'envoi SANS lui demander.
    if deja_aujourdhui >= plafond_jour:
        lignes.append(f"⚠️ {deja_aujourdhui} sermon(s) déjà envoyé(s) en 24 h "
                      f"(ton réglage : {plafond_jour}/jour)")
    lignes += [
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

    # UNE SEULE QUESTION À LA FOIS. Sans ce verrou, chaque passage du cron
    # (toutes les 30 min) poserait une question de plus tant que Michel n'a
    # pas répondu : le salon se remplirait, et plusieurs GO d'affilée
    # partiraient. C'est ce qui s'est produit à la première mise en service —
    # trois messages d'un coup pour du vieux fonds de catalogue.
    en_cours = db.conn.execute(
        "SELECT titre FROM sources_yt WHERE etat = 'A_CONFIRMER' LIMIT 1"
    ).fetchone()
    if en_cours:
        return {"proposes": 0, "envoyes": 0, "erreurs": 0,
                "raison": "une question attend déjà sa réponse : "
                          f"{(en_cours['titre'] or '')[:60]}"}

    # Budget réel : ce qui a déjà été engagé ce mois.
    maintenant = datetime.now(timezone.utc)
    debut_mois = maintenant.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    deja = db.credits_depenses_depuis(debut_mois)
    restants = cfg.opus_credits_par_mois - deja

    # Cadence du jour — pour information dans le message, pas pour bloquer.
    debut_jour = (maintenant - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    deja_aujourdhui = db.sources_envoyees_depuis(debut_jour)

    # ⚠️ On utilise choisir_sources() — les MÊMES filtres que `opus --live` :
    # bascule (traiter_a_partir_de), fraîcheur (fraicheur_max_jours), chaînes
    # réservées (chaines_reservees). Ainsi Michel ne reçoit QUE les nouveaux
    # sermons d'Amessan, jamais le backlog ni les autres chaînes.
    #
    # On ne prend que les sources qui n'ont PAS encore de telegram_msg
    # (pas déjà proposées). choisir_sources() lit REPERE, donc une source
    # déjà passée en A_CONFIRMER n'est pas re-sélectionnée.
    toutes, tri = opusclip.choisir_sources(cfg, db, limite * 3)
    logger.info("choisir_sources : %s examinees, %s retenues, %s avant_bascule, "
                "%s trop_vieilles, %s hors_reserve",
                tri.get("examinees", 0), tri.get("retenues", 0),
                tri.get("avant_bascule", 0), tri.get("trop_vieilles", 0),
                tri.get("hors_reserve", 0))

    candidates = []
    for src in toutes:
        row = db.conn.execute(
            "SELECT telegram_msg FROM sources_yt WHERE youtube_id = ?",
            (src["youtube_id"],),
        ).fetchone()
        if row and row["telegram_msg"]:
            continue  # déjà proposé, on ne renvoie pas
        candidates.append(dict(src))

    if not candidates:
        return {"proposes": 0, "envoyes": 0, "erreurs": 0,
                "raison": tri.get("raison", "aucune source éligible")}

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
            bilan["erreurs"] += 1
            continue

        msg = _message_confirmation(plan, restants, dict(src),
                                    deja_aujourdhui, cfg.opus_sermons_par_jour)
        telegram_id = telegram.envoyer_message(msg)

        if telegram_id:
            db.maj_source(src["youtube_id"], etat="A_CONFIRMER",
                          telegram_msg=str(telegram_id))
            bilan["envoyes"] += 1
            restants -= plan["credits"]
        else:
            bilan["erreurs"] += 1

    return bilan

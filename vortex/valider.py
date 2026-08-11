"""Phase 2 du protocole de confirmation : lire les réponses → enchaîner.

Interroge Telegram pour savoir si Michel a répondu GO ou NON aux messages
de confirmation. En cas de GO, lance OpusClip (crédits dépensés). En cas
de NON, écarte la source.

SANS RÉPONSE, ÇA PART QUAND MÊME — décision de Michel du 10/08 : « qu'il
aille automatique s'il n'a pas de réponse, du moment que ça concerne le
pasteur Jacques Amessan et que mes principes sont bien validés ».

Les « principes » sont donc vérifiés un par un avant tout départ automatique
(voir `_feu_vert_automatique`). Si l'un d'eux manque — et notamment si la
prédication n'a pas été repérée précisément — on n'engage rien et on attend
Michel. Le silence vaut accord seulement quand il n'y a plus de doute.

    python -m vortex valider            # simulation
    python -m vortex valider --live     # lance réellement OpusClip
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import opusclip, telegram
from .config import Config
from .db import Database

logger = logging.getLogger(__name__)

# Une confirmation sans réponse reçoit un rappel, puis part toute seule si
# tous les feux sont au vert. Le délai laisse à Michel le temps de voir le
# message et d'opposer son veto — c'est ce que la question sert désormais.
DELAI_RAPPEL_S = 3 * 3600
# Faute de feu vert automatique (chaîne non réservée, fenêtre incertaine…),
# la question finit par être retirée : elle sera reposée plus tard.
DELAI_ABANDON_S = 72 * 3600


def _champ(src, nom, defaut=None):
    """Lit une colonne qui peut manquer sur une base pas encore migrée."""
    try:
        valeur = src[nom]
    except (IndexError, KeyError):
        return defaut
    return defaut if valeur is None else valeur


def _feu_vert_automatique(cfg: Config, db: Database, src, maintenant) -> tuple[bool, str]:
    """Les « principes de Michel », vérifiés un par un.

    Retourne (autorisé, motif). Le motif explique le refus, ou nomme ce qui
    a été vérifié en cas d'accord — il part sur Telegram, pour que Michel
    voie toujours sur quelle base la machine a décidé seule.
    """
    handle = _champ(src, "handle", "")
    if cfg.opus_chaines_reservees and handle not in cfg.opus_chaines_reservees:
        return False, f"chaîne {handle} hors des chaînes réservées"

    # LE SILENCE NE VAUT ACCORD QUE POUR DU NEUF.
    #
    # Le 11/08 à 1 h 30 du matin, un sermon du 3 août est parti tout seul :
    # il passait tous les autres contrôles, et personne ne dormait pour dire
    # non. Or Michel ne cesse de le répéter — « on vise les nouveaux ». Un
    # sermon qui a huit jours n'est plus une actualité : il peut attendre un
    # accord explicite, il n'y a aucune urgence à le lancer la nuit.
    publie = opusclip.publie_ts(_champ(src, "published_at", ""))
    if not publie:
        return False, "date de publication inconnue"
    age_jours = (maintenant.timestamp() - publie) / 86400
    if age_jours > cfg.opus_fraicheur_auto_jours:
        return False, (f"sermon vieux de {age_jours:.0f} jours "
                       f"(départ seul réservé aux {cfg.opus_fraicheur_auto_jours} "
                       f"premiers jours)")

    # Le garde-fou décisif. Sans repérage de la prédication, la fenêtre vient
    # de la règle proportionnelle : correcte en moyenne, mais capable de
    # tomber sur la louange. On ne dépense pas 45 crédits sur une supposition
    # pendant que Michel dort ; on attend qu'il tranche.
    if not _champ(src, "fenetre_debut_s"):
        return False, "prédication pas encore repérée (fenêtre supposée)"

    debut_jour = (maintenant - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    partis = db.sources_envoyees_depuis(debut_jour)
    if partis >= cfg.opus_sermons_par_jour:
        return False, (f"{partis} sermon(s) déjà parti(s) en 24 h "
                       f"(plafond {cfg.opus_sermons_par_jour})")

    return True, (f"chaîne réservée, prédication repérée, "
                  f"{partis}/{cfg.opus_sermons_par_jour} sermon(s) aujourd'hui")


def _lancer(cfg: Config, db: Database, src, restants: int, maintenant,
            *, live: bool, automatique: bool, motif: str = "") -> tuple[str, int]:
    """Prépare puis envoie une source à OpusClip.

    Retourne (résultat, crédits dépensés) où résultat vaut
    "lance" | "ecarte" | "attente".
    """
    youtube_id = src["youtube_id"]
    titre = (src["titre"] or "")[:80]

    # LA VIDÉO EXISTE-T-ELLE ENCORE ? Les églises rendent parfois un direct
    # privé peu après sa fin, pour le remonter et le republier. Lancer un
    # import sur une vidéo disparue, c'est une tentative perdue — et Michel
    # verrait un échec sans comprendre pourquoi.
    from .veille import video_disponible
    if video_disponible(cfg, youtube_id) is False:
        db.maj_source(youtube_id, etat="ECARTE",
                      erreur="vidéo retirée de YouTube avant le découpage")
        telegram.signaler_action(
            f"🚫 <b>{titre}</b>\n"
            f"La chaîne a retiré cette vidéo de YouTube. Rien n'a été dépensé.\n"
            f"<i>Si elle est remise en ligne montée, je la reprendrai — et le "
            f"contrôle de doublon évitera de la payer deux fois.</i>")
        return "ecarte", 0

    try:
        plan = opusclip.preparer(cfg, dict(src))
    except opusclip.OpusError as exc:
        logger.warning("Validation %s — écarté : %s", youtube_id, exc)
        db.maj_source(youtube_id, etat="ECARTE",
                      erreur=f"plan invalide au moment du départ : {exc}")
        telegram.signaler_action(f"❌ <b>{titre}</b>\nPlan invalide : {exc}")
        return "ecarte", 0
    except Exception:
        logger.exception("Validation %s — erreur inattendue", youtube_id)
        return "attente", 0

    if plan["credits"] > restants:
        telegram.signaler_action(
            f"⚠️ <b>{titre}</b>\nIl faudrait {plan['credits']} crédits, "
            f"il n'en reste que {restants} ce mois-ci."
        )
        return "attente", 0

    if not live:
        opusclip.afficher_plan(plan, restants)
        print(f"  SIMULATION — {plan['credits']} crédits NON dépensés.")
        print("  Ajoute --live pour lancer réellement.")
        return "attente", 0

    try:
        projet = opusclip.creer_projet(plan["demande"])
    except opusclip.OpusError as exc:
        logger.error("OpusClip a refusé %s : %s", youtube_id, exc)
        db.maj_source(youtube_id, etat="ECHEC", erreur=str(exc))
        telegram.signaler_action(f"❌ <b>{titre}</b>\nOpusClip a refusé : {exc}")
        return "ecarte", 0

    projet_id = projet.get("id", "?")
    db.maj_source(
        youtube_id, etat="ENVOYE",
        submagic_id=f"opus:{projet_id}",
        credits=plan["credits"],
        envoye_at=maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    entete = ("🤖 <b>Parti tout seul</b> — sans réponse de ta part"
              if automatique else "✅ <b>Lancé</b>")
    detail = f"\n<i>Vérifié : {motif}</i>" if automatique and motif else ""
    telegram.signaler_action(
        f"{entete}\n<b>{titre}</b>\n"
        f"Projet <code>{projet_id}</code>, {plan['credits']} crédits, "
        f"{restants - plan['credits']} restants.{detail}\n"
        f"Les extraits arriveront dans 20 à 40 minutes."
    )
    return "lance", plan["credits"]


def valider(cfg: Config, db: Database, *, live: bool = False) -> dict:
    """Lit les réponses Telegram et exécute GO / NON / silence."""
    if not telegram.TOKEN:
        logger.warning("Telegram non configuré — impossible de lire les réponses.")
        return {"lances": 0, "ecartes": 0, "rappels": 0, "abandonnes": 0,
                "automatiques": 0, "en_attente": 0,
                "raison": "TELEGRAM_TOKEN absent"}

    maintenant = datetime.now(timezone.utc)
    en_attente = db.conn.execute(
        "SELECT * FROM sources_yt WHERE etat = 'A_CONFIRMER'"
    ).fetchall()

    bilan = {"lances": 0, "ecartes": 0, "rappels": 0, "abandonnes": 0,
             "automatiques": 0, "en_attente": len(en_attente)}
    if not en_attente:
        return bilan

    # Lire les réponses Telegram (fenêtre large : voir telegram.lire_reponses).
    reponses = {}
    for r in telegram.lire_reponses():
        reponses.setdefault(r["reply_to_message_id"], r)

    debut_mois = maintenant.replace(day=1, hour=0, minute=0, second=0, microsecond=0
                                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    restants = cfg.opus_credits_par_mois - db.credits_depenses_depuis(debut_mois)
    delai_auto_s = max(1, cfg.opus_delai_auto_h) * 3600

    for src in en_attente:
        youtube_id = src["youtube_id"]
        titre = (src["titre"] or "")[:80]
        msg_id = _champ(src, "telegram_msg", "")

        if not msg_id:
            # Sans message associé, on ne peut pas relier une réponse.
            db.maj_source(youtube_id, etat="REPERE")
            bilan["abandonnes"] += 1
            bilan["en_attente"] -= 1
            continue

        try:
            reponse = reponses.get(int(msg_id))
        except (TypeError, ValueError):
            reponse = None

        # ------------------------------------------------------------- NON
        if reponse and reponse["action"] == "NON":
            db.maj_source(youtube_id, etat="ECARTE", erreur="écarté par Michel")
            telegram.signaler_action(f"❌ <b>{titre}</b> — écarté.")
            bilan["ecartes"] += 1
            bilan["en_attente"] -= 1
            continue

        # -------------------------------------------------------------- GO
        if reponse and reponse["action"] == "GO":
            # Un GA explicite prime sur le plafond quotidien : Michel décide
            # en voyant le coût. Seul le budget du mois reste opposable.
            issue, depense = _lancer(cfg, db, src, restants, maintenant,
                                     live=live, automatique=False)
            restants -= depense
            if issue == "lance":
                bilan["lances"] += 1
                bilan["en_attente"] -= 1
            elif issue == "ecarte":
                bilan["ecartes"] += 1
                bilan["en_attente"] -= 1
            continue

        # -------------------------------------------------- pas de réponse
        try:
            depuis = datetime.fromisoformat(
                (_champ(src, "updated_at", "") or "").replace("Z", "+00:00"))
            age = (maintenant - depuis).total_seconds()
        except (ValueError, TypeError):
            age = 0.0

        if age >= delai_auto_s:
            permis, motif = _feu_vert_automatique(cfg, db, src, maintenant)
            if permis:
                issue, depense = _lancer(cfg, db, src, restants, maintenant,
                                         live=live, automatique=True, motif=motif)
                restants -= depense
                if issue == "lance":
                    bilan["automatiques"] += 1
                    bilan["en_attente"] -= 1
                elif issue == "ecarte":
                    bilan["ecartes"] += 1
                    bilan["en_attente"] -= 1
                continue
            logger.info("%s — départ automatique refusé : %s", youtube_id, motif)
            if age >= DELAI_ABANDON_S:
                db.maj_source(youtube_id, etat="REPERE", telegram_msg="")
                telegram.envoyer_message(
                    f"↩️ <b>{titre}</b>\nToujours sans réponse et je ne peux pas "
                    f"décider seul ({motif}). Je le remets en réserve."
                )
                bilan["abandonnes"] += 1
                bilan["en_attente"] -= 1
                continue

        if DELAI_RAPPEL_S <= age < DELAI_ABANDON_S and int(age) % 86400 < 1800:
            telegram.envoyer_message(
                f"⏰ <b>Rappel</b> — en attente :\n<b>{titre}</b>\n\n"
                f"<b>GO</b> pour lancer — <b>NON</b> pour ignorer."
            )
            bilan["rappels"] += 1

    return bilan

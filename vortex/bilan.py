"""Bilan quotidien des sermons, envoyé sur Telegram.

Michel, le 12/08 : « je veux plus t'utiliser chaque fois ». Ce message est
là pour ça — il répond sans qu'il ait à demander : combien de crédits
restent, ce qui attend une réponse, ce qui a été publié.

Il porte aussi le seul avertissement vraiment actionnable : **le PC est-il
resté éteint trop longtemps ?** Le repérage de la prédication ne peut tourner
que là (YouTube bloque l'adresse du serveur), et sans lui un sermon ne peut
pas partir tout seul. Le savoir à temps, c'est pouvoir allumer la machine
avant que le sermon ne soit périmé.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import telegram
from .config import Config
from .db import Database

# Au-delà, on considère que le PC n'a pas tourné et on le signale.
SILENCE_PC_H = 20


def _dernier_reperage(db: Database) -> str:
    ligne = db.conn.execute(
        "SELECT MAX(updated_at) AS quand FROM sources_yt "
        "WHERE fenetre_debut_s IS NOT NULL").fetchone()
    return (ligne["quand"] or "") if ligne else ""


def composer(cfg: Config, db: Database) -> str:
    maintenant = datetime.now(timezone.utc)
    debut_mois = maintenant.replace(day=1, hour=0, minute=0, second=0,
                                    microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    hier = (maintenant - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    restants = cfg.opus_credits_par_mois - db.credits_depenses_depuis(debut_mois)
    attente = db.conn.execute(
        "SELECT titre, fenetre_debut_s FROM sources_yt WHERE etat = 'A_CONFIRMER'"
    ).fetchall()
    publies = db.conn.execute(
        "SELECT COUNT(*) AS n FROM clips WHERE etat = 'PUBLIE' AND updated_at >= ?",
        (hier,)).fetchone()["n"]
    en_cours = db.conn.execute(
        "SELECT COUNT(*) AS n FROM sources_yt WHERE etat = 'ENVOYE'").fetchone()["n"]
    indispo = db.conn.execute(
        "SELECT COUNT(*) AS n FROM sources_yt WHERE etat = 'INDISPONIBLE'"
    ).fetchone()["n"]

    lignes = [f"📊 <b>Bilan du jour</b>",
              f"💰 {restants} crédits restants ce mois-ci",
              f"🎬 {publies} extrait(s) publié(s) en 24 h"]
    if en_cours:
        lignes.append(f"⏳ {en_cours} sermon(s) en cours de découpage")
    if indispo:
        lignes.append(f"🚫 {indispo} vidéo(s) retirée(s) de YouTube — "
                      f"je guette leur retour")

    if attente:
        lignes.append("")
        for a in attente:
            marque = "🎯" if a["fenetre_debut_s"] else "❓"
            lignes.append(f"{marque} <b>en attente de ta réponse</b>")
            lignes.append(f"<i>{(a['titre'] or '')[:70]}</i>")
            if not a["fenetre_debut_s"]:
                lignes.append("Prédication supposée : je ne lancerai pas seul, "
                              "réponds <b>GO</b> ou <b>NON</b>.")

    # L'avertissement qui compte : sans le PC, pas de repérage, donc pas de
    # départ automatique. Michel doit pouvoir agir avant que ça bloque.
    dernier = _dernier_reperage(db)
    try:
        ecoule = (maintenant - datetime.fromisoformat(
            dernier.replace("Z", "+00:00"))).total_seconds() / 3600
    except (ValueError, AttributeError):
        ecoule = None
    if ecoule is not None and ecoule > SILENCE_PC_H:
        lignes += ["", f"⚠️ <b>Aucun repérage depuis {ecoule:.0f} h</b> — "
                       f"ton PC est-il allumé ? Sans lui je ne peux pas situer "
                       f"la prédication, et rien ne part tout seul."]

    if not attente and not en_cours:
        lignes += ["", "Rien à faire de ton côté."]
    return "\n".join(lignes)


def envoyer(cfg: Config, db: Database) -> bool:
    return telegram.signaler_action(composer(cfg, db))

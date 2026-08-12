"""Trouver LA prédication dans un direct de trois heures.

Décision de Michel (05/08/2026) : « on sélectionne juste la prédication, pas
toute la durée de la vidéo ». C'est le levier de coût le plus important du
projet, et de loin.

OpusClip facture 1 crédit par minute IMPORTÉE. Un direct de 3 h 25 envoyé en
entier coûte 205 crédits — avec 300 crédits par mois, cela ferait UN sermon et
demi. En ne visant que le cœur de l'enseignement (~65 min), le même budget
traite QUATRE À CINQ sermons. Facteur 4, pour une seule décision.

Or ces directs ont tous la même forme, relevée à la main fin juillet sur les
conférences Sophos :

    0:00-1:20  louange
    1:20-2:00  mise en route, annonces, témoignages
    2:00-3:05  ★ le cœur de l'enseignement
    3:05-3:25  appel, prière finale

Payer pour analyser la louange et les annonces, c'est jeter l'argent.

Comment on trouve la fenêtre, sans rien télécharger :
1. Les sous-titres automatiques de YouTube sont publics et gratuits — yt-dlp
   les récupère sans toucher à la vidéo (aucun gigaoctet, aucun quota).
2. On les résume en tranches de 5 minutes.
3. DeepSeek lit ce résumé et dit où commence et où finit la prédication.
4. La fenêtre est ensuite bornée par la configuration, pour qu'aucune erreur
   de l'IA ne puisse déclencher une facture inattendue.

Aucun crédit OpusClip n'est consommé ici.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger("vortex.fenetre")


class FenetreError(RuntimeError):
    """Impossible de déterminer la fenêtre de prédication."""


# --------------------------------------------------------- sous-titres YouTube
def _horodatage_en_secondes(texte: str) -> float:
    m = re.match(r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})", texte.strip())
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


REPO = Path(__file__).resolve().parent.parent


def _cookies_youtube() -> str:
    """Chemin du fichier de cookies, ou chaîne vide.

    Sans cookies, YouTube répond « Sign in to confirm you're not a bot » et
    AUCUN sous-titre ne sort — vérifié le 05/08. Le repli proportionnel prend
    alors le relais et se trompe de vingt minutes sur certains directs.
    À réexporter depuis Firefox quand ils expirent (Chrome verrouille les siens).
    """
    candidat = os.environ.get("YOUTUBE_COOKIES_FILE", "")
    if candidat and Path(candidat).is_file():
        return candidat
    defaut = REPO / "secrets" / "youtube_cookies.txt"
    return str(defaut) if defaut.is_file() else ""


def sous_titres_youtube(youtube_id: str, langue: str = "fr",
                        timeout: int = 180) -> list[tuple[float, str]]:
    """Sous-titres automatiques d'une vidéo : [(seconde, texte), …].

    Rien n'est téléchargé de la vidéo elle-même. C'est gratuit et hors quota :
    ni crédits OpusClip, ni unités de l'API YouTube.
    """
    with tempfile.TemporaryDirectory() as dossier:
        gabarit = str(Path(dossier) / "st")
        commande = [
            sys.executable, "-m", "yt_dlp",
            "--skip-download",
            "--write-auto-sub", "--write-sub",
            "--sub-lang", f"{langue},{langue}-orig,{langue}.*",
            "--sub-format", "vtt",
            "--no-progress", "--quiet", "--no-warnings",
            "-o", gabarit,
        ]
        cookies = _cookies_youtube()
        if cookies:
            commande += ["--cookies", cookies]
        # yt-dlp a rendu obligatoire un moteur JavaScript : sans lui, une partie
        # des données de la page n'est plus lisible et l'extraction échoue.
        # Même moteur JavaScript que pour l'audio : voir ecoute.moteur_js().
        from .ecoute import moteur_js
        commande += moteur_js()
        commande.append(f"https://www.youtube.com/watch?v={youtube_id}")

        try:
            subprocess.run(commande, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise FenetreError(f"sous-titres de {youtube_id} : délai dépassé") from exc

        fichiers = sorted(Path(dossier).glob("*.vtt"))
        if not fichiers:
            raise FenetreError(
                f"aucun sous-titre disponible pour {youtube_id} "
                "(vidéo trop récente, sous-titres désactivés, ou blocage YouTube)")
        brut = fichiers[0].read_text(encoding="utf-8", errors="replace")

    lignes: list[tuple[float, str]] = []
    seconde = 0.0
    vus: set[str] = set()
    for ligne in brut.splitlines():
        ligne = ligne.strip()
        if "-->" in ligne:
            seconde = _horodatage_en_secondes(ligne.split("-->")[0])
            continue
        if not ligne or ligne.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        # Les sous-titres automatiques répètent chaque ligne à mesure qu'elle
        # se construit mot à mot : sans ce filtre, le texte est triplé.
        texte = re.sub(r"<[^>]+>", "", ligne).strip()
        if not texte or texte in vus:
            continue
        vus.add(texte)
        lignes.append((seconde, texte))
    if not lignes:
        raise FenetreError(f"sous-titres illisibles pour {youtube_id}")
    return lignes


def resumer_par_tranches(lignes: list[tuple[float, str]], tranche_s: int = 300,
                         mots_par_tranche: int = 60) -> list[tuple[int, str]]:
    """Condense les sous-titres en tranches de 5 minutes.

    Trois heures de parole font 30 000 mots : les donner entières à l'IA
    coûterait cher et noierait le signal. Un échantillon par tranche suffit
    largement à reconnaître « on chante » de « on enseigne ».
    """
    tranches: dict[int, list[str]] = {}
    for seconde, texte in lignes:
        index = int(seconde // tranche_s)
        seau = tranches.setdefault(index, [])
        if sum(len(t.split()) for t in seau) < mots_par_tranche:
            seau.append(texte)
    return [(i * tranche_s, " ".join(v)) for i, v in sorted(tranches.items())]


# ------------------------------------------------------------------- l'IA lit
PROMPT_FENETRE = """Tu analyses la retransmission d'un culte chrétien francophone \
(Afrique de l'Ouest) pour repérer LA prédication.

Ces directs suivent presque toujours la même forme :
  1. louange et chants — TRÈS LONG, souvent 1 h à 1 h 30
  2. annonces, offrandes, témoignages, présentation des invités
  3. ★ LA PRÉDICATION — l'enseignement suivi, un orateur qui développe un sujet
  4. appel, prière finale, bénédiction

Voici le déroulé de la vidéo, par tranches de 5 minutes (temps en secondes \
depuis le début, suivi d'un échantillon de ce qui est dit) :

{deroule}

DURÉE TOTALE : {duree} secondes

⚠️ NE CHOISIS PAS D'EXTRAIT. Donne les BORNES RÉELLES de la prédication, \
même si elle dure deux heures. Le découpage est fait ensuite, par calcul.

C'est un constat qu'on te demande, pas un avis : où la louange s'arrête, où \
l'enseignement commence, où il finit. Deux lectures d'un même sermon doivent \
donner les mêmes bornes. (Demandé auparavant de « choisir les meilleures \
minutes », le même sermon recevait deux réponses opposées d'un appel à \
l'autre — l'une et l'autre défendables, ce qui rendait la dépense imprévisible.)

Donne UNIQUEMENT un JSON avec :
- "fin_louange_s" : entier, seconde où la louange et les chants se terminent \
enfin. Repère-la d'abord : c'est elle qui protège du piège principal.
- "debut_s" : entier, seconde où commence réellement l'enseignement. \
OBLIGATOIREMENT après "fin_louange_s". Ce n'est PAS la première citation \
biblique venue : pendant la louange et les annonces, on cite aussi des \
versets. Cherche le moment où quelqu'un commence à EXPLIQUER, phrase après \
phrase, sans qu'on chante entre les phrases.
- "fin_s" : entier, seconde où l'enseignement s'arrête VRAIMENT (avant \
l'appel, la prière finale, les offrandes, les annonces de clôture). Donne la \
fin réelle, sans la raccourcir pour tenir dans une durée.
- "certitude" : "haute", "moyenne" ou "basse"
- "raison" : une phrase courte disant à quoi tu as reconnu le début et la fin.

Règles :
- La prédication est le plus long passage où UNE personne développe un \
raisonnement suivi, avec des références bibliques ET des explications.
- Les chants, les « alléluia » répétés, les annonces, les remerciements et les \
appels aux dons n'en font PAS partie.
- Ces cultes durent 3 heures et l'enseignement est presque toujours dans la \
SECONDE MOITIÉ. Si tu places le début dans le premier tiers, relis : tu as \
probablement pris un verset chanté pour le début du message.
- Si tu ne reconnais aucune prédication, mets "certitude": "basse".

Réponds UNIQUEMENT avec le JSON."""


def _demander_a_lia(deroule: str, duree_s: int, largeur_max_s: int) -> dict | None:
    from . import ai

    if not ai.available():
        return None
    import time
    import urllib.error
    import urllib.request

    prompt = PROMPT_FENETRE.format(deroule=deroule, duree=duree_s,
                                   largeur_max=largeur_max_s)
    payload = {
        "model": ai.MODEL,
        "messages": [{"role": "user", "content": prompt}],
        # deepseek-v4-pro RAISONNE avant de répondre : mesuré le 10/08 sur un
        # sermon de 2 h, 5 817 jetons de raisonnement pour 149 de réponse, soit
        # 5 966 sur les 6 000 alors autorisés. Un cheveu de plus et le JSON
        # sortait tronqué — panne silencieuse, la règle prenait le relais sans
        # que rien ne le signale. D'où la marge.
        "max_tokens": 8000,
    }
    if "reasoner" not in ai.MODEL:
        payload["response_format"] = {"type": "json_object"}
        # TEMPÉRATURE NULLE : ici on ne cherche pas de la variété, on cherche
        # un FAIT. Mesuré le 12/08 sur un même sermon, deux appels d'affilée
        # ont rendu 35→80 min puis 90→135 min, tous deux « haute certitude ».
        # Les deux tombaient dans la prédication — elle durait 1 h 50 — mais
        # une décision qui engage 45 crédits ne peut pas dépendre d'un tirage.
        payload["temperature"] = 0.0
    corps = json.dumps(payload).encode()

    for tentative in range(3):
        try:
            req = urllib.request.Request(
                ai.API_URL, data=corps,
                headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                         "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=240) as r:
                rep = json.load(r)
            return ai._parse_json_obj(rep["choices"][0]["message"]["content"])
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
                KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Repérage de la prédication, tentative %d/3 : %s", tentative + 1, exc)
            time.sleep(3 * (tentative + 1))
    return None


# --------------------------------------------------------------- le repli sûr
# ---------------------------------------------------------------------------
# OÙ VISER — mesuré, pas supposé.
#
# Relevé sur les trois conférences Sophos (durées 3 h 22, 3 h 36, 3 h 33), en
# situant le MILIEU de la prédication réelle par rapport à la durée totale :
#
#     SOIR 1     milieu à 73,8 %
#     SOIR 2     milieu à 61,4 %
#     MATINÉE 1  milieu à 72,8 %
#
# Une fenêtre de 45 min centrée sur 69 % tombe dans la prédication dans les
# TROIS cas (au pire 6 minutes de débord sur SOIR 2, la conférence atypique).
#
# ⚠️ On visait auparavant le DÉBUT du sermon (55 % de la vidéo). C'était bon
# pour une fenêtre de 60 min, mais avec 45 min on achetait ses préliminaires au
# lieu de son cœur. Viser le MILIEU est ce qui a été mesuré comme juste.
CENTRE_SERMON = 0.69

# Écart maximal toléré entre l'avis de l'IA et celui de la règle. Au-delà, on
# garde la règle : mesuré le 05/08, elle vise mieux (1 et 7 min d'écart, contre
# 15 min pour l'IA), et sur MATINÉE 1 l'IA aurait fait rater le sermon entier.
#
# Deux seuils depuis le 10/08. Un avis « haute certitude » cite la phrase de
# transition et situe la fin de la louange : il est d'une autre nature qu'une
# estimation prudente, et la règle — calibrée sur des conférences de 3 h 30 —
# n'a pas à l'écraser sur un culte de 2 h. Le garde-fou reste là pour les
# écarts grossiers (MATINÉE 1 : une heure de décalage), pas pour vingt minutes.
TOLERANCE_DESACCORD_S = 900
TOLERANCE_DESACCORD_HAUTE_S = 1500

# Marge ajoutée de chaque côté des bornes trouvées par l'IA. Règle de Michel :
# un extrait doit porter l'affirmation choc ET son explication entière. Face au
# doute, mieux vaut acheter trois minutes de trop que couper une démonstration.
MARGE_SECURITE_S = 180


def _fenetre_centree(centre_s: int, largeur_s: int, duree_s: int) -> tuple[int, int]:
    """Fenêtre de largeur voulue autour d'un point, sans sortir de la vidéo."""
    debut = max(0, centre_s - largeur_s // 2)
    fin = min(duree_s, debut + largeur_s)
    debut = max(0, fin - largeur_s)
    return debut, fin


def fenetre_par_defaut(duree_s: int, largeur_max_s: int) -> tuple[int, int, str]:
    """La règle proportionnelle : une fenêtre centrée sur le cœur du sermon.

    C'est le repère principal, pas un simple secours : à la mesure du 05/08,
    cette règle visait plus juste que l'analyse de la transcription par l'IA.
    """
    debut, fin = _fenetre_centree(int(duree_s * CENTRE_SERMON), largeur_max_s, duree_s)
    return debut, fin, f"règle mesurée : cœur du sermon vers {CENTRE_SERMON:.0%} de la vidéo"


def trouver(youtube_id: str, duree_s: int, *, largeur_max_s: int = 4200,
            largeur_min_s: int = 600, langue: str = "fr",
            lignes: list[tuple[float, str]] | None = None) -> dict:
    """Fenêtre de prédication d'une vidéo. Ne consomme AUCUN crédit OpusClip.

    Retourne {debut_s, fin_s, certitude, raison, source}. La fenêtre est
    toujours bornée : même une réponse aberrante de l'IA ne peut pas produire
    une facture surprise.

    `lignes` permet de fournir un relevé de paroles déjà obtenu autrement —
    typiquement la transcription maison de `vortex/ecoute.py` quand YouTube
    n'a pas encore généré ses sous-titres (cas d'un direct qui vient de se
    terminer, justement celui qu'on veut découper le soir même).
    """
    try:
        if lignes is None:
            lignes = sous_titres_youtube(youtube_id, langue)
        tranches = resumer_par_tranches(lignes)
        deroule = "\n".join(f"{s}s : {t}" for s, t in tranches)
        log.info("Sous-titres de %s : %d lignes, %d tranches", youtube_id, len(lignes), len(tranches))
        donnees = _demander_a_lia(deroule[:20000], duree_s, largeur_max_s)
    except FenetreError as exc:
        log.warning("%s", exc)
        donnees = None

    if donnees:
        def _entier(cle):
            try:
                return int(float(donnees.get(cle, 0) or 0))
            except (TypeError, ValueError):
                return 0

        debut, fin, fin_louange = _entier("debut_s"), _entier("fin_s"), _entier("fin_louange_s")
        certitude = str(donnees.get("certitude", "")).lower()
        raison = str(donnees.get("raison", ""))[:200]

        # L'IA doit avoir placé la fin de la louange AVANT le début du message.
        # Quand elle se contredit, c'est le signe qu'elle a pris un verset
        # chanté pour le début de la prédication : on la recale.
        if fin_louange and debut < fin_louange < fin:
            log.info("Début recalé sur la fin de la louange : %ds → %ds", debut, fin_louange)
            debut = fin_louange
            raison = f"{raison} (début recalé après la louange)"

        exploitable = (0 <= debut < fin <= duree_s
                       and (fin - debut) >= largeur_min_s
                       and certitude in ("haute", "moyenne"))
        if exploitable:
            # ARBITRAGE. La règle mesurée sert de garde-fou, pas d'autorité.
            #
            # Elle a été calibrée sur trois CONFÉRENCES de 3 h 22 à 3 h 36, où
            # la prédication vient tard. L'appliquer telle quelle à un culte
            # du dimanche de 2 h revient à comparer deux formats différents :
            # le 10/08, elle a écarté un avis « haute certitude » qui citait
            # la phrase de transition (« j'aimerais partager un message ») et
            # plaçait la louange jusqu'à 35 min — un avis manifestement juste.
            #
            # On garde donc le garde-fou contre les écarts GROSSIERS, seuls
            # observés en cas de vraie erreur : sur MATINÉE 1 l'IA plaçait le
            # message une heure trop tôt. Mais on desserre selon la certitude,
            # car un avis argumenté vaut mieux qu'une moyenne.
            milieu_ia = (debut + fin) // 2
            milieu_regle = int(duree_s * CENTRE_SERMON)
            ecart = abs(milieu_ia - milieu_regle)

            # CERTITUDE HAUTE : L'IA A LU, LA RÈGLE NE FAIT QUE SUPPOSER.
            #
            # La règle vient de trois CONFÉRENCES de 3 h 30 où la louange
            # durait 1 h 20. Un culte ordinaire n'a pas cette forme : le
            # 12/08, sur un culte de 2 h 27, la louange s'arrêtait à 15 min et
            # la prédication courait de 35 à 80 min. La règle visait 1 h 19 à
            # 2 h 04 — la fin du message, puis les offrandes et les annonces.
            # Quarante-cinq crédits pour acheter des annonces.
            #
            # L'IA, elle, citait la lecture d'Ecclésiaste 4 — le passage sur
            # l'amitié, précisément le sujet annoncé par le titre. Ce genre
            # d'accord entre le texte lu et le sujet ne s'invente pas.
            #
            # On ne suit pas l'IA aveuglément pour autant : elle doit avoir
            # placé la fin de la louange AVANT le début du message (contrôle
            # ci-dessus), et sa fenêtre doit tenir dans la vidéo. Ce sont des
            # contrôles de COHÉRENCE INTERNE, qui valent mieux qu'une moyenne.
            if certitude == "haute":
                if ecart > TOLERANCE_DESACCORD_HAUTE_S:
                    log.info("L'IA s'écarte de la règle de %d min mais elle a lu "
                             "la transcription et se dit sûre — on la suit",
                             ecart // 60)
                debut = max(0, debut - MARGE_SECURITE_S)
                fin = min(duree_s, fin + MARGE_SECURITE_S)
                if fin - debut > largeur_max_s:
                    debut, fin = _fenetre_centree(milieu_ia, largeur_max_s, duree_s)
                return {"debut_s": debut, "fin_s": fin, "certitude": certitude,
                        "raison": raison, "source": "analyse des paroles",
                        "precise": True}

            tolerance = TOLERANCE_DESACCORD_S
            if ecart <= tolerance:
                # On respecte les BORNES de l'IA, pas seulement son milieu :
                # elle a lu où le message commence et où il finit. On ajoute
                # une marge de sécurité — la règle de Michel veut l'affirmation
                # ET son explication entière, mieux vaut déborder que couper.
                debut = max(0, debut - MARGE_SECURITE_S)
                fin = min(duree_s, fin + MARGE_SECURITE_S)
                if fin - debut > largeur_max_s:
                    debut, fin = _fenetre_centree(milieu_ia, largeur_max_s, duree_s)
                return {"debut_s": debut, "fin_s": fin, "certitude": certitude,
                        "raison": f"{raison} (écart de {ecart // 60} min avec la règle)",
                        "source": "analyse des paroles", "precise": True}
            log.warning("L'IA place le milieu à %ds, la règle à %ds (%d min d'écart, "
                        "tolérance %d min) — la règle l'emporte",
                        milieu_ia, milieu_regle, ecart // 60, tolerance // 60)
            debut, fin, raison_regle = fenetre_par_defaut(duree_s, largeur_max_s)
            return {"debut_s": debut, "fin_s": fin, "certitude": "moyenne",
                    "raison": f"{raison_regle} — avis de l'IA écarté ({ecart // 60} min d'écart)",
                    "source": "règle mesurée", "precise": False}
        log.info("Avis de l'IA inexploitable (%ds→%ds, certitude %s) — règle mesurée",
                 debut, fin, certitude or "?")

    debut, fin, raison = fenetre_par_defaut(duree_s, largeur_max_s)
    return {"debut_s": debut, "fin_s": fin, "certitude": "moyenne",
            "raison": raison, "source": "règle mesurée", "precise": False}

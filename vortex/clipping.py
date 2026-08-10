"""Découpage des longues vidéos : envoi à Submagic, puis récolte des extraits.

Le cycle complet, en trois commandes indépendantes (chacune peut échouer et
reprendre au passage suivant, comme le reste du pipeline) :

    vortex veille      repère les nouveaux directs des chaînes visées
    vortex clip        envoie les plus prometteurs au découpage (1 crédit pièce)
    vortex recolter    récupère les extraits finis, les note, écrit le SEO
    vortex livrer      expédie les retenus par courriel

Le vrai travail de Vortex ici n'est pas le découpage — c'est le TRI. Submagic
rend 15 à 40 extraits par sermon ; en publier 4 par jour veut dire en jeter la
grande majorité. Deux notes indépendantes servent à trancher : celle de
Submagic (viralité mesurée sur le montage) et celle de DeepSeek (l'extrait
tient-il debout tout seul, en français, pour ce public).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import ai, submagic
from .config import Config
from .db import Database

log = logging.getLogger("vortex.clipping")


# ------------------------------------------------------------------- envoi
def envoyer(cfg: Config, db: Database, limite: int = 0) -> dict:
    """Envoie au découpage les sources repérées les plus prometteuses.

    Chaque envoi consomme un crédit Magic Clips : le plafond quotidien de la
    configuration (`projets_par_jour`) est vérifié AVANT tout appel.
    """
    if not submagic.available():
        log.error("SUBMAGIC_API_KEY absente — ajoute-la dans .env")
        return {"envoyes": 0, "raison": "clé absente"}

    depuis = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    deja = db.sources_envoyees_depuis(depuis)
    quota = max(0, cfg.projets_par_jour - deja)
    if limite:
        quota = min(quota, limite)
    if quota <= 0:
        log.info("Plafond atteint : %d source(s) déjà envoyée(s) en 24 h", deja)
        return {"envoyes": 0, "raison": f"plafond {cfg.projets_par_jour}/jour atteint"}

    candidates = db.sources_par_etat("REPERE", limit=quota)
    if not candidates:
        return {"envoyes": 0, "raison": "aucune source repérée"}

    bilan = {"envoyes": 0, "echecs": 0}
    for src in candidates:
        titre_projet = f"{src['titre']}"[:100]
        url = f"https://www.youtube.com/watch?v={src['youtube_id']}"
        try:
            projet = submagic.creer_magic_clips(
                titre=titre_projet,
                url_youtube=url,
                langue=cfg.langue_clipping,
                duree_min=cfg.clip_min_s,
                duree_max=cfg.clip_max_s,
                gabarit=cfg.gabarit_submagic,
                suivi_visage=cfg.suivi_visage,
            )
        except submagic.SubmagicError as exc:
            log.error("Découpage refusé pour %s : %s", src["youtube_id"], exc)
            db.maj_source(src["youtube_id"], etat="ECHEC", erreur=str(exc)[:400])
            bilan["echecs"] += 1
            # Crédits épuisés : inutile d'insister sur les suivantes, on
            # brûlerait des appels pour la même réponse.
            if "credit" in str(exc).lower() or "402" in str(exc):
                bilan["raison"] = "crédits Magic Clips épuisés"
                break
            continue

        db.maj_source(
            src["youtube_id"], etat="ENVOYE", submagic_id=projet.get("id", ""),
            envoye_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        bilan["envoyes"] += 1
        log.info("Envoyé au découpage : %s — %s (%d min) → projet %s",
                 src["youtube_id"], (src["titre"] or "")[:50],
                 (src["duration_s"] or 0) // 60, projet.get("id", "?"))
    return bilan


# ------------------------------------------------------------------ récolte
# Un projet OpusClip est enregistré avec ce préfixe, pour distinguer les deux
# moteurs dans une seule colonne : Submagic fait les extraits courts, OpusClip
# les longs (7-15 min), et la récolte doit savoir à qui parler.
PREFIXE_OPUS = "opus:"

def _interroger(projet_id: str) -> tuple[dict, str, list[dict], bool]:
    """(données, état, extraits, est_fini) — quel que soit le moteur."""
    if projet_id.startswith(PREFIXE_OPUS):
        from . import opusclip
        nu = projet_id[len(PREFIXE_OPUS):]
        donnees = opusclip.projet(nu)
        etat = opusclip.etat_projet(donnees)
        # Les extraits d'OpusClip se demandent à part : la fiche du projet ne
        # les porte pas. Un projet est réellement fini quand ils existent.
        extraits = []
        if etat not in ("queued", "") :
            try:
                extraits = opusclip.clips_du_projet(
                    {"clips": opusclip.clips_exportables(nu)})
            except opusclip.OpusError as exc:
                log.info("Extraits de %s pas encore lisibles : %s", nu, exc)
        fini = bool(extraits) or etat in opusclip.ETATS_ECHOUES_OPUS
        return donnees, etat, extraits, fini
    donnees = submagic.projet(projet_id)
    etat = str(donnees.get("status", "")).lower()
    return donnees, etat, submagic.clips_du_projet(donnees), etat in submagic.ETATS_FINIS


def recolter(cfg: Config, db: Database, limite: int = 0) -> dict:
    """Interroge les projets en cours et enregistre les extraits terminés.

    Traite indifféremment les projets Submagic et OpusClip : la source porte
    l'identifiant du moteur qui l'a découpée.
    """
    en_cours = db.sources_par_etat("ENVOYE", limit=limite)
    if not en_cours:
        return {"termines": 0, "en_cours": 0}

    bilan = {"termines": 0, "en_cours": 0, "echecs": 0, "clips_retenus": 0, "clips_ecartes": 0}
    for src in en_cours:
        projet_id = src["submagic_id"]
        if not projet_id:
            db.maj_source(src["youtube_id"], etat="ECHEC", erreur="projet sans identifiant")
            bilan["echecs"] += 1
            continue
        try:
            donnees, etat, extraits, fini = _interroger(projet_id)
        except Exception as exc:  # SubmagicError, OpusError, réseau
            log.warning("Projet %s illisible : %s", projet_id, exc)
            continue

        if not fini:
            bilan["en_cours"] += 1
            log.info("Projet %s toujours en cours (%s)", projet_id, etat or "?")
            continue
        from . import opusclip as _opus
        if etat in _opus.ETATS_ECHOUES_OPUS:
            raison = str(donnees.get("failureReason") or donnees.get("error")
                         or "échec du découpage")[:400]
            log.error("Découpage échoué pour %s : %s", src["youtube_id"], raison)
            db.maj_source(src["youtube_id"], etat="ECHEC", erreur=raison)
            bilan["echecs"] += 1
            continue

        if not extraits:
            db.maj_source(src["youtube_id"], etat="ECHEC",
                          erreur="projet terminé mais aucun extrait téléchargeable")
            bilan["echecs"] += 1
            continue

        gardes, rejets = _filtrer_extraits(
            cfg, extraits, moteur_opus=projet_id.startswith(PREFIXE_OPUS))
        if rejets["trop_courts"] or rejets["doublons"]:
            log.info("%s : %d trop court(s), %d doublon(s) écarté(s) sur %d",
                     src["youtube_id"], rejets["trop_courts"], rejets["doublons"],
                     len(extraits))
        if not gardes:
            db.maj_source(src["youtube_id"], etat="ECHEC",
                          erreur=f"aucun extrait publiable sur {len(extraits)} produits")
            bilan["echecs"] += 1
            continue

        retenus, ecartes = _trier_et_enregistrer(cfg, db, src, projet_id, gardes)
        ecartes += rejets["trop_courts"] + rejets["doublons"]
        bilan["clips_retenus"] += retenus
        bilan["clips_ecartes"] += ecartes
        bilan["termines"] += 1
        db.maj_source(src["youtube_id"], etat="DECOUPE")
        log.info("Découpé : %s → %d extrait(s) retenu(s) sur %d",
                 src["youtube_id"], retenus, len(extraits))
    return bilan


def _se_recouvrent(a: dict, b: dict, tolerance: float = 0.5) -> bool:
    """Deux extraits couvrent-ils largement le même passage du sermon ?

    OpusClip taille parfois un court morceau À L'INTÉRIEUR d'un extrait plus
    long : sur le premier projet réel, l'extrait de 18 secondes (5734→5754 s)
    était entièrement contenu dans celui de 5 min 36 (5419→5754 s). Publier
    les deux, c'est publier deux fois le même passage.
    """
    da, fa = a.get("debut_s"), a.get("fin_s")
    dbut, fb = b.get("debut_s"), b.get("fin_s")
    if None in (da, fa, dbut, fb):
        return False
    commun = min(fa, fb) - max(da, dbut)
    if commun <= 0:
        return False
    plus_court = min(fa - da, fb - dbut)
    return plus_court > 0 and commun / plus_court >= tolerance


def _filtrer_extraits(cfg: Config, extraits: list[dict], moteur_opus: bool) -> tuple[list[dict], dict]:
    """Écarte ce qui n'est pas publiable avant même d'appeler l'IA.

    ⚠️ LE CRITÈRE EST LA COMPLÉTUDE, PAS LA DURÉE. Michel l'a rappelé le
    09/08 : « il suffit que la vidéo soit complète, même si elle dure moins de
    5 minutes ». Un extrait court mais qui se tient est publiable ; un extrait
    long mais tronqué ne l'est pas.

    C'est le RECOUVREMENT qui trahit l'extrait incomplet, et lui seul. Sur le
    premier projet réel, le morceau de 18 secondes était entièrement contenu
    dans celui de 5 min 36 : ce n'était pas une vidéo, c'était sa fin
    recopiée. Aucun plancher de durée n'était nécessaire pour l'écarter — le
    contrôle de recouvrement suffit, et il ne jette pas les bons extraits
    courts au passage.
    """
    gardes: list[dict] = []
    rejets = {"trop_courts": 0, "doublons": 0}
    # Le plus long d'abord : à recouvrement égal, c'est lui qui porte le
    # raisonnement entier, et c'est donc lui qui doit survivre.
    for extrait in sorted(extraits, key=lambda c: -(c.get("duree_s") or 0)):
        # Seuil de sécurité, très bas : sous une poignée de secondes il ne
        # reste qu'une bribe, jamais une idée complète.
        if (extrait.get("duree_s") or 0) < cfg.opus_clip_plancher_s:
            rejets["trop_courts"] += 1
            continue
        if any(_se_recouvrent(extrait, deja) for deja in gardes):
            rejets["doublons"] += 1
            continue
        gardes.append(extrait)
    # On rend l'ordre de mérite, pas l'ordre de durée.
    gardes.sort(key=lambda c: c.get("score_total") or 0, reverse=True)
    return gardes, rejets


def _trier_et_enregistrer(cfg: Config, db: Database, src, projet_id: str,
                          extraits: list[dict]) -> tuple[int, int]:
    """Garde les meilleurs extraits, écarte le reste, écrit le SEO des retenus."""
    # On repart du nombre DÉJÀ retenu pour cette source : si un passage
    # précédent s'est interrompu au milieu (réseau, IA), reprendre à zéro
    # ferait dépasser le quota et livrerait dix extraits au lieu de cinq.
    retenus = sum(1 for c in db.clips_de_source(src["youtube_id"]) if c["etat"] == "RETENU")
    ecartes = 0

    for rang, extrait in enumerate(extraits):
        assez_bon = extrait["score_total"] >= cfg.note_minimale
        dans_le_quota = retenus < cfg.clips_retenus_par_source
        etat = "RETENU" if (assez_bon and dans_le_quota) else "ECARTE"

        nouveau = db.ajouter_clip({
            "id": extrait["id"] or f"{projet_id}-{rang}",
            "source_id": src["youtube_id"],
            "submagic_projet": projet_id,
            "titre": extrait["titre"],
            "duree_s": extrait["duree_s"],
            "score_total": extrait["score_total"],
            # OpusClip ne rend qu'une note globale ; Submagic la détaille en
            # quatre. On lit donc en tolérant l'absence plutôt que d'exiger
            # des champs qu'un seul des deux moteurs fournit.
            "score_hook": extrait.get("score_hook"),
            "score_partage": extrait.get("score_partage"),
            "score_histoire": extrait.get("score_histoire"),
            "score_emotion": extrait.get("score_emotion"),
            "download_url": extrait["download_url"],
            "direct_url": extrait["direct_url"],
            "preview_url": extrait.get("preview_url", ""),
            "etat": etat,
        })
        if not nouveau:
            continue
        if etat == "ECARTE":
            ecartes += 1
            continue

        retenus += 1
        legende, hashtags = _rediger_legende(cfg, src, extrait)
        db.maj_clip(extrait["id"] or f"{projet_id}-{rang}",
                    legende=legende, hashtags=" ".join(f"#{h}" for h in hashtags))
    return retenus, ecartes


def _rediger_legende(cfg: Config, src, extrait: dict) -> tuple[str, list[str]]:
    """Légende TikTok complète + liste de hashtags."""
    orateur = src["pasteur"] or ""
    eglise = src["eglise"] or src["chaine"] or ""
    source_titre = src["titre"] or ""
    # Aucun hashtag de la chaîne YouTube ici : ces extraits partent sur
    # TikTok @hedjav. « #sophosprophetikos » y renvoyait vers un compte
    # qui n'existe pas sur ce réseau (retiré le 10/08).
    fixes = [h.lstrip("#") for h in cfg.hashtags]

    donnees = None
    # OpusClip livre le texte de l'extrait avec l'extrait lui-même ; Submagic
    # oblige à le redemander, chaque extrait étant un projet à part entière.
    transcription = (extrait.get("texte") or "").strip()
    if not transcription:
        transcription = submagic.transcription_clip(extrait["id"])
    if ai.available() and transcription:
        from .intervenants import nomme
        donnees = ai.generer_legende_clip(
            titre=extrait["titre"],
            duree=extrait["duree_s"],
            # Titre officiel du registre, jamais deviné par le modèle.
            orateur=nomme(orateur) if orateur else "",
            eglise=eglise,
            source=source_titre,
            transcription=transcription,
            hashtags_fixes=fixes,
        )
    elif ai.available():
        # Sans la transcription, l'IA n'a que le titre : elle INVENTE le
        # contenu. Constaté le 03/08 — un extrait intitulé « L'Ukraine :
        # drogués devenus milliardaires » avait reçu une légende parlant des
        # « pièges de la richesse facile », ce que le pasteur ne dit peut-être
        # pas du tout. On préfère ne rien écrire : le passage suivant
        # réessaiera quand le réseau répondra.
        log.warning("Transcription indisponible pour %s — légende reportée", extrait["id"])
        return "", []

    if donnees:
        accroche, corps = donnees["accroche"], donnees["corps"]
        hashtags = donnees["hashtags"]
    else:
        # Repli local : le titre de Submagic est déjà rédigé à partir du
        # contenu réel, il fait une accroche honnête faute de mieux.
        accroche = (extrait["titre"] or "Un message qui va te parler").strip()
        corps = "Extrait d'une prédication à réécouter en entier."
        hashtags = ai._nettoyer_hashtags([], fixes)

    credit = _credit(orateur, eglise, src["handle"])
    legende = "\n\n".join(p for p in (accroche, corps, credit) if p)
    legende = f"{legende}\n\n" + " ".join(f"#{h}" for h in hashtags)
    # 2 200 caractères est la limite TikTok ; on reste large sous la barre.
    return legende[:2000], hashtags


def _credit(orateur: str, eglise: str, handle: str) -> str:
    """Mention de la source. Jamais de nom ni de titre qui ne soit certain.

    Le titre vient du registre `intervenants` (« pasteur Jacques Amessan »,
    mais « Yann Amon » tout court : il est entrepreneur, pas religieux). Sans
    orateur identifié on écrit « l'orateur » — surtout pas « le pasteur »,
    qui affirmerait une qualité qu'on ignore. Ces chaînes reçoivent des
    invités laïcs, et une prophétie a déjà été attribuée à tort le 03/08.

    On renvoie vers la CHAÎNE, pas vers la vidéo précise. Décision de Michel
    le 07/08 : les églises rendent parfois un direct privé pour le remonter,
    et le lien vers la vidéo mourait alors sous chaque TikTok déjà publié —
    le spectateur tombait sur « Vidéo non disponible ». Un lien de chaîne ne
    casse jamais.
    """
    from .intervenants import designation_neutre, nomme

    qui = nomme(orateur) if orateur else designation_neutre()
    ou = f" — {eglise}" if eglise else ""
    lien = f"\n▶️ Ses messages : https://www.youtube.com/@{handle}" if handle else ""
    return f"🎙️ {qui}{ou}{lien}"


# ------------------------------------------------------------- publication
def _creneaux_tiktok(cfg: Config, db: Database, nombre: int) -> list[datetime]:
    """Prochains créneaux TikTok libres.

    Grille PROPRE À TIKTOK (`[tiktok]` dans config.toml), distincte de celle de
    YouTube : publier sur l'un ne consomme pas un créneau de l'autre.

    Décision de Michel (07/08) : les extraits d'un même sermon sortent tous le
    même jour, **nuit comprise**. La grille couvre donc 0 h, 2 h et 4 h — un
    culte terminé à 23 h voit ses extraits partir dans la foulée au lieu
    d'attendre le matin.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(cfg.timezone)
    maintenant = datetime.now(timezone.utc).astimezone(tz)
    pris = set(db.creneaux_tiktok_reserves())

    par_jour: dict = {}
    for valeur in pris:
        try:
            moment = datetime.strptime(valeur, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        jour = moment.astimezone(tz).date()
        par_jour[jour] = par_jour.get(jour, 0) + 1

    creneaux: list[datetime] = []
    jour = maintenant.date()
    garde = 0
    while len(creneaux) < nombre and garde < 365:
        garde += 1
        compte = par_jour.get(jour, 0)
        for heure in sorted(cfg.tiktok_hours):
            if compte >= cfg.tiktok_daily_limit or len(creneaux) >= nombre:
                break
            candidat = datetime(jour.year, jour.month, jour.day, heure, 0, tzinfo=tz)
            # Marge courte : le but est de publier vite. À 30 minutes, un
            # sermon dont les extraits sont prêts à 23 h 45 ratait le créneau
            # de minuit et attendait 2 h. Cinq minutes suffisent à laisser le
            # temps à la programmation de partir.
            if candidat <= maintenant + timedelta(minutes=5):
                continue
            cle = candidat.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if cle in pris:
                continue
            creneaux.append(candidat.astimezone(timezone.utc))
            pris.add(cle)
            compte += 1
        jour += timedelta(days=1)
    return creneaux


def _publier_par_opus(clip, projet_clip: str, quand: str) -> dict:
    """Publie un extrait OpusClip sur TikTok.

    Vérifié le 09/08 : le compte @hedjav est relié chez OpusClip avec le droit
    `video.publish` — l'autorisation même que TikTok avait refusée à notre app
    en juillet. Publier ne coûte aucun crédit (seul X en consomme un).
    """
    from . import opusclip

    compte = opusclip.compte_pour(opusclip.TIKTOK)
    if not compte:
        raise opusclip.OpusError(
            "aucun compte TikTok relié chez OpusClip — app.opus.pro → Publishing")
    projet_id = projet_clip[len(PREFIXE_OPUS):]
    legende = clip["legende"] or ""
    # La première ligne est l'accroche : elle fait le titre, le reste la
    # description. TikTok n'affiche que le début avant « plus ».
    titre = (legende.split("\n", 1)[0] or clip["titre"] or "")[:150]
    return opusclip.publier_clip(
        projet_id, clip["id"], compte["postAccountId"],
        titre=titre, description=legende, planifie_pour=quand)


def _publier_par_submagic(clip, quand: str) -> dict:
    """Publie un extrait Submagic sur TikTok.

    Chaque extrait Magic Clips est un projet Submagic à part entière (son
    previewUrl est une adresse /view/<id>) : c'est son identifiant qu'on
    publie, pas celui du sermon entier.
    """
    plateformes = {"tiktok": {
        "content": (clip["legende"] or "")[:2200],
        "privacyLevel": "public",
        "allowComment": True,
        "allowDuet": True,
        "allowStitch": True,
        # Le contenu est une prédication rediffusée, pas une publicité :
        # aucune déclaration commerciale. La vidéo est montée par une IA
        # (recadrage, sous-titres) — TikTok demande à le savoir.
        "videoMadeWithAi": True,
    }}
    return submagic.publier(clip["id"], plateformes, planifie_pour=quand)


def publier_tiktok(cfg: Config, db: Database, limite: int = 0, *, live: bool = False) -> dict:
    """Programme les meilleurs extraits sur TikTok, via Submagic.

    L'app TikTok « Sophos Publisher » ayant été refusée le 31/07, l'API TikTok
    officielle nous est fermée. Submagic, lui, possède déjà l'autorisation :
    il suffit que le compte TikTok soit relié dans SON tableau de bord
    (section Publishing). Tant que ce n'est pas fait, l'API répond 412 et rien
    n'est publié — le message le dit clairement.

    Sans `--live`, la fonction se contente d'afficher ce qu'elle ferait.
    """
    if not submagic.available():
        return {"programmes": 0, "raison": "SUBMAGIC_API_KEY absente"}

    nombre = limite or cfg.tiktok_daily_limit
    # On publie ce qui a déjà été livré par courriel : Michel a le message
    # sous les yeux au moment où la vidéo part.
    def _publiable(c) -> bool:
        """Trois verrous, tous nés du double envoi du 10/08.

        Le même extrait de 5 min 36 était parti DEUX FOIS sur TikTok : la
        tâche automatique avait republié ce qu'un envoi manuel venait de
        programmer. Rien ne l'en empêchait.
        """
        if not (c["legende"] or "").strip():
            return False                      # une vidéo sans légende part muette
        if (c["publication_id"] or "").strip():
            return False                      # déjà publié une fois
        if (c["programme_at"] or "").strip():
            return False                      # déjà un créneau réservé
        return True

    candidats = [c for c in db.clips_par_etat("LIVRE", limit=nombre) if _publiable(c)]
    if not candidats:
        candidats = [c for c in db.clips_par_etat("RETENU", limit=nombre) if _publiable(c)]
    if not candidats:
        return {"programmes": 0, "raison": "aucun extrait prêt (sans légende, ou déjà publié)"}

    creneaux = _creneaux_tiktok(cfg, db, len(candidats))
    bilan = {"programmes": 0, "echecs": 0, "simulation": not live}

    for clip, creneau in zip(candidats, creneaux):
        quand = creneau.strftime("%Y-%m-%dT%H:%M:%SZ")
        if not live:
            log.info("[simulation] %s → TikTok le %s", (clip["titre"] or "")[:50], quand)
            bilan["programmes"] += 1
            continue

        projet_clip = clip["submagic_projet"] or ""
        try:
            if projet_clip.startswith(PREFIXE_OPUS):
                reponse = _publier_par_opus(clip, projet_clip, quand)
            else:
                reponse = _publier_par_submagic(clip, quand)
        except Exception as exc:
            message = str(exc)
            log.error("Publication TikTok refusée pour %s : %s", clip["id"], message)
            bilan["echecs"] += 1
            if "412" in message or "PRECONDITION" in message.upper():
                bilan["raison"] = ("compte TikTok non relié — le relier dans le "
                                   "tableau de bord du moteur concerné")
                break
            if "403" in message:
                bilan["raison"] = "le forfait n'autorise pas la publication par API"
                break
            continue

        db.maj_clip(clip["id"], etat="PUBLIE", programme_at=quand,
                    publication_id=str(reponse.get("id", "")))
        bilan["programmes"] += 1
        log.info("TikTok programmé le %s : %s", quand, (clip["titre"] or "")[:50])
    return bilan

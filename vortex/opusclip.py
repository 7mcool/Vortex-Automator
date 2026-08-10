"""Client OpusClip — pour les extraits LONGS, que Submagic ne sait pas faire.

Pourquoi les deux outils cohabitent (décision de Michel, 03/08/2026) :
Submagic plafonne à 5 minutes par extrait, or la règle éditoriale veut qu'un
extrait porte l'affirmation choc ET son explication entière — ce qui dépasse
souvent 5 minutes. OpusClip, lui, ne documente aucun plafond de durée.

    Submagic  →  extraits courts (≤ 5 min), recadrage vertical automatique
    OpusClip  →  extraits longs

------------------------------------------------------------------------------
LE COÛT, ET LE PIÈGE À 205 CRÉDITS
------------------------------------------------------------------------------
OpusClip facture **1 crédit par minute de vidéo IMPORTÉE**, pas par extrait
produit. Un direct de 3 h 25 envoyé en entier coûte donc 205 crédits.

Le champ `curationPref.range` restreint le traitement à une fenêtre, et la
facturation suit. MAIS leur documentation avertit qu'il faut **omettre `range`
entièrement plutôt qu'envoyer un objet vide** — et l'exemple officiel qu'ils
publient contient justement `"range": {}`. Copier leur exemple ferait traiter
la vidéo entière.

Ce module refuse donc **catégoriquement** d'envoyer un projet sans fenêtre
explicite. Il n'existe aucun moyen de traiter une vidéo entière par ici : c'est
volontaire, et c'est la conséquence directe du gaspillage constaté sur
Submagic le 03/08.

Autres garde-fous :
- plafond de crédits par projet (`credits_max_par_projet`) ;
- plafond mensuel maison, en plus de celui d'OpusClip (900 crédits/mois) ;
- refus de retraiter une source déjà envoyée ;
- **simulation par défaut** : rien ne part sans `live=True`.

La clé vit dans .env (OPUSCLIP_API_KEY), jamais dans le code.
Doc : https://help.opus.pro/api-reference/overview
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("vortex.opusclip")

API = "https://api.opus.pro/api"

# Facturation : 1 crédit par minute de source importée, minimum 10 par projet
# côté API (« about 10 minutes of clip time »).
CREDITS_MINIMUM_PAR_PROJET = 10
# Plafond imposé par OpusClip lui-même sur les forfaits Pro Beta / Max.
# Au-delà, l'API répond 403 — autant le savoir avant d'envoyer.
CREDITS_MAX_PAR_MOIS_OPUS = 900


class OpusError(RuntimeError):
    """Erreur remontée par l'API, ou refus d'un garde-fou local."""


def available() -> bool:
    return bool(os.environ.get("OPUSCLIP_API_KEY"))


def _requete(methode: str, chemin: str, corps: dict | None = None, *,
             essais: int = 3, timeout: int = 90) -> dict:
    cle = os.environ.get("OPUSCLIP_API_KEY")
    if not cle:
        raise OpusError("OPUSCLIP_API_KEY absente de l'environnement (.env)")

    data = json.dumps(corps).encode() if corps is not None else None
    # Sans User-Agent, la protection anti-robot d'OpusClip (Cloudflare) répond
    # « HTTP 403 error code 1010 » : elle refuse l'agent par défaut de Python
    # (`Python-urllib/3.x`). Vérifié le 09/08 — le même appel passe avec curl.
    entetes = {
        "Authorization": f"Bearer {cle}",
        "User-Agent": "Mozilla/5.0 (compatible; VortexAutomator/1.0)",
        "Accept": "application/json",
    }
    if data:
        entetes["Content-Type"] = "application/json"

    derniere = ""
    for tentative in range(essais):
        req = urllib.request.Request(f"{API}{chemin}", data=data, headers=entetes, method=methode)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                brut = r.read().decode("utf-8", "replace")
            return json.loads(brut) if brut.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            derniere = f"HTTP {exc.code} {detail}"
            # 4xx = demande fautive (crédits, quota mensuel, paramètre refusé) :
            # réessayer répéterait la même réponse. Seul 429 mérite une reprise.
            if 400 <= exc.code < 500 and exc.code != 429:
                raise OpusError(derniere) from exc
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError) as exc:
            derniere = str(exc)
        log.warning("OpusClip %s %s — tentative %d/%d : %s",
                    methode, chemin, tentative + 1, essais, derniere)
        time.sleep(3 * (tentative + 1))
    raise OpusError(derniere or "échec inconnu")


# ------------------------------------------------------------------ fenêtre
def en_secondes(valeur) -> int:
    """Accepte 4200, '4200', '1:10:00' ou '70:00'. Retourne des secondes."""
    if isinstance(valeur, (int, float)):
        return int(valeur)
    texte = str(valeur or "").strip()
    if not texte:
        raise OpusError("horodatage vide")
    if texte.isdigit():
        return int(texte)
    if not re.fullmatch(r"\d{1,3}(:\d{1,2}){1,2}", texte):
        raise OpusError(f"horodatage incompréhensible : {valeur!r} "
                        "(attendu 4200, 70:00 ou 1:10:00)")
    morceaux = [int(m) for m in texte.split(":")]
    while len(morceaux) < 3:
        morceaux.insert(0, 0)
    h, m, s = morceaux
    return h * 3600 + m * 60 + s


def cout_credits(debut_s: int, fin_s: int) -> int:
    """Crédits que coûterait cette fenêtre. 1 crédit = 1 minute importée."""
    duree = max(0, int(fin_s) - int(debut_s))
    return max(CREDITS_MINIMUM_PAR_PROJET, math.ceil(duree / 60))


def verifier_fenetre(debut_s: int, fin_s: int, duree_source_s: int | None,
                     plafond_credits: int) -> int:
    """Contrôle la fenêtre AVANT tout appel. Retourne le coût en crédits.

    Lève OpusError au moindre doute : mieux vaut un refus lisible qu'un projet
    lancé de travers et facturé.
    """
    if fin_s <= debut_s:
        raise OpusError(f"fenêtre vide ou inversée : {debut_s}s → {fin_s}s")
    if duree_source_s and fin_s > duree_source_s:
        raise OpusError(f"la fenêtre finit à {fin_s}s alors que la vidéo "
                        f"dure {duree_source_s}s")
    credits = cout_credits(debut_s, fin_s)
    if credits > plafond_credits:
        raise OpusError(f"cette fenêtre coûterait {credits} crédits, "
                        f"au-delà du plafond de {plafond_credits} "
                        f"(config.toml → [opusclip] credits_max_par_projet)")
    return credits


# ---------------------------------------------------------------- création
# Habillage demandé à OpusClip. Michel, 09/08 : « réactive toutes les
# fonctions désactivées », et « tout est gratuit » sur son forfait PRO.
#
# Le manque le plus visible était `enableVisualHook` : c'est le bandeau de
# texte accrocheur incrusté en tête de vidéo, la signature d'un montage
# OpusClip. Il était à `false` par défaut, et Michel l'a tout de suite
# remarqué sur les premiers rendus.
#
# `enableWatermark` reste à false : on ne veut pas de filigrane OpusClip sur
# les vidéos publiées sous la marque de la chaîne.
RENDU_COMPLET = {
    "enableVisualHook": True,        # bandeau d'accroche en tête — l'oubli du 09/08
    "enableVoiceEnhancement": True,  # « Enhance speech »
    "enableAutoTransition": True,    # transitions entre plans
    "enableCaption": True,           # sous-titres
    "enableCaptionAnimation": True,  # animation mot à mot (karaoké)
    "enableHighlight": True,         # mot prononcé mis en couleur
    "enableEmoji": True,             # émojis automatiques
    "enableAutoLayout": True,        # choix de mise en page selon le plan
    "skipReframe": False,            # recadrage vertical suivant le visage
    "enableWatermark": False,        # PAS de filigrane OpusClip
    "layoutAspectRatio": "portrait",  # 9:16, format TikTok
}


def construire_demande(*, url_video: str, titre: str, debut_s: int, fin_s: int,
                       clip_min_s: int, clip_max_s: int,
                       modele: str = "ClipBasic",
                       genre: str = "Auto",
                       mots_cles: list[str] | None = None,
                       rendu: dict | None = None) -> dict:
    """Le corps exact qui sera envoyé. Séparé de l'envoi pour être AFFICHABLE.

    C'est ce que la simulation montre à Michel : il voit la requête réelle,
    pas une description approximative.
    """
    if not debut_s and not fin_s:
        raise OpusError("fenêtre obligatoire — sans elle OpusClip traite (et "
                        "facture) la vidéo entière")
    return {
        "videoUrl": url_video,
        "uploadedVideoAttr": {"title": (titre or "Vortex")[:100]},
        "curationPref": {
            "model": modele,
            "clipDurations": [[int(clip_min_s), int(clip_max_s)]],
            "genre": genre,
            "topicKeywords": list(mots_cles or []),
            # JAMAIS un objet vide ici : `{}` fait traiter toute la vidéo.
            "range": {"startSec": int(debut_s), "endSec": int(fin_s)},
        },
        "renderPref": dict(RENDU_COMPLET, **(rendu or {})),
    }


def creer_projet(demande: dict) -> dict:
    """Envoie RÉELLEMENT le projet. Consomme des crédits.

    Ne jamais appeler sans être passé par verifier_fenetre().
    """
    fenetre = (demande.get("curationPref") or {}).get("range") or {}
    if "startSec" not in fenetre or "endSec" not in fenetre:
        raise OpusError("refus : demande sans fenêtre explicite")
    log.info("OpusClip — envoi réel : %ds → %ds (%d crédits)",
             fenetre["startSec"], fenetre["endSec"],
             cout_credits(fenetre["startSec"], fenetre["endSec"]))
    return _requete("POST", "/clip-projects", demande, timeout=120)


# OpusClip nomme l'avancement `stage`, pas `status` (vérifié le 09/08 sur un
# projet réel). Valeurs observées : QUEUED, puis les étapes de traitement,
# enfin un état fini. Lire le mauvais champ laissait le suivi afficher « ? »
# indéfiniment.
ETATS_FINIS_OPUS = {"completed", "complete", "done", "succeeded", "success",
                    "failed", "error", "cancelled", "canceled"}
ETATS_ECHOUES_OPUS = {"failed", "error", "cancelled", "canceled"}


def etat_projet(donnees: dict) -> str:
    """L'avancement d'un projet, en minuscules ('queued', 'completed'…)."""
    for cle in ("stage", "status", "state"):
        valeur = donnees.get(cle)
        if valeur:
            return str(valeur).lower()
    return ""


def projet(projet_id: str) -> dict:
    return _requete("GET", f"/clip-projects/{projet_id}")


def lister_projets() -> list[dict]:
    rep = _requete("GET", "/clip-projects")
    return list(rep.get("list", []))


def gabarits() -> dict:
    return _requete("GET", "/brand-templates")


# ------------------------------------------------------------- extraction
def choisir_sources(cfg, db, combien: int) -> tuple[list, dict]:
    """Les sermons à envoyer au découpage, du plus prometteur au moins.

    Trois règles, dans cet ordre :

    1. **Fraîcheur** (Michel, 06/08) : « la conférence Sophos est déjà passée,
       on vise les nouveaux. » Le fonds de catalogue n'a pas sa place quand
       le budget couvre 6 sermons pour une vingtaine qui sortent.
    2. **Budget réservé à Amessan** (Michel, 10/08) : « on vise ceux du
       pasteur Jacques Amessan tout au long du mois, et à la fin, quand il en
       reste, on choisit aléatoirement entre les autres chaînes. » Ses deux
       chaînes produisent 11 à 15 sermons longs par mois — largement de quoi
       remplir un budget de 6 — et il rapporte trois à vingt fois plus que
       les autres.
    3. **Plafond quotidien**, appliqué par l'appelant.

    Retourne (sources, bilan_du_tri) — le bilan sert à expliquer les écarts.
    """
    from datetime import datetime, timedelta, timezone

    maintenant = datetime.now(timezone.utc)
    limite = maintenant - timedelta(days=cfg.opus_fraicheur_max_jours)
    bascule = None
    if cfg.opus_traiter_a_partir_de:
        try:
            bascule = datetime.fromisoformat(cfg.opus_traiter_a_partir_de).replace(tzinfo=timezone.utc)
        except ValueError:
            log.warning("Date de bascule illisible : %r — ignorée",
                        cfg.opus_traiter_a_partir_de)

    reservees = set(cfg.opus_chaines_reservees)
    # Les autres chaînes n'entrent en jeu qu'en fin de mois, et seulement s'il
    # reste des crédits qu'Amessan n'a pas consommés.
    autres_ouvertes = (not reservees
                       or maintenant.day >= cfg.opus_jour_ouverture_autres)

    bilan = {"examinees": 0, "trop_vieilles": 0, "avant_bascule": 0,
             "hors_reserve": 0, "retenues": 0,
             "autres_ouvertes": autres_ouvertes}

    candidates = []
    for src in db.sources_par_etat("REPERE"):
        bilan["examinees"] += 1
        try:
            publie = datetime.fromisoformat((src["published_at"] or "").replace("Z", "+00:00"))
        except ValueError:
            publie = None
        if publie is None:
            bilan["trop_vieilles"] += 1
            continue
        if bascule and publie < bascule:
            bilan["avant_bascule"] += 1
            continue
        if publie < limite:
            bilan["trop_vieilles"] += 1
            continue
        if reservees and src["handle"] not in reservees and not autres_ouvertes:
            bilan["hors_reserve"] += 1
            continue
        candidates.append(src)

    def _cle(s):
        # Amessan d'abord, toujours. Entre ses propres sermons : le plus
        # récent, puis le plus regardé.
        prioritaire = 0 if s["handle"] in reservees else 1
        return (prioritaire, -publie_ts(s["published_at"]), -(s["view_count"] or 0))

    candidates.sort(key=_cle)
    retenues = candidates[:combien] if combien else candidates
    bilan["retenues"] = len(retenues)
    return retenues, bilan


def publie_ts(iso: str | None) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def hms(secondes) -> str:
    s = int(secondes or 0)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def preparer(cfg, src) -> dict:
    """Prépare l'envoi d'une source SANS rien envoyer.

    Retourne le plan complet : fenêtre trouvée, coût, requête exacte. C'est ce
    que la commande `vortex opus` affiche à Michel avant qu'il décide.
    Aucun crédit n'est consommé ici — seulement la lecture gratuite des
    sous-titres YouTube et un appel à DeepSeek.
    """
    from . import fenetre as mod_fenetre

    duree = int(src["duration_s"] or 0)
    if not duree:
        raise OpusError(f"durée inconnue pour {src['youtube_id']}")

    vue = mod_fenetre.trouver(
        src["youtube_id"], duree,
        largeur_max_s=cfg.opus_fenetre_max_s,
        largeur_min_s=cfg.opus_fenetre_min_s,
        langue=cfg.langue_clipping,
    )
    credits = verifier_fenetre(vue["debut_s"], vue["fin_s"], duree,
                               cfg.opus_credits_max_par_projet)
    demande = construire_demande(
        url_video=f"https://www.youtube.com/watch?v={src['youtube_id']}",
        titre=src["titre"] or src["youtube_id"],
        debut_s=vue["debut_s"], fin_s=vue["fin_s"],
        clip_min_s=cfg.opus_clip_min_s, clip_max_s=cfg.opus_clip_max_s,
        modele=cfg.opus_modele, genre=cfg.opus_genre,
        mots_cles=[m for m in (src["pasteur"], src["eglise"]) if m],
    )
    return {
        "youtube_id": src["youtube_id"],
        "titre": src["titre"],
        "duree_s": duree,
        "fenetre": vue,
        "credits": credits,
        "credits_si_video_entiere": cout_credits(0, duree),
        "demande": demande,
    }


def afficher_plan(plan: dict, credits_restants: int | None = None) -> None:
    """Imprime le plan en clair. C'est la dernière chose que Michel voit
    avant de décider de dépenser."""
    f = plan["fenetre"]
    duree_fenetre = f["fin_s"] - f["debut_s"]
    print(f"\n  {plan['titre'][:66]}")
    print(f"  vidéo      : {hms(plan['duree_s'])}  ({plan['youtube_id']})")
    print(f"  fenetre    : {hms(f['debut_s'])} -> {hms(f['fin_s'])}"
          f"   ({duree_fenetre // 60} min)")
    print(f"  repérage   : {f['source']}, certitude {f['certitude']}")
    print(f"  raison     : {f['raison'][:150]}")
    print(f"  extraits   : entre {plan['demande']['curationPref']['clipDurations'][0][0] // 60}"
          f" et {plan['demande']['curationPref']['clipDurations'][0][1] // 60} min")
    print(f"  COÛT       : {plan['credits']} crédits"
          f"   (la vidéo entière en coûterait {plan['credits_si_video_entiere']},"
          f" soit {plan['credits_si_video_entiere'] - plan['credits']} économisés)")
    if credits_restants is not None:
        print(f"  budget     : {credits_restants} crédits restants ce mois-ci"
              f" → {credits_restants - plan['credits']} après cet envoi")


# --------------------------------------------------------------- publication
#
# OpusClip publie DIRECTEMENT sur les réseaux reliés à son tableau de bord.
# Vérifié le 09/08/2026 : le compte TikTok @hedjav y est relié avec le droit
# `video.publish` — exactement l'autorisation que TikTok nous avait refusée en
# juillet pour notre propre app. La chaîne YouTube « Sophos PropheTikos » l'est
# aussi. Publier ne coûte AUCUN crédit (seul X en consomme un par post).
#
# Structure des appels, découverte en sondant l'API (la documentation publique
# ne la détaille pas) :
#   GET  /api/social-accounts?q=mine
#   GET  /api/exportable-clips?q=findByProjectId&projectId=…
#   POST /api/post-tasks         {projectId, clipId, postAccountId, postDetail}
#   POST /api/publish-schedules  idem + date de programmation
#
# ⚠️ Ces points d'accès sont limités à 1 requête par seconde.

TIKTOK = "TIKTOK_BUSINESS"
YOUTUBE = "YOUTUBE"


def comptes_relies() -> list[dict]:
    """Comptes sociaux reliés au compte OpusClip."""
    rep = _requete("GET", "/social-accounts?q=mine")
    return list(rep.get("data") or [])


def compte_pour(plateforme: str = TIKTOK) -> dict | None:
    """Le compte relié pour une plateforme, ou None."""
    for c in comptes_relies():
        if str(c.get("platform", "")).upper() == plateforme.upper():
            return c
    return None


def clips_exportables(projet_id: str) -> list[dict]:
    """Extraits d'un projet, tels que l'API de publication les voit."""
    rep = _requete("GET", f"/exportable-clips?q=findByProjectId&projectId={projet_id}")
    donnees = rep.get("data") if isinstance(rep, dict) else rep
    return list(donnees or [])


def _clip_nu(clip_id: str) -> str:
    """« P123.CU456 » → « CU456 ».

    L'API rend des identifiants composés mais n'accepte que la partie droite
    pour publier. C'est écrit dans leur documentation, et c'est le genre de
    détail qui fait échouer un envoi sans explication lisible.
    """
    return (clip_id or "").split(".")[-1]


def publications_du_projet(projet_id: str) -> list[dict]:
    """Publications déjà créées pour un projet, quel qu'en soit l'état."""
    rep = _requete("GET", f"/post-tasks?q=findByProjectId&projectId={projet_id}")
    donnees = rep.get("data") if isinstance(rep, dict) else rep
    if isinstance(donnees, dict):
        donnees = donnees.get("data") or donnees.get("list") or []
    return [p for p in (donnees or []) if isinstance(p, dict)]


def deja_publie(projet_id: str, clip_id: str) -> dict | None:
    """La publication existante de cet extrait, ou None.

    ⚠️ CONTRÔLE INDISPENSABLE. Le 10/08, le même extrait de 5 min 36 est parti
    DEUX FOIS sur TikTok : la tâche automatique a republié ce qui venait
    d'être envoyé à la main. Notre base ne suffit pas à l'empêcher — deux
    machines ont chacune la leur. La seule source de vérité est OpusClip
    lui-même, qui sait ce qu'il a déjà posté.
    """
    nu = _clip_nu(clip_id)
    for p in publications_du_projet(projet_id):
        if _clip_nu(str(p.get("clipId") or "")) != nu:
            continue
        if str(p.get("status", "")).lower() in ("cancelled", "canceled", "failed", "error"):
            continue
        return p
    return None


def publier_clip(projet_id: str, clip_id: str, compte_id: str, *,
                 titre: str, description: str = "",
                 planifie_pour: str = "", forcer: bool = False) -> dict:
    """Publie ou programme un extrait sur un compte relié.

    `planifie_pour` : date ISO 8601 UTC. Vide = publication immédiate.
    Ne consomme aucun crédit sur TikTok et YouTube.
    """
    # Verrou anti-doublon : on demande à OpusClip s'il a déjà posté cet
    # extrait, avant de lui en redemander un. C'est le seul contrôle qui
    # tienne quand plusieurs machines publient.
    if not forcer:
        existante = deja_publie(projet_id, clip_id)
        if existante:
            raise OpusError(
                f"extrait déjà publié le {str(existante.get('publishAt'))[:16]} "
                f"({existante.get('status')}) — {existante.get('extVideoLink') or 'sans lien'}")

    # ⚠️ La description est IMBRIQUÉE dans `postDetail.custom`. Envoyée à plat
    # (`postDetail.description`), elle est acceptée sans erreur puis ignorée :
    # trois vidéos sont parties sur TikTok sans un mot de légende le 10/08,
    # tout le travail de SEO perdu en silence. Vérifié depuis sur les
    # publications enregistrées : `postDetail.custom.description` est le seul
    # champ que TikTok reçoit.
    corps = {
        "projectId": projet_id,
        "clipId": _clip_nu(clip_id),
        "postAccountId": compte_id,
        "postDetail": {
            "title": (titre or "")[:150],
            "custom": {"description": (description or "")[:2200]},
        },
    }
    if not planifie_pour:
        return _requete("POST", "/post-tasks", corps, timeout=120)

    # Le champ de date s'appelle `publishAt` — non documenté, révélé par le
    # message d'erreur de l'API le 09/08 (« publishAt must be a valid date
    # string »). Il attend un ISO 8601 avec millisecondes, la forme que
    # l'API emploie elle-même partout ailleurs.
    corps["publishAt"] = _iso_millisecondes(planifie_pour)
    return _requete("POST", "/publish-schedules", corps, timeout=120)


def _iso_millisecondes(iso: str) -> str:
    """« 2026-08-10T02:00:00Z » → « 2026-08-10T02:00:00.000Z »."""
    from datetime import datetime, timezone

    try:
        d = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return iso
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{d.microsecond // 1000:03d}Z"


def clips_du_projet(donnees: dict) -> list[dict]:
    """Normalise les extraits, quel que soit le nom des champs renvoyés."""
    bruts = (donnees.get("clips") or donnees.get("list")
             or (donnees.get("data") or {}).get("clips") or [])
    sortie = []
    for c in bruts:
        if not isinstance(c, dict):
            continue
        # OpusClip nomme ses liens `uriForExport` et `uriForPreview` — pas
        # `downloadUrl` comme Submagic. Chercher les mauvais noms rendait une
        # liste vide, et aucun extrait n'aurait jamais été récolté.
        lien = (c.get("uriForExport") or c.get("uriForPreview")
                or c.get("downloadUrl") or c.get("videoUrl") or c.get("url") or "")
        if not lien:
            continue
        debut = c.get("startSec", c.get("start"))
        fin = c.get("endSec", c.get("end"))
        # OpusClip donne la position sous forme de `timeRanges`, en
        # MILLISECONDES : [[4849971, 5418790]]. C'est ce qui permet de
        # repérer un extrait taillé à l'intérieur d'un autre.
        plages = c.get("timeRanges")
        if debut is None and isinstance(plages, list) and plages:
            try:
                debut = float(plages[0][0]) / 1000
                fin = float(plages[-1][1]) / 1000
            except (TypeError, ValueError, IndexError):
                debut = fin = None
        duree = c.get("duration")
        if duree is None and c.get("durationMs") is not None:
            try:
                duree = float(c["durationMs"]) / 1000
            except (TypeError, ValueError):
                duree = None
        if duree is None and debut is not None and fin is not None:
            try:
                duree = float(fin) - float(debut)
            except (TypeError, ValueError):
                duree = 0
        sortie.append({
            "id": str(c.get("id") or c.get("clipId") or ""),
            "titre": (c.get("title") or c.get("name") or "").strip(),
            "duree_s": float(duree or 0),
            "debut_s": float(debut) if debut is not None else None,
            "fin_s": float(fin) if fin is not None else None,
            # OpusClip note ses extraits sur 100 (« score »).
            "score_total": float(c.get("score") or c.get("viralityScore") or 0),
            "download_url": c.get("uriForExport") or lien,
            "direct_url": c.get("uriForExport") or lien,
            "preview_url": c.get("uriForPreview") or "",
            # `text` porte la transcription de l'extrait : elle nourrit
            # directement le SEO français, sans second appel.
            "texte": c.get("text") or c.get("transcript") or "",
            "hashtags_source": list(c.get("hashtags") or []),
        })
    sortie.sort(key=lambda c: c["score_total"], reverse=True)
    return sortie

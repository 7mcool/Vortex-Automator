"""Veille des chaînes YouTube visées : repérer les longues vidéos et les directs.

Deux sources d'information, choisies pour leur coût :

- **Le flux RSS de la chaîne** (`feeds/videos.xml?channel_id=…`) donne les 15
  dernières vidéos, gratuitement et sans toucher au quota de l'API. C'est lui
  qui fait la détection.
- **L'API YouTube** ne sert qu'à connaître la durée et le nombre de vues, par
  paquets de 50 identifiants : 1 unité de quota par paquet, soit 3 unités pour
  les sept chaînes. À comparer aux 1 600 unités que coûte UNE publication.

Règle sur le nom de l'orateur (retour de Michel, 24/07 — deux vidéos avaient
été attribuées au mauvais pasteur) : **on ne nomme jamais par déduction**. Le
nom n'est retenu que s'il est écrit dans le titre de la vidéo, ou si la chaîne
n'a qu'un seul prédicateur déclaré dans la configuration.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .config import Config
from .db import Database

log = logging.getLogger("vortex.veille")

RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
# YouTube renvoie une page de consentement aux clients sans navigateur déclaré.
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


# --------------------------------------------------------------------- outils
def _sans_accent(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def empreinte(titre: str) -> str:
    """Clé stricte : le titre normalisé, DATE COMPRISE.

    Deux chaînes rediffusent parfois le même culte (Yannick Djatti et le
    Centre Chrétien de Réveil) : sans cette clé, le même sermon partirait deux
    fois au découpage.

    La date écrite DANS le titre est conservée volontairement : c'est elle qui
    distingue deux numéros d'une émission hebdomadaire qui garde son nom
    (« RDV DES CHAMPIONS | 05/08 » et « | 12/08 » sont bien deux cultes).
    """
    base = _sans_accent(titre or "").lower()
    base = re.sub(r"[^a-z0-9]+", " ", base).strip()
    return base[:70]


def empreinte_lache(titre: str) -> str:
    """Clé souple : même titre, dates retirées.

    Sert à reconnaître une REMISE EN LIGNE. Michel, 07/08 : l'église rend
    parfois le direct privé, coupe des passages, et le republie en vidéo. La
    nouvelle version porte une nouvelle adresse, et souvent une nouvelle date
    dans son titre — la clé stricte ne la reconnaît donc pas.

    Associée à un contrôle de durée (une version remontée est toujours plus
    courte que le direct d'origine), elle évite de payer 45 crédits deux fois
    pour le même sermon.
    """
    base = _sans_accent(titre or "").lower()
    base = re.sub(r"\d{1,2}[/_-]\d{1,2}([/_-]\d{2,4})?", " ", base)
    base = re.sub(r"[^a-z0-9]+", " ", base).strip()
    return base[:70]


# Fenêtre de recherche des doublons. Portée de 4 à 45 jours le 07/08 : une
# remise en ligne peut arriver plusieurs semaines après le direct. Michel a
# tranché — « on ne repaie jamais ». Le risque inverse (écarter à tort un vrai
# nouveau sermon) coûte une occasion, pas de l'argent : avec 11 à 15 sermons
# d'Amessan par mois pour un budget de 6, en manquer un ne change rien.
FENETRE_DOUBLON_JOURS = 45


def _iso_en_secondes(duree_iso: str) -> int:
    m = re.match(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duree_iso or "")
    if not m:
        return 0
    j, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return j * 86400 + h * 3600 + mi * 60 + s


def lire_flux(channel_id: str, timeout: int = 45) -> list[dict]:
    """Les 15 dernières vidéos d'une chaîne, via son flux RSS public."""
    req = urllib.request.Request(RSS.format(channel_id), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        xml = r.read().decode("utf-8", "replace")

    entrees = []
    for bloc in xml.split("<entry>")[1:]:
        vid = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", bloc)
        titre = re.search(r"<title>([^<]*)</title>", bloc)
        pub = re.search(r"<published>([^<]+)</published>", bloc)
        if not vid:
            continue
        brut = titre.group(1) if titre else ""
        entrees.append({
            "youtube_id": vid.group(1),
            "titre": _decoder_xml(brut),
            "published_at": pub.group(1) if pub else "",
        })
    return entrees


def _decoder_xml(texte: str) -> str:
    for source, cible in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                          ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'")):
        texte = texte.replace(source, cible)
    return texte.strip()


def lire_directs(handle: str, combien: int = 15, timeout: int = 240) -> list[dict]:
    """Les derniers DIRECTS d'une chaîne, via son onglet /streams.

    Indispensable en complément du flux RSS, qui ne montre que les 15
    dernières publications tous formats confondus. Mesuré le 06/08 sur
    @lamaisondesagesse : la chaîne publie une dizaine de vidéos courtes par
    semaine, si bien que ses directs — les sermons de Jacques Amessan, 100 à
    160 minutes — ne figuraient JAMAIS dans le flux. La veille annonçait
    0,7 sermon par semaine là où il y en a 1,8.

    Plus lent que le RSS (une dizaine de secondes par chaîne) mais toujours
    gratuit : aucune unité de quota, aucun téléchargement de vidéo.
    """
    from .fenetre import _cookies_youtube

    commande = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist", "--playlist-end", str(combien),
        "--no-warnings", "--quiet",
        "--print", "%(id)s\t%(duration)s\t%(title)s",
    ]
    cookies = _cookies_youtube()
    if cookies:
        commande += ["--cookies", cookies]
    if shutil.which("node"):
        commande += ["--js-runtimes", "node"]
    commande.append(f"https://www.youtube.com/@{urllib.parse.quote(handle)}/streams")

    try:
        res = subprocess.run(commande, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        log.warning("Onglet /streams de @%s : délai dépassé", handle)
        return []

    sorties = []
    for ligne in (res.stdout or "").splitlines():
        morceaux = ligne.split("\t")
        if len(morceaux) < 3 or not morceaux[0].strip():
            continue
        sorties.append({"youtube_id": morceaux[0].strip(), "titre": morceaux[2].strip(),
                        "published_at": ""})
    if not sorties and res.stderr:
        log.warning("Onglet /streams de @%s illisible : %s", handle,
                    res.stderr.strip().splitlines()[-1][:160] if res.stderr.strip() else "?")
    return sorties


# Un titre qui nomme explicitement un intervenant, quel qu'il soit. Sert de
# garde-fou : si le titre annonce « Pst N'ZUÉ Daniel », la chaîne peut bien
# appartenir à Yannick Djatti, ce n'est pas lui qui prêche ce jour-là.
_ANNONCE_ORATEUR = re.compile(
    # « Pr » manquait, et « SOIREE DE VERITES PROFONDES - Pr ARISTON
    # TELESPHORE » s'est retrouvé attribué à Jacques Amessan (constaté le
    # 09/08 sur le serveur). Toute abréviation de civilité doit figurer ici.
    r"\b(?:pst|past|pasteur|pr|prophete|proph[eè]te|ap[oô]tre|apotre|ev|[eé]vang[eé]liste"
    r"|r[eé]v[eé]rend|rev|dr|bishop|mgr|fr[eè]re|s[oœ]ur|serviteur|min|ministre)"
    r"\.?\s+[A-ZÀ-Ý][\w'’-]+",
    re.IGNORECASE)


def orateur(titre: str, chaine: dict, connus: list[str]) -> tuple[str, str]:
    """(orateur, organisation) — le nom n'est rendu que s'il est CERTAIN.

    Priorité 1 : un intervenant du registre nommé dans le titre.
    Priorité 2 : la chaîne ne diffuse qu'une seule personne — SAUF si le titre
    annonce quelqu'un d'autre.
    Sinon : rien, et le SEO dira « l'orateur » (jamais « le pasteur » : ces
    chaînes reçoivent aussi des laïcs, voir intervenants.py).
    """
    from .intervenants import INTERVENANTS, canonique, organisation

    titre_norm = _sans_accent(titre or "").lower()
    # Le registre fait foi : il porte l'orthographe officielle et le rôle réel
    # de chacun (tous ne sont pas pasteurs — voir intervenants.py).
    for nom in list(connus) + [n for n in INTERVENANTS if n not in connus]:
        # TOUS les mots du nom doivent figurer dans le titre. Se contenter du
        # nom de famille attribuait « LA NÉCESSITÉ DU SAINT-ESPRIT | Pasteur
        # Lilliane SANOGO » à Mohammed Sanogo (constaté le 03/08) — exactement
        # l'erreur d'orateur signalée par Michel le 24/07. Les chaînes
        # d'église diffusent l'épouse, les invités, les pasteurs associés.
        morceaux = [_sans_accent(m).lower() for m in nom.split() if len(m) >= 3]
        if morceaux and all(m in titre_norm for m in morceaux):
            officiel = canonique(nom)
            return officiel, organisation(officiel) or chaine.get("eglise", "")

    if chaine.get("pasteur") and chaine.get("pasteur_unique"):
        # Le titre annonce un intervenant que le registre ne connaît pas ?
        # Alors ce n'est PAS le titulaire de la chaîne. Constaté le 09/08 :
        # « CROIS TOI ET TA FAMILLE… | Pst N'ZUÉ Daniel » sur la chaîne de
        # Yannick Djatti était attribué à Djatti. Mieux vaut ne nommer
        # personne que nommer le mauvais.
        if _ANNONCE_ORATEUR.search(titre or ""):
            log.info("Titre annonçant un tiers — aucun nom retenu : %s", (titre or "")[:60])
            return "", chaine.get("eglise", "")
        return canonique(chaine["pasteur"]), chaine.get("eglise", "")
    return "", chaine.get("eglise", "")


# ---------------------------------------------------------------------- veille
def veiller(cfg: Config, db: Database, *, service=None) -> dict:
    """Parcourt les chaînes visées et enregistre les nouvelles sources longues.

    Retourne un bilan chiffré. Aucune vidéo n'est téléchargée : à ce stade on
    ne manipule que des identifiants.
    """
    chaines = cfg.chaines_surveillees
    if not chaines:
        log.warning("Aucune chaîne surveillée dans config.toml ([[clipping.chaines]])")
        return {"vues": 0, "nouvelles": 0}

    candidats: dict[str, dict] = {}
    bilan = {"vues": 0, "nouvelles": 0, "deja_connues": 0, "trop_courtes": 0,
             "doublons": 0, "chaines_ko": 0}

    for chaine in chaines:
        cid = chaine.get("id", "")
        if not cid:
            log.warning("Chaîne @%s sans identifiant UC… — ignorée", chaine.get("handle"))
            continue
        try:
            entrees = lire_flux(cid)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("Flux RSS @%s indisponible : %s", chaine.get("handle"), exc)
            bilan["chaines_ko"] += 1
            continue
        # Le flux RSS suffit pour REPÉRER une nouveauté (elle y arrive en tête
        # dès sa publication), mais il ne suffit pas à connaître le catalogue :
        # sur une chaîne qui publie beaucoup de formats courts, les directs en
        # sont chassés. On complète donc par l'onglet /streams.
        directs = lire_directs(chaine.get("handle", ""))
        log.info("@%s : %d entrées RSS, %d direct(s)",
                 chaine.get("handle"), len(entrees), len(directs))

        vus_ici = set()
        for e in entrees + directs:
            if e["youtube_id"] in vus_ici:
                continue
            vus_ici.add(e["youtube_id"])
            bilan["vues"] += 1
            # UNE SOURCE ENREGISTRÉE PENDANT SON DIRECT DOIT ÊTRE REVUE.
            #
            # Elle a été inscrite avec la durée partielle du moment et la date
            # de programmation du live. Tant qu'on la traite comme « déjà
            # connue », elle garde ces valeurs fausses à vie et n'est jamais
            # découpée. On la repasse donc dans le circuit tant qu'elle porte
            # la marque du direct.
            connue = db.conn.execute(
                "SELECT is_live, etat FROM sources_yt WHERE youtube_id = ?",
                (e["youtube_id"],)).fetchone()
            if connue and not (connue["is_live"] and connue["etat"] == "REPERE"):
                bilan["deja_connues"] += 1
                continue
            e["chaine_cfg"] = chaine
            e["a_rafraichir"] = bool(connue)
            candidats[e["youtube_id"]] = e

    if not candidats:
        return bilan

    # Durée et audience : un seul aller-retour par paquet de 50.
    details = _details_videos(cfg, list(candidats), service=service)

    # Le plus récent d'abord : si deux chaînes diffusent le même culte, c'est
    # celle qui a le plus d'audience qui est retenue (meilleure source).
    ordre = sorted(
        candidats.values(),
        key=lambda e: (e.get("published_at", ""), details.get(e["youtube_id"], {}).get("vues", 0)),
        reverse=True,
    )

    for e in ordre:
        info = details.get(e["youtube_id"])
        if not info:
            continue  # vidéo supprimée ou privée entre le flux et l'appel API
        duree = info["duree_s"]
        chaine = e["chaine_cfg"]
        # Les entrées venues de /streams n'ont pas de date : l'API la donne.
        if not e.get("published_at"):
            e["published_at"] = info.get("publie_le", "")

        # UN DIRECT EST DATÉ PAR SA FIN, PAS PAR SA MISE EN LIGNE.
        #
        # Une église crée son direct plusieurs jours à l'avance : le culte du
        # mardi soir porte la date du dimanche où il a été programmé. Constaté
        # le 11/08 — le culte qui venait de se terminer était daté du 9, et les
        # filtres de fraîcheur l'écartaient comme s'il s'agissait d'archives.
        # Ce qui date un sermon, c'est le moment où il a été prêché.
        if info.get("fin_direct"):
            e["published_at"] = info["fin_direct"]

        if info.get("direct_en_cours"):
            # Le culte est en train de se dérouler. On ne l'enregistre pas :
            # la prochaine veille le reprendra une fois terminé, avec sa vraie
            # durée. L'enregistrer maintenant le figerait à zéro minute.
            bilan["en_direct"] = bilan.get("en_direct", 0) + 1
            log.info("En direct, on repassera : %s — %s", e["youtube_id"], e["titre"][:50])
            continue

        if duree < cfg.source_duree_min_s:
            bilan["trop_courtes"] += 1
            continue

        emp = empreinte(e["titre"])
        emp_lache = empreinte_lache(e["titre"])

        # RAFRAÎCHISSEMENT d'un direct terminé, déjà en base. On corrige la
        # durée et la date — la recherche de doublon n'a pas lieu d'être, elle
        # retrouverait la source elle-même et l'écarterait comme sa propre copie.
        if e.get("a_rafraichir"):
            db.maj_source(e["youtube_id"], duration_s=duree, is_live=0,
                          published_at=e["published_at"],
                          view_count=info["vues"], empreinte=emp,
                          empreinte_lache=emp_lache)
            bilan["nouvelles"] += 1
            log.info("Direct terminé, fiche corrigée : %s — %s (%d min, fin %s)",
                     e["youtube_id"], e["titre"][:50], duree // 60,
                     e["published_at"][:16])
            continue

        jumelle, raison = db.empreinte_connue(
            emp, e["published_at"], FENETRE_DOUBLON_JOURS,
            empreinte_lache=emp_lache, duration_s=duree)
        if jumelle:
            log.info("Écarté (%s) : %s — déjà couvert par %s",
                     raison, e["youtube_id"], jumelle)
            bilan["doublons"] += 1
            db.ajouter_source({
                "youtube_id": e["youtube_id"], "handle": chaine["handle"],
                "chaine": chaine.get("nom", ""), "titre": e["titre"],
                "published_at": e["published_at"], "duration_s": duree,
                "is_live": info["live"], "view_count": info["vues"],
                "empreinte": emp, "empreinte_lache": emp_lache, "etat": "ECARTE",
            })
            continue

        pasteur, eglise = orateur(e["titre"], chaine, cfg.known_speakers)
        db.ajouter_source({
            "youtube_id": e["youtube_id"], "handle": chaine["handle"],
            "chaine": chaine.get("nom", ""), "pasteur": pasteur, "eglise": eglise,
            "titre": e["titre"], "published_at": e["published_at"],
            "duration_s": duree, "is_live": info["live"], "view_count": info["vues"],
            "empreinte": emp, "empreinte_lache": emp_lache, "etat": "REPERE",
        })
        bilan["nouvelles"] += 1
        log.info("Repérée : %s — %s (%d min, %s)", e["youtube_id"], e["titre"][:60],
                 duree // 60, pasteur or "orateur non nommé")

    return bilan


def video_disponible(cfg: Config, youtube_id: str) -> bool | None:
    """La vidéo est-elle encore publique ? None si on n'a pas pu vérifier.

    Michel l'avait annoncé, et c'est arrivé le 11/08 : « parfois ils peuvent
    rendre privé un direct, couper certaines parties et le remettre en ligne
    en forme de vidéos ». Le culte du soir a disparu deux heures après sa fin.

    Sans ce contrôle, on proposerait à Michel un sermon introuvable — et un GO
    de sa part lancerait un import voué à l'échec. On préfère l'écarter : la
    version remontée sera repérée à sa republication, et le contrôle de
    doublon empêchera de la payer deux fois.
    """
    try:
        from .youtube_client import get_service
        rep = get_service(cfg).videos().list(part="status", id=youtube_id).execute()
    except Exception as exc:
        log.warning("Disponibilité de %s invérifiable : %s", youtube_id, exc)
        return None
    items = rep.get("items", [])
    if not items:
        return False
    return items[0].get("status", {}).get("privacyStatus") == "public"


def _details_videos(cfg: Config, ids: list[str], *, service=None) -> dict[str, dict]:
    """Durée, direct et vues pour une liste d'identifiants (1 unité / 50 ids)."""
    if service is None:
        from .youtube_client import get_service
        service = get_service(cfg)

    sortie: dict[str, dict] = {}
    for debut in range(0, len(ids), 50):
        lot = ids[debut:debut + 50]
        try:
            rep = service.videos().list(
                part="snippet,contentDetails,liveStreamingDetails,statistics",
                id=",".join(lot),
            ).execute()
        except Exception as exc:  # quota, réseau : la veille reprendra plus tard
            log.warning("API YouTube indisponible pour un lot de %d : %s", len(lot), exc)
            continue
        for it in rep.get("items", []):
            details = it.get("contentDetails", {})
            stats = it.get("statistics", {})
            direct = it.get("liveStreamingDetails", {})
            sortie[it["id"]] = {
                "duree_s": _iso_en_secondes(details.get("duration", "")),
                "live": "liveStreamingDetails" in it,
                "vues": int(stats.get("viewCount", 0) or 0),
                "publie_le": it.get("snippet", {}).get("publishedAt", ""),
                # Un direct en COURS n'a pas de fin : il n'y a rien à découper
                # tant qu'il tourne. C'est ce champ, et non la date de mise en
                # ligne, qui dit qu'un culte est terminé et exploitable.
                "direct_termine": bool(direct.get("actualEndTime")),
                # L'heure de FIN du direct. Pour un culte, c'est elle qui date
                # le sermon — voir plus bas dans veiller().
                "fin_direct": direct.get("actualEndTime", ""),
                "direct_en_cours": bool(direct.get("actualStartTime")
                                        and not direct.get("actualEndTime")),
            }
    return sortie


def resoudre_handle(handle: str, timeout: int = 60) -> str:
    """Identifiant UC… d'une chaîne à partir de son @handle.

    Sert à ajouter une chaîne à la configuration sans aller la chercher à la
    main. L'identifiant est ensuite figé dans config.toml : un @handle peut
    changer, un UC… jamais.
    """
    url = f"https://www.youtube.com/@{urllib.parse.quote(handle)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        page = r.read().decode("utf-8", "replace")
    m = re.search(r"channel/(UC[\w-]{22})", page)
    return m.group(1) if m else ""

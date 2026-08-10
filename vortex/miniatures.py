"""Remplace les miniatures TOUT-TEXTE de la chaîne par des miniatures à VISAGE.

Michel, 10/08/2026 : « supprime les miniatures sans visage et qui sont
uniquement du texte sur toutes les vidéos YouTube ». Relevé ce jour-là : 109
vidéos sur 301 en portaient une.

⚠️ L'API YouTube ne sait PAS retirer une miniature : `thumbnails.set` est la
seule méthode, il n'y a pas de `thumbnails.delete`. On ne peut donc que
REMPLACER — et poser une image de la vidéo revient au même à l'écran.

DEUX FORMULES, moitié-moitié (Michel : « on peut faire les deux ? ») :
  * `image`        — un plan de la vidéo, sans rien ajouter ;
  * `visage-texte` — le même visage recadré, plus une accroche courte.
La formule est inscrite dans le NOM du fichier préparé : les deux machines la
lisent sans avoir à partager un journal.

DEUX MACHINES, DEUX RÔLES (Michel : « que mon ordi soit allumé ou pas tout
doit passer, avec aussi mon PC »).

    PC        →  --preparer   puis  --envoyer
    PC + VPS  →  --poser

Le serveur ne peut PAS préparer : YouTube lui refuse tout téléchargement
(« Sign in to confirm you're not a bot », vérifié le 10/08 avec et sans
cookies). Il sait en revanche très bien poser une miniature, puisque c'est
lui qui publie. Le PC fabrique donc les images et les dépose sur le serveur,
qui les pose ensuite tout seul, PC éteint.

AUCUN RISQUE DE DOUBLON entre les deux machines : avant de poser, chacune
regarde la miniature réellement en ligne. Une vidéo déjà traitée montre un
visage, elle est donc ignorée — sans journal partagé.

LA LIMITE À CONNAÎTRE : YouTube borne le RYTHME de dépôt, indépendamment du
quota. Au-delà de quelques envois rapprochés il répond 429 « The user has
uploaded too many thumbnails recently », et chaque refus compte. D'où la
pause entre deux envois et l'arrêt net au premier refus.

    python scripts/refaire_miniatures_youtube.py --analyser
    python scripts/refaire_miniatures_youtube.py --preparer 20
    python scripts/refaire_miniatures_youtube.py --envoyer
    python scripts/refaire_miniatures_youtube.py --poser 6
    python scripts/refaire_miniatures_youtube.py --resultats
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import thumbs, youtube_client
from .config import load_config
from .metadata import derive_thumb_title
from .visage import image_miniature, portrait_depuis_video

# Racine du dépôt : ce module vit dans vortex/, les données un cran au-dessus.
RACINE = Path(__file__).resolve().parent.parent

log = logging.getLogger("refaire-miniatures")

PRETES = RACINE / "data" / "miniatures_pretes"
JOURNAL = RACINE / "data" / "miniatures_refaites.json"
CACHE_VERDICTS = RACINE / "data" / "verdicts_visage.json"
DOSSIER_VIDEOS = RACINE / "data" / "videos_temporaires"
DOSSIER_VIGNETTES = RACINE / "data" / "vignettes_chaine"
COOKIES = RACINE / "secrets" / "youtube_cookies.txt"
MODELE = RACINE / "assets" / "modeles" / "face_detection_yunet_2023mar.onnx"

FORMULES = ("image", "visage-texte")
PAUSE_PAR_DEFAUT = 120
POSES_PAR_DEFAUT = 6
PREPARATIONS_PAR_DEFAUT = 20

# Serveur de publication (voir secrets/hostinger.env).
VPS_HOTE = os.environ.get("VORTEX_VPS_HOTE", "srv1769401.hstgr.cloud")
VPS_UTILISATEUR = os.environ.get("VORTEX_VPS_USER", "root")
VPS_CLE = Path(os.environ.get("VORTEX_VPS_CLE", str(Path.home() / ".ssh" / "vortex_vps")))
VPS_DEPOT = "/opt/vortex/repo/data/miniatures_pretes"


# --------------------------------------------------------------------------
# journal (indicatif : la vérité reste ce qui est en ligne)
# --------------------------------------------------------------------------
def lire_journal() -> dict:
    if JOURNAL.is_file():
        try:
            return json.loads(JOURNAL.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("Journal illisible — on repart de zéro")
    return {}


def ecrire_journal(journal: dict) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.write_text(json.dumps(journal, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# inventaire de la chaîne
# --------------------------------------------------------------------------
def _secondes(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mn, s = (int(v) if v else 0 for v in m.groups())
    return h * 3600 + mn * 60 + s


def inventaire(service) -> list[dict]:
    """Toutes les vidéos de la chaîne, dédoublonnées, avec leur miniature."""
    chaine = service.channels().list(part="contentDetails,snippet", mine=True).execute()
    items = chaine.get("items") or []
    if not items:
        raise SystemExit("l'API ne renvoie aucune chaîne pour ce compte")
    log.info("Chaîne : %s", items[0]["snippet"]["title"])
    playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, page = [], None
    while True:
        reponse = service.playlistItems().list(
            part="contentDetails", playlistId=playlist,
            maxResults=50, pageToken=page).execute()
        for it in reponse.get("items", []):
            ids.append(it["contentDetails"]["videoId"])
        page = reponse.get("nextPageToken")
        if not page:
            break
    # La playlist « uploads » peut servir deux fois la même vidéo d'une page à
    # l'autre : sans ce filtre, on la traiterait en double.
    uniques = list(dict.fromkeys(ids))

    videos = []
    for i in range(0, len(uniques), 50):
        reponse = service.videos().list(
            part="snippet,status,contentDetails",
            id=",".join(uniques[i:i + 50])).execute()
        for it in reponse.get("items", []):
            videos.append({
                "youtube_id": it["id"],
                "titre": it["snippet"]["title"],
                "publiee_le": it["snippet"].get("publishedAt", ""),
                "confidentialite": it["status"].get("privacyStatus", ""),
                "duree_s": _secondes(it["contentDetails"].get("duration", "")),
                "miniatures": it["snippet"].get("thumbnails", {}),
            })
    return videos


def _url_miniature(miniatures: dict) -> str:
    for cle in ("maxres", "standard", "high", "medium", "default"):
        if cle in miniatures:
            return miniatures[cle]["url"]
    return ""


def _detecte_visage(fichier: Path) -> bool:
    """Un visage est-il visible sur cette miniature ?

    YouTube livre les vignettes des Shorts en 16:9 avec des bandes floues sur
    les côtés : le visage y est petit. On cherche donc sur l'image agrandie
    ET sur la bande centrale, sinon on le manque.
    """
    import cv2

    image = cv2.imread(str(fichier))
    if image is None:
        return False
    hauteur, largeur = image.shape[:2]

    def cherche(vue) -> bool:
        h, w = vue.shape[:2]
        det = cv2.FaceDetectorYN.create(str(MODELE), "", (w, h), 0.75, 0.3, 5000)
        det.setInputSize((w, h))
        _, visages = det.detect(vue)
        return visages is not None and len(visages) > 0

    if cherche(cv2.resize(image, (largeur * 2, hauteur * 2), interpolation=cv2.INTER_CUBIC)):
        return True
    bande = image[:, int(largeur * 0.36):int(largeur * 0.64)]
    if bande.size:
        bh, bw = bande.shape[:2]
        f = 640.0 / max(bw, 1)
        if cherche(cv2.resize(bande, (int(bw * f), int(bh * f)), interpolation=cv2.INTER_CUBIC)):
            return True
    return False


def _vignette(youtube_id: str, url: str, forcer: bool) -> Path | None:
    import requests

    DOSSIER_VIGNETTES.mkdir(parents=True, exist_ok=True)
    fichier = DOSSIER_VIGNETTES / f"{youtube_id}.jpg"
    if url and (forcer or not fichier.is_file()):
        try:
            reponse = requests.get(url, timeout=30)
            if reponse.ok:
                fichier.write_bytes(reponse.content)
        except Exception as exc:
            log.warning("Vignette %s non récupérée : %s", youtube_id, exc)
    return fichier if fichier.is_file() else None


def sans_visage(videos: list[dict]) -> list[dict]:
    """Vidéos dont la miniature EN LIGNE ne montre aucun visage.

    Le verdict est mis en cache — examiner 300 vignettes prend des minutes et
    le rattrapage se fait en plusieurs passes. Mais une vignette déjà classée
    « sans visage » est RETÉLÉCHARGÉE à chaque fois : c'est ainsi que les deux
    machines voient le travail l'une de l'autre. Une fois traitée, la vidéo
    montre un visage, se met en cache, et n'est plus jamais retéléchargée.
    """
    cache = {}
    if CACHE_VERDICTS.is_file():
        try:
            cache = json.loads(CACHE_VERDICTS.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}

    vises, analysees = [], 0
    for i, v in enumerate(videos, 1):
        vid = v["youtube_id"]
        connu = cache.get(vid)
        # Rafraîchir seulement ce qui reste à faire : le reste ne peut plus
        # redevenir « sans visage ».
        fichier = _vignette(vid, _url_miniature(v["miniatures"]),
                            forcer=bool(connu and not connu.get("visage")))
        if not fichier:
            continue
        empreinte = str(fichier.stat().st_size)
        if connu and connu.get("taille") == empreinte:
            visage = connu["visage"]
        else:
            visage = _detecte_visage(fichier)
            cache[vid] = {"taille": empreinte, "visage": visage}
            analysees += 1
        if not visage:
            vises.append(v)
        if i % 50 == 0:
            log.info("  analyse %d/%d", i, len(videos))

    CACHE_VERDICTS.parent.mkdir(parents=True, exist_ok=True)
    CACHE_VERDICTS.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Vignettes examinées cette fois : %d (le reste vient du cache)", analysees)
    return vises


# --------------------------------------------------------------------------
# répartition des deux formules
# --------------------------------------------------------------------------
def repartir(cibles: list[dict], journal: dict) -> None:
    """Attribue une formule à chaque vidéo, moitié-moitié.

    Pour que la comparaison veuille dire quelque chose, les deux groupes
    doivent se ressembler — c'est la date de publication qui pèse le plus sur
    le nombre de vues, le format ensuite. On trie donc par format puis par
    date, et on alterne : deux vidéos voisines partent dans les deux groupes.

    L'attribution est figée au premier passage. Une miniature déjà PRÉPARÉE
    fait foi : son nom de fichier porte la formule, et c'est ce nom que le
    serveur lira.
    """
    ordonnees = sorted(cibles, key=lambda v: (v["duree_s"] > 180, v["publiee_le"]))
    for rang, video in enumerate(ordonnees):
        vid = video["youtube_id"]
        deja = journal.get(vid, {}).get("formule")
        prete = _miniature_prete(vid)
        if prete:
            deja = prete.stem.split("--")[-1]
        video["formule"] = deja if deja in FORMULES else FORMULES[rang % 2]
        journal.setdefault(vid, {})["formule"] = video["formule"]
    ecrire_journal(journal)


def _miniature_prete(youtube_id: str) -> Path | None:
    for formule in FORMULES:
        fichier = PRETES / f"{youtube_id}--{formule}.jpg"
        if fichier.is_file():
            return fichier
    return None


# --------------------------------------------------------------------------
# PRÉPARER (PC uniquement)
# --------------------------------------------------------------------------
def telecharger(youtube_id: str) -> Path | None:
    DOSSIER_VIDEOS.mkdir(parents=True, exist_ok=True)
    dest = DOSSIER_VIDEOS / f"{youtube_id}.mp4"
    if dest.is_file():
        return dest
    commande = [sys.executable, "-m", "yt_dlp",
                "-f", "bestvideo[height<=1920][ext=mp4]/best[ext=mp4]/best",
                "-o", str(dest), "--no-warnings", "--quiet", "--no-playlist"]
    if COOKIES.is_file():
        commande += ["--cookies", str(COOKIES)]
    commande.append(f"https://www.youtube.com/watch?v={youtube_id}")
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if not dest.is_file():
        detail = (resultat.stderr or resultat.stdout or "").strip()
        raison = ("vidéo privée ou blocage YouTube" if "Sign in" in detail
                  or "Please sign in" in detail else detail[-140:])
        log.warning("Téléchargement impossible (%s) : %s", youtube_id, raison)
        return None
    return dest


def _est_vertical(video: Path) -> bool:
    """Format réel du fichier — jamais la durée.

    Se fier à « moins de 3 minutes = Short » avait déjà collé une cover 9:16
    sur des vidéos 16:9 (Michel, 30/07 : « cette vidéo n'est pas un short »).
    """
    import cv2

    capture = cv2.VideoCapture(str(video))
    largeur = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
    hauteur = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    capture.release()
    return bool(hauteur > largeur)


def fabriquer(cfg, video_yt: dict, fichier_video: Path, formule: str) -> Path | None:
    PRETES.mkdir(parents=True, exist_ok=True)
    sortie = PRETES / f"{video_yt['youtube_id']}--{formule}.jpg"
    vertical = _est_vertical(fichier_video)

    if formule == "image":
        donnees = image_miniature(fichier_video, vertical=vertical)
        if not donnees:
            return None
        sortie.write_bytes(donnees)
        log.info("Image prête : %s (%d Ko)", sortie.name, len(donnees) // 1024)
        return sortie

    photo = portrait_depuis_video(fichier_video, vertical=vertical)
    if not photo:
        return None
    accroche = derive_thumb_title(video_yt["titre"])
    if not accroche:
        mots = [m for m in video_yt["titre"].split() if any(c.isalnum() for c in m)]
        accroche = " ".join(mots[:5]).upper()
    if not accroche:
        log.warning("Titre inexploitable pour %s", video_yt["youtube_id"])
        return None
    # Varie accents et teintes d'une vidéo à l'autre ; stable pour un même
    # identifiant, donc une reprise redonne exactement la même cover.
    graine = sum(ord(c) for c in video_yt["youtube_id"]) % 997
    largeur, hauteur = (thumbs.H, thumbs.W) if vertical else (thumbs.W, thumbs.H)
    html = thumbs._html(cfg, graine, accroche, largeur, hauteur,
                        photo_uri=thumbs._b64(photo, "image/jpeg"))
    if not thumbs._render_html(html, sortie, vp_w=largeur, vp_h=hauteur):
        return None
    if not thumbs.valid_thumbnail(sortie):
        log.warning("Cover produite mais non conforme : %s", sortie.name)
        sortie.unlink(missing_ok=True)
        return None
    log.info("Cover prête : %s « %s »", sortie.name, accroche)
    return sortie


def preparer(cfg, cibles: list[dict], journal: dict, combien: int,
             garder_videos: bool) -> int:
    faites = 0
    for video in cibles:
        if faites >= combien:
            break
        vid = video["youtube_id"]
        if _miniature_prete(vid):
            continue
        formule = video["formule"]
        log.info("--- préparation %s [%s] « %s »", vid, formule, video["titre"][:55])
        fichier = telecharger(vid)
        if not fichier:
            journal.setdefault(vid, {}).update(
                {"etat": "video-indisponible", "titre": video["titre"]})
            ecrire_journal(journal)
            continue
        try:
            sortie = fabriquer(cfg, video, fichier, formule)
        finally:
            if not garder_videos and fichier.is_file():
                fichier.unlink(missing_ok=True)
        etat = "prete" if sortie else "sans-visage-exploitable"
        journal.setdefault(vid, {}).update({"etat": etat, "titre": video["titre"]})
        ecrire_journal(journal)
        if sortie:
            faites += 1
    return faites


# --------------------------------------------------------------------------
# ENVOYER au serveur (PC uniquement)
# --------------------------------------------------------------------------
def envoyer() -> int:
    """Dépose les miniatures préparées sur le serveur, qui les posera seul."""
    fichiers = sorted(PRETES.glob("*.jpg"))
    if not fichiers:
        log.info("Rien à envoyer.")
        return 0
    if not VPS_CLE.is_file():
        log.error("Clé SSH introuvable : %s", VPS_CLE)
        return 1
    cible = f"{VPS_UTILISATEUR}@{VPS_HOTE}"
    subprocess.run(["ssh", "-i", str(VPS_CLE), "-o", "StrictHostKeyChecking=no",
                    cible, f"mkdir -p {VPS_DEPOT}"], capture_output=True, text=True)
    # `scp` d'un coup : une connexion au lieu de cent.
    commande = (["scp", "-i", str(VPS_CLE), "-o", "StrictHostKeyChecking=no", "-q"]
                + [str(f) for f in fichiers] + [f"{cible}:{VPS_DEPOT}/"])
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if resultat.returncode:
        log.error("Envoi au serveur impossible : %s",
                  (resultat.stderr or resultat.stdout)[-200:])
        return 1
    log.info("%d miniature(s) déposée(s) sur le serveur.", len(fichiers))
    return 0


# --------------------------------------------------------------------------
# POSER (PC et serveur)
# --------------------------------------------------------------------------
def poser(service, cibles: list[dict], journal: dict, combien: int, pause: int) -> int:
    """Pose les miniatures déjà préparées, en respectant le rythme de YouTube."""
    a_faire = [v for v in cibles if _miniature_prete(v["youtube_id"])]
    if not a_faire:
        log.info("Aucune miniature prête à poser (lancer --preparer sur le PC).")
        return 0
    log.info("%d miniature(s) prête(s) à poser", len(a_faire))

    faites = 0
    for video in a_faire:
        if faites >= combien:
            log.info("Limite de la passe atteinte (%d)", combien)
            break
        vid = video["youtube_id"]
        fichier = _miniature_prete(vid)
        formule = fichier.stem.split("--")[-1]
        log.info("--- pose %s [%s]", vid, formule)
        try:
            youtube_client.set_thumbnail(service, vid, str(fichier))
        except Exception as exc:
            message = str(exc)
            journal.setdefault(vid, {}).update(
                {"etat": "echec-envoi", "detail": message[:200]})
            ecrire_journal(journal)
            if "429" in message or "too many" in message.lower():
                # Chaque refus compte : insister aggrave le blocage.
                log.error("YouTube refuse les envois (rythme) — arrêt de la passe.")
                log.error("Les miniatures préparées sont gardées pour la suivante.")
                break
            log.error("Envoi impossible : %s", message[:200])
            continue
        journal.setdefault(vid, {}).update(
            {"etat": "reposee", "formule": formule,
             "le": time.strftime("%Y-%m-%d %H:%M:%S")})
        ecrire_journal(journal)
        faites += 1
        log.info("Miniature reposée (%d/%d)", faites, combien)
        if faites < combien:
            time.sleep(pause)
    return faites


# --------------------------------------------------------------------------
# RÉSULTATS
# --------------------------------------------------------------------------
def resultats(service, journal: dict) -> None:
    """Compare les vues des deux formules. À lancer une à deux semaines après."""
    import statistics

    poses = {vid: info for vid, info in journal.items() if info.get("etat") == "reposee"}
    if not poses:
        log.info("Aucune miniature reposée pour l'instant — rien à comparer.")
        return
    vues, identifiants = {}, list(poses)
    for i in range(0, len(identifiants), 50):
        reponse = service.videos().list(
            part="statistics", id=",".join(identifiants[i:i + 50])).execute()
        for it in reponse.get("items", []):
            vues[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0) or 0)

    log.info("")
    log.info("RÉSULTATS — vues par formule")
    for formule in FORMULES:
        lot = [vues[v] for v, info in poses.items()
               if info.get("formule") == formule and v in vues]
        if not lot:
            log.info("  %-13s : aucune vidéo", formule)
            continue
        log.info("  %-13s : %3d vidéos | médiane %6.0f | moyenne %7.0f",
                 formule, len(lot), statistics.median(lot), statistics.mean(lot))
    log.info("")
    log.info("La médiane est le bon repère : une seule vidéo virale fausserait")
    log.info("la moyenne.")


# --------------------------------------------------------------------------
# programme
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--preparer", type=int, nargs="?", const=PREPARATIONS_PAR_DEFAUT,
                           help="fabriquer N miniatures (PC : télécharge les vidéos)")
    analyseur.add_argument("--envoyer", action="store_true",
                           help="déposer les miniatures prêtes sur le serveur")
    analyseur.add_argument("--poser", type=int, nargs="?", const=POSES_PAR_DEFAUT,
                           help="poser N miniatures prêtes sur YouTube")
    analyseur.add_argument("--pause", type=int, default=PAUSE_PAR_DEFAUT,
                           help="secondes entre deux poses")
    analyseur.add_argument("--analyser", action="store_true",
                           help="compter les miniatures sans visage et s'arrêter")
    analyseur.add_argument("--resultats", action="store_true",
                           help="comparer les vues des deux formules et s'arrêter")
    analyseur.add_argument("--garder-videos", action="store_true",
                           help="ne pas supprimer les vidéos téléchargées")
    arguments = analyseur.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not MODELE.is_file():
        log.error("Modèle de détection absent : %s", MODELE)
        return 1

    # --envoyer ne touche ni à l'API ni à la chaîne : on le traite d'abord.
    if arguments.envoyer and not (arguments.preparer or arguments.poser):
        return envoyer()

    cfg = load_config()
    service = youtube_client.get_service(cfg)
    journal = lire_journal()

    if arguments.resultats:
        resultats(service, journal)
        return 0

    videos = inventaire(service)
    log.info("%d vidéos sur la chaîne", len(videos))
    cibles = sans_visage(videos)
    log.info("%d miniatures SANS VISAGE", len(cibles))
    repartir(cibles, journal)

    pretes = sum(1 for v in cibles if _miniature_prete(v["youtube_id"]))
    log.info("%d prête(s) à poser, %d encore à fabriquer", pretes, len(cibles) - pretes)

    if arguments.analyser:
        publiques = [v for v in cibles if v["confidentialite"] == "public"]
        log.info("dont %d publiques et %d encore privées",
                 len(publiques), len(cibles) - len(publiques))
        for formule in FORMULES:
            log.info("  formule %-13s : %d vidéos", formule,
                     sum(1 for v in cibles if v["formule"] == formule))
        return 0

    # Par défaut (aucun mode demandé) : poser ce qui est prêt.
    if arguments.preparer is None and arguments.poser is None:
        arguments.poser = POSES_PAR_DEFAUT

    if arguments.preparer:
        faites = preparer(cfg, cibles, journal, arguments.preparer,
                          arguments.garder_videos)
        log.info("%d miniature(s) fabriquée(s)", faites)
        if arguments.envoyer:
            envoyer()

    if arguments.poser:
        poser(service, cibles, journal, arguments.poser, arguments.pause)

    restant = sum(1 for v in journal.values() if v.get("etat") == "reposee")
    log.info("Total reposé à ce jour : %d", restant)
    return 0

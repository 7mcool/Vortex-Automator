"""Trouve un VISAGE dans la vidéo elle-même, pour les miniatures.

Pourquoi ce module (Michel, 10/08/2026) : « supprime les miniatures sans
visage et qui sont uniquement du texte, ce type de miniature n'a pas de
succès ». Relevé le même jour sur la chaîne : 114 vidéos sur 299 portaient une
cover tout-texte, faute de portrait disponible pour l'orateur.

La bibliothèque `assets/portraits/` ne couvre que quatre prédicateurs, et
seulement quand le nom est écrit dans le titre de la source. Tout le reste
retombait sur le décor abstrait. Ici on prend le visage là où il est
forcément : dans l'extrait lui-même.

Ce que l'essai du 30/07 avait raté — il avait conclu « visages mous » et la
piste avait été abandonnée :

* il jugeait un plan pris au hasard ; on parcourt ici toute la vidéo et on
  garde le MEILLEUR (netteté mesurée sur le visage, pas sur l'image entière) ;
* il gardait le plan entier, où le visage ne pèse que 2 à 8 % de la surface ;
  on RECADRE sur le buste, ce qui évite tout agrandissement du visage ;
* il utilisait les cascades de Haar, qui manquent un visage sur deux dès qu'il
  est de trois quarts. YuNet les remplace (`assets/modeles/`).

Le recadrage écarte aussi la bande de sous-titres incrustés en bas des
extraits Submagic/OpusClip : sans cela, la cover affichait deux textes.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("vortex.visage")

MODELE = (Path(__file__).resolve().parent.parent
          / "assets" / "modeles" / "face_detection_yunet_2023mar.onnx")

# Netteté (variance de Laplace sur le visage) en dessous de laquelle l'image
# ne vaut pas mieux qu'un décor. Mesuré le 10/08 sur les extraits réels : les
# bons plans sortent entre 25 et 125, le flou de mouvement sous 10.
NETTETE_MINIMALE = 12.0
# Un visage plus petit que cela ne survit pas au recadrage sans être agrandi.
LARGEUR_VISAGE_MINIMALE = 80
# En dessous de cette trace, la bande basse ne porte aucun sous-titre. Relevé
# le 10/08 : les plans sous-titrés sortent entre 0,012 et 0,081, les plans
# propres exactement à 0.
SEUIL_BANDE_PROPRE = 0.002
# Où chercher le texte incrusté, en fraction de hauteur. Les sous-titres de
# Submagic et d'OpusClip sont centrés vers 75-85 % : une bande limitée aux
# 20 % du bas passait juste EN DESSOUS et les déclarait absents.
BANDE_SOUSTITRES = (0.62, 1.0)
BANDE_BANDEAU = (0.0, 0.16)


def _detecteur(largeur: int, hauteur: int, seuil: float = 0.85):
    import cv2
    if not MODELE.is_file():
        raise FileNotFoundError(f"modèle de détection absent : {MODELE}")
    det = cv2.FaceDetectorYN.create(str(MODELE), "", (largeur, hauteur), seuil, 0.3, 5000)
    det.setInputSize((largeur, hauteur))
    return det


def _candidats(video: Path, echantillons: int, marge_bas: float):
    """Sonde la vidéo en `echantillons` points et rend les plans à visage net.

    On saute d'un instant à l'autre au lieu de décoder toute la vidéo : un
    extrait de cinq minutes serait sinon plus long à analyser qu'à regarder,
    et le rattrapage porte sur plus de cent vidéos.
    """
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        return []
    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    images = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    largeur = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    hauteur = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duree = images / fps if fps else 0
    if not largeur or not hauteur or duree <= 0:
        capture.release()
        return []
    detecteur = _detecteur(largeur, hauteur)

    # Les premières et dernières secondes sont souvent un fondu ou un carton.
    debut, fin = duree * 0.04, duree * 0.96
    points = [debut + (fin - debut) * i / max(echantillons - 1, 1)
              for i in range(echantillons)]

    trouves = []
    for seconde in points:
        capture.set(cv2.CAP_PROP_POS_MSEC, seconde * 1000.0)
        lu, image = capture.read()
        if not lu or image is None:
            continue
        _, visages = detecteur.detect(image)
        if visages is None:
            continue
        for v in visages:
            x, y, vw, vh = (int(n) for n in v[:4])
            x, y = max(0, x), max(0, y)
            if vw < LARGEUR_VISAGE_MINIMALE or x + vw > largeur or y + vh > hauteur:
                continue
            # Un visage assis dans la bande de sous-titres n'est pas cadrable.
            if y > hauteur * (1 - marge_bas):
                continue
            gris = cv2.cvtColor(image[y:y + vh, x:x + vw], cv2.COLOR_BGR2GRAY)
            if gris.size == 0:
                continue
            nettete = float(cv2.Laplacian(gris, cv2.CV_64F).var())
            if nettete < NETTETE_MINIMALE:
                continue
            luminosite = float(gris.mean())
            # Un visage dans le noir ou cramé ne donne rien de lisible.
            if not 35 <= luminosite <= 225:
                continue
            trouves.append({
                "image": image, "boite": (x, y, vw, vh), "nettete": nettete,
                "part": vw * vh / float(largeur * hauteur),
                "seconde": seconde,
                "texte_bas": _trace_texte(image, *BANDE_SOUSTITRES),
                "texte_haut": _trace_texte(image, *BANDE_BANDEAU),
            })
    capture.release()
    return trouves


def _trace_texte(image, haut: float, bas: float) -> float:
    """Trace d'un texte incrusté dans la bande [haut, bas] (0 = bande propre).

    Les extraits Submagic et OpusClip portent des sous-titres en bas et, par
    moments, un bandeau d'appel à l'action en haut (« ENVOIE À QUELQU'UN »).
    Michel a choisi le 10/08 de publier l'image de la vidéo telle quelle :
    autant prendre un instant où rien n'est affiché. Pas d'OCR — il faudrait
    le lancer sur des milliers d'images — on mesure la signature d'un texte
    incrusté : des pixels francs ET beaucoup de contours. Un mur uni n'a
    presque pas de bords, un décor chargé presque pas de pixels francs.

    ⚠️ Chercher du BLANC ne suffit pas : ces générateurs colorent le mot en
    cours (« TRAVAILLEURS. » en orange, « DÉFINITION. » en vert). Mesuré le
    10/08, un sous-titre orange ne contient aucun pixel au-dessus de 215 en
    luminance — il passait donc pour une bande propre. On retient donc aussi
    les couleurs vives.
    """
    import cv2
    import numpy as np

    hauteur = image.shape[0]
    bande = image[int(hauteur * haut):int(hauteur * bas), :]
    if bande.size == 0:
        return 0.0
    gris = cv2.cvtColor(bande, cv2.COLOR_BGR2GRAY)
    tsv = cv2.cvtColor(bande, cv2.COLOR_BGR2HSV)
    francs = (gris > 215) | ((tsv[:, :, 1] > 110) & (tsv[:, :, 2] > 150))
    if not francs.any():
        return 0.0
    bords = cv2.Canny(gris, 90, 200) > 0
    return (float(np.count_nonzero(francs)) / francs.size
            * float(np.count_nonzero(bords)) / bords.size * 100)


def _recadre(image, boite, ratio: float, marge_bas: float):
    """Cadre buste autour du visage, au format demandé, sans agrandissement.

    Le visage est placé au tiers supérieur — c'est le cadrage des affiches, et
    cela laisse la place au texte de la cover au-dessus.
    """
    hauteur, largeur = image.shape[:2]
    x, y, vw, vh = boite
    # 3,6 hauteurs de visage : le buste entre, la bande de sous-titres non.
    cadre_h = min(hauteur, int(vh * 3.6))
    cadre_w = int(cadre_h * ratio)
    if cadre_w > largeur:
        cadre_w = largeur
        cadre_h = min(hauteur, int(cadre_w / ratio))
    # Bas de cadre autorisé : on évite la zone des sous-titres incrustés tant
    # qu'il reste de la place au-dessus.
    plancher = int(hauteur * (1 - marge_bas))
    haut = int(y + vh * 0.5 - cadre_h * 0.38)
    haut = max(0, min(haut, hauteur - cadre_h))
    if haut + cadre_h > plancher:
        haut = max(0, min(haut, plancher - cadre_h))
    gauche = int(x + vw / 2 - cadre_w / 2)
    gauche = max(0, min(gauche, largeur - cadre_w))
    return image[haut:haut + cadre_h, gauche:gauche + cadre_w]


def _meilleur(trouves: list[dict], penalite_bas: float = 0.0,
              penalite_haut: float = 0.0) -> dict:
    """Le plan retenu : net, cadré serré, et de préférence sans texte incrusté."""
    def note(c: dict) -> float:
        base = c["nettete"] * (c["part"] ** 0.45)
        gene = (penalite_bas * c.get("texte_bas", 0.0)
                + penalite_haut * c.get("texte_haut", 0.0))
        return base / (1.0 + gene)
    return max(trouves, key=note)


def _en_jpeg(image, largeur_cible: int, hauteur_cible: int) -> bytes | None:
    """Image de vidéo mise au format d'une miniature YouTube (≤ 2 Mio).

    On recadre au centre juste ce qu'il faut pour atteindre le format visé,
    puis on met à l'échelle. YouTube recommande 2160×3840 pour les vignettes
    de Shorts et 3840×2160 pour les vidéos.
    """
    import cv2

    hauteur, largeur = image.shape[:2]
    vise = largeur_cible / hauteur_cible
    actuel = largeur / hauteur
    if actuel > vise:                       # trop large : on rogne les côtés
        neuve = int(hauteur * vise)
        depart = (largeur - neuve) // 2
        image = image[:, depart:depart + neuve]
    elif actuel < vise:                     # trop haute : on rogne haut et bas
        neuve = int(largeur / vise)
        depart = (hauteur - neuve) // 2
        image = image[depart:depart + neuve, :]
    interpolation = (cv2.INTER_LANCZOS4 if largeur_cible > image.shape[1]
                     else cv2.INTER_AREA)
    image = cv2.resize(image, (largeur_cible, hauteur_cible), interpolation=interpolation)
    for qualite in (92, 88, 84, 80, 76, 72, 68, 64, 60):
        ok, encode = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, qualite])
        if ok and encode.nbytes <= 1_900_000:
            return encode.tobytes()
    return None


def image_miniature(video: str | Path, *, vertical: bool | None = None,
                    echantillons: int = 90, marge_bas: float = 0.20) -> bytes | None:
    """Un PLAN DE LA VIDÉO, sans rien ajouter, prêt à servir de miniature.

    Choix de Michel du 10/08/2026 : « carrément faire sans miniature et laisser
    juste une partie de la vidéo ». L'API YouTube ne sachant pas retirer une
    miniature, on obtient le même résultat en posant l'image elle-même — à ceci
    près qu'elle est CHOISIE : le plan le plus net où l'on voit le visage, et
    de préférence sans sous-titre affiché.
    """
    import cv2

    chemin = Path(video)
    if not chemin.is_file():
        return None
    try:
        trouves = _candidats(chemin, echantillons, marge_bas)
    except Exception as exc:
        log.warning("Recherche de visage impossible dans %s : %s", chemin.name, exc)
        return None
    if not trouves:
        log.info("Aucun visage exploitable dans %s", chemin.name)
        return None

    if vertical is None:
        capture = cv2.VideoCapture(str(chemin))
        vertical = capture.get(cv2.CAP_PROP_FRAME_HEIGHT) > capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        capture.release()

    # L'image part telle quelle : tout texte incrusté se retrouve sur la
    # miniature. Mesuré le 10/08 sur les extraits réels : un tiers des plans a
    # la bande basse VIDE (entre deux phrases sous-titrées), mais la netteté
    # varie d'un facteur dix — une simple pénalité se faisait toujours écraser
    # par elle. On élimine donc d'abord les plans sous-titrés, et on ne
    # retombe sur l'ensemble que s'il n'en reste pas assez pour choisir.
    propres = [c for c in trouves if c.get("texte_bas", 0.0) <= SEUIL_BANDE_PROPRE]
    if len(propres) >= 2:
        # Deux suffisent : sur une miniature, une image un peu moins nette vaut
        # mieux qu'un bout de phrase en travers. Les silences sous-titrés sont
        # rares — 4 à 5 plans sur 40 à 85 relevés le 10/08.
        log.debug("%d plans sans sous-titre sur %d", len(propres), len(trouves))
        trouves = propres
    meilleur = _meilleur(trouves, penalite_bas=8.0, penalite_haut=8.0)
    largeur, hauteur = (2160, 3840) if vertical else (3840, 2160)
    donnees = _en_jpeg(meilleur["image"], largeur, hauteur)
    if donnees:
        log.info("Plan retenu dans %s à %.1f s (netteté %.0f, texte bas %.3f haut %.3f)",
                 chemin.name, meilleur["seconde"], meilleur["nettete"],
                 meilleur.get("texte_bas", 0.0), meilleur.get("texte_haut", 0.0))
    return donnees


def portrait_depuis_video(video: str | Path, *, vertical: bool = False,
                          echantillons: int = 90, marge_bas: float = 0.18) -> bytes | None:
    """Meilleur cadrage-portrait trouvé dans la vidéo, en JPEG. None si aucun.

    `vertical` vise le gabarit 9:16 (photo en bas de la cover), sinon le 16:9
    où la photo occupe une moitié.
    """
    import cv2

    chemin = Path(video)
    if not chemin.is_file():
        return None
    try:
        trouves = _candidats(chemin, echantillons, marge_bas)
    except Exception as exc:
        log.warning("Recherche de visage impossible dans %s : %s", chemin.name, exc)
        return None
    if not trouves:
        log.info("Aucun visage exploitable dans %s", chemin.name)
        return None

    # Net d'abord, mais un gros plan vaut mieux qu'un plan large très net : le
    # visage doit se voir sur une vignette large comme le pouce. Le recadrage
    # écarte déjà les sous-titres du bas ; le bandeau du haut, lui, tombe en
    # plein dans le cadre — c'est celui-là qu'on évite.
    meilleur = _meilleur(trouves, penalite_haut=8.0)
    ratio = 0.72 if vertical else 1.03
    cadre = _recadre(meilleur["image"], meilleur["boite"], ratio, marge_bas)
    if cadre is None or cadre.size == 0:
        return None
    ok, encode = cv2.imencode(".jpg", cadre, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        return None
    log.info("Visage retenu dans %s à %.1f s (netteté %.0f, %d×%d)", chemin.name,
             meilleur["seconde"], meilleur["nettete"], cadre.shape[1], cadre.shape[0])
    return encode.tobytes()

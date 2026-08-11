"""Habillage LÉGER des extraits OpusClip, avant publication.

⚠️ CE N'EST PAS `vortex/render.py`. Ce moteur-là habille les TikToks de
@hedjav : accroche géante, sous-titres karaoké, étalonnage cinéma. Michel
l'a écarté ici (11/08) — « pas ce moteur là », « retire les hook que notre
moteur génère, OpusClip le fait déjà très bien ».

On ne touche donc NI à l'accroche (l'Auto headline d'OpusClip), NI aux
sous-titres (déjà incrustés). On ajoute seulement ce qu'OpusClip ne fait
pas : des appels à l'action, et un peu de netteté.

CE QUI EST FAIT, ET POURQUOI

1. NETTETÉ. Mesuré le 11/08 : la source YouTube plafonne à 1920×1080, et
   tailler du 9:16 dedans ne laisse que 608 pixels de large, étirés à 1080 —
   un agrandissement de 1,78×. Aucun réglage OpusClip ne peut inventer ces
   pixels, mais un accentuage dosé récupère une part réelle de la perte.
   C'est le seul gain de qualité honnête possible.

2. APPELS À L'ACTION, à deux moments seulement.
   - JAMAIS au début : les trois premières secondes décident du visionnage,
     et l'accroche d'OpusClip y est déjà.
   - JAMAIS pendant l'explication : la règle de Michel veut qu'un extrait
     porte l'affirmation choc ET son explication entière. La couper d'un
     bandeau casse exactement ce qu'on a payé pour obtenir.
   - Donc : une fois la valeur passée (~58 % de l'extrait), puis à la fin.

3. LE TEXTE. « PARTAGE ! » ne fonctionne pas sur de la prédication : c'est
   transactionnel. Ce qui fait réellement partager un message, c'est de
   penser à quelqu'un — « il a besoin d'entendre ça ». Les formules de
   partage sont donc RELATIONNELLES. L'abonnement, lui, est gardé pour la
   fin : celui qui est encore là a déjà prouvé son intérêt.

4. PLACEMENT. Le bandeau reste HAUT (~11 % de la hauteur). Le bas de l'écran
   appartient à TikTok (légende, pseudo, boutons) et le milieu aux
   sous-titres d'OpusClip : c'est la seule bande vraiment libre.
"""

from __future__ import annotations

import logging
import random
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------- textes
# Formules de PARTAGE — relationnelles, jamais impératives sèches. Elles
# désignent quelqu'un d'autre, ce qui est le vrai moteur du partage sur du
# contenu de foi.
PARTAGE = [
    "ENVOIE-LE A QUELQU'UN QUI EN A BESOIN",
    "QUELQU'UN DOIT ENTENDRE CECI AUJOURD'HUI",
    "TU CONNAIS QUELQU'UN QUE CA CONCERNE ?",
    "PARTAGE : CA PEUT DEBLOQUER QUELQU'UN",
    "PENSE A CETTE PERSONNE. ENVOIE-LUI.",
]

# Formules de FIN — abonnement et mention d'accord. Le spectateur arrivé
# jusque-là est qualifié : c'est le seul moment où demander est légitime.
FINAL = [
    "ABONNE-TOI, LA SUITE ARRIVE",
    "CA T'A PARLE ? ABONNE-TOI",
    "ABONNE-TOI POUR NE RIEN MANQUER",
    "AIME ET ABONNE-TOI POUR LA SUITE",
]

# Proportion de l'extrait à laquelle paraît le premier bandeau. À 58 %, le
# cœur de la démonstration est passé et il reste assez de vidéo pour que le
# geste se fasse.
INSTANT_PARTAGE = 0.58
DUREE_BANDEAU = 5.0        # secondes d'affichage
FONDU = 0.4                # secondes de fondu d'entrée et de sortie
DUREE_FINAL = 8.0          # le bandeau de fin couvre les dernières secondes

# Accentuage. Volontairement plus doux que l'étalonnage cinéma de render.py :
# ici l'image est une captation d'église, pas un clip stylisé. On corrige
# l'agrandissement, on ne réinvente pas la photo.
NETTETE = "unsharp=5:5:0.9:5:5:0.4,eq=contrast=1.06:saturation=1.05"


class HabillageError(RuntimeError):
    pass


def _police() -> str:
    """Chemin d'une police utilisable par ffmpeg, sans dépendre du système."""
    anton = REPO / "assets" / "fonts" / "Anton-Regular.ttf"
    if anton.is_file():
        return anton.as_posix()
    for candidat in (r"C:\Windows\Fonts\arialbd.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(candidat).is_file():
            return Path(candidat).as_posix()
    raise HabillageError("aucune police trouvée pour les bandeaux")


def duree(chemin: str | Path) -> float:
    sortie = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(chemin)],
        capture_output=True, text=True, timeout=120)
    try:
        return float((sortie.stdout or "0").strip())
    except ValueError:
        raise HabillageError(f"durée illisible pour {chemin}")


def _chemin_filtre(chemin: Path) -> str:
    """Un chemin lisible par un filtre ffmpeg (le « : » de C: doit être protégé)."""
    return chemin.as_posix().replace(":", r"\:")


def _bandeau(fichier_texte: Path, debut: float, longueur: float, police: str) -> str:
    """Un bandeau qui paraît, tient, puis s'efface — sans coupure sèche.

    Le texte passe par un FICHIER et non par `text=`. Les formules françaises
    contiennent des apostrophes (« QUELQU'UN »), et une apostrophe dans une
    option ffmpeg déjà entre apostrophes casse l'analyse du filtre entier —
    constaté le 11/08, ffmpeg tronquait la chaîne au milieu de `fontsize`.
    Avec `textfile=`, plus aucun échappement n'est en jeu.
    """
    fin = debut + longueur
    # L'opacité monte, tient, redescend. Sans ce fondu le bandeau « claque »
    # et attire l'œil au détriment de ce qui est dit.
    alpha = (f"if(lt(t,{debut + FONDU:.2f}),(t-{debut:.2f})/{FONDU},"
             f"if(lt(t,{fin - FONDU:.2f}),1,({fin:.2f}-t)/{FONDU}))")
    return (
        f"drawtext=fontfile='{_chemin_filtre(police)}'"
        f":textfile='{_chemin_filtre(fichier_texte)}'"
        f":fontcolor=white@1:fontsize=h*0.028"
        f":box=1:boxcolor=black@0.62:boxborderw=26"
        f":x=(w-text_w)/2:y=h*0.11"
        f":enable='between(t\\,{debut:.2f}\\,{fin:.2f})'"
        f":alpha='{alpha}'"
    )


def plan_bandeaux(duree_s: float, graine: str) -> list[tuple[str, float, float]]:
    """Les bandeaux à poser : (texte, début, durée). Stable pour un extrait donné.

    Le tirage est déterministe : un même extrait garde toujours le même
    habillage, mais deux extraits voisins ne portent pas la même phrase —
    répéter mot pour mot le même appel lasse et fait chuter l'effet.
    """
    rng = random.Random(graine)
    bandeaux: list[tuple[str, float, float]] = []

    # Extrait trop court pour deux bandeaux : on ne garde que la fin.
    if duree_s >= 90:
        debut = duree_s * INSTANT_PARTAGE
        bandeaux.append((rng.choice(PARTAGE), debut, DUREE_BANDEAU))

    debut_final = max(0.0, duree_s - DUREE_FINAL)
    # On ne colle pas les deux bandeaux : au moins 10 s de respiration.
    if not bandeaux or debut_final - (bandeaux[0][1] + DUREE_BANDEAU) >= 10:
        bandeaux.append((rng.choice(FINAL), debut_final, DUREE_FINAL))
    return bandeaux


def habiller(source: str | Path, cible: str | Path, *, graine: str = "",
             nettete: bool = True, crf: str = "17") -> Path:
    """Pose les bandeaux et corrige la netteté. Retourne le chemin produit.

    CRF 17 : le rendu OpusClip arrive à ~16 Mbit/s, il faut réencoder pour
    incruster quoi que ce soit. À ce niveau la perte n'est pas visible, alors
    qu'un CRF plus élevé annulerait le gain de netteté qu'on vient de poser.
    """
    source, cible = Path(source), Path(cible)
    if not source.is_file():
        raise HabillageError(f"fichier absent : {source}")
    if not shutil.which("ffmpeg"):
        raise HabillageError("ffmpeg absent du système")

    import tempfile

    longueur = duree(source)
    police = Path(_police())
    bandeaux = plan_bandeaux(longueur, graine or source.stem)
    cible.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vortex-habillage-") as tmp:
        dossier = Path(tmp)
        filtres = [NETTETE] if nettete else []
        for i, (texte, debut, longueur_bandeau) in enumerate(bandeaux):
            fichier = dossier / f"bandeau{i}.txt"
            fichier.write_text(texte, encoding="utf-8")
            filtres.append(_bandeau(fichier, debut, longueur_bandeau, police))

        commande = [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(source),
            "-vf", ",".join(filtres),
            "-c:v", "libx264", "-preset", "slow", "-crf", crf,
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            # L'audio n'est pas retouché : OpusClip a déjà passé sa correction
            # de voix, un second traitement ne ferait que l'abîmer.
            "-c:a", "copy",
            str(cible),
        ]
        log.info("Habillage de %s (%.0f s, %d bandeau(x))…",
                 source.name, longueur, len(bandeaux))
        fait = subprocess.run(commande, capture_output=True, text=True, timeout=3600)
    if fait.returncode != 0 or not cible.is_file():
        raise HabillageError((fait.stderr or "")[-500:])
    return cible

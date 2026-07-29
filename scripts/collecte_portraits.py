"""Constitue la bibliotheque de portraits d'un pasteur a partir de ses videos.

Les miniatures YouTube plafonnent a 1280x720 et le visage n'y occupe qu'une
fraction de l'image : un portrait decoupe dedans est trop petit pour une
miniature UHD. Une video 1080p donne au contraire des visages larges et nets.

Contrairement a `vortex/portraits.py`, qui deduit le nom depuis le titre de la
source, le nom est ici donne explicitement : la video peut etre n'importe
laquelle du chaine officielle du pasteur.

    python scripts/collecte_portraits.py "Yannick Djatti" <video.mp4> [autres.mp4...]
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ASSETS = RACINE / "assets" / "portraits"
sys.path.insert(0, str(RACINE))

from vortex.scanner import find_ffprobe      # noqa: E402
from vortex.textdetect import find_ffmpeg    # noqa: E402

# Un portrait doit rester net et grand une fois pose sur une miniature UHD.
LARGEUR_MINI = 700
NETTETE_MINI = 90.0


def _slug(valeur: str) -> str:
    plat = unicodedata.normalize("NFD", valeur.lower())
    return "-".join("".join(c for c in plat if not unicodedata.combining(c)).split())


def _duree(chemin: Path) -> float:
    sortie = subprocess.run(
        [find_ffprobe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(chemin)],
        capture_output=True, text=True, timeout=120)
    try:
        return float(sortie.stdout.strip())
    except ValueError:
        return 0.0


def collecter(pasteur: str, video: Path, maximum: int = 12) -> int:
    import cv2
    from PIL import Image

    duree = _duree(video)
    if duree < 10:
        print(f"  {video.name} : duree illisible")
        return 0

    dossier = ASSETS / _slug(pasteur)
    dossier.mkdir(parents=True, exist_ok=True)
    manifeste = ASSETS / "manifest.jsonl"
    connus = {p.stem.rsplit("-", 1)[-1] for p in dossier.glob("*.jpg") if "-" in p.stem}

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    ffmpeg = find_ffmpeg()
    infos = {}
    sidecar = video.with_suffix(".info.json")
    if sidecar.exists():
        try:
            infos = json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError:
            pass

    faits = 0
    # Beaucoup plus de candidats que de sorties : la plupart sont des plans
    # larges, du public ou des images floues.
    echantillons = max(maximum * 6, 48)
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(echantillons):
            if faits >= maximum:
                break
            at = duree * (0.05 + 0.9 * i / max(echantillons - 1, 1))
            image_path = Path(tmp) / f"{i:03d}.jpg"
            proc = subprocess.run(
                [ffmpeg, "-v", "error", "-ss", f"{at:.2f}", "-i", str(video),
                 "-frames:v", "1", "-q:v", "2", "-y", str(image_path)],
                capture_output=True, timeout=90)
            if proc.returncode or not image_path.exists():
                continue
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            hauteur, largeur = image.shape[:2]
            gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            visages = cascade.detectMultiScale(gris, 1.08, 6, minSize=(150, 150))
            # Un seul visage : sinon c'est le public ou un plan a plusieurs.
            if len(visages) != 1:
                continue
            x, y, lv, hv = (int(v) for v in visages[0])
            # Critere en PIXELS, pas en fraction de l'image : sur une video
            # 1080p un visage de 160 px est parfaitement exploitable alors
            # qu'il ne represente que 1,2 % de la surface. L'ancien seuil de
            # 2 % rejetait absolument tout.
            if lv < 140:
                continue
            nettete = float(cv2.Laplacian(gris[y:y + hv, x:x + lv], cv2.CV_64F).var())
            if nettete < NETTETE_MINI:
                continue

            # Cadrage portrait genereux autour du visage.
            crop_h = min(hauteur, max(900, int(hv * 4.0)))
            crop_l = min(largeur, int(crop_h * 0.78))
            if crop_l < LARGEUR_MINI:
                continue
            centre = x + lv // 2
            haut = max(0, min(hauteur - crop_h, int(y + hv * 0.45 - crop_h * 0.34)))
            gauche = max(0, min(largeur - crop_l, centre - crop_l // 2))
            crop = image[haut:haut + crop_h, gauche:gauche + crop_l]
            ok, encode = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 96])
            if not ok:
                continue
            donnees = encode.tobytes()
            empreinte = hashlib.sha256(donnees).hexdigest()[:12]
            if empreinte in connus:
                continue

            fichier = dossier / f"auto-{video.stem}-{int(at):06d}-{empreinte}.jpg"
            fichier.write_bytes(donnees)
            try:
                with Image.open(fichier) as verif:
                    verif.verify()
            except Exception:
                fichier.unlink(missing_ok=True)
                continue

            with manifeste.open("a", encoding="utf-8") as flux:
                flux.write(json.dumps({
                    "file": fichier.relative_to(ASSETS.parent).as_posix(),
                    "speaker": pasteur,
                    "source_url": infos.get("webpage_url")
                        or (f"https://www.youtube.com/watch?v={infos.get('id')}"
                            if infos.get("id") else ""),
                    "source_title": infos.get("title", ""),
                    "timecode_seconds": round(at, 2),
                    "width": crop_l, "height": crop_h,
                    "face_sharpness": round(nettete, 1),
                    "usage_basis": "chaine-officielle-du-pasteur",
                }, ensure_ascii=False) + "\n")
            connus.add(empreinte)
            faits += 1
    print(f"  {video.name} : {faits} portrait(s)")
    return faits


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        return
    pasteur = sys.argv[1]
    total = sum(collecter(pasteur, Path(v)) for v in sys.argv[2:])
    print(f"{total} portrait(s) pour {pasteur} — dossier {ASSETS / _slug(pasteur)}")


if __name__ == "__main__":
    main()

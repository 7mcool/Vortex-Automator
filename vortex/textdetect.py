"""Phase 2 — Détection de texte incrusté dans les vidéos (règle de Michel :
beaucoup de vidéos ont DÉJÀ des sous-titres/textes ; ne jamais rien retirer,
et n'ajouter des éléments visuels qu'aux vidéos qui n'en ont pas).

Méthode 100 % gratuite et locale : extraction d'images via ffmpeg puis OCR
Tesseract (français). Verdict par vidéo :
  - "texte"      : du texte est incrusté (sous-titres/titres) -> ne pas toucher
  - "sans_texte" : rien détecté -> candidate au hook visuel / sous-titres
  - "douteux"    : détection partielle -> validation manuelle
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import Config
from .db import Database

log = logging.getLogger("vortex.textdetect")

SAMPLES = 10         # images analysées par vidéo (correctif 17/07 : 5 ratait les
                     # sous-titres intermittents qui n'apparaissent que pendant la parole)
MIN_WORDS_HIT = 2    # mots lisibles pour compter une image comme "avec texte"


def find_tool(name: str, hints: list[str]) -> str | None:
    exe = shutil.which(name)
    if exe:
        return exe
    for hint in hints:
        p = Path(hint)
        if p.exists():
            return str(p)
    return None


def find_ffmpeg() -> str:
    exe = find_tool("ffmpeg", [])
    if exe:
        return exe
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    hits = sorted(winget.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
    if hits:
        return str(hits[-1])
    raise FileNotFoundError("ffmpeg introuvable")


def find_tesseract() -> str | None:
    return find_tool("tesseract", [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ])


def _tessdata_dir() -> str | None:
    """Dossier tessdata utilisateur si le pack français y a été installé
    (l'écriture dans Program Files est refusée sans droits admin)."""
    import os
    user_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "vortex-tessdata"
    if (user_dir / "fra.traineddata").exists():
        return str(user_dir)
    return None


def ocr_image(tesseract: str, image: Path) -> str:
    cmd = [tesseract, str(image), "stdout", "-l", "fra+eng", "--psm", "6"]
    tessdata = _tessdata_dir()
    if tessdata:
        cmd += ["--tessdata-dir", tessdata]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                             encoding="utf-8", errors="ignore")
        return out.stdout or ""
    except Exception as exc:
        log.debug("OCR échoué sur %s : %s", image, exc)
        return ""


def count_real_words(text: str) -> int:
    """Compte les mots plausibles (3+ lettres) pour ignorer le bruit OCR."""
    return len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}", text))


def detect_video_text(ffmpeg: str, tesseract: str, path: Path, duration: float) -> tuple[str, int]:
    """Retourne (verdict, nb_images_avec_texte)."""
    hits = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(SAMPLES):
            # Échantillonne entre 10 % et 90 % de la durée (évite intro/fin noires)
            t = duration * (0.1 + 0.8 * i / max(SAMPLES - 1, 1))
            frame = Path(tmp) / f"f{i}.png"
            subprocess.run(
                [ffmpeg, "-v", "quiet", "-ss", f"{t:.1f}", "-i", str(path),
                 "-frames:v", "1", "-vf", "scale=720:-1", "-y", str(frame)],
                capture_output=True, timeout=60,
            )
            if not frame.exists():
                continue
            if count_real_words(ocr_image(tesseract, frame)) >= MIN_WORDS_HIT:
                hits += 1
    # Seuil abaissé (correctif 17/07) : sur 10 images, ≥2 avec texte = sous-titré.
    # Mieux vaut détecter « texte » à tort (on saute le karaoké) que l'inverse
    # (double sous-titre). 1 seule image = douteux (on saute aussi le karaoké).
    if hits >= 2:
        return "texte", hits
    if hits == 0:
        return "sans_texte", hits
    return "douteux", hits


def detect_pending(cfg: Config, db: Database, limit: int = 0) -> dict:
    """Analyse les vidéos dont has_text est inconnu (toutes états confondus)."""
    tesseract = find_tesseract()
    if not tesseract:
        raise FileNotFoundError(
            "Tesseract introuvable — installez-le : winget install UB-Mannheim.TesseractOCR")
    ffmpeg = find_ffmpeg()

    # Colonne ajoutée à la volée si absente (migration douce)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "has_text" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN has_text TEXT")
        db.conn.commit()

    sql = "SELECT id, path, duration_s FROM videos WHERE has_text IS NULL AND duration_s IS NOT NULL"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = db.conn.execute(sql).fetchall()
    stats = {"texte": 0, "sans_texte": 0, "douteux": 0, "erreur": 0}
    for r in rows:
        try:
            verdict, hits = detect_video_text(ffmpeg, tesseract, Path(r["path"]), r["duration_s"])
        except Exception as exc:
            log.warning("Détection impossible pour #%d : %s", r["id"], exc)
            stats["erreur"] += 1
            continue
        db.update_fields(r["id"], has_text=verdict)
        stats[verdict] += 1
        log.info("Texte #%d : %s (%d/%d images)", r["id"], verdict, hits, SAMPLES)
    return stats

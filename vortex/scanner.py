"""Étape 1 — Détection : scan du dossier source, intégrité, empreinte, couverture.

- ffprobe vérifie que chaque fichier est lisible (les corrompus -> BLOCKED).
- SHA-256 empêche les doublons même après renommage.
- La couverture `<nom>_cover.jpeg` du dossier cover/ est associée si présente.
- La légende TikTok d'origine est récupérée dans la base data.sqlite de 4K Tokkit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import subprocess
from pathlib import Path

from .config import Config
from .db import Database

log = logging.getLogger("vortex.scanner")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def find_ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if winget.exists():
        hits = sorted(winget.glob("Gyan.FFmpeg*/**/bin/ffprobe.exe"))
        if hits:
            return str(hits[-1])
    raise FileNotFoundError("ffprobe introuvable — installez FFmpeg (winget install Gyan.FFmpeg)")


def sha256_file(path: Path, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(bufsize):
            h.update(chunk)
    return h.hexdigest()


def probe(ffprobe: str, path: Path) -> dict | None:
    """Retourne durée/dimensions, ou None si le fichier est illisible."""
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(out.stdout)
        vstream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
        astream = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
        if vstream is None:
            return None
        return {
            "duration_s": round(float(data["format"]["duration"]), 1),
            "width": int(vstream["width"]),
            "height": int(vstream["height"]),
            "has_audio": astream is not None,
        }
    except Exception as exc:  # fichier corrompu, JSON invalide, timeout…
        log.warning("ffprobe a échoué sur %s : %s", path.name, exc)
        return None


def load_tokkit_captions(tokkit_db: Path) -> dict[str, str]:
    """Légendes TikTok d'origine, indexées par id TikTok.

    La base est souvent VERROUILLÉE par l'application 4K Tokkit : on travaille
    donc sur une copie temporaire, et on signale clairement un résultat vide.
    """
    captions: dict[str, str] = {}
    if not tokkit_db.exists():
        return captions
    tmp_copy = None
    try:
        import tempfile
        tmp_copy = Path(tempfile.gettempdir()) / "vortex_tokkit_copy.sqlite"
        shutil.copy2(tokkit_db, tmp_copy)
        con = sqlite3.connect(f"file:{tmp_copy}?mode=ro", uri=True)
        for tid, desc in con.execute(
            "SELECT id, description FROM MediaItems WHERE description IS NOT NULL AND description != ''"
        ):
            captions[str(tid)] = desc
        con.close()
    except Exception as exc:
        log.warning("Lecture de la base 4K Tokkit impossible : %s", exc)
    finally:
        if tmp_copy is not None:
            tmp_copy.unlink(missing_ok=True)
    if not captions:
        log.warning("AUCUNE légende TikTok chargée — le SEO reposera sur la transcription seule "
                    "(les légendes seront récupérées à un prochain scan).")
    else:
        log.info("%d légendes TikTok chargées.", len(captions))
    return captions


def classify(duration_s: float, width: int, height: int, shorts_max: int) -> str:
    vertical = height > width
    if vertical and duration_s <= shorts_max:
        return "short"
    return "long_vertical" if vertical else "long_horizontal"


def scan(cfg: Config, db: Database) -> dict:
    """Scanne le dossier source ; retourne un résumé chiffré."""
    if not cfg.source_dir.exists():
        log.error("Dossier source inaccessible : %s — disque externe débranché ? Scan annulé.",
                  cfg.source_dir)
        return {"seen": 0, "new": 0, "known": 0, "blocked": 0, "too_short": 0,
                "in_progress": 0, "errors": 1}
    ffprobe = find_ffprobe()
    captions = load_tokkit_captions(cfg.tokkit_db)
    cover_dir = cfg.source_dir / "cover"

    stats = {"seen": 0, "new": 0, "known": 0, "blocked": 0, "too_short": 0, "in_progress": 0, "errors": 0}
    files = sorted(
        p for p in cfg.source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )
    import time
    for path in files:
        try:
            stats["seen"] += 1
            stat = path.stat()
            # Fichier probablement en cours de téléchargement (4K Tokkit actif) :
            # on l'ignore pour ce scan, il sera repris au suivant.
            if time.time() - stat.st_mtime < 120:
                stats["in_progress"] += 1
                continue

            name = path.stem
            tiktok_id = name.split("_")[-1]
            cover = cover_dir / f"{name}_cover.jpeg"
            if not cover.exists():
                # Miniature yt-dlp pas encore déplacée dans cover/
                alt = path.parent / f"{name}.jpg"
                if alt.exists():
                    cover = alt

            # Légende : base 4K Tokkit (PC) OU fichier .info.json de yt-dlp (VPS)
            caption = captions.get(tiktok_id)
            if not caption:
                info_json = path.parent / f"{name}.info.json"
                if info_json.exists():
                    try:
                        caption = json.loads(info_json.read_text(encoding="utf-8")).get("description")
                    except Exception:
                        pass

            meta = probe(ffprobe, path)
            info = {
                "name": name,
                "path": str(path),
                "tiktok_id": tiktok_id,
                "sha256": sha256_file(path),
                "size_bytes": stat.st_size,
                "caption": caption,
                "cover_path": str(cover) if cover.exists() else None,
            }
        except OSError as exc:
            log.warning("Fichier inaccessible pendant le scan : %s (%s)", path.name, exc)
            stats["errors"] += 1
            continue
        if meta is None:
            video_id, is_new = db.upsert_video(info)
            if is_new:
                db.set_state(video_id, "BLOCKED", "fichier illisible (ffprobe)")
                stats["blocked"] += 1
            continue

        info.update(meta)
        info["category"] = classify(meta["duration_s"], meta["width"], meta["height"], cfg.shorts_max_seconds)
        video_id, is_new = db.upsert_video(info)
        if not is_new:
            stats["known"] += 1
            continue
        stats["new"] += 1
        if meta["duration_s"] < cfg.min_duration_seconds:
            db.set_state(video_id, "SKIPPED", f"durée {meta['duration_s']}s < minimum")
            stats["too_short"] += 1
        elif not meta["has_audio"]:
            db.set_state(video_id, "BLOCKED", "aucune piste audio")
            stats["blocked"] += 1

    log.info("Scan terminé : %s", stats)
    return stats

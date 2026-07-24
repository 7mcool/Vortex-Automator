"""Constitue une bibliothèque de portraits HD depuis les sermons officiels.

On n'aspire pas Google Images : chaque image garde la vidéo source, son titre,
le timecode, ses dimensions et son hash dans `assets/portraits/manifest.jsonl`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from .textdetect import find_ffmpeg

log = logging.getLogger("vortex.portraits")
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "portraits"

SPEAKER_MARKERS = {
    "jacques amessan": "Jacques Amessan",
    "mohammed sanogo": "Mohammed Sanogo",
    "aime bodjiye": "Aimé Bodjiyé",
}


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower())
    return "".join(c for c in value if not unicodedata.combining(c))


def _slug(value: str) -> str:
    return "-".join(_plain(value).split())


def speaker_from_info(source: Path) -> tuple[str, dict] | tuple[None, dict]:
    """Nomme le pasteur seulement si son nom figure dans le titre officiel."""
    info_path = source.with_suffix(".info.json")
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    title = _plain(str(info.get("title") or ""))
    for marker, speaker in SPEAKER_MARKERS.items():
        if marker in title:
            return speaker, info
    return None, info


def harvest_portraits(source: Path, duration: float, limit: int = 10) -> int:
    """Extrait des cadrages nets contenant un seul grand visage.

    Les fichiers sont de vrais crops HD issus de la source 1080p ; aucune
    interpolation ne prétend inventer de l'Ultra HD.
    """
    speaker, info = speaker_from_info(source)
    if not speaker or duration < 60:
        return 0
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        log.warning("Collecte portraits indisponible (%s)", exc)
        return 0

    folder = ASSETS_DIR / _slug(speaker)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = ASSETS_DIR / "manifest.jsonl"
    known_hashes = {
        p.stem.rsplit("-", 1)[-1]
        for p in folder.glob("auto-*.jpg")
        if "-" in p.stem
    }
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    ffmpeg = find_ffmpeg()
    made = 0

    # Davantage de candidats que de sorties pour écarter flou, foule et plans larges.
    sample_count = max(limit * 3, 24)
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(sample_count):
            if made >= limit:
                break
            at = duration * (0.08 + 0.84 * index / max(sample_count - 1, 1))
            frame = Path(tmp) / f"{index:03d}.jpg"
            proc = subprocess.run(
                [ffmpeg, "-v", "error", "-ss", f"{at:.2f}", "-i", str(source),
                 "-frames:v", "1", "-q:v", "2", "-y", str(frame)],
                capture_output=True, timeout=90,
            )
            if proc.returncode or not frame.exists():
                continue
            image = cv2.imread(str(frame))
            if image is None:
                continue
            height, width = image.shape[:2]
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.08, 6, minSize=(120, 120))
            if len(faces) != 1:
                continue
            x, y, face_w, face_h = [int(v) for v in faces[0]]
            if face_w * face_h < width * height * 0.018:
                continue
            face_gray = gray[y:y + face_h, x:x + face_w]
            sharpness = float(cv2.Laplacian(face_gray, cv2.CV_64F).var())
            if sharpness < 70:
                continue

            crop_h = min(height, max(720, int(face_h * 4.2)))
            crop_w = min(width, int(crop_h * 0.8))
            if crop_w < 640 or crop_h < 720:
                continue
            center_x = x + face_w // 2
            top = max(0, min(height - crop_h, int(y + face_h * 0.45 - crop_h * 0.32)))
            left = max(0, min(width - crop_w, center_x - crop_w // 2))
            crop = image[top:top + crop_h, left:left + crop_w]
            ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                continue
            data = encoded.tobytes()
            digest = hashlib.sha256(data).hexdigest()[:12]
            if digest in known_hashes:
                continue

            # Pillow valide le JPEG final avant qu'il entre dans la bibliothèque.
            candidate = folder / f"auto-{source.stem}-{int(at):06d}-{digest}.jpg"
            candidate.write_bytes(data)
            try:
                with Image.open(candidate) as checked:
                    checked.verify()
            except Exception:
                candidate.unlink(missing_ok=True)
                continue

            record = {
                "file": candidate.relative_to(ASSETS_DIR.parent).as_posix(),
                "speaker": speaker,
                "source_url": info.get("webpage_url")
                    or (f"https://www.youtube.com/watch?v={info.get('id')}" if info.get("id") else ""),
                "source_title": info.get("title", ""),
                "timecode_seconds": round(at, 2),
                "width": crop_w,
                "height": crop_h,
                "face_sharpness": round(sharpness, 1),
                "sha256": hashlib.sha256(data).hexdigest(),
                "usage_basis": "official-partner-video",
            }
            with manifest.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            known_hashes.add(digest)
            made += 1

    if made:
        log.info("%d portrait(s) HD collecté(s) pour %s", made, speaker)
    return made

"""Phase 5 — Le Clipper : découpage INTELLIGENT des longues vidéos sources
(type OpusClip/Submagic), validé par Michel avec l'accord des chaînes sources.

Chaîne complète pour UNE vidéo longue :
1. transcription horodatée (faster-whisper, segments avec début/fin) ;
2. DeepSeek lit la transcription minutée et propose des extraits typés
   (phrase choc / enseignement / témoignage / message complet), en coupant
   UNIQUEMENT aux frontières de phrases — jamais de coupure brutale ;
3. validation des bornes (calées sur les segments réels) ;
4. découpe ffmpeg précise en DEUX formats (décision de Michel) :
   - HORIZONTAL 16:9 (max 1920x1080) → dossier source du pipeline normal
     avec .info.json : circuit habituel vers la chaîne YouTube ;
   - VERTICAL 9:16 recadré centré sur le visage → file d'attente TikTok
     (/app/videos/tiktok_queue/), publiée dès l'approbation de l'API TikTok.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.request
from pathlib import Path

from .config import Config
from .db import Database
from .textdetect import find_ffmpeg

log = logging.getLogger("vortex.clipper")

SOURCES_DIR = Path("/app/videos/sources")

CLIP_PROMPT = """Tu es monteur pour une chaîne YouTube/TikTok de prédications chrétiennes francophones.
Voici la transcription HORODATÉE (en secondes) d'une longue vidéo ({duration:.0f} s au total) :

{transcript}

Propose entre 3 et {max_clips} EXTRAITS à découper, en JSON strict :
{{"clips": [{{"start": <s>, "end": <s>, "type": "choc|enseignement|temoignage|message_complet",
  "title": "titre YouTube accrocheur fidèle (60-85 caractères)",
  "hook": "la phrase la plus forte de l'extrait (max 90 caractères)",
  "description": "2-3 phrases fidèles au contenu"}}]}}

RÈGLES ABSOLUES :
- start/end doivent tomber sur des DÉBUTS/FINS de phrases visibles dans la transcription
  (utilise les horodatages fournis) — jamais au milieu d'une phrase ;
- chaque extrait doit se comprendre SEUL (contexte inclus si nécessaire) ;
- durées cibles : 40-70 s (choc), 60-180 s (enseignement/témoignage), 300-600 s (message complet) ;
- pas de chevauchement entre extraits ; choisis les passages les PLUS forts ;
- aucun extrait incompréhensible ou coupé brutalement.

Réponds UNIQUEMENT avec le JSON."""


def _audio_duration(path: str) -> float:
    out = subprocess.run(
        [find_ffmpeg().replace("ffmpeg", "ffprobe"), "-v", "quiet",
         "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=120)
    try:
        return float(out.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _transcribe_timed(cfg: Config, path: str) -> tuple[list, float]:
    # Repérage des extraits sur une source longue (jusqu'à 2 h). Sur un VPS avec
    # peu de RAM libre, transcrire 2 h d'un coup fait exploser la mémoire (OOM) :
    # faster-whisper décode TOUT l'audio en mémoire d'abord. On découpe donc en
    # tranches de 10 min transcrites une par une — la mémoire reste minuscule.
    # Modèle LÉGER 'base' : cette transcription ne sert qu'à SITUER les passages ;
    # chaque extrait court est re-transcrit en 'small' au stade des sous-titres,
    # donc aucune perte de qualité finale. Surchargeable via cfg.clip_whisper_model.
    from faster_whisper import WhisperModel
    import gc
    import os
    import tempfile

    model_name = getattr(cfg, "clip_whisper_model", None) or "base"
    chunk_s = int(getattr(cfg, "clip_chunk_seconds", 0) or 600)
    duration = _audio_duration(path)
    log.info("Transcription de repérage (modèle '%s', source %.0f min, tranches de %d min)…",
             model_name, duration / 60, chunk_s // 60)
    model = WhisperModel(model_name, device=cfg.whisper_device,
                         compute_type=cfg.whisper_compute,
                         cpu_threads=os.cpu_count() or 2)
    segs: list = []
    try:
        if duration and duration > chunk_s * 1.5:
            ffmpeg = find_ffmpeg()
            start = 0.0
            while start < duration:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    wav = tf.name
                try:
                    subprocess.run(
                        [ffmpeg, "-v", "error", "-ss", f"{start:.1f}",
                         "-t", f"{chunk_s}", "-i", path,
                         "-vn", "-ac", "1", "-ar", "16000", "-y", wav],
                        capture_output=True, timeout=600, check=True)
                    seg_iter, _ = model.transcribe(wav, vad_filter=True)
                    for s in seg_iter:
                        if s.text.strip():
                            segs.append((round(s.start + start, 1),
                                         round(s.end + start, 1), s.text.strip()))
                finally:
                    try:
                        os.remove(wav)
                    except OSError:
                        pass
                    gc.collect()
                log.info("  … %.0f/%.0f min transcrites (%d segments)",
                         min(start + chunk_s, duration) / 60, duration / 60, len(segs))
                start += chunk_s
        else:
            seg_iter, info = model.transcribe(path, vad_filter=True)
            segs = [(round(s.start, 1), round(s.end, 1), s.text.strip())
                    for s in seg_iter if s.text.strip()]
            duration = duration or info.duration
    finally:
        del model
        gc.collect()
    return segs, duration


def _ask_clips(cfg: Config, segs: list, duration: float) -> list[dict]:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        log.error("DEEPSEEK_API_KEY absent — clipper indisponible")
        return []
    lines = [f"[{s:.0f}-{e:.0f}] {t}" for s, e, t in segs]
    transcript = "\n".join(lines)
    if len(transcript) > 90000:  # ~2 h de sermon max par appel
        transcript = transcript[:90000]
    max_clips = 8 if duration > 1200 else 5
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": CLIP_PROMPT.format(
            duration=duration, transcript=transcript, max_clips=max_clips)}],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 2000,
    }).encode()
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.load(r)
        clips = json.loads(resp["choices"][0]["message"]["content"]).get("clips", [])
    except Exception as exc:
        log.error("DeepSeek clipper échoué : %s", exc)
        return []
    # Validation : bornes calées sur les segments réels, durées plausibles
    starts = [s for s, _, _ in segs]
    ends = [e for _, e, _ in segs]
    valid = []
    for c in clips:
        try:
            start = min(starts, key=lambda x: abs(x - float(c["start"])))
            end = min(ends, key=lambda x: abs(x - float(c["end"])))
        except (KeyError, ValueError, TypeError):
            continue
        if end - start < 25 or end - start > 620 or start >= end:
            continue
        valid.append({"start": start, "end": end,
                      "type": str(c.get("type", "enseignement"))[:20],
                      "title": str(c.get("title", "")).strip()[:95],
                      "hook": str(c.get("hook", "")).strip()[:90],
                      "description": str(c.get("description", "")).strip()[:500]})
    return valid


def _face_center_x(path: str, at: float, width: int, height: int) -> float:
    """Centre horizontal du visage (0-1) pour le recadrage vertical."""
    try:
        import cv2
        import numpy as np
        out = subprocess.run(
            [find_ffmpeg(), "-v", "quiet", "-ss", f"{at:.1f}", "-i", path,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=60)
        img = cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            return (x + w / 2) / img.shape[1]
    except Exception as exc:
        log.debug("Visage non détecté (%s)", exc)
    return 0.5


def _cut(src: str, start: float, end: float, out: Path, vf: str) -> bool:
    """Découpe précise ré-encodée avec le filtre vidéo donné."""
    cmd = [find_ffmpeg(), "-v", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
           "-i", src, "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-y", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3600, check=True)
        return out.exists()
    except subprocess.CalledProcessError as exc:
        log.error("Découpe échouée : %s", exc.stderr[-300:] if exc.stderr else exc)
        return False


def _cut_horizontal(src: str, start: float, end: float, out: Path,
                    src_w: int, src_h: int) -> bool:
    """Version YouTube : format d'origine 16:9, plafonné à 3840 de large (jamais de downscale)."""
    vf = "scale=3840:-2:flags=lanczos" if src_w > 3840 else f"scale={src_w}:{src_h}"
    return _cut(src, start, end, out, vf)


def _cut_vertical(src: str, start: float, end: float, out: Path,
                  src_w: int, src_h: int) -> bool:
    """Version TikTok : recadrage 9:16 centré sur le visage."""
    mid = (start + end) / 2
    cx = _face_center_x(src, mid, src_w, src_h)
    crop_w = int(src_h * 9 / 16 // 2 * 2)
    if crop_w >= src_w:  # source déjà verticale/carrée : pas de recadrage
        vf = "scale=1080:-2"
    else:
        x = int(max(0, min(src_w - crop_w, cx * src_w - crop_w / 2)))
        vf = f"crop={crop_w}:{src_h}:{x}:0,scale=1080:1920"
    return _cut(src, start, end, out, vf)


def _probe_dims(path: str) -> tuple[int, int]:
    out = subprocess.run(
        [find_ffmpeg().replace("ffmpeg", "ffprobe"), "-v", "quiet", "-print_format",
         "json", "-show_streams", path], capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    return int(v["width"]), int(v["height"])


def _ensure_table(db: Database) -> None:
    db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS clip_sources (
            path TEXT PRIMARY KEY,
            processed_at TEXT,
            clips_count INTEGER
        );
    """)
    db.conn.commit()


def process_one_source(cfg: Config, db: Database) -> int:
    """Traite UNE vidéo source non encore découpée. Retourne le nb d'extraits créés."""
    _ensure_table(db)
    if not SOURCES_DIR.is_dir():
        log.info("Aucun dossier sources (%s)", SOURCES_DIR)
        return 0
    candidates = sorted(SOURCES_DIR.glob("*/*.mp4"), key=lambda p: p.name, reverse=True)
    src = None
    for c in candidates:
        done = db.conn.execute("SELECT 1 FROM clip_sources WHERE path = ?", (str(c),)).fetchone()
        if not done:
            src = c
            break
    if src is None:
        log.info("Toutes les sources sont déjà découpées.")
        return 0

    log.info("Découpage de la source : %s", src.name)
    segs, duration = _transcribe_timed(cfg, str(src))
    if not segs:
        db.conn.execute("INSERT OR REPLACE INTO clip_sources VALUES (?, datetime('now'), 0)", (str(src),))
        db.conn.commit()
        return 0
    clips = _ask_clips(cfg, segs, duration)
    log.info("%d extraits proposés par DeepSeek", len(clips))

    src_w, src_h = _probe_dims(str(src))
    chan = src.parent.name
    tiktok_dir = Path("/app/videos/tiktok_queue")
    tiktok_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    for i, c in enumerate(clips, start=1):
        stem = f"clip_{chan}_{src.stem[:24]}_{i}_{int(c['start'])}"
        info = {"description": f"{c['title']} — {c['hook']} {c['description']}"}
        # 1) version HORIZONTALE → pipeline YouTube habituel
        out_h = cfg.source_dir / f"{stem}.mp4"
        if not _cut_horizontal(str(src), c["start"], c["end"], out_h, src_w, src_h):
            continue
        out_h.with_name(out_h.stem + ".info.json").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8")
        # 2) version VERTICALE → file d'attente TikTok
        out_v = tiktok_dir / f"{stem}_tiktok.mp4"
        if _cut_vertical(str(src), c["start"], c["end"], out_v, src_w, src_h):
            out_v.with_name(out_v.stem + ".info.json").write_text(json.dumps(
                {"title": c["title"], "hook": c["hook"],
                 "description": c["description"], "type": c["type"]},
                ensure_ascii=False), encoding="utf-8")
        made += 1
        log.info("Extrait %d/%d : %s (%ds, %s) + version TikTok", i, len(clips),
                 out_h.name, int(c["end"] - c["start"]), c["type"])
    db.conn.execute("INSERT OR REPLACE INTO clip_sources VALUES (?, datetime('now'), ?)",
                    (str(src), made))
    db.conn.commit()
    return made

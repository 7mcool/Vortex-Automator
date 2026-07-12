"""Étape 3 — Transcription locale gratuite avec faster-whisper.

Produit un .txt (texte brut) et un .srt (sous-titres) par vidéo.
Le modèle est chargé UNE seule fois par session (pas à chaque vidéo).
La langue est détectée automatiquement (pas de 'fr' forcé).
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Config
from .db import Database

log = logging.getLogger("vortex.transcribe")

_model = None


def get_model(cfg: Config):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("Chargement du modèle Whisper '%s' (%s/%s)…",
                 cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute)
        _model = WhisperModel(cfg.whisper_model, device=cfg.whisper_device,
                              compute_type=cfg.whisper_compute)
    return _model


def _fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_video(cfg: Config, db: Database, video_id: int) -> bool:
    row = db.get(video_id)
    if row is None:
        return False
    path = Path(row["path"])
    if not path.exists():
        # Disque externe débranché ou fichier déplacé : on n'échoue pas la vidéo,
        # elle sera reprise quand le fichier réapparaîtra (prochain scan/run).
        log.warning("Fichier inaccessible (disque débranché ?) : %s — vidéo laissée en attente", path)
        return False

    model = get_model(cfg)
    try:
        segments_iter, info = model.transcribe(str(path), vad_filter=True,
                                               word_timestamps=True)
        segments = list(segments_iter)
    except Exception as exc:
        log.error("Transcription échouée pour %s : %s", row["name"], exc)
        db.set_state(video_id, "FAILED", f"transcription : {exc}")
        return False

    text = " ".join(seg.text.strip() for seg in segments).strip()
    txt_path = cfg.transcripts_dir / f"{row['name']}.txt"
    txt_path.write_text(text, encoding="utf-8")

    # Timing mot à mot pour les captions karaoké (style Submagic/OpusClip)
    import json as _json
    words = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
             for seg in segments for w in (seg.words or []) if w.word.strip()]
    words_dir = cfg.data_dir / "words"
    words_dir.mkdir(parents=True, exist_ok=True)
    (words_dir / f"{row['name']}.json").write_text(
        _json.dumps(words, ensure_ascii=False), encoding="utf-8")

    srt_lines = []
    for i, seg in enumerate(segments, start=1):
        srt_lines += [str(i), f"{_fmt_ts(seg.start)} --> {_fmt_ts(seg.end)}", seg.text.strip(), ""]
    srt_path = cfg.subtitles_dir / f"{row['name']}.srt"
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

    db.set_state(
        video_id, "TRANSCRIBED", f"langue={info.language} (p={info.language_probability:.2f})",
        transcript_path=str(txt_path), srt_path=str(srt_path), language=info.language,
    )
    log.info("Transcrit %s (%.0fs, langue %s)", row["name"], row["duration_s"] or 0, info.language)
    return True


def transcribe_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    """Transcrit jusqu'à `limit` vidéos AVEC SUCCÈS (les fichiers absents —
    disque débranché, pas encore synchronisés — ne consomment pas la limite)."""
    done = 0
    for row in db.by_state("DISCOVERED"):
        if limit and done >= limit:
            break
        if transcribe_video(cfg, db, row["id"]):
            done += 1
    return done

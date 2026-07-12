"""Phase 2 — Habillage visuel FFmpeg, OBLIGATOIRE pour TOUTES les vidéos.

Règle de Michel (12/07 soir) : les textes déjà présents dans les vidéos ne sont
que des sous-titres simples — aucun appel à l'action stratégique. L'habillage
s'applique donc à toutes les vidéos, SANS jamais retirer l'existant :
- accroche texte des 2,5 premières secondes (haut de l'image — zone libre) ;
- rappel « Abonne-toi ✚ » pendant les 3 dernières secondes (remonté si la
  vidéo a déjà des sous-titres en bas, pour éviter le chevauchement) ;
- filigrane du nom de la chaîne en haut (semi-transparent).
L'original n'est JAMAIS modifié : copie habillée dans data/exports/.
La détection OCR (has_text) sert à choisir la position du CTA.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import Config
from .db import Database
from .textdetect import find_ffmpeg

log = logging.getLogger("vortex.render")


def find_font() -> str:
    for candidate in (
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("Aucune police trouvée pour drawtext")


def _esc(text: str) -> str:
    """Échappe un texte pour le filtre drawtext de FFmpeg."""
    return (text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
            .replace("%", r"\%").replace(",", r"\,"))


def _wrap(text: str, width: int = 26, max_lines: int = 3) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
        else:
            cur = f"{cur} {w}".strip()
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return "\n".join(lines)


def render_video(cfg: Config, db: Database, video_id: int) -> bool:
    row = db.get(video_id)
    if row is None:
        return False
    has_text = row["has_text"] if "has_text" in row.keys() else None
    src = Path(row["path"])
    if not src.exists():
        log.warning("Fichier inaccessible : %s", src)
        return False

    exports = cfg.data_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    out = exports / f"{row['name']}_v.mp4"

    def _ffpath(p: str) -> str:
        return p.replace("\\", "/").replace(":", r"\:")

    font = _ffpath(find_font())
    duration = row["duration_s"] or 30

    # Le hook passe par un fichier texte : les apostrophes/caractères des titres
    # français cassent l'échappement en ligne du filtre drawtext.
    # Largeur : 18 caractères par ligne à fontsize h/26 tiennent dans une
    # vidéo verticale (vérifié sur 576×1024 — le débordement du 1er essai
    # venait de 26 chars à h/22).
    hook = (row["title"] or "").replace(" #Shorts", "").strip()
    hook_file = exports / f"{row['name']}_hook.txt"
    hook_file.write_text(_wrap(hook, width=18, max_lines=4), encoding="utf-8")
    cta_txt = "Abonne-toi + et partage"
    mid_txt = "Abonne-toi pour la suite"
    brand_txt = _esc(cfg.channel_name)
    cta_start = max(duration - 3.5, duration * 0.66)
    mid_start = duration * 0.45
    mid_end = min(mid_start + 3.0, cta_start - 1)
    # Si la vidéo a déjà des sous-titres (souvent en bas/centre), on remonte les
    # bandeaux pour ne pas les chevaucher — on n'efface jamais rien.
    lifted = has_text in ("texte", "douteux")
    cta_y = "h-7*text_h" if lifted else "h-3*text_h"

    vf = (
        # Accroche : 0 -> 4 s, centrée dans le tiers haut, fond noir léger
        f"drawtext=fontfile='{font}':textfile='{_ffpath(str(hook_file))}':fontsize=h/26:fontcolor=white:"
        f"box=1:boxcolor=black@0.55:boxborderw=16:x=(w-text_w)/2:y=h/7:"
        f"enable='lt(t,4)',"
        # Rappel bref en milieu de vidéo
        f"drawtext=fontfile='{font}':text='{mid_txt}':fontsize=h/32:fontcolor=white:"
        f"box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y={cta_y}:"
        f"enable='between(t,{mid_start:.1f},{mid_end:.1f})',"
        # CTA fin de vidéo
        f"drawtext=fontfile='{font}':text='{cta_txt}':fontsize=h/30:fontcolor=white:"
        f"box=1:boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y={cta_y}:"
        f"enable='gt(t,{cta_start:.1f})',"
        # Filigrane discret permanent
        f"drawtext=fontfile='{font}':text='{brand_txt}':fontsize=h/42:fontcolor=white@0.5:"
        f"x=(w-text_w)/2:y=h/40"
    )
    cmd = [find_ffmpeg(), "-v", "error", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
           "-c:a", "copy", "-movflags", "+faststart", "-y", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1800, check=True)
    except subprocess.CalledProcessError as exc:
        log.error("Rendu échoué pour %s : %s", row["name"], exc.stderr[-400:] if exc.stderr else exc)
        return False
    finally:
        hook_file.unlink(missing_ok=True)

    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "render_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN render_path TEXT")
        db.conn.commit()
    db.update_fields(video_id, render_path=str(out))
    log.info("Rendu OK : %s", out.name)
    return True


def render_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    """Habille les vidéos READY qui n'ont pas encore de rendu (TOUTES les vidéos,
    dans le même ordre que la publication pour que les prochaines publiées
    soient habillées en premier)."""
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "render_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN render_path TEXT")
        db.conn.commit()
    sql = ("SELECT id FROM videos WHERE state = 'READY' AND render_path IS NULL "
           "ORDER BY CASE WHEN duration_s BETWEEN 30 AND 180 THEN 0 ELSE 1 END, "
           "duration_s DESC")
    rows = db.conn.execute(sql).fetchall()
    done = 0
    for r in rows:
        if limit and done >= limit:
            break
        if render_video(cfg, db, r["id"]):
            done += 1
    return done

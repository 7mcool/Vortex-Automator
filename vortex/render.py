"""Phase 2 — Habillage visuel FFmpeg, UNIQUEMENT pour les vidéos sans texte incrusté.

Règles de Michel :
- ne JAMAIS toucher aux vidéos qui ont déjà des sous-titres/textes (has_text='texte');
- les 'douteux' restent tels quels (validation manuelle possible plus tard) ;
- l'original n'est JAMAIS modifié : on produit une copie dans data/exports/.

Habillage v1 (sobre, varié par vidéo) :
- accroche texte des 2,5 premières secondes (le titre, sans #Shorts) ;
- rappel « Abonne-toi ✚ » discret en bas pendant les 3 dernières secondes ;
- filigrane du nom de la chaîne en haut (semi-transparent).
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
    if has_text != "sans_texte":
        log.info("Vidéo #%d ignorée (has_text=%s) — on ne touche pas à l'image", video_id, has_text)
        return False
    src = Path(row["path"])
    if not src.exists():
        log.warning("Fichier inaccessible : %s", src)
        return False

    exports = cfg.data_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    out = exports / f"{row['name']}_v.mp4"
    font = find_font().replace("\\", "/").replace(":", r"\:")
    duration = row["duration_s"] or 30

    hook = (row["title"] or "").replace(" #Shorts", "").strip()
    hook_txt = _esc(_wrap(hook))
    cta_txt = _esc("Abonne-toi ✚ et partage")
    brand_txt = _esc(cfg.channel_name)
    cta_start = max(duration - 3.5, duration * 0.66)

    vf = (
        # Accroche : 0 -> 2,5 s, centrée dans le tiers haut, fond noir léger
        f"drawtext=fontfile='{font}':text='{hook_txt}':fontsize=h/22:fontcolor=white:"
        f"box=1:boxcolor=black@0.55:boxborderw=18:x=(w-text_w)/2:y=h/6:"
        f"enable='lt(t,2.5)',"
        # CTA fin de vidéo, bas de l'écran
        f"drawtext=fontfile='{font}':text='{cta_txt}':fontsize=h/30:fontcolor=white:"
        f"box=1:boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y=h-3*text_h:"
        f"enable='gt(t,{cta_start:.1f})',"
        # Filigrane discret permanent
        f"drawtext=fontfile='{font}':text='{brand_txt}':fontsize=h/45:fontcolor=white@0.45:"
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

    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "render_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN render_path TEXT")
        db.conn.commit()
    db.update_fields(video_id, render_path=str(out))
    log.info("Rendu OK : %s", out.name)
    return True


def render_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    """Rend les vidéos READY sans texte incrusté qui n'ont pas encore de rendu."""
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "render_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN render_path TEXT")
        db.conn.commit()
    sql = ("SELECT id FROM videos WHERE state = 'READY' AND has_text = 'sans_texte' "
           "AND render_path IS NULL")
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = db.conn.execute(sql).fetchall()
    return sum(1 for r in rows if render_video(cfg, db, r["id"]))

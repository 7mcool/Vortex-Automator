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


def _ass_time(seconds: float) -> str:
    seconds = max(seconds, 0)
    h, rem = divmod(int(seconds * 100), 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(cfg: Config, *, width: int, height: int, duration: float,
              title: str, lifted: bool) -> str:
    """Habillage professionnel via sous-titres ASS (libass) :
    - accroche avec contour noir épais + premiers mots en OR (lisible sur tout fond),
      fondu d'apparition/disparition ;
    - badge rouge « S'ABONNER » façon bouton YouTube (milieu + fin de vidéo) ;
    - filigrane discret permanent.
    `lifted` remonte les badges quand la vidéo a déjà des sous-titres en bas."""
    fontname = "Arial" if Path(r"C:\Windows\Fonts\arial.ttf").exists() else "DejaVu Sans"

    hook = title.replace(" #Shorts", "").strip()
    words = hook.split()
    gold_part = " ".join(words[:3])
    rest_part = " ".join(words[3:])
    # \N tous les ~20 caractères pour rester dans le cadre
    def wrap_ass(text: str, w: int = 20) -> str:
        lines, cur = [], ""
        for word in text.split():
            if len(cur) + len(word) + 1 > w and cur:
                lines.append(cur)
                cur = word
            else:
                cur = f"{cur} {word}".strip()
        if cur:
            lines.append(cur)
        return r"\N".join(lines[:4])

    gold = r"{\c&H00D7FF&}"     # or (BGR)
    white = r"{\c&HFFFFFF&}"
    hook_txt = gold + wrap_ass(gold_part) + (r"\N" + white + wrap_ass(rest_part) if rest_part else "")

    fs_hook = int(height / 16)
    fs_badge = int(height / 26)
    fs_brand = int(height / 42)
    margin_badge = int(height * (0.30 if lifted else 0.12))

    cta_start = max(duration - 3.5, duration * 0.66)
    mid_start = duration * 0.45
    mid_end = min(mid_start + 2.8, cta_start - 0.8)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{fontname},{fs_hook},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0.5,0,1,4,2,8,30,30,{int(height * 0.10)},1
Style: Badge,{fontname},{fs_badge},&H00FFFFFF,&H00FFFFFF,&H002313E6,&H002313E6,-1,0,0,0,100,100,1,0,3,10,0,2,30,30,{margin_badge},1
Style: Brand,{fontname},{fs_brand},&H64FFFFFF,&H64FFFFFF,&H64000000,&H00000000,-1,0,0,0,100,100,1,0,1,2,0,8,30,30,{int(height * 0.015)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 1,{_ass_time(0.3)},{_ass_time(4.5)},Hook,,0,0,0,,{{\\fad(250,300)}}{hook_txt}",
        f"Dialogue: 1,{_ass_time(mid_start)},{_ass_time(mid_end)},Badge,,0,0,0,,{{\\fad(200,200)}}► S'ABONNER",
        f"Dialogue: 1,{_ass_time(cta_start)},{_ass_time(duration)},Badge,,0,0,0,,{{\\fad(250,0)}}❤ ABONNE-TOI ✚ PARTAGE",
        f"Dialogue: 0,{_ass_time(0)},{_ass_time(duration)},Brand,,0,0,0,,{cfg.channel_name}",
    ]
    return header + "\n".join(events) + "\n"


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

    duration = row["duration_s"] or 30
    width = row["width"] or 576
    height = row["height"] or 1024

    ass_file = exports / f"{row['name']}.ass"
    ass_file.write_text(
        build_ass(cfg, width=width, height=height, duration=duration,
                  title=row["title"] or "", lifted=has_text in ("texte", "douteux")),
        encoding="utf-8")

    def _ffpath(p: str) -> str:
        return p.replace("\\", "/").replace(":", r"\:")

    cmd = [find_ffmpeg(), "-v", "error", "-i", str(src),
           "-vf", f"ass='{_ffpath(str(ass_file))}'",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
           "-c:a", "copy", "-movflags", "+faststart", "-y", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1800, check=True)
    except subprocess.CalledProcessError as exc:
        log.error("Rendu échoué pour %s : %s", row["name"], exc.stderr[-400:] if exc.stderr else exc)
        return False
    finally:
        ass_file.unlink(missing_ok=True)

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

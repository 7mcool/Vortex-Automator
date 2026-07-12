"""Habillage vidéo v3 — format « prédication » (template de Michel) + karaoké Submagic.

Mise en page (canvas 1080×1920) :
- bande noire HAUT : la citation-accroche en MAJUSCULES, 3 premiers mots en OR,
  suite en blanc, visible en permanence ;
- vidéo au centre (jamais recadrée, réduite pour tenir) ;
- captions KARAOKÉ mot-à-mot dans le bas de la vidéo (MAJUSCULES, mot courant
  en VERT, style Submagic/OpusClip) quand le timing des mots existe ;
- bande noire BAS : @handle souligné + badges CTA en rotation pendant TOUTE la
  vidéo : ► S'ABONNER / ❤ LIKE SI TU CROIS / ★ PARTAGE À UN AMI / ✎ COMMENTE « AMEN »
  (demande de Michel : « un truc qui fait exploser le compte »).

L'original n'est JAMAIS modifié : copie habillée dans data/exports/.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .config import Config
from .db import Database
from .textdetect import find_ffmpeg

log = logging.getLogger("vortex.render")

CANVAS_W, CANVAS_H = 1080, 1920
BAND_TOP, BAND_BOTTOM = 320, 240
VIDEO_H = CANVAS_H - BAND_TOP - BAND_BOTTOM  # 1360

GOLD = r"\c&H00D7FF&"
WHITE = r"\c&HFFFFFF&"

CTA_ROTATION = ["► S'ABONNER", "❤ LIKE SI TU CROIS", "★ PARTAGE À UN AMI", "✎ COMMENTE « AMEN »"]
CTA_FINAL = "► ABONNE-TOI ✚ PARTAGE ❤"


def _ass_time(seconds: float) -> str:
    seconds = max(seconds, 0)
    h, rem = divmod(int(seconds * 100), 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width and cur:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
        else:
            cur = f"{cur} {word}".strip()
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


def _fontname() -> str:
    return "Arial" if Path(r"C:\Windows\Fonts\arial.ttf").exists() else "DejaVu Sans"


def _karaoke_events(words_file: Path, duration: float) -> list[str]:
    """Chunks de 3 mots max, mot courant vert via \\k (style Submagic)."""
    try:
        words = json.loads(words_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    events = []
    chunk: list[dict] = []
    for w in words:
        chunk.append(w)
        span = chunk[-1]["e"] - chunk[0]["s"]
        chars = sum(len(x["w"]) + 1 for x in chunk)
        if len(chunk) >= 3 or span >= 1.6 or chars >= 15:
            events.append(chunk)
            chunk = []
    if chunk:
        events.append(chunk)

    out = []
    for ch in events:
        start, end = ch[0]["s"], max(ch[-1]["e"], ch[0]["s"] + 0.3)
        parts = []
        for w in ch:
            k_cs = max(int((w["e"] - w["s"]) * 100), 8)
            parts.append(f"{{\\k{k_cs}}}{w['w'].upper()}")
        text = r"{\fad(60,60)}" + " ".join(parts)
        out.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(min(end, duration))},Karaoke,,0,0,0,,{text}")
    return out


def build_ass(cfg: Config, *, duration: float, title: str, words_file: Path | None) -> str:
    fontname = _fontname()

    hook = title.replace(" #Shorts", "").strip().upper()
    words = hook.split()
    if len(words) > 12:
        words = words[:12]
    # Retire les fragments disgracieux en fin d'accroche (tirets, attributions coupées…)
    while words and (words[-1].strip("-–—|.…") == "" or words[-1].rstrip(".…") in ("EV", "ÉV", "PST", "PASTEUR")):
        words.pop()
    if len(hook.split()) > len(words):
        words[-1] = words[-1].rstrip(",;:-") + "…"
    gold_txt = " ".join(words[:3])
    rest_txt = " ".join(words[3:])
    hook_lines = []
    for i, line in enumerate(_wrap(f"{gold_txt}\x00{rest_txt}".replace("\x00", " "), 21, 4)):
        hook_lines.append(line)
    # Couleur : on passe au blanc dès que les mots dorés sont épuisés
    gold_chars = len(gold_txt)
    flat = " ".join(hook_lines)
    hook_txt = ""
    count = 0
    hook_txt += "{" + GOLD + "}"
    switched = False
    for line in hook_lines:
        for ch in line:
            if not switched and count >= gold_chars:
                hook_txt += "{" + WHITE + "}"
                switched = True
            hook_txt += ch
            count += 1
        hook_txt += r"\N"
        count += 1
    hook_txt = hook_txt.rstrip(r"\N")

    handle = "@sophos_prophetikos"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {CANVAS_W}
PlayResY: {CANVAS_H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{fontname},62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,-1,0,0,100,100,0.5,0,1,4,0,8,36,36,30,1
Style: Karaoke,{fontname},64,&H0005FF2C,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,5,2,2,50,50,{BAND_BOTTOM + 40},1
Style: Badge,{fontname},56,&H00FFFFFF,&H00FFFFFF,&H001323E6,&H001323E6,-1,0,0,0,100,100,1,0,3,14,0,2,40,40,116,1
Style: Handle,{fontname},40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,-1,-1,0,100,100,1,0,1,2,0,2,40,40,34,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 1,{_ass_time(0)},{_ass_time(duration)},Hook,,0,0,0,,{hook_txt}",
        f"Dialogue: 1,{_ass_time(0)},{_ass_time(duration)},Handle,,0,0,0,,{handle}",
    ]
    # CTA agressifs : 5 fenêtres de 3,5 s réparties sur toute la durée,
    # avec pulsation d'attention (Michel : « inciter les gens à passer à l'action »)
    pulse = r"{\fad(150,150)\t(0,180,\fscx112\fscy112)\t(180,360,\fscx100\fscy100)}"
    for i, frac in enumerate((0.08, 0.27, 0.46, 0.65, 0.82)):
        start = duration * frac
        end = min(start + 3.5, duration - 5.5)
        if end <= start:
            continue
        txt = CTA_ROTATION[i % len(CTA_ROTATION)]
        events.append(
            f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Badge,,0,0,0,,{pulse}{txt}")
    # CTA final appuyé (5 dernières secondes)
    events.append(
        f"Dialogue: 1,{_ass_time(max(duration - 5.0, 0))},{_ass_time(duration)},Badge,,0,0,0,,"
        f"{pulse}{CTA_FINAL}")

    if words_file and words_file.exists():
        events += _karaoke_events(words_file, duration)

    return header + "\n".join(events) + "\n"


def render_video(cfg: Config, db: Database, video_id: int) -> bool:
    row = db.get(video_id)
    if row is None:
        return False
    src = Path(row["path"])
    if not src.exists():
        log.warning("Fichier inaccessible : %s", src)
        return False

    exports = cfg.data_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    out = exports / f"{row['name']}_v.mp4"
    duration = row["duration_s"] or 30
    words_file = cfg.data_dir / "words" / f"{row['name']}.json"

    ass_file = exports / f"{row['name']}.ass"
    ass_file.write_text(
        build_ass(cfg, duration=duration, title=row["title"] or "",
                  words_file=words_file if words_file.exists() else None),
        encoding="utf-8")

    def _ffpath(p: str) -> str:
        return p.replace("\\", "/").replace(":", r"\:")

    vf = (
        f"scale={CANVAS_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
        f"pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:{BAND_TOP}+({VIDEO_H}-ih)/2:color=black,"
        f"ass='{_ffpath(str(ass_file))}'"
    )
    cmd = [find_ffmpeg(), "-v", "error", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
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
    """Habille les vidéos READY sans rendu, dans l'ordre de publication."""
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "render_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN render_path TEXT")
        db.conn.commit()
    rows = db.conn.execute(
        "SELECT id FROM videos WHERE state = 'READY' AND render_path IS NULL "
        "ORDER BY CASE WHEN duration_s BETWEEN 30 AND 180 THEN 0 ELSE 1 END, "
        "duration_s DESC").fetchall()
    done = 0
    for r in rows:
        if limit and done >= limit:
            break
        if render_video(cfg, db, r["id"]):
            done += 1
    return done

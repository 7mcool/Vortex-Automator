"""Covers YouTube automatiques — style du template de Michel (tpl1) :
fond violet dégradé, photo du prédicateur DÉTOURÉE avec contour blanc,
titre penché en MAJUSCULES (1re ligne OR, suite BLANC), badge doré en bas.

- extraction d'une image du meilleur moment de la vidéo (ffmpeg) ;
- détourage IA gratuit (rembg/U2Net, CPU) avec repli « carte arrondie »
  si rembg indisponible ;
- rendu 1280×720 (standard YouTube), < 2 Mo ;
- la cover générée remplace la cover TikTok à l'upload quand elle existe.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import Config
from .db import Database
from .textdetect import find_ffmpeg

log = logging.getLogger("vortex.thumbs")

W, H = 1280, 720
PURPLE_DARK = (43, 8, 66)
PURPLE_MID = (91, 20, 130)
PURPLE_LIGHT = (150, 45, 190)
GOLD = (255, 200, 30)
WHITE = (255, 255, 255)


def _font(size: int, bold: bool = True):
    from PIL import ImageFont
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def _gradient_bg():
    """Fond violet en dégradé diagonal + halo lumineux central."""
    from PIL import Image
    import math
    bg = Image.new("RGB", (W, H))
    px = bg.load()
    for y in range(H):
        for x in range(0, W, 2):  # pas de 2 pour la vitesse
            t = (x / W + y / H) / 2
            r = int(PURPLE_DARK[0] + (PURPLE_MID[0] - PURPLE_DARK[0]) * t)
            g = int(PURPLE_DARK[1] + (PURPLE_MID[1] - PURPLE_DARK[1]) * t)
            b = int(PURPLE_DARK[2] + (PURPLE_MID[2] - PURPLE_DARK[2]) * t)
            # halo autour du tiers droit (là où sera la photo)
            d = math.hypot((x - W * 0.72) / W, (y - H * 0.45) / H)
            glow = max(0, 1 - d * 2.2) * 0.55
            r = min(255, int(r + (PURPLE_LIGHT[0] - r) * glow))
            g = min(255, int(g + (PURPLE_LIGHT[1] - g) * glow))
            b = min(255, int(b + (PURPLE_LIGHT[2] - b) * glow))
            px[x, y] = (r, g, b)
            if x + 1 < W:
                px[x + 1, y] = (r, g, b)
    return bg


def _extract_frame(video_path: str, at: float, out_png: Path) -> bool:
    try:
        subprocess.run(
            [find_ffmpeg(), "-v", "error", "-ss", f"{at:.1f}", "-i", video_path,
             "-frames:v", "1", "-vf", "scale=-2:900", "-y", str(out_png)],
            capture_output=True, timeout=120, check=True)
        return out_png.exists()
    except Exception as exc:
        log.warning("Extraction d'image impossible (%s) : %s", video_path, exc)
        return False


def _cutout(frame_png: Path):
    """Détourage du sujet avec contour blanc. Repli : carte arrondie."""
    from PIL import Image, ImageFilter, ImageDraw, ImageOps
    img = Image.open(frame_png).convert("RGBA")
    try:
        from rembg import remove
        cut = remove(img)
        alpha = cut.getchannel("A")
        if sum(alpha.point(lambda a: 1 if a > 128 else 0).getdata()) < 5000:
            raise ValueError("détourage vide")
        # contour blanc : alpha dilaté
        outline_a = alpha.filter(ImageFilter.MaxFilter(15))
        outline = Image.new("RGBA", cut.size, (255, 255, 255, 0))
        outline.putalpha(outline_a)
        base = Image.new("RGBA", cut.size, (0, 0, 0, 0))
        base.alpha_composite(outline)
        base.alpha_composite(cut)
        return base
    except Exception as exc:
        log.info("rembg indisponible/échec (%s) — repli carte arrondie", exc)
        img = ImageOps.fit(img, (620, 720), centering=(0.5, 0.35))
        mask = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(mask)
        d.rounded_rectangle([0, 0, img.size[0], img.size[1]], radius=40, fill=255)
        card = Image.new("RGBA", (img.size[0] + 16, img.size[1] + 16), (0, 0, 0, 0))
        d2 = ImageDraw.Draw(card)
        d2.rounded_rectangle([0, 0, card.size[0], card.size[1]], radius=46, fill=(255, 255, 255, 255))
        card.paste(img, (8, 8), mask)
        return card


def _title_lines(title: str) -> list[str]:
    text = title.replace(" #Shorts", "").strip().upper()
    words = text.split()[:9]
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 14 and cur:
            lines.append(cur)
            cur = w
            if len(lines) == 3:
                break
        else:
            cur = f"{cur} {w}".strip()
    if cur and len(lines) < 4:
        lines.append(cur)
    return lines[:4]


def generate_thumb(cfg: Config, db: Database, video_id: int) -> bool:
    from PIL import Image, ImageDraw

    row = db.get(video_id)
    if row is None or not row["title"]:
        return False
    src = Path(row["path"])
    if not src.exists():
        return False

    thumbs_dir = cfg.data_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    out = thumbs_dir / f"{row['name']}.jpg"
    tmp_frame = thumbs_dir / f"{row['name']}_frame.png"

    if not _extract_frame(str(src), (row["duration_s"] or 30) * 0.3, tmp_frame):
        return False

    canvas = _gradient_bg().convert("RGBA")
    subject = _cutout(tmp_frame)
    # photo aux 2/3 droits, calée en bas
    ratio = min(680 / subject.height, 620 / subject.width)
    subject = subject.resize((int(subject.width * ratio), int(subject.height * ratio)))
    canvas.alpha_composite(subject, (W - subject.width - 40, H - subject.height))

    # titre penché à gauche : 1re ligne OR, suite BLANC, ombre noire
    lines = _title_lines(row["title"])
    txt_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt_layer)
    y = 90
    for i, line in enumerate(lines):
        size = 86 if i == 0 else 72
        font = _font(size)
        color = GOLD if i == 0 else WHITE
        for dx, dy in ((4, 4), (2, 2)):
            d.text((70 + dx, y + dy), line, font=font, fill=(0, 0, 0, 230))
        d.text((70, y), line, font=font, fill=color + (255,))
        y += size + 18
    txt_layer = txt_layer.rotate(3, resample=Image.BICUBIC, center=(W // 3, H // 2))
    canvas.alpha_composite(txt_layer)

    # badge doré en bas à gauche
    badge_txt = cfg.channel_name.upper()
    bfont = _font(40)
    bbox = d.textbbox((0, 0), badge_txt, font=bfont)
    bw, bh = bbox[2] - bbox[0] + 60, bbox[3] - bbox[1] + 34
    badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.rounded_rectangle([0, 0, bw, bh], radius=bh // 2, fill=GOLD + (255,),
                         outline=(255, 255, 255, 255), width=4)
    bd.text((30, 14), badge_txt, font=bfont, fill=(20, 5, 30, 255))
    canvas.alpha_composite(badge, (60, H - bh - 46))

    canvas.convert("RGB").save(out, "JPEG", quality=88)
    tmp_frame.unlink(missing_ok=True)

    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "thumb_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN thumb_path TEXT")
        db.conn.commit()
    db.update_fields(video_id, thumb_path=str(out))
    log.info("Cover générée : %s", out.name)
    return True


def thumbs_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "thumb_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN thumb_path TEXT")
        db.conn.commit()
    rows = db.conn.execute(
        "SELECT id FROM videos WHERE state = 'READY' AND thumb_path IS NULL "
        "ORDER BY CASE WHEN duration_s BETWEEN 30 AND 180 THEN 0 ELSE 1 END, "
        "duration_s DESC").fetchall()
    done = 0
    for r in rows:
        if limit and done >= limit:
            break
        if generate_thumb(cfg, db, r["id"]):
            done += 1
    return done

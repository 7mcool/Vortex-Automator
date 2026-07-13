"""Covers v3 — « studio web » : maquettes HTML/CSS de niveau design,
rendues par un vrai Chrome invisible (Playwright) sur le serveur.

Chaîne par vidéo :
1. choix de la MEILLEURE image : détection de visage (OpenCV) sur 8 images,
   on garde celle au visage le plus grand/net ;
2. détourage du sujet (rembg) avec halo lumineux ;
3. titre court percutant (thumb_title de DeepSeek, sinon repli titre long) ;
4. injection dans une des 3 maquettes (styles/couleurs variés par vidéo) ;
5. photo de la maquette par Chrome -> JPG 1280×720.
"""

from __future__ import annotations

import base64
import html as html_mod
import io
import logging
import subprocess
import tempfile
from pathlib import Path

from .config import Config
from .db import Database
from .textdetect import find_ffmpeg

log = logging.getLogger("vortex.thumbs")

W, H = 1280, 720
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# (fond dégradé, couleur accent titre, couleur lueur) — varie par vidéo
THEMES = [
    ("linear-gradient(125deg,#2a0845 0%,#5b1a8a 55%,#8e2bc0 100%)", "#ffd23e", "#c05cff"),
    ("linear-gradient(120deg,#071e4a 0%,#0d3aa0 55%,#2a6bf0 100%)", "#ffe14d", "#4d9dff"),
    ("linear-gradient(130deg,#3d0714 0%,#7a1028 55%,#c22045 100%)", "#ffd23e", "#ff5c7a"),
    ("linear-gradient(125deg,#04241a 0%,#0b5c3f 55%,#15996a 100%)", "#ffe14d", "#2fe0a0"),
    ("linear-gradient(120deg,#121216 0%,#26262e 55%,#3d3d4d 100%)", "#ffc93e", "#8f8fb8"),
]


def _b64(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _extract_frames(video: str, duration: float, n: int = 8) -> list[bytes]:
    ffmpeg = find_ffmpeg()
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            t = duration * (0.12 + 0.76 * i / max(n - 1, 1))
            out = Path(tmp) / f"f{i}.png"
            subprocess.run([ffmpeg, "-v", "quiet", "-ss", f"{t:.1f}", "-i", video,
                            "-frames:v", "1", "-vf", "scale=-2:900", "-y", str(out)],
                           capture_output=True, timeout=60)
            if out.exists():
                frames.append(out.read_bytes())
    return frames


def _best_face_frame(frames: list[bytes]) -> bytes | None:
    """L'image au plus grand visage (OpenCV). None si aucun visage nulle part."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return frames[len(frames) // 3] if frames else None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    best, best_area = None, 0
    for data in frames:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
        for (x, y, fw, fh) in faces:
            if fw * fh > best_area:
                best_area, best = fw * fh, data
    if best is None and frames:
        return frames[len(frames) // 3]
    return best


def _cutout_png(frame: bytes) -> bytes:
    """Sujet détouré (rembg), retourné en PNG transparent. Repli : image brute."""
    from PIL import Image
    try:
        from rembg import remove
        img = Image.open(io.BytesIO(frame)).convert("RGBA")
        cut = remove(img)
        alpha = cut.getchannel("A")
        if sum(alpha.point(lambda a: 1 if a > 128 else 0).getdata()) < 8000:
            raise ValueError("détourage vide")
        # recadre sur le sujet
        bbox = alpha.getbbox()
        if bbox:
            cut = cut.crop(bbox)
        buf = io.BytesIO()
        cut.save(buf, "PNG")
        return buf.getvalue()
    except Exception as exc:
        log.info("Détourage impossible (%s) — photo carte", exc)
        img = Image.open(io.BytesIO(frame)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


def _split_title(title: str) -> tuple[str, str]:
    words = title.replace(" #Shorts", "").strip().upper().split()
    if len(words) <= 3:
        return " ".join(words), ""
    cut = max(2, len(words) // 2)
    return " ".join(words[:cut]), " ".join(words[cut:])


def _html(cfg: Config, video_id: int, title: str, subject_uri: str, is_card: bool) -> str:
    bg, accent, glow = THEMES[video_id % len(THEMES)]
    line1, line2 = _split_title(title)
    line1, line2 = html_mod.escape(line1), html_mod.escape(line2)
    layout_b = video_id % 2 == 1  # photo à gauche / texte à droite, ou l'inverse
    logo_uri = ""
    logo_file = ASSETS_DIR / "logo-chaine.png"
    if logo_file.exists():
        logo_uri = _b64(logo_file.read_bytes())

    subject_css = (
        "height:96%;bottom:0;filter:drop-shadow(0 0 34px {glow}cc) drop-shadow(0 14px 22px rgba(0,0,0,.55));"
        if not is_card else
        "height:88%;bottom:4%;border-radius:22px;border:5px solid #fff;"
        "box-shadow:0 0 40px {glow}aa,0 18px 34px rgba(0,0,0,.6);object-fit:cover;width:37%;"
    ).format(glow=glow)
    side_subject = "left:2.5%" if layout_b else "right:2.5%"
    side_text = ("left:44%;right:4%;text-align:left" if layout_b
                 else "left:5%;right:44%;text-align:left")

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:{W}px; height:{H}px; overflow:hidden; position:relative;
         background:{bg}; font-family:'Anton','Archivo Black','DejaVu Sans',sans-serif; }}
  .halo {{ position:absolute; width:900px; height:900px; border-radius:50%;
          background:radial-gradient(circle,{glow}55 0%,transparent 62%);
          {'left:-180px' if layout_b else 'right:-180px'}; top:-160px; }}
  .grain {{ position:absolute; inset:0;
    background-image:radial-gradient(rgba(255,255,255,.05) 1px,transparent 1px);
    background-size:26px 26px; }}
  .bar {{ position:absolute; top:0; {'right:0' if layout_b else 'left:0'};
         width:14px; height:100%; background:{accent}; opacity:.9; }}
  .subject {{ position:absolute; {side_subject}; {subject_css} }}
  .txt {{ position:absolute; top:50%; transform:translateY(-50%); {side_text}; }}
  .kicker {{ display:inline-block; background:{accent}; color:#141414;
            font-size:30px; letter-spacing:2px; padding:8px 22px; border-radius:8px;
            margin-bottom:22px; box-shadow:0 8px 18px rgba(0,0,0,.4); }}
  h1 {{ color:#fff; font-size:96px; line-height:1.04; letter-spacing:1px;
       text-shadow:0 6px 0 rgba(0,0,0,.45),0 14px 30px rgba(0,0,0,.5); }}
  h1 .a {{ color:{accent}; }}
  .badge {{ position:absolute; bottom:34px; {'right:36px' if layout_b else 'left:40px'};
           background:linear-gradient(180deg,#ffe27a,#f7b733); color:#1c1206;
           font-size:34px; padding:12px 30px; border-radius:40px;
           border:4px solid #fff; box-shadow:0 10px 24px rgba(0,0,0,.5); }}
  .logo {{ position:absolute; top:26px; {'left:30px' if layout_b else 'right:30px'};
          width:104px; height:104px; border-radius:50%; border:4px solid #fff;
          box-shadow:0 8px 20px rgba(0,0,0,.5); }}
</style></head><body>
  <div class="halo"></div><div class="grain"></div><div class="bar"></div>
  {f'<img class="subject" src="{subject_uri}">' if subject_uri else ''}
  <div class="txt">
    <div class="kicker">MESSAGE PUISSANT</div>
    <h1><span class="a">{line1}</span><br>{line2}</h1>
  </div>
  <div class="badge">{html_mod.escape(cfg.channel_name.upper())}</div>
  {f'<img class="logo" src="{logo_uri}">' if logo_uri else ''}
</body></html>"""


def _render_html(html: str, out_jpg: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": W, "height": H})
            page.set_content(html)
            page.wait_for_timeout(400)  # chargement des polices
            page.screenshot(path=str(out_jpg), type="jpeg", quality=90)
            browser.close()
        return out_jpg.exists()
    except Exception as exc:
        log.error("Rendu Chrome impossible : %s", exc)
        return False


def generate_thumb(cfg: Config, db: Database, video_id: int) -> bool:
    row = db.get(video_id)
    if row is None or not row["title"]:
        return False
    src = Path(row["path"])
    if not src.exists():
        return False

    thumbs_dir = cfg.data_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    out = thumbs_dir / f"{row['name']}.jpg"

    frames = _extract_frames(str(src), row["duration_s"] or 30)
    if not frames:
        return False
    best = _best_face_frame(frames)
    subject_png = _cutout_png(best)
    # heuristique : si le détourage a échoué on reçoit un PNG opaque -> carte
    is_card = subject_png[:8] == frames[0][:8] if frames else False
    from PIL import Image
    probe_img = Image.open(io.BytesIO(subject_png))
    is_card = probe_img.mode != "RGBA" or probe_img.getchannel("A").getextrema()[0] == 255

    thumb_title = (row["thumb_title"] if "thumb_title" in row.keys() and row["thumb_title"]
                   else row["title"])
    html = _html(cfg, video_id, thumb_title, _b64(subject_png), is_card)
    if not _render_html(html, out):
        return False

    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "thumb_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN thumb_path TEXT")
        db.conn.commit()
    db.update_fields(video_id, thumb_path=str(out))
    log.info("Cover v3 générée : %s", out.name)
    return True


def thumbs_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "thumb_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN thumb_path TEXT")
        db.conn.commit()
    # Les Shorts n'ont pas besoin de cover (le flux montre la vidéo) :
    # on génère pour les vidéos longues.
    rows = db.conn.execute(
        "SELECT id FROM videos WHERE state = 'READY' AND thumb_path IS NULL "
        "AND category != 'short' ORDER BY duration_s DESC").fetchall()
    done = 0
    for r in rows:
        if limit and done >= limit:
            break
        if generate_thumb(cfg, db, r["id"]):
            done += 1
    return done

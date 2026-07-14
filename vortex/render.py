"""Habillage vidéo v4 — plein écran + textes centrés avec effets pro (Submagic).

Retour de Michel (12/07 soir) : PAS de bandes noires, PAS de vidéo réduite —
la vidéo reste PLEIN ÉCRAN et les textes apparaissent PAR-DESSUS, centrés,
avec des effets pro et des marges de sécurité loin des bords :
- accroche (5 premières secondes) : MAJUSCULES, 3 premiers mots OR + suite
  blanc, contour noir épais, fondu + zoom d'entrée, tiers haut de l'écran ;
- karaoké mot-à-mot GROS au centre-bas (~2/3 de la hauteur), mot courant VERT,
  pop à chaque groupe de mots (style Submagic/OpusClip) ;
- badges CTA rouges pulsés, centrés au-dessus du bord bas (marge 12 %) :
  ► S'ABONNER / ❤ LIKE SI TU CROIS / ★ PARTAGE À UN AMI / ✎ COMMENTE « AMEN » ;
- filigrane @handle discret en haut.

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

WHITE = r"\c&HFFFFFF&"

# ------------------------------------------------------------------ variété
# Chaque vidéo tire son propre style (couleurs, police, textes) de façon
# DÉTERMINISTE (seed = id) — demande de Michel : « toujours du nouveau,
# police, couleurs, effets » (et YouTube pénalise l'uniformité de masse).

ACCENTS = [  # hex ASS BBGGRR — accent accroche + mot karaoké
    "00D7FF",  # or
    "05FF2C",  # vert
    "FFE500",  # cyan
    "1C9FFF",  # orange
    "B369FF",  # rose
    "00E5FF",  # jaune
]
BADGE_COLORS = [  # fond du badge CTA (hex ASS BBGGRR)
    "1323E6",  # rouge YouTube
    "E66F1E",  # bleu
    "AA2490",  # violet
    "128CE6",  # orange foncé
]
FONT_POOL = ["DejaVu Sans", "Liberation Sans", "Anton", "Archivo Black"]

CTA_POOL = [
    "► S'ABONNER", "► ABONNE-TOI", "► ABONNE-TOI MAINTENANT",
    "❤ LIKE SI TU CROIS", "❤ DIS AMEN",
    "★ PARTAGE À UN AMI", "★ ENVOIE À QUELQU'UN", "★ PARTAGE CE MESSAGE",
    "✎ COMMENTE « AMEN »", "✎ TON AVIS EN COMMENTAIRE",
    "❤ SAUVEGARDE CETTE VIDÉO",
]
CTA_FINALS = ["ABONNE-TOI ✚ PARTAGE", "ABONNE-TOI ❤ MERCI", "REJOINS-NOUS ► ABONNE-TOI"]


def _variant(video_id: int) -> dict:
    """Style propre à la vidéo, stable dans le temps (seed = id)."""
    import random
    rng = random.Random(video_id * 2654435761 % 2**32)
    return {
        "accent": rng.choice(ACCENTS),
        "kara": rng.choice(ACCENTS),
        "badge_bg": rng.choice(BADGE_COLORS),
        "font": rng.choice(FONT_POOL),
        "ctas": rng.sample(CTA_POOL, 6),
        "cta_final": rng.choice(CTA_FINALS),
        "pulse_amp": rng.choice([108, 112, 116]),
        # style des captions : karaoké (groupe + mot illuminé), word-pop
        # (1-2 mots géants façon Hormozi) ou build (la ligne se construit
        # mot après mot, style machine à écrire CapCut)
        "caption_mode": rng.choice(["karaoke", "pop", "build"]),
    }


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


def _pop_events(words_file: Path, duration: float, fs_pop: int = 0) -> list[str]:
    """Style word-pop (Hormozi) : 1-2 mots géants qui apparaissent au moment
    où ils sont prononcés, avec un petit rebond d'échelle."""
    try:
        words = json.loads(words_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    i = 0
    while i < len(words):
        # regroupe 2 mots très courts, sinon 1 mot
        group = [words[i]]
        if (i + 1 < len(words) and len(words[i]["w"]) <= 4
                and words[i + 1]["s"] - words[i]["e"] < 0.25):
            group.append(words[i + 1])
        start = group[0]["s"]
        end = max(group[-1]["e"], start + 0.28)
        if i + len(group) < len(words):
            end = min(end + 0.12, words[i + len(group)]["s"])
        txt = " ".join(w["w"].upper() for w in group)
        fs_tag = f"{{\\fs{fs_pop}}}" if fs_pop else ""
        pop = r"{\fad(40,30)\t(0,110,\fscx118\fscy118)\t(110,220,\fscx100\fscy100)}"
        out.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(min(end, duration))},Karaoke,,0,0,0,,{fs_tag}{pop}{txt}")
        i += len(group)
    return out


def _build_events(words_file: Path, duration: float, max_chars: int, accent_hex: str) -> list[str]:
    """Style « build » : la ligne se construit mot après mot (machine à écrire),
    le dernier mot arrivé est en couleur d'accent."""
    try:
        words = json.loads(words_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    chunk: list[dict] = []
    chunks: list[list[dict]] = []
    for w in words:
        if chunk and sum(len(x["w"]) + 1 for x in chunk) + len(w["w"]) > max_chars:
            chunks.append(chunk)
            chunk = []
        chunk.append(w)
        if len(chunk) >= 4 or (chunk[-1]["e"] - chunk[0]["s"]) >= 2.0:
            chunks.append(chunk)
            chunk = []
    if chunk:
        chunks.append(chunk)
    accent = r"{\c&H" + accent_hex + "&}"
    white = r"{\c&HFFFFFF&}"
    for ch in chunks:
        for i in range(len(ch)):
            start = ch[i]["s"]
            end = ch[i + 1]["s"] if i + 1 < len(ch) else max(ch[i]["e"], start + 0.3)
            parts = [w["w"].upper() for w in ch[: i + 1]]
            text = white + " ".join(parts[:-1])
            text += (" " if len(parts) > 1 else "") + accent + parts[-1]
            out.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(min(end, duration))},Karaoke,,0,0,0,,{text}")
    return out


def _karaoke_events(words_file: Path, duration: float, max_chars: int) -> list[str]:
    """Chunks courts, mot courant illuminé via \\k (style Submagic).
    max_chars est calculé depuis la largeur réelle de la vidéo."""
    try:
        words = json.loads(words_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    events = []
    chunk: list[dict] = []
    for w in words:
        # un mot seul trop long part dans son propre chunk
        if chunk and sum(len(x["w"]) + 1 for x in chunk) + len(w["w"]) > max_chars:
            events.append(chunk)
            chunk = []
        chunk.append(w)
        span = chunk[-1]["e"] - chunk[0]["s"]
        if len(chunk) >= 3 or span >= 1.6:
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


def build_ass(cfg: Config, *, width: int, height: int, duration: float,
              title: str, words_file: Path | None, skip_hook: bool = False,
              lifted: bool = False, video_id: int = 0) -> str:
    v = _variant(video_id)
    fontname = v["font"] if not Path(r"C:\Windows\Fonts\arial.ttf").exists() else "Arial"
    accent = r"\c&H" + v["accent"] + "&"

    # Tailles et marges relatives à la vidéo. Retour de Michel (14/07) :
    # sous-titres PLUS PETITS et JAMAIS sur le visage. Le visage occupe la zone
    # centrale/haute — donc : sous-titres dans le tiers BAS (zone sûre), boutons
    # du haut remontés TOUT EN HAUT (au-dessus du visage), boutons du bas en bas.
    fs_hook = int(height / 22)
    fs_kara = int(height / 22)
    fs_badge = int(height / 26)
    fs_handle = int(height / 32)
    margin_lr = int(width * 0.07)
    # Largeur maximale des lignes CALCULÉE (bold uppercase ≈ 0,62 × fontsize par caractère)
    hook_chars = max(int(width * 0.84 / (fs_hook * 0.62)), 8)
    kara_chars = max(int(width * 0.84 / (fs_kara * 0.62)), 6)
    # Accroche ANCRÉE EN HAUT (bande au-dessus du visage). Avec 3 lignes max
    # partant de 5,5 %, elle se termine vers ~22 % — au-dessus du visage du
    # prédicateur (centré plus bas), donc l'accroche ET son encadré ne le
    # couvrent jamais (retour Michel 14/07).
    hook_top = int(height * 0.055)
    # Sous-titres TOUJOURS bas (≈ 12 % du bas = zone caption standard, sous le
    # visage). Badges : haut = 7 % du haut (au-dessus du visage), bas = 11 %.
    kara_bottom = int(height * 0.12)
    badge_bottom = int(height * 0.11)
    badge_top = int(height * 0.07)     # variante haute des badges — AU-DESSUS du visage
    handle_top = int(height * 0.035)
    hook_box = max(int(height / 110), 10)  # padding du fond semi-transparent DERRIÈRE L'ACCROCHE (hook)

    def badge_fs(text: str) -> int:
        """Taille auto-ajustée pour qu'un badge ne déborde JAMAIS."""
        return min(fs_badge, int(width * 0.80 / (max(len(text), 1) * 0.62)))

    hook = title.replace(" #Shorts", "").strip().upper()
    words = hook.split()
    if len(words) > 10:
        words = words[:10]
    # Retire les fragments disgracieux en fin d'accroche (tirets, attributions coupées…)
    while words and (words[-1].strip("-–—|.…") == "" or words[-1].rstrip(".…") in ("EV", "ÉV", "PST", "PASTEUR")):
        words.pop()
    if len(hook.split()) > len(words):
        words[-1] = words[-1].rstrip(",;:-") + "…"
    # Auto-ajustement (retour Michel 14/07) : l'accroche doit tenir en 3 LIGNES MAX
    # et le texte s'ÉTIRE sur toute la largeur. On réduit la police juste assez
    # pour que tout tienne en 3 lignes, sans jamais coller aux bords.
    full_hook = " ".join(words)
    longest = max((len(w) for w in words), default=8)
    # L'accroche : bien visible, LARGE MAIS PAS TROP, jamais collée aux bords
    # (retour Michel 14/07). Largeur utile 0,84. Répartie sur 1 à 3 lignes, police
    # calée pour que la ligne la plus longue occupe ~0,84.
    usable = width * 0.84
    n = len(full_hook)
    target_lines = 1 if n <= 15 else (2 if n <= 34 else 3)
    cpl = max((n + target_lines - 1) // target_lines, longest)
    hook_lines = list(_wrap(full_hook, cpl, 3))
    n_lines = max(1, len(hook_lines))
    longest_line = max((len(ln) for ln in hook_lines), default=cpl)
    fs_w = int(usable / (max(longest_line, 1) * 0.62))   # remplit la largeur
    fs_h = int(height / (7.3 * n_lines))                 # reste dans la bande haute
    fs_hook = max(int(height / 30), min(fs_w, fs_h))
    # Accroche façon OpusClip : PILULE CLAIRE + texte FONCÉ (couleur portée par le
    # style Hook). Les 3 premiers mots en accent chaud lisible sur fond clair.
    hook_accent = r"\c&H1A24C8&"     # rouge chaud (BGR) — lisible sur pilule blanche
    hook_ink = r"\c&H262626&"        # gris très foncé
    gold_chars = len(" ".join(words[:3]))
    hook_txt = "{" + hook_accent + "}"
    count = 0
    switched = False
    for line in hook_lines:
        for ch in line:
            if not switched and count >= gold_chars:
                hook_txt += "{" + hook_ink + "}"
                switched = True
            hook_txt += ch
            count += 1
        hook_txt += r"\N"
        count += 1
    hook_txt = hook_txt.rstrip(r"\N")

    handle = "@sophos_prophetikos"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{fontname},{fs_hook},&H00262626,&H00262626,&H0AF2F2F2,&H0AF2F2F2,-1,-1,0,0,100,100,0.5,0,3,{hook_box},0,8,{margin_lr},{margin_lr},{hook_top},1
Style: Karaoke,{fontname},{fs_kara},&H00{v["kara"]},&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,1,0,1,5,3,2,{margin_lr},{margin_lr},{kara_bottom},1
Style: BadgeBas,{fontname},{fs_badge},&H00FFFFFF,&H00FFFFFF,&H00{v["badge_bg"]},&H00{v["badge_bg"]},-1,0,0,0,100,100,1,0,3,{max(int(height/160), 8)},0,2,{margin_lr},{margin_lr},{badge_bottom},1
Style: BadgeHaut,{fontname},{fs_badge},&H00FFFFFF,&H00FFFFFF,&H00{v["badge_bg"]},&H00{v["badge_bg"]},-1,0,0,0,100,100,1,0,3,{max(int(height/160), 8)},0,8,{margin_lr},{margin_lr},{badge_top},1
Style: Handle,{fontname},{fs_handle},&H38FFFFFF,&H38FFFFFF,&H38000000,&H00000000,-1,-1,0,0,100,100,1,0,1,2,0,8,{margin_lr},{margin_lr},{handle_top},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    zoom_in = r"{\fad(250,300)\t(0,250,\fscx104\fscy104)\t(250,500,\fscx100\fscy100)}"
    events = [
        f"Dialogue: 0,{_ass_time(0)},{_ass_time(duration)},Handle,,0,0,0,,{handle}",
    ]
    if not skip_hook:
        # Accroche : 5 premières secondes seulement (elle recouvre la vidéo).
        # Supprimée quand la vidéo affiche déjà son message à l'écran
        # (retour de Michel : jamais deux fois le même message).
        events.append(
            f"Dialogue: 1,{_ass_time(0.2)},{_ass_time(5.2)},Hook,,0,0,0,,{zoom_in}{hook_txt}")
    # CTA agressifs ÉPARPILLÉS : 6 fenêtres à des moments ET des positions
    # variés (bas / haut en alternance), taille auto-ajustée, pulsation.
    amp = v["pulse_amp"]
    pulse = (r"{\fad(150,150)\t(0,180,\fscx" + str(amp) + r"\fscy" + str(amp) +
             r")\t(180,360,\fscx100\fscy100)}")
    for i, frac in enumerate((0.07, 0.21, 0.36, 0.51, 0.66, 0.80)):
        start = duration * frac
        # anti-superposition : jamais de badge pendant l'accroche (6 premières s)
        if not skip_hook and start < 6.0:
            start = 6.0
        end = min(start + 3.2, duration - 5.5)
        if end <= start:
            continue
        txt = v["ctas"][i % len(v["ctas"])]
        style = "BadgeBas" if i % 2 == 0 else "BadgeHaut"
        events.append(
            f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,"
            f"{{\\fs{badge_fs(txt)}}}{pulse}{txt}")
    # CTA final appuyé (5 dernières secondes, en bas)
    events.append(
        f"Dialogue: 1,{_ass_time(max(duration - 5.0, 0))},{_ass_time(duration)},BadgeBas,,0,0,0,,"
        f"{{\\fs{badge_fs(v['cta_final'])}}}{pulse}{v['cta_final']}")

    if words_file and words_file.exists():
        if v["caption_mode"] == "pop":
            events += _pop_events(words_file, duration, fs_pop=int(height / 15))
        elif v["caption_mode"] == "build":
            events += _build_events(words_file, duration, kara_chars, v["kara"])
        else:
            events += _karaoke_events(words_file, duration, kara_chars)

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

    has_text = row["has_text"] if "has_text" in row.keys() else None
    src_w, src_h = row["width"] or 576, row["height"] or 1024
    # Qualité maximale raisonnable : sortie 2K (verticale 1440x2560, horizontale
    # 2560x1440). Dès 1440p, YouTube sert un codec bien meilleur (VP9/AV1) qu'en
    # 1080p — c'est le principal levier de netteté perçue. La vraie 4K coûterait
    # des heures d'encodage par vidéo sur un serveur 2 cœurs pour un gain marginal
    # (surchargeable via cfg.render_width). Jamais de downscale.
    target_w = int(getattr(cfg, "render_width", 0)) or (1440 if src_h > src_w else 2560)
    out_w = max(src_w, target_w) // 2 * 2
    out_h = int(src_h * out_w / src_w) // 2 * 2

    # Accroche à l'écran = phrase CHOC courte (thumb_title, 4-6 mots) façon OpusClip,
    # PAS le titre YouTube long/descriptif (retour Michel 14/07 : « le texte est bad »).
    hook_text = ""
    if "thumb_title" in row.keys() and row["thumb_title"]:
        hook_text = row["thumb_title"]
    if not hook_text:
        hook_text = row["title"] or ""

    ass_file = exports / f"{row['name']}.ass"
    ass_file.write_text(
        build_ass(cfg, width=out_w, height=out_h,
                  duration=duration, title=hook_text,
                  words_file=words_file if words_file.exists() else None,
                  skip_hook=(has_text == "texte"),
                  lifted=(has_text in ("texte", "douteux")), video_id=video_id),
        encoding="utf-8")

    def _ffpath(p: str) -> str:
        return p.replace("\\", "/").replace(":", r"\:")

    # Vidéo PLEIN ÉCRAN améliorée, textes par-dessus (pas de bandes)
    vf = (
        f"scale={out_w}:{out_h}:flags=lanczos,"
        f"hqdn3d=1.5:1.5:6:6,"
        f"unsharp=5:5:0.7:5:5:0.3,"
        f"eq=contrast=1.05:saturation=1.14:brightness=0.008,"
        f"ass='{_ffpath(str(ass_file))}'"
    )
    cmd = [find_ffmpeg(), "-v", "error", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "copy", "-movflags", "+faststart", "-y", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=7200, check=True)
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

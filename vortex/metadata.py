"""Étape 5 — SEO local et gratuit : titre, description, tags, hashtags.

Sources, par ordre de priorité :
1. La légende TikTok d'origine (base 4K Tokkit) — écrite par un humain.
2. La transcription Whisper — le vrai contenu de la vidéo.

Règles (conformité YouTube) : titres fidèles au contenu, pas de promesse
mensongère, pas de bourrage de mots-clés, description honnête.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .config import Config
from .db import Database

log = logging.getLogger("vortex.metadata")

# Mots vides français (pour l'extraction de mots-clés)
STOPWORDS = set("""
le la les un une des du de d l et ou mais donc or ni car que qui quoi dont où
je tu il elle on nous vous ils elles me te se ce cette ces cet mon ton son ma
ta sa mes tes ses notre votre leur nos vos leurs y en ne pas plus moins très
est sont était sera être avoir a ai as avons avez ont fait faire dit dire va
aller peut pouvoir veut vouloir dois devoir tout tous toute toutes rien chose
alors aussi comme si dans sur sous avec sans pour par entre vers chez avant
après pendant depuis jusqu quand lorsque parce puisque afin ainsi cela ça ceci
celui celle ceux celles même mêmes autre autres quel quelle quels quelles au
aux c'est n'est j'ai d'un d'une qu'il qu'elle il-y-a là ici oui non
""".split())

# Amorces de titre variées (rotation pour éviter l'uniformité)
TITLE_LEADS = [
    "", "", "",  # le plus souvent : la phrase clé seule
    "À méditer : ",
    "Écoute bien : ",
    "Vérité puissante : ",
]

CTA_BLOCKS = [
    "👉 Abonne-toi pour ne rien manquer : de nouvelles pépites chaque jour.",
    "🔔 Active la cloche et abonne-toi pour grandir chaque jour.",
    "🙏 Si ce message t'a touché, partage-le à quelqu'un qui en a besoin.",
]


def clean_caption(caption: str | None, speakers: list[str]) -> str:
    """Nettoie la légende TikTok : retire les hashtags, les mentions d'orateurs répétées."""
    if not caption:
        return ""
    text = re.sub(r"#\S+", "", caption)
    text = text.replace("Ev. ", "")
    for name in speakers:
        text = text.replace(name, "")
    text = text.strip(" -–—:;,.")
    return re.sub(r"\s{2,}", " ", text).strip()


def first_sentences(text: str, max_len: int) -> str:
    """Prend les premières phrases entières qui tiennent dans max_len caractères."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    parts = re.split(r"(?<=[.!?…])\s+", text)
    out = ""
    for p in parts:
        if len(out) + len(p) + 1 > max_len:
            break
        out = f"{out} {p}".strip()
    if not out:  # première phrase déjà trop longue : coupe au dernier mot
        out = text[:max_len].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out


def extract_keywords(text: str, count: int) -> list[str]:
    """Extraction de mots-clés par fréquence, sans mots vides."""
    words = re.findall(r"[a-zà-öø-ÿ'’-]{4,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        w = w.strip("'’-")
        if w and w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: -kv[1])
    return [w for w, _ in ranked[:count]]


def build_title(cfg: Config, video_id: int, caption: str, transcript: str, is_short: bool) -> str:
    base = clean_caption(caption, cfg.known_speakers) or first_sentences(transcript, 80)
    if not base.strip():
        # Titre de secours : jamais de titre vide (l'API rejette) ni trompeur.
        base = f"Message de foi — {cfg.channel_name}"
    lead = TITLE_LEADS[video_id % len(TITLE_LEADS)]
    suffix = " #Shorts" if is_short else ""
    budget = cfg.max_title_len - len(lead) - len(suffix)
    title = (lead + first_sentences(base, budget) + suffix).strip()
    return title[:100]  # limite dure de l'API YouTube


def derive_thumb_title(title: str, hook: str = "") -> str:
    """Phrase choc COURTE (4-6 mots) pour l'accroche à l'écran façon OpusClip,
    dérivée localement quand l'IA n'en fournit pas. Le hook affiché ne doit
    JAMAIS être le titre long (retour Michel : « le texte de l'extrait 1 est bad »)."""
    base = (hook or title or "").strip()
    # retire une amorce du type « À méditer : » / « Écoute bien : »
    if ":" in base:
        head, tail = base.split(":", 1)
        if len(head) <= 14 and tail.strip():
            base = tail.strip()
    # coupe à la 1re ponctuation forte (garde une clause nette)
    for sep in ("!", "?", ".", ":", ";", "—", ",", "-"):
        i = base.find(sep)
        if 12 <= i <= 42:
            base = base[:i]
            break
    base = re.sub(r"\s+", " ", base).strip(" .,-—:;#")
    words = base.split()
    if len(words) > 6:
        words = words[:6]
    # évite de finir sur un mot de liaison (« … ET LES »)
    _trailing = {"et", "de", "des", "du", "la", "le", "les", "un", "une", "à",
                 "en", "ce", "qui", "que", "d", "l", "au", "aux", "ou", "ni", "pour"}
    while len(words) > 2 and words[-1].lower().strip("'") in _trailing:
        words.pop()
    base = " ".join(words)[:42].strip()
    return base.upper() if base else ""


def build_description(cfg: Config, caption: str, transcript: str, video_id: int) -> str:
    hook = clean_caption(caption, cfg.known_speakers) or first_sentences(transcript, 160)
    excerpt = first_sentences(transcript, 400)
    cta = CTA_BLOCKS[video_id % len(CTA_BLOCKS)]
    hashtags = " ".join(cfg.hashtags)
    parts = [hook]
    if excerpt and excerpt != hook:
        parts.append(f"Extrait : {excerpt}")
    parts += [f"Un message pour ta foi, sur {cfg.channel_name}.\n{cta}", hashtags]
    description = "\n\n".join(p for p in parts if p.strip())
    return description[:4900]  # marge sous la limite de 5000 octets de l'API


def build_tags(cfg: Config, caption: str, transcript: str) -> list[str]:
    tags = [cfg.channel_name, "motivation chrétienne", "foi", "prédication", "parole de Dieu"]
    tags += extract_keywords(f"{caption} {transcript}", cfg.tags_count)
    seen, out = set(), []
    for t in tags:
        low = t.lower()
        if low not in seen and len(", ".join(out + [t])) < 480:  # limite API ~500 caractères
            seen.add(low)
            out.append(t)
    return out[: cfg.tags_count + 5]


def transcript_quality(text: str) -> tuple[bool, str]:
    """Garde-fou : rejette les transcriptions vides, trop courtes ou aberrantes
    (vidéos musicales, bruit, hallucinations Whisper en caractères exotiques)."""
    text = text.strip()
    words = re.findall(r"[a-zà-öø-ÿA-ZÀ-Ö]{2,}", text)
    if len(words) < 8:
        return False, f"transcription trop pauvre ({len(words)} mots)"
    letters = sum(1 for c in text if c.isalpha() or c in " .,!?'’-…")
    if letters / max(len(text), 1) < 0.75:
        return False, "transcription aberrante (caractères non textuels majoritaires)"
    freq: dict[str, int] = {}
    for c in text.replace(" ", ""):
        freq[c] = freq.get(c, 0) + 1
    if freq and max(freq.values()) / max(len(text.replace(" ", "")), 1) > 0.4:
        return False, "transcription aberrante (caractère répété)"
    return True, ""


def prepare_video(cfg: Config, db: Database, video_id: int) -> bool:
    """TRANSCRIBED -> READY : génère titre/description/tags."""
    row = db.get(video_id)
    if row is None or row["state"] != "TRANSCRIBED":
        return False
    transcript = ""
    if row["transcript_path"] and Path(row["transcript_path"]).exists():
        transcript = Path(row["transcript_path"]).read_text(encoding="utf-8")
    if not transcript and not row["caption"]:
        db.set_state(video_id, "BLOCKED", "ni transcription ni légende exploitable")
        return False
    ok, reason = transcript_quality(transcript)
    usable_caption = clean_caption(row["caption"], cfg.known_speakers)
    if not ok and not usable_caption:
        db.set_state(video_id, "BLOCKED", f"contrôle qualité : {reason}")
        log.warning("Bloquée [%d] %s : %s", video_id, row["name"], reason)
        return False
    if not ok:
        transcript = ""  # transcription aberrante : on ne s'appuie que sur la légende

    caption = row["caption"] or ""
    is_short = row["category"] == "short"

    # Renfort IA (DeepSeek) : titres/descriptions corrigés et optimisés.
    # En cas d'échec, repli transparent sur la génération locale.
    from . import ai
    source = "locale"
    generated = None
    if ai.available():
        generated = ai.generate_metadata(
            cfg.channel_name, cfg.known_speakers, caption, transcript,
            row["duration_s"] or 0,
        )
    if generated:
        source = "deepseek"
        suffix = " #Shorts" if is_short else ""
        title = (generated["title"] + suffix)[:100]
        description = generated["description"]
        tags = generated["tags"]
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
        for col in ("thumb_title", "speaker"):
            if col not in cols:
                db.conn.execute(f"ALTER TABLE videos ADD COLUMN {col} TEXT")
                db.conn.commit()
        thumb = generated.get("thumb_title") or derive_thumb_title(title, generated.get("hook", ""))
        if thumb:
            db.update_fields(video_id, thumb_title=thumb)
        if generated.get("speaker"):
            db.update_fields(video_id, speaker=generated["speaker"])
    else:
        title = build_title(cfg, video_id, caption, transcript, is_short)
        description = build_description(cfg, caption, transcript, video_id)
        tags = build_tags(cfg, caption, transcript)
        # Repli local : garantir une accroche courte (jamais le titre long à l'écran)
        thumb = derive_thumb_title(title, clean_caption(caption, cfg.known_speakers))
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
        if "thumb_title" not in cols:
            db.conn.execute("ALTER TABLE videos ADD COLUMN thumb_title TEXT")
            db.conn.commit()
        if thumb:
            db.update_fields(video_id, thumb_title=thumb)

    db.set_state(
        video_id, "READY", f"métadonnées générées ({source})",
        title=title, description=description, tags=json.dumps(tags, ensure_ascii=False),
    )
    log.info("Prête (%s) : [%d] %s", source, video_id, title)
    return True


def prepare_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    done = 0
    for row in db.by_state("TRANSCRIBED"):
        if limit and done >= limit:
            break
        if prepare_video(cfg, db, row["id"]):
            done += 1
    return done

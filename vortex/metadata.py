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


def clean_caption(caption: str | None, author: str) -> str:
    """Nettoie la légende TikTok : retire les hashtags, les mentions d'auteur répétées."""
    if not caption:
        return ""
    text = re.sub(r"#\S+", "", caption)
    text = text.replace("Ev. ", "").replace(author, "").strip(" -–—:;,.")
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
    base = clean_caption(caption, cfg.author_name) or first_sentences(transcript, 80)
    lead = TITLE_LEADS[video_id % len(TITLE_LEADS)]
    suffix = " #Shorts" if is_short else ""
    budget = cfg.max_title_len - len(lead) - len(suffix)
    title = lead + first_sentences(base, budget) + suffix
    return title.strip()


def build_description(cfg: Config, caption: str, transcript: str, video_id: int) -> str:
    hook = clean_caption(caption, cfg.author_name) or first_sentences(transcript, 160)
    excerpt = first_sentences(transcript, 400)
    cta = CTA_BLOCKS[video_id % len(CTA_BLOCKS)]
    hashtags = " ".join(cfg.hashtags)
    return (
        f"{hook}\n\n"
        f"Extrait : {excerpt}\n\n"
        f"Un message de {cfg.author_name}.\n"
        f"{cta}\n\n"
        f"{hashtags}"
    )


def build_tags(cfg: Config, caption: str, transcript: str) -> list[str]:
    tags = [cfg.author_name, cfg.channel_name, "motivation chrétienne", "foi", "prédication"]
    tags += extract_keywords(f"{caption} {transcript}", cfg.tags_count)
    seen, out = set(), []
    for t in tags:
        low = t.lower()
        if low not in seen and len(", ".join(out + [t])) < 480:  # limite API ~500 caractères
            seen.add(low)
            out.append(t)
    return out[: cfg.tags_count + 5]


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

    caption = row["caption"] or ""
    is_short = row["category"] == "short"
    title = build_title(cfg, video_id, caption, transcript, is_short)
    description = build_description(cfg, caption, transcript, video_id)
    tags = build_tags(cfg, caption, transcript)

    db.set_state(
        video_id, "READY", "métadonnées générées",
        title=title, description=description, tags=json.dumps(tags, ensure_ascii=False),
    )
    log.info("Prête : [%d] %s", video_id, title)
    return True


def prepare_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    done = 0
    for row in db.by_state("TRANSCRIBED", limit=limit):
        if prepare_video(cfg, db, row["id"]):
            done += 1
    return done

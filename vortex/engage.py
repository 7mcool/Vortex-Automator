"""Moteur d'engagement (stratégie « viser loin » de Michel) :

1. Constate les publications effectives (SCHEDULED -> PUBLISHED quand l'heure est passée).
2. Poste un commentaire d'accroche avec une question sous chaque vidéo publiée
   (l'engagement précoce améliore la distribution par l'algorithme).
3. Répond chaleureusement aux commentaires des spectateurs (DeepSeek),
   en ignorant les trolls — jamais de débat.

Quota API : commentThreads.insert / comments.insert ≈ 50 unités chacun.
Le budget par exécution est plafonné (max_actions) pour préserver les
~1 500 unités restantes après les 5 uploads quotidiens.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone

from .config import Config
from .db import Database
from . import youtube_client

log = logging.getLogger("vortex.engage")

QUESTION_PROMPT = """Vidéo YouTube d'une chaîne de prédications chrétiennes francophones :
TITRE : {title}
DESCRIPTION : {description}

Écris UN court commentaire d'accroche (2 phrases max, ton chaleureux, 1 emoji max) que la chaîne
poste sous sa propre vidéo : une pensée qui prolonge le message + une question simple qui invite
les spectateurs à témoigner ou répondre. Réponds en JSON: {{"comment": "..."}}"""

REPLY_PROMPT = """Tu gères les commentaires de la chaîne YouTube chrétienne « {channel} ».
Un spectateur a commenté sous la vidéo « {title} » :

« {comment} »

Si ce commentaire est hostile, moqueur, hors sujet ou du spam : réponds {{"skip": true}}.
Sinon écris une réponse courte (1-2 phrases), chaleureuse et personnelle, sans prêchi-prêcha,
avec au plus 1 emoji. Jamais de débat théologique, jamais de promesse. JSON: {{"skip": false, "reply": "..."}}"""


def _deepseek_json(prompt: str) -> dict | None:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 1.1,
        "max_tokens": 200,
    }).encode()
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.load(r)
        return json.loads(resp["choices"][0]["message"]["content"])
    except Exception as exc:
        log.warning("DeepSeek engagement indisponible : %s", exc)
        return None


def _ensure_columns(db: Database) -> None:
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "seed_comment_id" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN seed_comment_id TEXT")
    db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS replied_comments (
            comment_id TEXT PRIMARY KEY,
            video_youtube_id TEXT,
            replied_at TEXT
        );
    """)
    db.conn.commit()


def mark_published(db: Database, service) -> int:
    """SCHEDULED dont l'heure est passée -> vérifie sur YouTube -> PUBLISHED."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [r for r in db.by_state("SCHEDULED") if (r["publish_at"] or "9999") <= now]
    if not rows:
        return 0
    ids = ",".join(r["youtube_id"] for r in rows if r["youtube_id"])
    statuses = {}
    if ids:
        resp = service.videos().list(part="status", id=ids).execute()
        statuses = {it["id"]: it["status"]["privacyStatus"] for it in resp.get("items", [])}
    n = 0
    for r in rows:
        if statuses.get(r["youtube_id"]) == "public":
            db.set_state(r["id"], "PUBLISHED", "publication constatée")
            n += 1
    return n


def seed_comments(cfg: Config, db: Database, service, budget: list[int]) -> int:
    """Commentaire d'accroche sous chaque vidéo PUBLISHED qui n'en a pas encore."""
    rows = db.conn.execute(
        "SELECT * FROM videos WHERE state = 'PUBLISHED' AND seed_comment_id IS NULL "
        "AND youtube_id IS NOT NULL"
    ).fetchall()
    n = 0
    for r in rows:
        if budget[0] <= 0:
            break
        gen = _deepseek_json(QUESTION_PROMPT.format(
            title=r["title"] or "", description=(r["description"] or "")[:500]))
        comment = (gen or {}).get("comment", "").strip()
        if not comment:
            comment = "🙏 Que ce message fortifie ta foi. Dis-nous en commentaire : quelle parole t'a le plus touché ?"
        try:
            resp = service.commentThreads().insert(
                part="snippet",
                body={"snippet": {
                    "videoId": r["youtube_id"],
                    "topLevelComment": {"snippet": {"textOriginal": comment[:900]}},
                }},
            ).execute()
            db.update_fields(r["id"], seed_comment_id=resp["id"])
            budget[0] -= 1
            n += 1
            log.info("Commentaire d'accroche posté sur %s", r["youtube_id"])
            time.sleep(2)
        except Exception as exc:
            log.warning("Commentaire refusé sur %s : %s", r["youtube_id"], exc)
    return n


def reply_to_comments(cfg: Config, db: Database, service, budget: list[int]) -> int:
    """Répond aux commentaires récents des spectateurs (une seule fois par commentaire)."""
    rows = db.conn.execute(
        "SELECT * FROM videos WHERE state = 'PUBLISHED' AND youtube_id IS NOT NULL "
        "ORDER BY publish_at DESC LIMIT 30"
    ).fetchall()
    n = 0
    for r in rows:
        if budget[0] <= 0:
            break
        try:
            threads = service.commentThreads().list(
                part="snippet", videoId=r["youtube_id"], maxResults=50,
                textFormat="plainText", order="time",
            ).execute()
        except Exception as exc:
            log.debug("Lecture commentaires impossible sur %s : %s", r["youtube_id"], exc)
            continue
        for th in threads.get("items", []):
            if budget[0] <= 0:
                break
            top = th["snippet"]["topLevelComment"]
            cid = top["id"]
            sn = top["snippet"]
            # Ne jamais se répondre à soi-même, ni répondre deux fois
            if sn.get("authorChannelId", {}).get("value") == th["snippet"].get("channelId"):
                continue
            if db.conn.execute("SELECT 1 FROM replied_comments WHERE comment_id = ?", (cid,)).fetchone():
                continue
            gen = _deepseek_json(REPLY_PROMPT.format(
                channel=cfg.channel_name, title=r["title"] or "",
                comment=sn.get("textDisplay", "")[:600]))
            if not gen or gen.get("skip") or not gen.get("reply"):
                db.conn.execute(
                    "INSERT OR IGNORE INTO replied_comments VALUES (?,?,?)",
                    (cid, r["youtube_id"], datetime.now(timezone.utc).isoformat()))
                db.conn.commit()
                continue
            try:
                service.comments().insert(
                    part="snippet",
                    body={"snippet": {"parentId": cid, "textOriginal": gen["reply"][:900]}},
                ).execute()
                db.conn.execute(
                    "INSERT OR IGNORE INTO replied_comments VALUES (?,?,?)",
                    (cid, r["youtube_id"], datetime.now(timezone.utc).isoformat()))
                db.conn.commit()
                budget[0] -= 1
                n += 1
                log.info("Réponse postée sur %s (commentaire %s)", r["youtube_id"], cid)
                time.sleep(2)
            except Exception as exc:
                log.warning("Réponse refusée (%s) : %s", cid, exc)
    return n


def run_engagement(cfg: Config, db: Database, max_actions: int = 20) -> dict:
    _ensure_columns(db)
    service = youtube_client.get_service(cfg)
    budget = [max_actions]
    published = mark_published(db, service)
    seeded = seed_comments(cfg, db, service, budget)
    replied = reply_to_comments(cfg, db, service, budget)
    stats = {"nouvelles_publiques": published, "accroches": seeded, "reponses": replied}
    log.info("Engagement : %s", stats)
    return stats

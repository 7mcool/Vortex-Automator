"""Orchestration : enchaîne les étapes avec DRY_RUN par défaut.

En mode simulation (par défaut), AUCUN appel YouTube n'est fait :
le plan de publication est simplement affiché.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import Config
from .db import Database
from .schedule import next_free_slots, rfc3339_utc
from . import youtube_client

log = logging.getLogger("vortex.pipeline")


def plan_batch(cfg: Config, db: Database, count: int) -> list[dict]:
    """Associe les vidéos READY aux prochains créneaux libres (sans rien envoyer)."""
    ready = db.by_state("READY", limit=count)
    slots = next_free_slots(cfg, db, len(ready))
    plan = []
    for row, slot in zip(ready, slots):
        plan.append({
            "video_id": row["id"],
            "name": row["name"],
            "title": row["title"],
            "duration_s": row["duration_s"],
            "category": row["category"],
            "cover": row["cover_path"],
            "srt": row["srt_path"],
            "publish_at_utc": rfc3339_utc(slot),
        })
    return plan


def describe_plan(db: Database, plan: list[dict]) -> str:
    lines = ["=== PLAN DE PUBLICATION (simulation) ==="]
    for p in plan:
        row = db.get(p["video_id"])
        tags = json.loads(row["tags"] or "[]")
        lines += [
            f"\n— Vidéo #{p['video_id']} : {p['name']} ({p['duration_s']}s, {p['category']})",
            f"  Titre       : {p['title']}",
            f"  Publication : {p['publish_at_utc']} (UTC)",
            f"  Miniature   : {p['cover'] or 'AUCUNE'}",
            f"  Sous-titres : {p['srt'] or 'AUCUNS'}",
            f"  Tags        : {', '.join(tags[:8])}…",
            f"  Description : {(row['description'] or '')[:150]}…",
        ]
    return "\n".join(lines)


def execute_plan(cfg: Config, db: Database, plan: list[dict], live: bool) -> None:
    """Exécute le plan. live=False -> simulation pure (affichage seulement)."""
    if not plan:
        log.info("Rien à programmer (aucune vidéo READY).")
        return
    print(describe_plan(db, plan))
    if not live:
        print("\nMode SIMULATION (par défaut) : rien n'a été envoyé à YouTube.")
        print("Relance avec --live pour uploader réellement (en privé, programmé).")
        return

    service = youtube_client.get_service(cfg)
    for p in plan:
        row = db.get(p["video_id"])
        db.set_state(p["video_id"], "UPLOADING", "upload en cours")
        try:
            youtube_id = youtube_client.upload_video(
                cfg, service,
                path=row["path"],
                title=row["title"],
                description=row["description"],
                tags=json.loads(row["tags"] or "[]"),
                publish_at_utc=p["publish_at_utc"],
                language=row["language"] or cfg.default_language,
            )
            if row["cover_path"] and Path(row["cover_path"]).exists():
                try:
                    youtube_client.set_thumbnail(service, youtube_id, row["cover_path"])
                except Exception as exc:
                    log.warning("Miniature refusée pour %s : %s", row["name"], exc)
            if row["srt_path"] and Path(row["srt_path"]).exists():
                try:
                    youtube_client.upload_captions(service, youtube_id, row["srt_path"],
                                                   row["language"] or cfg.default_language)
                except Exception as exc:
                    log.warning("Sous-titres refusés pour %s : %s", row["name"], exc)
            db.set_state(p["video_id"], "SCHEDULED",
                         f"programmé {p['publish_at_utc']}",
                         youtube_id=youtube_id, publish_at=p["publish_at_utc"])
            log.info("✔ %s -> https://youtu.be/%s (publication %s)",
                     row["name"], youtube_id, p["publish_at_utc"])
        except Exception as exc:
            log.error("✘ Upload échoué pour %s : %s", row["name"], exc)
            db.set_state(p["video_id"], "FAILED", f"upload : {exc}")


def sync_channel(cfg: Config, db: Database) -> int:
    """Récupère la liste des vidéos déjà sur la chaîne (référence anti-doublon)."""
    service = youtube_client.get_service(cfg)
    videos = youtube_client.fetch_channel_videos(service)
    for v in videos:
        db.record_channel_video(v["youtube_id"], v["title"], v["published_at"])
    log.info("%d vidéos déjà en ligne enregistrées comme référence.", len(videos))
    return len(videos)

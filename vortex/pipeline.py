"""Orchestration : enchaîne les étapes avec DRY_RUN par défaut.

En mode simulation (par défaut), AUCUN appel YouTube n'est fait :
le plan de publication est simplement affiché.

Protections en mode --live :
- réservation atomique des vidéos (deux `publish` concurrents ne se marchent pas dessus) ;
- requalification des uploads orphelins (crash pendant un upload précédent) ;
- anti-republication : comparaison avec les vidéos déjà présentes sur la chaîne ;
- créneau recalculé juste avant chaque upload (jamais de publishAt passé) ;
- quota API : un 403 quotaExceeded remet la vidéo en READY et arrête le lot.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

from .config import Config
from .db import Database
from .schedule import next_free_slots, rfc3339_utc
from . import youtube_client

log = logging.getLogger("vortex.pipeline")


# ------------------------------------------------------------ anti-republication
def _normalize(text: str) -> set[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return set(re.findall(r"[a-z0-9]{3,}", text))


def already_on_channel(db: Database, title: str, caption: str | None) -> str | None:
    """Retourne le titre déjà en ligne le plus proche si la vidéo semble déjà publiée."""
    candidate = _normalize(f"{title} {caption or ''}")
    if not candidate:
        return None
    for online_title in db.channel_titles():
        online = _normalize(online_title)
        if not online:
            continue
        overlap = len(candidate & online) / min(len(candidate), len(online))
        if overlap >= 0.7 and len(candidate & online) >= 4:
            return online_title
    return None


# ------------------------------------------------------------------------- plan
def plan_batch(cfg: Config, db: Database, count: int) -> list[dict]:
    """Associe les vidéos READY aux prochains créneaux libres (sans rien envoyer).
    Écarte (SKIPPED) les vidéos qui semblent déjà publiées sur la chaîne."""
    plan: list[dict] = []
    candidates = db.by_state("READY", limit=count * 10 or 0)
    for row in candidates:
        if len(plan) >= count:
            break
        if "render_path" in row.keys() and not row["render_path"]:
            log.info("Reportée [%d] %s — pas encore habillée (rendu manquant)",
                     row["id"], row["name"])
            continue
        match = already_on_channel(db, row["title"] or "", row["caption"])
        if match:
            db.set_state(row["id"], "SKIPPED", f"déjà sur la chaîne : « {match} »")
            log.info("Écartée [%d] %s — déjà en ligne (« %s »)", row["id"], row["name"], match)
            continue
        plan.append({
            "video_id": row["id"],
            "name": row["name"],
            "title": row["title"],
            "duration_s": row["duration_s"],
            "category": row["category"],
            "cover": row["cover_path"],
            "srt": row["srt_path"],
        })
    # Créneaux indicatifs pour l'affichage (recalculés au moment de l'upload réel)
    slots = next_free_slots(cfg, db, len(plan))
    for p, slot in zip(plan, slots):
        p["publish_at_utc"] = rfc3339_utc(slot)
    return plan


def describe_plan(db: Database, plan: list[dict]) -> str:
    lines = ["=== PLAN DE PUBLICATION ==="]
    for p in plan:
        row = db.get(p["video_id"])
        tags = json.loads(row["tags"] or "[]")
        lines += [
            f"\n— Vidéo #{p['video_id']} : {p['name']} ({p['duration_s']}s, {p['category']})",
            f"  Titre       : {p['title']}",
            f"  Publication : {p.get('publish_at_utc', '?')} (UTC)",
            f"  Miniature   : {p['cover'] or 'AUCUNE'}",
            f"  Sous-titres : {p['srt'] or 'AUCUNS'}",
            f"  Tags        : {', '.join(tags[:8])}…",
            f"  Description : {(row['description'] or '')[:150]}…",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------- execute
def _is_quota_error(err) -> bool:
    try:
        for detail in (err.error_details or []):
            if detail.get("reason") in ("quotaExceeded", "dailyLimitExceeded",
                                        "rateLimitExceeded", "uploadLimitExceeded",
                                        "userRateLimitExceeded"):
                return True
    except Exception:
        pass
    return getattr(getattr(err, "resp", None), "status", None) == 403


def execute_plan(cfg: Config, db: Database, plan: list[dict], live: bool) -> None:
    """Exécute le plan. live=False -> simulation pure (affichage seulement)."""
    if not plan:
        log.info("Rien à programmer (aucune vidéo READY éligible).")
        return
    print(describe_plan(db, plan))
    if not live:
        print("\nMode SIMULATION (par défaut) : rien n'a été envoyé à YouTube.")
        print("Relance avec --live pour uploader réellement (en privé, programmé).")
        return

    from googleapiclient.errors import HttpError

    requalified = db.requalify_stale_uploads()
    if requalified:
        log.warning("%d upload(s) orphelin(s) repassé(s) en READY.", requalified)

    service = youtube_client.get_service(cfg)

    # Référence anti-republication : synchronisation automatique si jamais faite.
    if not db.channel_titles():
        log.info("Première utilisation : synchronisation de la liste des vidéos déjà en ligne…")
        sync_channel(cfg, db, service=service)
        survivors = []
        for p in plan:
            row = db.get(p["video_id"])
            match = already_on_channel(db, row["title"] or "", row["caption"])
            if match:
                db.set_state(p["video_id"], "SKIPPED", f"déjà sur la chaîne : « {match} »")
            else:
                survivors.append(p)
        plan = survivors

    for p in plan:
        row_check = db.get(p["video_id"])
        if not Path(row_check["path"]).exists():
            log.warning("Fichier inaccessible (disque débranché ?) : %s — vidéo laissée en READY",
                        row_check["path"])
            continue
        # Créneau recalculé maintenant : jamais de publishAt déjà passé.
        slots = next_free_slots(cfg, db, 1)
        if not slots:
            log.error("Aucun créneau disponible — arrêt.")
            break
        publish_at = rfc3339_utc(slots[0])

        if not db.claim_for_upload(p["video_id"], publish_at):
            log.warning("Vidéo #%d déjà réservée par un autre processus — ignorée.", p["video_id"])
            continue
        row = db.get(p["video_id"])
        # Version habillée (Phase 2) si elle existe, sinon l'original
        upload_path = row["path"]
        if "render_path" in row.keys() and row["render_path"] and Path(row["render_path"]).exists():
            upload_path = row["render_path"]
        try:
            youtube_id = youtube_client.upload_video(
                cfg, service,
                path=upload_path,
                title=row["title"],
                description=row["description"],
                tags=json.loads(row["tags"] or "[]"),
                publish_at_utc=publish_at,
                language=row["language"] or cfg.default_language,
            )
        except HttpError as err:
            if _is_quota_error(err):
                db.set_state(p["video_id"], "READY", "quota API atteint — remis en file")
                log.error("Quota YouTube atteint : arrêt du lot (reprise demain). %s", err)
                break
            db.set_state(p["video_id"], "FAILED", f"upload : {err}")
            log.error("✘ Upload échoué pour %s : %s", row["name"], err)
            continue
        except Exception as exc:
            db.set_state(p["video_id"], "FAILED", f"upload : {exc}")
            log.error("✘ Upload échoué pour %s : %s", row["name"], exc)
            continue

        # Cover générée (style violet/or) prioritaire sur la cover TikTok
        thumb = None
        if "thumb_path" in row.keys() and row["thumb_path"] and Path(row["thumb_path"]).exists():
            thumb = row["thumb_path"]
        elif row["cover_path"] and Path(row["cover_path"]).exists():
            thumb = row["cover_path"]
        if thumb:
            try:
                youtube_client.set_thumbnail(service, youtube_id, thumb)
            except Exception as exc:
                log.warning("Miniature refusée pour %s : %s", row["name"], exc)
        if cfg.upload_captions and row["srt_path"] and Path(row["srt_path"]).exists():
            try:
                youtube_client.upload_captions(service, youtube_id, row["srt_path"],
                                               row["language"] or cfg.default_language)
            except Exception as exc:
                log.warning("Sous-titres refusés pour %s : %s", row["name"], exc)

        db.set_state(p["video_id"], "SCHEDULED", f"programmé {publish_at}",
                     youtube_id=youtube_id, publish_at=publish_at)
        log.info("OK %s -> https://youtu.be/%s (publication %s)",
                 row["name"], youtube_id, publish_at)

        # Aimant vers YouTube : republier les clips VERTICAUX sur la Page Facebook
        # avec un CTA « Sermon complet 👉 YouTube ». Derrière l'interrupteur
        # facebook_publish (voir config) pour ne pas reposter tout le backlog.
        # Sélection par ORIENTATION uniquement (correctif 17/07 : l'ancien filtre
        # basé sur le nom « tiktok »/« _short » excluait les vidéos hedjav_* — le gros
        # du contenu vertical — donc rien ne partait sur FB/IG).
        keys = row.keys()
        cat = row["category"] if "category" in keys else ""
        h = (row["height"] if "height" in keys else 0) or 0
        w = (row["width"] if "width" in keys else 0) or 0
        fb_vertical = cat in ("short", "long_vertical") or (h and w and h > w)
        if cfg.facebook_publish and fb_vertical:
            try:
                from . import facebook_client
                if facebook_client.available(cfg):
                    fb_id = facebook_client.post_video_to_page(cfg, upload_path, row["title"] or "")
                    if fb_id:
                        log.info("Facebook : clip publié (post %s) pour %s", fb_id, row["name"])
            except Exception as exc:
                log.warning("Facebook : publication ignorée (%s)", exc)

        # Aimant Instagram : Reel du même clip vertical. L'API Reels exige une URL
        # publique → on sert le clip habillé (data/exports) via la route /media du
        # dashboard. On n'essaie donc QUE si le rendu existe (l'original sur le
        # disque source n'est pas servi publiquement).
        rendered = "render_path" in keys and row["render_path"] and Path(row["render_path"]).exists()
        if cfg.instagram_publish and fb_vertical and rendered:
            try:
                from . import facebook_client
                if facebook_client.available(cfg):
                    ig_url = facebook_client.media_url(cfg, Path(row["render_path"]).name)
                    ig_id = facebook_client.post_reel_to_instagram(cfg, ig_url, row["title"] or "")
                    if ig_id:
                        log.info("Instagram : Reel publié (%s) pour %s", ig_id, row["name"])
            except Exception as exc:
                log.warning("Instagram : publication ignorée (%s)", exc)


def _rendered_clips(cfg: Config):
    """Clips verticaux DÉJÀ habillés et servables (data/exports/*_v.mp4), triés."""
    return sorted((cfg.data_dir / "exports").glob("*_v.mp4"))


def _caption_for(db: Database, clip_name: str) -> str:
    """Titre de la vidéo correspondant au fichier {name}_v.mp4, sinon défaut."""
    name = clip_name[:-2] if clip_name.endswith("_v") else clip_name
    row = db.conn.execute("SELECT title FROM videos WHERE name = ?", (name,)).fetchone()
    return (row["title"] if row and row["title"] else "Un message pour ta foi")


def publish_daily_story(cfg: Config, db: Database) -> dict | None:
    """Story du jour sur Instagram + Facebook, à partir d'un clip vertical déjà
    habillé (rotation via data/last_story.txt pour ne pas reposter le même)."""
    from . import facebook_client
    if not facebook_client.available(cfg):
        log.warning("Story : Facebook/Instagram indisponible (pas de token).")
        return None
    clips = _rendered_clips(cfg)
    if not clips:
        log.warning("Story : aucun clip habillé disponible.")
        return None
    marker = cfg.data_dir / "last_story.txt"
    last = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    names = [c.name for c in clips]
    idx = (names.index(last) + 1) % len(clips) if last in names else 0
    pick = clips[idx]
    res = facebook_client.post_story_both(cfg, str(pick))
    marker.write_text(pick.name, encoding="utf-8")
    log.info("Story : %s → Instagram=%s Facebook=%s", pick.name,
             res.get("instagram"), res.get("facebook"))
    return res


def backfill_social(cfg: Config, db: Database, count: int = 12) -> int:
    """Poste un lot de clips déjà habillés sur la Page Facebook + en Reel Instagram,
    pour PEUPLER les réseaux (les pages étaient vides). Mémorise ce qui est fait
    (data/backfill_done.txt) pour ne pas reposter les mêmes."""
    from . import facebook_client
    if not facebook_client.available(cfg):
        log.warning("Backfill : Facebook/Instagram indisponible.")
        return 0
    marker = cfg.data_dir / "backfill_done.txt"
    done = set(marker.read_text(encoding="utf-8").splitlines()) if marker.exists() else set()
    todo = [c for c in _rendered_clips(cfg) if c.name not in done][:count]
    posted = 0
    for c in todo:
        caption = _caption_for(db, c.stem)
        try:
            fb_id = facebook_client.post_video_to_page(cfg, str(c), caption)
            ig_url = facebook_client.media_url(cfg, c.name)
            ig_id = facebook_client.post_reel_to_instagram(cfg, ig_url, caption)
            log.info("Backfill : %s → Facebook=%s Instagram=%s", c.name, fb_id, ig_id)
            if fb_id or ig_id:
                posted += 1
            done.add(c.name)
        except Exception as exc:
            log.warning("Backfill : %s ignoré (%s)", c.name, exc)
    marker.write_text("\n".join(sorted(done)), encoding="utf-8")
    return posted


def retry_failed(db: Database) -> int:
    """Remet les FAILED dans le circuit, à l'étape où ils avaient échoué."""
    rows = db.by_state("FAILED")
    for r in rows:
        if r["title"]:
            target = "READY"
        elif r["transcript_path"]:
            target = "TRANSCRIBED"
        else:
            target = "DISCOVERED"
        db.set_state(r["id"], target, "nouvelle tentative demandée")
    return len(rows)


def sync_channel(cfg: Config, db: Database, service=None) -> int:
    """Récupère la liste des vidéos déjà sur la chaîne (référence anti-doublon)."""
    if service is None:
        service = youtube_client.get_service(cfg)
    videos = youtube_client.fetch_channel_videos(service)
    for v in videos:
        db.record_channel_video(v["youtube_id"], v["title"], v["published_at"])
    log.info("%d vidéos déjà en ligne enregistrées comme référence.", len(videos))
    return len(videos)

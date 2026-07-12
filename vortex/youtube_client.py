"""Étape 10 — client YouTube officiel (OAuth + upload résumable + miniature + sous-titres).

- OAuth Desktop (client_secret.json local, token stocké dans secrets/, jamais commité).
- Scopes minimaux : upload + force-ssl (miniatures et sous-titres).
- Upload en PRIVÉ avec date de publication programmée (publishAt, UTC).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .config import Config

log = logging.getLogger("vortex.youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def get_service(cfg: Config):
    """Service YouTube authentifié. Ouvre le navigateur au premier lancement."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if cfg.token_file.exists():
        creds = Credentials.from_authorized_user_file(str(cfg.token_file), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            log.warning("Rafraîchissement du token impossible (%s) — nouvelle autorisation", exc)
            creds = None
    if not creds or not creds.valid:
        if not cfg.client_secret_file.exists():
            raise FileNotFoundError(f"client_secret.json introuvable : {cfg.client_secret_file}")
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secret_file), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
        cfg.token_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.token_file.write_text(creds.to_json(), encoding="utf-8")
        log.info("Token OAuth enregistré dans %s", cfg.token_file)
    return build("youtube", "v3", credentials=creds)


def upload_video(cfg: Config, service, *, path: str, title: str, description: str,
                 tags: list[str], publish_at_utc: str, language: str = "fr") -> str:
    """Upload résumable en privé + programmation. Retourne l'ID YouTube."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": cfg.category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_utc,
            "selfDeclaredMadeForKids": cfg.made_for_kids,
        },
    }
    media = MediaFileUpload(path, chunksize=8 * 1024 * 1024, resumable=True)
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=cfg.notify_subscribers,
    )
    import socket
    import ssl

    response = None
    retries = 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as err:
            if err.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                wait = 2 ** retries
                log.warning("Erreur %s, nouvel essai dans %ss", err.resp.status, wait)
                time.sleep(wait)
            else:
                raise
        except (ConnectionError, socket.timeout, ssl.SSLError, OSError) as err:
            # Coupure réseau passagère : l'upload résumable reprend où il en était.
            if retries < 5:
                retries += 1
                wait = 2 ** retries
                log.warning("Erreur réseau (%s), reprise dans %ss", err, wait)
                time.sleep(wait)
            else:
                raise
    return response["id"]


def set_thumbnail(service, youtube_id: str, thumbnail_path: str) -> None:
    from googleapiclient.http import MediaFileUpload

    service.thumbnails().set(
        videoId=youtube_id,
        media_body=MediaFileUpload(thumbnail_path),
    ).execute()


def upload_captions(service, youtube_id: str, srt_path: str, language: str = "fr") -> None:
    from googleapiclient.http import MediaFileUpload

    service.captions().insert(
        part="snippet",
        body={"snippet": {"videoId": youtube_id, "language": language,
                          "name": "Sous-titres", "isDraft": False}},
        media_body=MediaFileUpload(srt_path, mimetype="application/octet-stream"),
    ).execute()


def fetch_channel_videos(service) -> list[dict]:
    """Liste les vidéos déjà présentes sur la chaîne (anti-republication)."""
    channels = service.channels().list(part="contentDetails", mine=True).execute()
    items = channels.get("items", [])
    if not items:
        return []
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    videos, page_token = [], None
    while True:
        resp = service.playlistItems().list(
            part="snippet", playlistId=uploads_playlist, maxResults=50, pageToken=page_token
        ).execute()
        for it in resp.get("items", []):
            sn = it["snippet"]
            videos.append({
                "youtube_id": sn["resourceId"]["videoId"],
                "title": sn["title"],
                "published_at": sn.get("publishedAt", ""),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return videos

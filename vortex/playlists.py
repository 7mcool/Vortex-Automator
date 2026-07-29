"""Classement des extraits en playlists YouTube, par événement.

Une conférence ou une série de soirées produit des dizaines d'extraits. Sans
regroupement, ils se noient dans la chaîne. Chaque événement reçoit donc sa
playlist (« Conférence Sophos 2026 »), et chaque extrait y est ajouté après
son envoi.

Les identifiants de playlist sont mémorisés en base : sans cela, chaque
passage rechercherait la playlist à coups d'appels API, et le quota
quotidien — déjà largement consommé par les envois de vidéos — n'y
résisterait pas.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .db import Database

log = logging.getLogger("vortex.playlists")


def _ensure_table(db: Database) -> None:
    db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS playlists (
            nom TEXT PRIMARY KEY,
            playlist_id TEXT NOT NULL,
            cree_le TEXT
        );
    """)
    db.conn.commit()


def evenement_de(chemin: str | None) -> str:
    """Nom de l'événement écrit par le découpeur dans le sidecar de l'extrait."""
    if not chemin:
        return ""
    try:
        sidecar = Path(chemin).with_suffix(".info.json")
        if not sidecar.exists():
            return ""
        return str(json.loads(sidecar.read_text(encoding="utf-8")).get("evenement", "")).strip()
    except (OSError, ValueError):
        return ""


def _chercher_en_ligne(service, nom: str) -> str:
    """Playlist existante portant ce titre, sur la chaîne authentifiée."""
    jeton = None
    while True:
        reponse = service.playlists().list(
            part="snippet", mine=True, maxResults=50, pageToken=jeton,
        ).execute()
        for item in reponse.get("items", []):
            if item["snippet"]["title"].strip().lower() == nom.strip().lower():
                return item["id"]
        jeton = reponse.get("nextPageToken")
        if not jeton:
            return ""


def playlist_pour(db: Database, service, nom: str, description: str = "") -> str:
    """Identifiant de la playlist de cet événement, créée au besoin."""
    if not nom:
        return ""
    _ensure_table(db)
    ligne = db.conn.execute(
        "SELECT playlist_id FROM playlists WHERE nom = ?", (nom,)
    ).fetchone()
    if ligne:
        return ligne["playlist_id"]

    # Une playlist peut exister sur la chaîne sans être en base (créée à la
    # main, ou base repartie de zéro) : la retrouver évite un doublon.
    playlist_id = _chercher_en_ligne(service, nom)
    if not playlist_id:
        reponse = service.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": nom[:150],
                            "description": description[:5000] or nom},
                "status": {"privacyStatus": "public"},
            },
        ).execute()
        playlist_id = reponse["id"]
        log.info("Playlist créée : %s (%s)", nom, playlist_id)

    db.conn.execute(
        "INSERT OR REPLACE INTO playlists VALUES (?, ?, datetime('now'))",
        (nom, playlist_id),
    )
    db.conn.commit()
    return playlist_id


def ajouter(service, playlist_id: str, youtube_id: str) -> bool:
    if not playlist_id or not youtube_id:
        return False
    try:
        service.playlistItems().insert(
            part="snippet",
            body={"snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": youtube_id},
            }},
        ).execute()
        return True
    except Exception as exc:
        log.warning("Ajout à la playlist refusé (%s) : %s", youtube_id, exc)
        return False


def classer(db: Database, service, chemin_source: str | None, youtube_id: str) -> str:
    """Range une vidéo fraîchement envoyée dans la playlist de son événement.

    Renvoie le nom de la playlist, ou une chaîne vide si l'extrait
    n'appartient à aucun événement.
    """
    nom = evenement_de(chemin_source)
    if not nom:
        return ""
    try:
        playlist_id = playlist_pour(db, service, nom)
    except Exception as exc:
        log.warning("Playlist « %s » indisponible : %s", nom, exc)
        return ""
    return nom if ajouter(service, playlist_id, youtube_id) else ""

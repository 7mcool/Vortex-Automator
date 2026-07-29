"""Enregistre chaque jour les vues de chaque video publiee.

L'API ne donne que le compteur du moment. Sans historique, impossible de
comparer deux cadences de publication : une video d'hier a forcement moins de
vues qu'une video de la semaine derniere, et une video ancienne a une vitesse
moyenne forcement plus basse. Les deux mesures se contredisent, et aucune ne
tranche.

Ce releve quotidien construit la donnee qui manque : les vues de chaque video
A UN AGE DONNE. Au bout de deux semaines, comparer « les videos a trois jours
selon la cadence du jour de publication » devient possible, et la question de
la frequence se decide sur des faits.

    python3 /app/vps/releve_vues.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from vortex.config import load_config   # noqa: E402
from vortex import youtube_client       # noqa: E402

DB = Path("/app/data/vortex.db")


def _table(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS releve_vues (
            youtube_id TEXT NOT NULL,
            releve_le  TEXT NOT NULL,
            age_jours  REAL,
            vues       INTEGER,
            likes      INTEGER,
            commentaires INTEGER,
            PRIMARY KEY (youtube_id, releve_le)
        );
    """)
    db.commit()


def main() -> None:
    cfg = load_config()
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    _table(db)

    lignes = db.execute(
        "SELECT youtube_id FROM videos WHERE state = 'PUBLISHED' "
        "AND youtube_id IS NOT NULL AND youtube_id != ''"
    ).fetchall()
    if not lignes:
        print("Aucune vidéo publiée.")
        return

    service = youtube_client.get_service(cfg)
    identifiants = [r["youtube_id"] for r in lignes]
    aujourdhui = datetime.now(timezone.utc)
    jour = aujourdhui.date().isoformat()
    enregistres = 0

    for debut in range(0, len(identifiants), 50):
        lot = identifiants[debut:debut + 50]
        reponse = service.videos().list(
            part="statistics,snippet", id=",".join(lot)
        ).execute()
        for item in reponse.get("items", []):
            s = item.get("statistics", {})
            publiee_txt = item["snippet"].get("publishedAt", "")
            try:
                publiee = datetime.fromisoformat(publiee_txt.replace("Z", "+00:00"))
                age = (aujourdhui - publiee).total_seconds() / 86400
            except ValueError:
                age = None
            db.execute(
                "INSERT OR REPLACE INTO releve_vues VALUES (?, ?, ?, ?, ?, ?)",
                (item["id"], jour, age,
                 int(s.get("viewCount", 0)), int(s.get("likeCount", 0)),
                 int(s.get("commentCount", 0))),
            )
            enregistres += 1
    db.commit()

    total = db.execute("SELECT COUNT(DISTINCT releve_le) FROM releve_vues").fetchone()[0]
    db.close()
    print(f"{enregistres} vidéo(s) relevée(s) — {total} jour(s) d'historique")


if __name__ == "__main__":
    main()

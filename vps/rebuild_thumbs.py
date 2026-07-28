"""Refait la miniature de videos designees, quel que soit leur etat.

`vortex thumbs` ne traite que les videos en etat READY. Une video deja
programmee ou publiee garde donc sa miniature meme apres un rejet. Ce script
permet de la refaire sans toucher a l'etat de publication.

    python3 /app/vps/rebuild_thumbs.py <nom> [nom ...]
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from vortex.config import load_config   # noqa: E402
from vortex.db import Database          # noqa: E402
from vortex.thumbs import generate_thumb  # noqa: E402


def main() -> None:
    noms = sys.argv[1:]
    if not noms:
        print("usage : rebuild_thumbs.py <nom> [nom ...]")
        return

    cfg = load_config()
    db = Database(cfg.db_file)
    marques = ",".join("?" * len(noms))
    rows = db.conn.execute(
        f"SELECT id, name, thumb_path FROM videos WHERE name IN ({marques})", noms
    ).fetchall()

    refaites = 0
    for row in rows:
        # L'ancienne image part avant le rendu : en cas d'echec, l'absence de
        # miniature est visible plutot que masquee par la version rejetee.
        if row["thumb_path"]:
            try:
                os.remove(row["thumb_path"])
            except OSError:
                pass
            db.update_fields(row["id"], thumb_path=None)
        if generate_thumb(cfg, db, row["id"]):
            refaites += 1
        else:
            print(f"  echec : {row['name']}")

    manquants = set(noms) - {r["name"] for r in rows}
    for nom in sorted(manquants):
        print(f"  inconnu : {nom}")
    print(f"{refaites}/{len(noms)} miniature(s) refaite(s)")


if __name__ == "__main__":
    main()

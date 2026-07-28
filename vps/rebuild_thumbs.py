"""Refait la miniature de videos designees, quel que soit leur etat.

`vortex thumbs` ne traite que les videos en etat READY. Une video deja
programmee ou publiee garde donc sa miniature meme apres un rejet. Ce script
permet de la refaire sans toucher a l'etat de publication.

    python3 /app/vps/rebuild_thumbs.py <nom> [nom ...]
    python3 /app/vps/rebuild_thumbs.py --anciennes [nombre]

Le second mode reprend les miniatures restees a l'ancienne definition
(1280x720). Pour une video deja en ligne, refaire l'image ne suffit pas : il
faut ensuite la reposer avec `push_thumbs.py`.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from vortex.config import load_config     # noqa: E402
from vortex.db import Database            # noqa: E402
from vortex.thumbs import generate_thumb, valid_thumbnail  # noqa: E402


def _anciennes(db: Database, limite: int):
    """Videos dont la miniature n'est pas a la generation actuelle."""
    rows = db.conn.execute(
        "SELECT id, name, thumb_path FROM videos WHERE thumb_path IS NOT NULL "
        "ORDER BY rowid DESC"
    ).fetchall()
    return [r for r in rows if not valid_thumbnail(r["thumb_path"])][:limite]


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("usage : rebuild_thumbs.py <nom> [nom ...] | --anciennes [nombre]")
        return

    cfg = load_config()
    db = Database(cfg.db_file)

    if args[0] == "--anciennes":
        limite = int(args[1]) if len(args) > 1 else 10
        rows = _anciennes(db, limite)
        noms = [r["name"] for r in rows]
        print(f"{len(rows)} miniature(s) a refaire")
    else:
        noms = args
        marques = ",".join("?" * len(noms))
        rows = db.conn.execute(
            f"SELECT id, name, thumb_path FROM videos WHERE name IN ({marques})", noms
        ).fetchall()

    # La trace d'envoi doit repartir a zero : une miniature refaite n'est plus
    # celle qui est en ligne sur YouTube.
    colonnes = {r[1] for r in db.conn.execute("PRAGMA table_info(videos)")}
    suit_les_envois = "thumb_pushed_at" in colonnes

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
            if suit_les_envois:
                db.conn.execute(
                    "UPDATE videos SET thumb_pushed_at = NULL WHERE id = ?",
                    (row["id"],),
                )
                db.conn.commit()
        else:
            print(f"  echec : {row['name']}")

    manquants = set(noms) - {r["name"] for r in rows}
    for nom in sorted(manquants):
        print(f"  inconnu : {nom}")
    print(f"{refaites}/{len(noms)} miniature(s) refaite(s)")


if __name__ == "__main__":
    main()

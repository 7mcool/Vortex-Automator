"""Renvoie sur YouTube les miniatures refaites des videos deja en ligne.

Regenerer une miniature en local ne change rien sur YouTube : il faut la
reposer via l'API. Ce script traite les videos deja publiees ou programmees
dont la miniature locale est a la generation actuelle (UHD) mais n'a jamais
ete reposee.

Le quota YouTube est la contrainte : `thumbnails.set` coute 50 unites, un
upload de video en coute 1600. Le budget quotidien est de 10 000 unites et la
publication des cinq videos du jour en consomme environ 8 250. La limite par
defaut reste donc basse pour ne jamais faire echouer les publications, qui
sont prioritaires.

    python3 /app/vps/push_thumbs.py [nombre]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from vortex import youtube_client          # noqa: E402
from vortex.config import load_config      # noqa: E402
from vortex.thumbs import valid_thumbnail  # noqa: E402

DB = Path("/app/data/vortex.db")
LIMITE_PAR_DEFAUT = 12   # 12 x 50 = 600 unites, marge confortable


def _colonnes(db: sqlite3.Connection) -> set[str]:
    return {r[1] for r in db.execute("PRAGMA table_info(videos)")}


def main() -> None:
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else LIMITE_PAR_DEFAUT

    cfg = load_config()
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    # Trace des envois : sans elle, chaque passage reposerait les memes
    # miniatures et brulerait le quota sans rien changer.
    if "thumb_pushed_at" not in _colonnes(db):
        db.execute("ALTER TABLE videos ADD COLUMN thumb_pushed_at TEXT")
        db.commit()

    rows = db.execute(
        "SELECT id, name, youtube_id, thumb_path FROM videos "
        "WHERE state IN ('PUBLISHED','SCHEDULED') "
        "AND youtube_id IS NOT NULL AND youtube_id != '' "
        "AND thumb_path IS NOT NULL "
        "AND thumb_pushed_at IS NULL "
        "ORDER BY rowid DESC"
    ).fetchall()

    service = None
    envoyees = ignorees = 0
    for row in rows:
        if envoyees >= limite:
            break
        # Seule la generation actuelle merite de consommer du quota.
        if not valid_thumbnail(row["thumb_path"]):
            ignorees += 1
            continue
        if service is None:
            service = youtube_client.get_service(cfg)
        try:
            youtube_client.set_thumbnail(service, row["youtube_id"], row["thumb_path"])
        except Exception as exc:
            print(f"  refus {row['name']} : {exc}")
            # Un quota epuise touche tout le reste : inutile d'insister.
            if "quota" in str(exc).lower():
                print("  quota YouTube atteint — arret")
                break
            continue
        db.execute(
            "UPDATE videos SET thumb_pushed_at = datetime('now') WHERE id = ?",
            (row["id"],),
        )
        db.commit()
        envoyees += 1
        print(f"  {row['name']} -> https://youtu.be/{row['youtube_id']}")

    db.close()
    print(
        f"{envoyees} miniature(s) reposee(s) sur YouTube "
        f"({envoyees * 50} unites de quota) — "
        f"{ignorees} ignoree(s), pas encore en UHD"
    )


if __name__ == "__main__":
    main()

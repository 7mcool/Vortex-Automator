"""Regenere l'accroche et l'ambiance visuelle des miniatures, sans toucher au reste.

Le prompt d'accroche a ete durci apres le retour de Michel du 24/07 (« hook pas
attirant, fond incoherent »). Les videos deja preparees gardent pourtant leur
ancienne accroche : ce script rejoue uniquement cette partie.

Il ne modifie ni le titre, ni la description, ni les tags : une video deja en
ligne garderait son referencement YouTube intact. La miniature correspondante
est effacee pour que `vortex thumbs` la refasse au passage suivant.

    python3 /app/vps/refresh_hooks.py [nombre] [nom ...]
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from vortex import ai                      # noqa: E402
from vortex.config import load_config      # noqa: E402
from vortex.metadata import (              # noqa: E402
    clean_caption,
    derive_thumb_title,
)

DB = Path("/app/data/vortex.db")


def _colonnes(db: sqlite3.Connection) -> set[str]:
    return {r[1] for r in db.execute("PRAGMA table_info(videos)")}


def _cibles(db: sqlite3.Connection, limite: int, noms: list[str]):
    if noms:
        marques = ",".join("?" * len(noms))
        return db.execute(
            f"SELECT * FROM videos WHERE name IN ({marques})", noms
        ).fetchall()
    # Sans nom explicite : les videos dont l'ambiance n'a jamais ete calculee.
    return db.execute(
        "SELECT * FROM videos "
        "WHERE state IN ('READY','SCHEDULED','PUBLISHED') "
        "AND (thumb_theme IS NULL OR thumb_theme = '') "
        "ORDER BY rowid DESC LIMIT ?",
        (limite,),
    ).fetchall()


def main() -> None:
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    noms = sys.argv[2:]

    # load_config() peuple os.environ depuis .env : la cle DeepSeek n'existe
    # pas avant cet appel.
    cfg = load_config()
    if not ai.available():
        print("DEEPSEEK_API_KEY absente — rien a faire")
        return

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    for colonne in ("thumb_title", "thumb_theme"):
        if colonne not in _colonnes(db):
            db.execute(f"ALTER TABLE videos ADD COLUMN {colonne} TEXT")
            db.commit()

    traitees = 0
    for row in _cibles(db, limite, noms):
        transcript = ""
        chemin = row["transcript_path"]
        if chemin and Path(chemin).exists():
            transcript = Path(chemin).read_text(encoding="utf-8")
        caption = row["caption"] or ""
        if not transcript and not caption:
            print(f"  ignoree (aucun texte) : {row['name']}")
            continue

        genere = ai.generate_metadata(
            cfg.channel_name, cfg.known_speakers, caption, transcript,
            row["duration_s"] or 0,
        )
        if not genere:
            print(f"  IA indisponible : {row['name']}")
            continue

        accroche = genere.get("thumb_title") or derive_thumb_title(
            row["title"] or "", genere.get("hook", "")
        )
        if not accroche:
            accroche = derive_thumb_title(
                clean_caption(caption, cfg.known_speakers) or row["title"] or ""
            )
        theme = genere.get("thumb_theme") or ""
        if not accroche and not theme:
            print(f"  rien d'exploitable : {row['name']}")
            continue

        db.execute(
            "UPDATE videos SET thumb_title = ?, thumb_theme = ?, thumb_path = NULL "
            "WHERE id = ?",
            (accroche or row["thumb_title"], theme, row["id"]),
        )
        db.commit()
        # La miniature devenue obsolete est retiree du disque.
        if row["thumb_path"]:
            try:
                os.remove(row["thumb_path"])
            except OSError:
                pass
        traitees += 1
        print(f"  {row['name']}\n      accroche : {accroche!r}  ambiance : {theme!r}")

    db.close()
    print(f"{traitees} accroche(s) regeneree(s) — relancer `vortex thumbs`")


if __name__ == "__main__":
    main()

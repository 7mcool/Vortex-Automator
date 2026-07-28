"""Supprime les fichiers video devenus inutiles, a l'interieur du conteneur.

Trois familles de fichiers sont concernees :

1. `data/exports/<nom>_v.mp4` : la version habillee. Elle a servi a l'upload
   YouTube et aux posts Facebook/Instagram ; une fois la video PUBLISHED ou
   SCHEDULED, le fichier local ne sert plus a rien.
2. `videos/sources/<chaine>/<sermon>.mp4` : le sermon d'origine. Des que
   `clip_sources` indique qu'il a produit au moins un extrait, la source
   (souvent 0,5-2 Go) est inutile.
3. `videos/hedjav/<nom>.mp4` : le TikTok d'origine, une fois la video en ligne.
   La suppression exige un `youtube_id` : sans preuve que l'upload a reussi, on
   garde le fichier, sinon un echec silencieux deviendrait irreversible.

Jamais touche : `videos/tiktok_queue` (file en attente de l'approbation TikTok),
les rendus dont la video n'est pas encore en ligne, les transcriptions, les
assets et la base.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path("/app/data/vortex.db")
EXPORTS = Path("/app/data/exports")
SOURCES = Path("/app/videos/sources")
HEDJAV = Path("/app/videos/hedjav")
DONE_STATES = ("PUBLISHED", "SCHEDULED")


def _mib(size: int) -> int:
    return size // (1024 * 1024)


def _drop(path: Path) -> int:
    """Supprime un fichier et renvoie l'espace libere (0 si echec)."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    try:
        path.unlink()
    except OSError as exc:
        print(f"  echec {path.name} : {exc}")
        return 0
    return size


def clean_exports(db: sqlite3.Connection) -> tuple[int, int]:
    """Rendus des videos deja en ligne."""
    if not EXPORTS.is_dir():
        return 0, 0
    freed = count = 0
    for mp4 in sorted(EXPORTS.glob("*_v.mp4")):
        name = mp4.stem[:-2]  # retire le suffixe _v
        row = db.execute(
            "SELECT state FROM videos WHERE name = ?", (name,)
        ).fetchone()
        if row is None or row["state"] not in DONE_STATES:
            continue
        size = _drop(mp4)
        if size:
            freed += size
            count += 1
            print(f"  export {mp4.name} ({_mib(size)} Mio, {row['state']})")
    return freed, count


def clean_sources(db: sqlite3.Connection) -> tuple[int, int]:
    """Sermons dont les extraits sont deja produits."""
    if not SOURCES.is_dir():
        return 0, 0
    clipped = {
        row["path"]
        for row in db.execute(
            "SELECT path FROM clip_sources WHERE clips_count > 0"
        )
    }
    freed = count = 0
    for mp4 in sorted(SOURCES.glob("*/*.mp4")):
        if str(mp4) not in clipped:
            continue
        size = _drop(mp4)
        if size:
            freed += size
            count += 1
            print(f"  source {mp4.name} ({_mib(size)} Mio)")
        # Le sidecar de metadonnees n'a plus d'utilite sans sa video.
        mp4.with_suffix(".info.json").unlink(missing_ok=True)
    return freed, count


def clean_originals(db: sqlite3.Connection) -> tuple[int, int]:
    """TikTok d'origine des videos deja en ligne sur YouTube.

    `youtube_id` sert de preuve d'upload : tant qu'il est vide, l'original
    reste sur le disque pour permettre une reprise.
    """
    if not HEDJAV.is_dir():
        return 0, 0
    freed = count = 0
    rows = db.execute(
        "SELECT path FROM videos "
        "WHERE state IN (?, ?) AND youtube_id IS NOT NULL AND youtube_id != ''",
        DONE_STATES,
    ).fetchall()
    for row in rows:
        original = Path(row["path"])
        # Ne jamais sortir du dossier des originaux TikTok.
        if HEDJAV not in original.parents or not original.is_file():
            continue
        size = _drop(original)
        if size:
            freed += size
            count += 1
            print(f"  original {original.name} ({_mib(size)} Mio)")
    return freed, count


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        exports_freed, exports_n = clean_exports(db)
        sources_freed, sources_n = clean_sources(db)
        originals_freed, originals_n = clean_originals(db)
    finally:
        db.close()

    total = exports_freed + sources_freed + originals_freed
    print(
        f"Libere : {_mib(total)} Mio "
        f"({exports_n} rendu(s), {sources_n} source(s), "
        f"{originals_n} original(aux))"
    )


if __name__ == "__main__":
    main()

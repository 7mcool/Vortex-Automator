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
import time
from pathlib import Path

DB = Path("/app/data/vortex.db")
EXPORTS = Path("/app/data/exports")
SOURCES = Path("/app/videos/sources")
HEDJAV = Path("/app/videos/hedjav")
TIKTOK = Path("/app/videos/tiktok_queue")
DONE_STATES = ("PUBLISHED", "SCHEDULED")
# La file TikTok n'a aucune sortie tant que l'API n'est pas approuvee : elle
# grossit d'un vertical par extrait, indefiniment. On la borne en gardant les
# plus recents, qui sont ceux qu'on publierait en premier.
TIKTOK_BUDGET = 2 * 1024 ** 3   # 2 Gio
# Un .part inactif depuis six heures n'appartient plus a aucun telechargement :
# yt-dlp ecrit en continu, et le pipeline lui-meme ne dure jamais aussi longtemps
# sans toucher a son fichier.
AGE_ABANDON = 6 * 3600


def _mib(size: int) -> int:
    return size // (1024 * 1024)


def _drop(path: Path) -> int:
    """Supprime un fichier et renvoie l'espace REELLEMENT libere.

    Un fichier partage par un lien dur ne libere rien tant que l'autre nom
    existe : le compter fausserait le bilan et ferait croire le menage
    efficace alors que le disque n'a pas bouge.
    """
    try:
        infos = path.stat()
    except OSError:
        return 0
    size = 0 if infos.st_nlink > 1 else infos.st_size
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
        if not mp4.exists():
            continue
        size = _drop(mp4)
        if not mp4.exists():
            freed += size
            count += 1
            print(f"  source {mp4.name} ({_mib(size)} Mio)")
            # Le sidecar ne part qu'avec sa video : le garder seul empecherait
            # de savoir quoi retelecharger si la suppression avait echoue.
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


def clean_avortes() -> tuple[int, int]:
    """Restes de telechargements ABANDONNES : .part et .ytdl.

    Un yt-dlp vivant reecrit son .part en permanence. Toucher un fichier
    encore actif serait desastreux : sous Linux l'inode reste ouvert, donc
    aucun octet n'est rendu, et le renommage final echoue — le sermon est
    perdu et retelecharge au passage suivant. L'age depuis la derniere
    ecriture distingue de facon fiable l'abandon du travail en cours.
    """
    freed = count = 0
    maintenant = time.time()
    for dossier in (SOURCES, HEDJAV):
        if not dossier.is_dir():
            continue
        for motif in ("*/*.part", "*.part", "*/*.ytdl", "*.ytdl"):
            for reste in dossier.glob(motif):
                try:
                    inactif = maintenant - reste.stat().st_mtime
                except OSError:
                    continue
                if inactif < AGE_ABANDON:
                    continue
                size = _drop(reste)
                if size:
                    freed += size
                    count += 1
                    print(f"  avorte {reste.name} ({_mib(size)} Mio)")
    return freed, count


def clean_tiktok(db: sqlite3.Connection) -> tuple[int, int]:
    """Borne la file TikTok, sans jamais detruire un exemplaire unique.

    L'API TikTok n'est pas approuvee : rien ne vide ce dossier, qui grossit
    d'un vertical par extrait. Mais le sermon d'origine est efface des qu'il
    est decoupe : un vertical peut donc etre le SEUL exemplaire de ce
    passage. On ne supprime donc que ce qui est deja en ligne sur YouTube,
    et seulement au-dela du budget.
    """
    if not TIKTOK.is_dir():
        return 0, 0

    candidats = []
    for clip in TIKTOK.glob("*.mp4"):
        try:
            infos = clip.stat()
        except OSError:
            continue
        # Le nom de la video en base est le radical, sans le suffixe _tiktok.
        nom = clip.stem[:-7] if clip.stem.endswith("_tiktok") else clip.stem
        ligne = db.execute(
            "SELECT state FROM videos WHERE name = ?", (nom,)
        ).fetchone()
        remplacable = ligne is not None and ligne["state"] in DONE_STATES
        candidats.append((infos.st_mtime, infos.st_size, clip, remplacable))

    candidats.sort(reverse=True)          # les plus recents sont gardes
    cumul = freed = count = 0
    for _, taille, clip, remplacable in candidats:
        if cumul + taille <= TIKTOK_BUDGET:
            cumul += taille
            continue
        if not remplacable:
            # Aucune trace de ce passage ailleurs : on le garde, quitte a
            # depasser le budget. Mieux vaut un disque plein qu'un extrait perdu.
            cumul += taille
            continue
        size = _drop(clip)
        if size:
            freed += size
            count += 1
            print(f"  file TikTok {clip.name} ({_mib(size)} Mio)")
            clip.with_suffix(".info.json").unlink(missing_ok=True)
    return freed, count


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        exports_freed, exports_n = clean_exports(db)
        sources_freed, sources_n = clean_sources(db)
        originals_freed, originals_n = clean_originals(db)
        tiktok_freed, tiktok_n = clean_tiktok(db)
    finally:
        db.close()
    avortes_freed, avortes_n = clean_avortes()

    total = (exports_freed + sources_freed + originals_freed
             + avortes_freed + tiktok_freed)
    print(
        f"Libere : {_mib(total)} Mio "
        f"({exports_n} rendu(s), {sources_n} source(s), "
        f"{originals_n} original(aux), {avortes_n} avorte(s), "
        f"{tiktok_n} de la file TikTok)"
    )


if __name__ == "__main__":
    main()

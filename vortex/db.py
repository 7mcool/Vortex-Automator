"""Base d'état SQLite : une ligne par vidéo, un journal d'événements.

États (sous-ensemble du cahier des charges) :
DISCOVERED -> TRANSCRIBED -> READY -> UPLOADING -> SCHEDULED -> PUBLISHED
avec FAILED / BLOCKED / SKIPPED possibles à tout moment.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

STATES = [
    "DISCOVERED", "TRANSCRIBED", "READY", "UPLOADING",
    "SCHEDULED", "PUBLISHED", "FAILED", "BLOCKED", "SKIPPED",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    path TEXT NOT NULL,
    tiktok_id TEXT,
    sha256 TEXT UNIQUE,
    size_bytes INTEGER,
    duration_s REAL,
    width INTEGER,
    height INTEGER,
    category TEXT,                 -- short | long_vertical | long_horizontal
    caption TEXT,                  -- légende TikTok d'origine si connue
    cover_path TEXT,
    state TEXT NOT NULL DEFAULT 'DISCOVERED',
    transcript_path TEXT,
    srt_path TEXT,
    language TEXT,
    title TEXT,
    description TEXT,
    tags TEXT,                     -- JSON list
    youtube_id TEXT,
    publish_at TEXT,               -- RFC3339 UTC
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_videos (
    youtube_id TEXT PRIMARY KEY,
    title TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_state ON videos(state);

-- ------------------------------------------------------------------------
-- Découpage des longues vidéos YouTube (Submagic). Tables séparées de
-- `videos` : une source n'est pas une vidéo à publier, c'est un gisement de
-- 3 heures dont on tire quelques extraits.
CREATE TABLE IF NOT EXISTS sources_yt (
    youtube_id TEXT PRIMARY KEY,
    handle TEXT NOT NULL,          -- chaîne d'origine (@handle)
    chaine TEXT,                   -- nom lisible de la chaîne
    pasteur TEXT,                  -- SEULEMENT si certain (voir veille.py)
    eglise TEXT,
    titre TEXT,
    published_at TEXT,
    duration_s INTEGER,
    is_live INTEGER DEFAULT 0,
    view_count INTEGER,
    empreinte TEXT,                -- clé de dédoublonnage inter-chaînes
    etat TEXT NOT NULL,            -- REPERE|ENVOYE|DECOUPE|ECARTE|ECHEC
    submagic_id TEXT,
    envoye_at TEXT,
    erreur TEXT,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,           -- identifiant Submagic de l'extrait
    source_id TEXT NOT NULL,
    submagic_projet TEXT,
    titre TEXT,
    duree_s REAL,
    score_total REAL,
    score_hook REAL,
    score_partage REAL,
    score_histoire REAL,
    score_emotion REAL,
    download_url TEXT,
    direct_url TEXT,
    preview_url TEXT,
    legende TEXT,                  -- légende TikTok prête (SEO + hashtags)
    hashtags TEXT,
    etat TEXT NOT NULL,            -- RETENU|ECARTE|LIVRE|PUBLIE
    livre_at TEXT,
    programme_at TEXT,             -- créneau TikTok réservé (RFC3339 UTC)
    publication_id TEXT,           -- identifiant de publication Submagic
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_etat ON sources_yt(etat);
CREATE INDEX IF NOT EXISTS idx_sources_empreinte ON sources_yt(empreinte);
CREATE INDEX IF NOT EXISTS idx_clips_etat ON clips(etat);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, db_file: Path):
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_file, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 15000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._migrer()
        self.conn.commit()

    def _migrer(self) -> None:
        """Ajoute les colonnes apparues après la création d'une base.

        `CREATE TABLE IF NOT EXISTS` ne touche pas une table déjà présente :
        sans ceci, une base créée avant l'ajout d'une colonne resterait
        incomplète et le pipeline planterait sur un `no such column`.
        """
        ajouts = {
            "clips": {
                "programme_at": "TEXT",
                "publication_id": "TEXT",
            },
            "sources_yt": {
                # Clé souple (titre sans les dates) : reconnaît un sermon
                # remis en ligne après montage, qui porte une adresse et
                # souvent une date différentes.
                "empreinte_lache": "TEXT",
                # Crédits réellement engagés sur cette source. Sans cette
                # colonne, le budget affiché restait figé au plafond mensuel
                # et n'avertissait jamais d'un dépassement.
                "credits": "INTEGER",
                # Identifiant du message Telegram de confirmation. Sert à
                # lier la réponse de Michel (reply_to_message) à la source.
                "telegram_msg": "TEXT",
            },
        }
        for table, colonnes in ajouts.items():
            existantes = {r["name"] for r in
                          self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for nom, type_sql in colonnes.items():
                if nom not in existantes:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {type_sql}")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ vidéos
    def upsert_video(self, info: dict) -> tuple[int, bool]:
        """Insère une vidéo découverte. Retourne (id, est_nouvelle).

        Le dédoublonnage se fait sur sha256 (résiste au renommage) puis sur name.
        """
        cur = self.conn.cursor()
        row = None
        if info.get("sha256"):
            row = cur.execute("SELECT * FROM videos WHERE sha256 = ?", (info["sha256"],)).fetchone()
        if row is None:
            row = cur.execute("SELECT * FROM videos WHERE name = ?", (info["name"],)).fetchone()
        if row is not None:
            video_id = int(row["id"])
            # Fichier modifié depuis (téléchargement terminé, remplacement…) :
            # on rafraîchit les métadonnées et on redonne sa chance à la vidéo.
            if info.get("sha256") and row["sha256"] and info["sha256"] != row["sha256"]:
                self.update_fields(
                    video_id, sha256=info["sha256"], path=info["path"],
                    size_bytes=info.get("size_bytes"), duration_s=info.get("duration_s"),
                    width=info.get("width"), height=info.get("height"),
                    category=info.get("category"),
                )
                if row["state"] in ("BLOCKED", "FAILED", "SKIPPED"):
                    self.set_state(video_id, "DISCOVERED", "fichier modifié, ré-examen")
            else:
                # Champs mutables : chemin (renommage), couverture, légende si absente.
                updates = {}
                if info["path"] != row["path"]:
                    updates["path"] = info["path"]
                if info.get("cover_path") and info["cover_path"] != row["cover_path"]:
                    updates["cover_path"] = info["cover_path"]
                if info.get("caption") and not row["caption"]:
                    updates["caption"] = info["caption"]
                if updates:
                    self.update_fields(video_id, **updates)
            return video_id, False

        now = utcnow()
        cur.execute(
            """INSERT INTO videos (name, path, tiktok_id, sha256, size_bytes, duration_s,
                                   width, height, category, caption, cover_path,
                                   state, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'DISCOVERED',?,?)""",
            (
                info["name"], info["path"], info.get("tiktok_id"), info.get("sha256"),
                info.get("size_bytes"), info.get("duration_s"), info.get("width"),
                info.get("height"), info.get("category"), info.get("caption"),
                info.get("cover_path"), now, now,
            ),
        )
        video_id = cur.lastrowid
        cur.execute(
            "INSERT INTO events (video_id, from_state, to_state, detail, at) VALUES (?,?,?,?,?)",
            (video_id, None, "DISCOVERED", "scan", now),
        )
        self.conn.commit()
        return int(video_id), True

    def set_state(self, video_id: int, state: str, detail: str = "", **fields) -> None:
        if state not in STATES:
            raise ValueError(f"État inconnu : {state}")
        cur = self.conn.cursor()
        old = cur.execute("SELECT state FROM videos WHERE id = ?", (video_id,)).fetchone()
        now = utcnow()
        sets = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values())
        cur.execute(
            f"UPDATE videos SET state = ?, updated_at = ?{', ' + sets if sets else ''} WHERE id = ?",
            [state, now, *params, video_id],
        )
        cur.execute(
            "INSERT INTO events (video_id, from_state, to_state, detail, at) VALUES (?,?,?,?,?)",
            (video_id, old["state"] if old else None, state, detail, now),
        )
        self.conn.commit()

    def update_fields(self, video_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE videos SET {sets}, updated_at = ? WHERE id = ?",
            [*fields.values(), utcnow(), video_id],
        )
        self.conn.commit()

    def get(self, video_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()

    def by_state(self, state: str, limit: int = 0) -> list[sqlite3.Row]:
        # LE RÉCENT D'ABORD (règle de Michel, 29/07) : un sermon prêché hier
        # intéresse davantage que le fonds de catalogue, et une conférence en
        # cours doit sortir pendant qu'elle a lieu. `rowid` décroissant suffit :
        # une vidéo entre en base au moment où elle est découverte.
        # À fraîcheur égale, on garde les vidéos substantielles (30 s à 3 min)
        # avant les mini-clips.
        sql = ("SELECT * FROM videos WHERE state = ? "
               "ORDER BY rowid DESC, "
               "CASE WHEN duration_s BETWEEN 30 AND 180 THEN 0 ELSE 1 END, "
               "duration_s DESC")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql, (state,)).fetchall()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT state, COUNT(*) AS n FROM videos GROUP BY state").fetchall()
        return {r["state"]: r["n"] for r in rows}

    def scheduled_publish_times(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT publish_at FROM videos WHERE publish_at IS NOT NULL AND state IN ('SCHEDULED','UPLOADING','PUBLISHED')"
        ).fetchall()
        return [r["publish_at"] for r in rows]

    def set_tags(self, video_id: int, tags: list[str]) -> None:
        self.update_fields(video_id, tags=json.dumps(tags, ensure_ascii=False))

    def claim_for_upload(self, video_id: int, publish_at: str) -> bool:
        """Réservation atomique READY -> UPLOADING (empêche deux publish concurrents)."""
        cur = self.conn.execute(
            "UPDATE videos SET state = 'UPLOADING', publish_at = ?, updated_at = ? "
            "WHERE id = ? AND state = 'READY'",
            (publish_at, utcnow(), video_id),
        )
        self.conn.commit()
        if cur.rowcount == 1:
            self.conn.execute(
                "INSERT INTO events (video_id, from_state, to_state, detail, at) VALUES (?,?,?,?,?)",
                (video_id, "READY", "UPLOADING", "réservation upload", utcnow()),
            )
            self.conn.commit()
            return True
        return False

    def requalify_stale_uploads(self, max_age_hours: int = 6) -> int:
        """Repasse en READY les UPLOADING orphelins (crash/coupure pendant l'upload)."""
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self.conn.execute(
            "SELECT id FROM videos WHERE state = 'UPLOADING' AND updated_at < ?", (cutoff,)
        ).fetchall()
        for r in rows:
            self.set_state(r["id"], "READY", "upload orphelin requalifié")
        return len(rows)

    # -------------------------------------------------------- chaîne existante
    def record_channel_video(self, youtube_id: str, title: str, published_at: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO channel_videos (youtube_id, title, published_at, fetched_at) VALUES (?,?,?,?)",
            (youtube_id, title, published_at, utcnow()),
        )
        self.conn.commit()

    def channel_titles(self) -> list[str]:
        return [r["title"] for r in self.conn.execute("SELECT title FROM channel_videos").fetchall()]

    # ------------------------------------------------- sources longues YouTube
    def source_connue(self, youtube_id: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM sources_yt WHERE youtube_id = ?", (youtube_id,)
        ).fetchone() is not None

    def empreinte_connue(self, empreinte: str, published_at: str = "",
                         fenetre_jours: int = 45, *, empreinte_lache: str = "",
                         duration_s: int = 0) -> tuple[str, str]:
        """(identifiant du jumeau, raison) — chaîne vide s'il n'y en a pas.

        Deux cas de figure, tous deux coûteux si on les rate :

        1. **Rediffusion sur une autre chaîne.** Yannick Djatti et le Centre
           Chrétien de Réveil publient le même culte. Titre identique, date
           identique : la clé stricte suffit.
        2. **Remise en ligne après montage.** L'église rend le direct privé,
           coupe des passages, republie. Nouvelle adresse, souvent nouvelle
           date dans le titre. On la reconnaît par la clé souple ET par la
           durée : une version remontée est plus COURTE que le direct.
        """
        from datetime import datetime, timedelta

        def _date(valeur):
            try:
                return datetime.fromisoformat((valeur or "").replace("Z", "+00:00"))
            except ValueError:
                return None

        ref = _date(published_at)

        def _dans_la_fenetre(row):
            if ref is None:
                return True
            autre = _date(row["published_at"])
            return autre is None or abs(autre - ref) <= timedelta(days=fenetre_jours)

        for row in self.conn.execute(
            "SELECT youtube_id, published_at FROM sources_yt "
            "WHERE empreinte = ? AND etat != 'ECARTE'", (empreinte,),
        ).fetchall():
            if _dans_la_fenetre(row):
                return row["youtube_id"], "même titre et même date"

        if not empreinte_lache:
            return "", ""
        for row in self.conn.execute(
            "SELECT youtube_id, published_at, duration_s FROM sources_yt "
            "WHERE empreinte_lache = ? AND etat != 'ECARTE'", (empreinte_lache,),
        ).fetchall():
            if not _dans_la_fenetre(row):
                continue
            ancienne = row["duration_s"] or 0
            if not (duration_s and ancienne):
                continue
            # Le signe décisif : une version remontée est NETTEMENT plus
            # courte, puisqu'on lui a retiré la louange et les annonces — un
            # direct de 2 h 30 redevient 1 h. Une émission hebdomadaire qui
            # garde son nom, elle, dure à peu près pareil d'un numéro à
            # l'autre : c'est ce qui les distingue.
            #
            # Le seuil penche volontairement vers l'écartement, sur décision
            # de Michel (« on ne repaie jamais ») : écarter à tort un vrai
            # nouveau sermon coûte une occasion, repayer coûte 45 crédits,
            # soit un sermon entier sur les six du mois.
            if duration_s > ancienne * 0.85:
                continue
            return row["youtube_id"], "sermon déjà traité, remis en ligne après montage"
        return "", ""

    def ajouter_source(self, info: dict) -> None:
        now = utcnow()
        self.conn.execute(
            """INSERT OR IGNORE INTO sources_yt
               (youtube_id, handle, chaine, pasteur, eglise, titre, published_at,
                duration_s, is_live, view_count, empreinte, empreinte_lache, etat,
                discovered_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                info["youtube_id"], info["handle"], info.get("chaine"),
                info.get("pasteur", ""), info.get("eglise", ""), info.get("titre"),
                info.get("published_at"), info.get("duration_s"),
                1 if info.get("is_live") else 0, info.get("view_count"),
                info.get("empreinte"), info.get("empreinte_lache"),
                info.get("etat", "REPERE"), now, now,
            ),
        )
        self.conn.commit()

    def sources_par_etat(self, etat: str, limit: int = 0) -> list[sqlite3.Row]:
        # Le plus récent d'abord, et à fraîcheur égale la plus regardée : un
        # direct qui fait 30 000 vues sur la chaîne source a déjà prouvé qu'il
        # portait quelque chose.
        sql = ("SELECT * FROM sources_yt WHERE etat = ? "
               "ORDER BY published_at DESC, view_count DESC")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql, (etat,)).fetchall()

    def maj_source(self, youtube_id: str, **champs) -> None:
        if not champs:
            return
        sets = ", ".join(f"{k} = ?" for k in champs)
        self.conn.execute(
            f"UPDATE sources_yt SET {sets}, updated_at = ? WHERE youtube_id = ?",
            [*champs.values(), utcnow(), youtube_id],
        )
        self.conn.commit()

    def credits_depenses_depuis(self, iso_utc: str) -> int:
        """Crédits OpusClip réellement engagés depuis une date.

        C'est le seul compteur fiable : l'API OpusClip n'expose aucun solde
        (toutes ses adresses de compte répondent 404, vérifié le 05/08).
        """
        row = self.conn.execute(
            "SELECT COALESCE(SUM(credits), 0) AS total FROM sources_yt "
            "WHERE credits IS NOT NULL AND envoye_at >= ?", (iso_utc,),
        ).fetchone()
        return int(row["total"]) if row else 0

    def sources_envoyees_depuis(self, iso_utc: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM sources_yt WHERE envoye_at IS NOT NULL AND envoye_at >= ?",
            (iso_utc,),
        ).fetchone()
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------ clips
    def ajouter_clip(self, info: dict) -> bool:
        """Enregistre un extrait. Retourne True s'il est nouveau."""
        now = utcnow()
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO clips
               (id, source_id, submagic_projet, titre, duree_s, score_total,
                score_hook, score_partage, score_histoire, score_emotion,
                download_url, direct_url, preview_url, etat, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                info["id"], info["source_id"], info.get("submagic_projet"),
                info.get("titre"), info.get("duree_s"), info.get("score_total"),
                info.get("score_hook"), info.get("score_partage"),
                info.get("score_histoire"), info.get("score_emotion"),
                info.get("download_url"), info.get("direct_url"),
                info.get("preview_url"), info.get("etat", "RETENU"), now, now,
            ),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def clips_par_etat(self, etat: str, limit: int = 0) -> list[sqlite3.Row]:
        sql = "SELECT * FROM clips WHERE etat = ? ORDER BY score_total DESC, rowid DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql, (etat,)).fetchall()

    def clips_de_source(self, source_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM clips WHERE source_id = ? ORDER BY score_total DESC", (source_id,)
        ).fetchall()

    def maj_clip(self, clip_id: str, **champs) -> None:
        if not champs:
            return
        sets = ", ".join(f"{k} = ?" for k in champs)
        self.conn.execute(
            f"UPDATE clips SET {sets}, updated_at = ? WHERE id = ?",
            [*champs.values(), utcnow(), clip_id],
        )
        self.conn.commit()

    def creneaux_tiktok_reserves(self) -> list[str]:
        """Créneaux TikTok déjà pris. Indépendant de la grille YouTube :
        les deux réseaux ont leur propre rythme."""
        return [r["programme_at"] for r in self.conn.execute(
            "SELECT programme_at FROM clips WHERE programme_at IS NOT NULL"
        ).fetchall()]

    def compteurs_clipping(self) -> dict[str, dict[str, int]]:
        sources = {r["etat"]: r["n"] for r in self.conn.execute(
            "SELECT etat, COUNT(*) AS n FROM sources_yt GROUP BY etat").fetchall()}
        clips = {r["etat"]: r["n"] for r in self.conn.execute(
            "SELECT etat, COUNT(*) AS n FROM clips GROUP BY etat").fetchall()}
        return {"sources": sources, "clips": clips}

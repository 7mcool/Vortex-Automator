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
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, db_file: Path):
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_file)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

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
            row = cur.execute("SELECT id FROM videos WHERE sha256 = ?", (info["sha256"],)).fetchone()
        if row is None:
            row = cur.execute("SELECT id FROM videos WHERE name = ?", (info["name"],)).fetchone()
        if row is not None:
            return int(row["id"]), False

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
        sql = "SELECT * FROM videos WHERE state = ? ORDER BY duration_s ASC"
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

    # -------------------------------------------------------- chaîne existante
    def record_channel_video(self, youtube_id: str, title: str, published_at: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO channel_videos (youtube_id, title, published_at, fetched_at) VALUES (?,?,?,?)",
            (youtube_id, title, published_at, utcnow()),
        )
        self.conn.commit()

    def channel_titles(self) -> list[str]:
        return [r["title"] for r in self.conn.execute("SELECT title FROM channel_videos").fetchall()]

"""Configuration centralisée : config.toml (réglages) + .env (secrets).

Aucun secret dans ce fichier ni dans config.toml — les secrets vivent
uniquement dans .env (jamais commité, voir .gitignore).
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = REPO_ROOT / "config.toml"


def load_env(env_file: Path | None = None) -> None:
    """Charge un fichier .env minimaliste dans os.environ (sans dépendance)."""
    path = env_file or REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Config:
    # Chemins
    source_dir: Path
    tokkit_db: Path
    data_dir: Path
    client_secret_file: Path
    token_file: Path

    # Publication
    publish_hours: list[int] = field(default_factory=lambda: [9, 12, 15, 18, 21])
    daily_limit: int = 5
    timezone: str = "Africa/Porto-Novo"
    category_id: str = "27"  # Éducation
    default_language: str = "fr"
    made_for_kids: bool = False
    notify_subscribers: bool = True
    playlist_id: str = ""
    upload_captions: bool = False  # 400 unités de quota/vidéo — désactivé pour tenir 5/jour
    # Aimant Facebook : republier chaque clip vertical sur la Page FB (lien YouTube).
    # Désactivé par défaut (éviter de reposter tout le backlog d'un coup) ; activer
    # via config.toml [publish] facebook_publish = true quand prêt.
    facebook_publish: bool = False
    fb_page_id: str = "1203021176235142"
    # Base publique pour servir les clips à l'API Reels Instagram (dashboard :8787).
    media_base_url: str = "http://187.127.235.148:8787"

    # Transcription
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"

    # SEO
    channel_name: str = "Sophos PropheTikos"
    known_speakers: list[str] = field(default_factory=lambda: ["Jacques Amessan", "Mohammed Sanogo"])
    hashtags: list[str] = field(default_factory=lambda: ["#foi", "#motivation", "#predication"])
    max_title_len: int = 95
    tags_count: int = 15

    # Vidéo
    shorts_max_seconds: int = 180
    min_duration_seconds: int = 5

    @property
    def db_file(self) -> Path:
        return self.data_dir / "vortex.db"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def subtitles_dir(self) -> Path:
        return self.data_dir / "subtitles"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.transcripts_dir, self.subtitles_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config(config_file: Path | None = None) -> Config:
    load_env()
    path = config_file or Path(os.environ.get("VORTEX_CONFIG", DEFAULT_CONFIG_FILE))
    if not path.exists():
        sys.exit(f"Fichier de configuration introuvable : {path}")
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    paths = raw.get("paths", {})
    publish = raw.get("publish", {})
    whisper = raw.get("whisper", {})
    seo = raw.get("seo", {})
    video = raw.get("video", {})

    def _path(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else REPO_ROOT / p

    cfg = Config(
        source_dir=_path(paths.get("source_dir", r"E:\hedjav\4K Tokkit\hedjav")),
        tokkit_db=_path(paths.get("tokkit_db", r"E:\hedjav\4K Tokkit\data.sqlite")),
        data_dir=_path(paths.get("data_dir", "data")),
        client_secret_file=_path(
            os.environ.get("VORTEX_CLIENT_SECRET", paths.get("client_secret_file", r"secrets\client_secret.json"))
        ),
        token_file=_path(
            os.environ.get("VORTEX_TOKEN_FILE", paths.get("token_file", r"secrets\youtube_token.json"))
        ),
        publish_hours=list(publish.get("hours", [9, 12, 15, 18, 21])),
        daily_limit=int(publish.get("daily_limit", 5)),
        timezone=publish.get("timezone", "Africa/Porto-Novo"),
        category_id=str(publish.get("category_id", "27")),
        default_language=publish.get("language", "fr"),
        made_for_kids=bool(publish.get("made_for_kids", False)),
        notify_subscribers=bool(publish.get("notify_subscribers", True)),
        playlist_id=publish.get("playlist_id", ""),
        upload_captions=bool(publish.get("upload_captions", False)),
        facebook_publish=bool(publish.get("facebook_publish", False)),
        fb_page_id=str(publish.get("fb_page_id", "1203021176235142")),
        media_base_url=str(publish.get("media_base_url", "http://187.127.235.148:8787")),
        whisper_model=whisper.get("model", "small"),
        whisper_device=whisper.get("device", "cpu"),
        whisper_compute=whisper.get("compute_type", "int8"),
        channel_name=seo.get("channel_name", "Sophos PropheTikos"),
        known_speakers=list(seo.get("known_speakers", ["Jacques Amessan", "Mohammed Sanogo"])),
        hashtags=list(seo.get("hashtags", ["#foi", "#motivation", "#predication"])),
        max_title_len=int(seo.get("max_title_len", 95)),
        tags_count=int(seo.get("tags_count", 15)),
        shorts_max_seconds=int(video.get("shorts_max_seconds", 180)),
        min_duration_seconds=int(video.get("min_duration_seconds", 5)),
    )
    cfg.ensure_dirs()
    return cfg

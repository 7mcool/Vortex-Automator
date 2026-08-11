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
    # Poser une miniature maison au moment de la publication ?
    #
    # ⚠️ YouTube plafonne le nombre de miniatures personnalisées PAR JOUR selon
    # l'historique de la chaîne (« Développer l'historique de votre chaîne »,
    # lu dans Studio le 11/08/2026). Sur cette chaîne le plafond tourne autour
    # de cinq : les publications du jour le mangeaient en entier, et le
    # rattrapage des 80 anciennes miniatures ne pouvait plus rien poser.
    #
    # À false, YouTube choisit lui-même une image de la vidéo — exactement la
    # formule retenue par Michel le 10/08 — et tout le plafond du jour reste
    # disponible pour le rattrapage.
    poser_miniature: bool = True
    # Aimant Facebook : republier chaque clip vertical sur la Page FB (lien YouTube).
    # Désactivé par défaut (éviter de reposter tout le backlog d'un coup) ; activer
    # via config.toml [publish] facebook_publish = true quand prêt.
    facebook_publish: bool = False
    # Aimant Instagram : republier chaque clip vertical en Reel (API Graph, token
    # de Page partagé avec Facebook). Nécessite le compte IG relié à la Page et le
    # droit instagram_content_publish. Activer via [publish] instagram_publish = true.
    instagram_publish: bool = False
    fb_page_id: str = "1203021176235142"
    # Base publique pour servir les clips à l'API Reels Instagram (dashboard :8787).
    media_base_url: str = "http://187.127.235.148:8787"

    # Grille TikTok, indépendante de celle de YouTube. Michel, 07/08 : les
    # extraits d'un même sermon sortent TOUS le même jour, nuit comprise —
    # un culte qui finit à 23 h publie à 0 h, 2 h, 4 h puis 7 h.
    tiktok_hours: list[int] = field(default_factory=lambda: [0, 2, 4, 7, 10, 12, 14, 16, 19, 21])
    tiktok_daily_limit: int = 10

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

    # Découpage des longues vidéos YouTube (Submagic)
    chaines_surveillees: list[dict] = field(default_factory=list)
    source_duree_min_s: int = 1800
    clip_min_s: int = 30
    clip_max_s: int = 120
    gabarit_submagic: str = "Sara"
    suivi_visage: bool = True
    projets_par_jour: int = 2
    clips_retenus_par_source: int = 5
    note_minimale: float = 55.0
    langue_clipping: str = "fr"

    # OpusClip (extraits longs) — voir vortex/opusclip.py et vortex/fenetre.py
    opus_credits_par_mois: int = 300
    opus_fenetre_max_s: int = 2700
    opus_fenetre_min_s: int = 900
    opus_credits_max_par_projet: int = 50
    opus_clip_min_s: int = 420
    opus_clip_max_s: int = 900
    opus_clip_plancher_s: int = 300
    opus_modele: str = "ClipBasic"
    opus_genre: str = "Auto"
    opus_fraicheur_max_jours: int = 12
    opus_traiter_a_partir_de: str = ""
    opus_sermons_par_jour: int = 1
    opus_chaines_reservees: list[str] = field(default_factory=list)
    opus_jour_ouverture_autres: int = 24
    # Heures d'attente avant qu'une question sans réponse parte toute seule.
    opus_delai_auto_h: int = 3
    # Âge maximal d'un sermon pour qu'il puisse partir SANS réponse. Un vieux
    # sermon demande toujours un GO explicite.
    opus_fraicheur_auto_jours: int = 2
    # Heures laissées au PC pour repérer la prédication avant qu'on pose la
    # question. Un direct fraîchement terminé n'est pas encore téléchargeable.
    opus_attente_reperage_h: int = 4

    # Livraison par courriel
    courriel_destinataires: list[str] = field(default_factory=list)
    courriel_expediteur: str = ""
    smtp_serveur: str = "smtp.gmail.com"
    smtp_port: int = 587
    courriel_pieces_jointes: bool = True
    courriel_taille_max_mo: int = 20

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
    tiktok = raw.get("tiktok", {})
    whisper = raw.get("whisper", {})
    seo = raw.get("seo", {})
    video = raw.get("video", {})
    clipping = raw.get("clipping", {})
    opus = raw.get("opusclip", {})
    courriel = raw.get("courriel", {})

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
        # Valeurs par défaut identiques à l'ancien code en dur : le VPS ne bouge
        # pas. Le PC les redéfinit en relatif dans son propre config.toml.
        publish_hours=list(publish.get("hours", [9, 12, 15, 18, 21])),
        daily_limit=int(publish.get("daily_limit", 5)),
        timezone=publish.get("timezone", "Africa/Porto-Novo"),
        category_id=str(publish.get("category_id", "27")),
        default_language=publish.get("language", "fr"),
        made_for_kids=bool(publish.get("made_for_kids", False)),
        notify_subscribers=bool(publish.get("notify_subscribers", True)),
        playlist_id=publish.get("playlist_id", ""),
        upload_captions=bool(publish.get("upload_captions", False)),
        poser_miniature=bool(publish.get("poser_miniature", True)),
        facebook_publish=bool(publish.get("facebook_publish", False)),
        instagram_publish=bool(publish.get("instagram_publish", False)),
        fb_page_id=str(publish.get("fb_page_id", "1203021176235142")),
        media_base_url=str(publish.get("media_base_url", "http://187.127.235.148:8787")),
        tiktok_hours=list(tiktok.get("hours", [0, 2, 4, 7, 10, 12, 14, 16, 19, 21])),
        tiktok_daily_limit=int(tiktok.get("daily_limit", 10)),
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
        # [[clipping.chaines]] est une liste de tables TOML : chaque entrée est
        # déjà un dict {handle, id, nom, pasteur, eglise, pasteur_unique}.
        chaines_surveillees=list(clipping.get("chaines", [])),
        source_duree_min_s=int(clipping.get("source_duree_min_s", 1800)),
        clip_min_s=int(clipping.get("clip_min_s", 30)),
        clip_max_s=int(clipping.get("clip_max_s", 120)),
        gabarit_submagic=str(clipping.get("gabarit", "Sara")),
        suivi_visage=bool(clipping.get("suivi_visage", True)),
        projets_par_jour=int(clipping.get("projets_par_jour", 2)),
        clips_retenus_par_source=int(clipping.get("clips_retenus_par_source", 5)),
        note_minimale=float(clipping.get("note_minimale", 55)),
        langue_clipping=str(clipping.get("langue", "fr")),
        opus_credits_par_mois=int(opus.get("credits_par_mois", 300)),
        opus_fenetre_max_s=int(opus.get("fenetre_max_s", 2700)),
        opus_fenetre_min_s=int(opus.get("fenetre_min_s", 900)),
        opus_credits_max_par_projet=int(opus.get("credits_max_par_projet", 50)),
        opus_clip_min_s=int(opus.get("clip_min_s", 420)),
        opus_clip_max_s=int(opus.get("clip_max_s", 900)),
        opus_clip_plancher_s=int(opus.get("clip_plancher_s", 300)),
        opus_modele=str(opus.get("modele", "ClipBasic")),
        opus_genre=str(opus.get("genre", "Auto")),
        opus_fraicheur_max_jours=int(opus.get("fraicheur_max_jours", 12)),
        opus_traiter_a_partir_de=str(opus.get("traiter_a_partir_de", "")),
        opus_sermons_par_jour=int(opus.get("sermons_par_jour", 1)),
        opus_chaines_reservees=list(opus.get("chaines_reservees", [])),
        opus_jour_ouverture_autres=int(opus.get("jour_ouverture_autres", 24)),
        opus_delai_auto_h=int(opus.get("delai_auto_h", 3)),
        opus_fraicheur_auto_jours=int(opus.get("fraicheur_auto_jours", 2)),
        opus_attente_reperage_h=int(opus.get("attente_reperage_h", 4)),
        # Accepte une adresse seule ou une liste : Michel veut recevoir sur
        # deux boîtes (celle de la chaîne et la sienne).
        courriel_destinataires=(
            [courriel["destinataire"]] if courriel.get("destinataire")
            else [a for a in courriel.get("destinataires", []) if a]
        ),
        courriel_expediteur=str(courriel.get("expediteur", "")),
        smtp_serveur=str(courriel.get("serveur", "smtp.gmail.com")),
        smtp_port=int(courriel.get("port", 587)),
        courriel_pieces_jointes=bool(courriel.get("pieces_jointes", True)),
        courriel_taille_max_mo=int(courriel.get("taille_max_mo", 20)),
    )
    cfg.ensure_dirs()
    return cfg

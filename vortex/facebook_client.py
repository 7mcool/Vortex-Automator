"""Étape 11 — publication Facebook (+ Instagram) via l'API Graph Meta.

Aimant vers YouTube : chaque extrait vertical est publié sur la Page Facebook
(et, quand la connexion Instagram est branchée, en Reel) avec un lien
« Sermon complet 👉 YouTube » pour ramener l'audience vers la chaîne principale.

- App Meta « Sophos PropheTikos » (créée 14/07/2026). Permissions en mode
  développement (Prête pour le test) : pages_manage_posts, pages_read_engagement,
  pages_show_list, business_management — PAS besoin d'App Review pour les propres
  comptes de l'admin.
- Le token de Page vit dans secrets/meta_page_token.txt (jamais commité).
- L'upload vidéo passe par `curl` (multipart), comme ffmpeg côté clipper :
  robuste et éprouvé, sans dépendance HTTP lourde.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Config

log = logging.getLogger("vortex.facebook")

GRAPH = "https://graph.facebook.com/v21.0"
YT_CHANNEL = "https://www.youtube.com/@sophos_prophetikos"


def _page_id(cfg: Config) -> str:
    return getattr(cfg, "fb_page_id", "") or "1203021176235142"


def _page_token(cfg: Config) -> str | None:
    """Token de Page Facebook, depuis secrets/meta_page_token.txt (jamais loggé)."""
    base = Path(cfg.client_secret_file).parent if getattr(cfg, "client_secret_file", None) \
        else Path("secrets")
    p = base / "meta_page_token.txt"
    if not p.exists():
        return None
    tok = p.read_text(encoding="utf-8").strip()
    return tok or None


def available(cfg: Config) -> bool:
    return _page_token(cfg) is not None


def _cta(caption: str) -> str:
    """Ajoute l'appel à l'action vers YouTube (aimant) s'il n'y est pas déjà."""
    caption = (caption or "").strip()
    if "youtube.com/@sophos" in caption.lower():
        return caption
    return f"{caption}\n\n🎥 Sermon complet 👉 {YT_CHANNEL}".strip()


def post_video_to_page(cfg: Config, video_path: str, caption: str) -> str | None:
    """Publie une vidéo sur la Page Facebook. Retourne l'ID du post ou None."""
    token = _page_token(cfg)
    if not token:
        log.warning("Facebook : pas de token de Page (secrets/meta_page_token.txt) — ignoré.")
        return None
    if not Path(video_path).exists():
        log.warning("Facebook : vidéo introuvable %s", video_path)
        return None
    desc = _cta(caption)
    # --form-string : valeur LITTÉRALE (désactive l'interprétation curl d'un '@'
    # ou '<' initial comme référence de fichier — sinon une légende commençant par
    # « @sophos… » casserait le post PUBLIC, voire ferait fuiter un fichier local).
    # source=@"..." : guillemets pour qu'un chemin contenant une virgule ne soit
    # pas scindé par curl (syntaxe multi-fichiers).
    cmd = [
        "curl", "-s", "-X", "POST", f"{GRAPH}/{_page_id(cfg)}/videos",
        "--form-string", f"access_token={token}",
        "--form-string", f"description={desc}",
        "-F", f'source=@"{video_path}"',
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600).stdout
        data = json.loads(out or "{}")
    except Exception as exc:  # réseau, JSON, timeout
        log.error("Facebook : échec upload (%s)", exc)
        return None
    if "id" in data:
        log.info("Facebook : vidéo publiée (post %s)", data["id"])
        return data["id"]
    log.error("Facebook : réponse inattendue : %s", str(data)[:300])
    return None


def media_url(cfg: Config, filename: str) -> str:
    """URL PUBLIQUE d'un clip (servi par le dashboard) — l'API Reels Instagram
    exige une URL vidéo publiquement téléchargeable par les serveurs Meta."""
    base = (getattr(cfg, "media_base_url", "") or "http://187.127.235.148:8787").rstrip("/")
    tok = os.environ.get("MEDIA_TOKEN", "") or os.environ.get("DASHBOARD_TOKEN", "")
    return f"{base}/media/{tok}/{filename}"


def _ig_business_id(cfg: Config, token: str) -> str | None:
    """ID du compte Instagram Business relié à la Page (None si aucun).
    Se peuple dès que Michel relie son vrai compte IG à la Page dans Business Suite."""
    try:
        url = f"{GRAPH}/{_page_id(cfg)}?fields=instagram_business_account&access_token={token}"
        with urllib.request.urlopen(url, timeout=30) as r:
            acc = json.load(r).get("instagram_business_account")
        return acc.get("id") if acc else None
    except Exception:
        return None


def post_reel_to_instagram(cfg: Config, video_url: str, caption: str) -> str | None:
    """Publie un Reel Instagram (conteneur → attente FINISHED → publication).
    Retourne l'ID du média ou None. Nécessite un compte IG Business relié à la Page."""
    token = _page_token(cfg)
    if not token:
        return None
    ig = _ig_business_id(cfg, token)
    if not ig:
        log.warning("Instagram : aucun compte IG Business relié à la Page — Reel ignoré.")
        return None
    # 1) créer le conteneur média
    data = urllib.parse.urlencode({
        "media_type": "REELS", "video_url": video_url,
        "caption": _cta(caption), "access_token": token,
    }).encode()
    try:
        req = urllib.request.Request(f"{GRAPH}/{ig}/media", data=data)
        with urllib.request.urlopen(req, timeout=60) as r:
            cid = json.load(r).get("id")
    except Exception as exc:
        log.error("Instagram : création du conteneur échouée (%s)", exc)
        return None
    if not cid:
        return None
    # 2) attendre la fin du traitement de la vidéo (jusqu'à ~2,5 min)
    for _ in range(30):
        time.sleep(5)
        try:
            with urllib.request.urlopen(
                    f"{GRAPH}/{cid}?fields=status_code&access_token={token}", timeout=30) as r:
                status = json.load(r).get("status_code")
        except Exception:
            status = None
        if status == "FINISHED":
            break
        if status == "ERROR":
            log.error("Instagram : traitement média en ERROR")
            return None
    else:
        log.warning("Instagram : média pas prêt à temps — abandon.")
        return None
    # 3) publier
    pub = urllib.parse.urlencode({"creation_id": cid, "access_token": token}).encode()
    try:
        req = urllib.request.Request(f"{GRAPH}/{ig}/media_publish", data=pub)
        with urllib.request.urlopen(req, timeout=60) as r:
            mid = json.load(r).get("id")
        if mid:
            log.info("Instagram : Reel publié (%s)", mid)
        return mid
    except Exception as exc:
        log.error("Instagram : publication échouée (%s)", exc)
        return None


def page_ok(cfg: Config) -> str | None:
    """Vérifie le token : retourne le nom de la Page ou None (diagnostic)."""
    token = _page_token(cfg)
    if not token:
        return None
    try:
        url = f"{GRAPH}/me?fields=name&access_token={token}"
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r).get("name")
    except Exception as exc:
        log.warning("Facebook : token invalide/expiré (%s)", exc)
        return None

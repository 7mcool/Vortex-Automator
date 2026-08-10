"""Livraison des extraits par courriel.

Pourquoi le courriel : l'app TikTok « Sophos Publisher » a été REFUSÉE le
31/07 (le site de démonstration a été jugé trop mince), donc la publication
automatique par l'API officielle nous est fermée. En attendant, Michel reçoit
les extraits prêts à poster : la vidéo, la légende à copier telle quelle, et
les notes qui disent lesquels valent le coup.

Le message est construit pour être utilisable depuis un téléphone : un bloc
par extrait, la légende en premier, un bouton de téléchargement.

Réglages : [courriel] dans config.toml pour les adresses et le serveur ;
SMTP_USER et SMTP_PASSWORD dans .env pour l'identification (avec Gmail il faut
un « mot de passe d'application », le mot de passe du compte ne marche pas).
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate

from .config import Config
from .db import Database

log = logging.getLogger("vortex.livraison")

UA = "Mozilla/5.0 (compatible; VortexAutomator/1.0)"


def configure(cfg: Config) -> tuple[bool, str]:
    """(prêt, raison) — dit si l'envoi est possible sans rien tenter."""
    if not cfg.courriel_destinataires:
        return False, "aucun destinataire dans config.toml ([courriel] destinataires)"
    if not os.environ.get("SMTP_USER"):
        return False, "SMTP_USER absent de .env"
    if not os.environ.get("SMTP_PASSWORD"):
        return False, "SMTP_PASSWORD absent de .env (Gmail : mot de passe d'application)"
    return True, ""


def _telecharger(url: str, taille_max_octets: int) -> bytes | None:
    """Télécharge un extrait, ou None s'il dépasse la taille autorisée.

    La taille est vérifiée pendant la lecture et pas seulement sur l'en-tête :
    certains hébergeurs n'annoncent pas Content-Length, et on ne veut pas
    charger 300 Mo en mémoire sur un serveur qui n'a qu'un giga-octet libre.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            annonce = r.headers.get("Content-Length")
            if annonce and int(annonce) > taille_max_octets:
                return None
            donnees = bytearray()
            while True:
                bloc = r.read(262144)
                if not bloc:
                    break
                donnees.extend(bloc)
                if len(donnees) > taille_max_octets:
                    return None
            return bytes(donnees)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        log.warning("Téléchargement impossible (%s) : %s", url[:80], exc)
        return None


def _duree_lisible(secondes) -> str:
    try:
        s = int(float(secondes or 0))
    except (TypeError, ValueError):
        return "?"
    return f"{s // 60}:{s % 60:02d}"


def _echapper(texte) -> str:
    return str(texte or "").replace("&", "&amp;").replace("<", "&lt;")


def _bloc_html(rang: int, clip, source) -> str:
    legende = _echapper(clip["legende"])
    titre = _echapper(clip["titre"] or "Extrait")
    src_titre = _echapper(source["titre"] if source else "")
    note = clip["score_total"] or 0
    lien = clip["download_url"] or clip["direct_url"] or ""

    details = " · ".join(filter(None, [
        f"⏱ {_duree_lisible(clip['duree_s'])}",
        f"🔥 accroche {clip['score_hook']:.0f}" if clip["score_hook"] else "",
        f"↗️ partage {clip['score_partage']:.0f}" if clip["score_partage"] else "",
        f"❤️ émotion {clip['score_emotion']:.0f}" if clip["score_emotion"] else "",
    ]))

    return f"""
  <div style="border:1px solid #e3e3e8;border-radius:14px;padding:18px;margin:0 0 20px">
    <div style="font-size:13px;color:#6b6b76">EXTRAIT {rang} — note {note:.0f}/100</div>
    <div style="font-size:18px;font-weight:700;margin:6px 0 4px;color:#1a1a24">{titre}</div>
    <div style="font-size:13px;color:#6b6b76;margin-bottom:14px">{details}</div>
    <div style="font-size:12px;color:#6b6b76;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">
      Légende à copier
    </div>
    <pre style="white-space:pre-wrap;font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;
                line-height:1.5;background:#f6f6f9;border-radius:10px;padding:14px;margin:0 0 14px;
                color:#1a1a24">{legende}</pre>
    <a href="{lien}" style="display:inline-block;background:#5b3df5;color:#fff;text-decoration:none;
       padding:11px 20px;border-radius:9px;font-weight:600;font-size:14px">⬇️ Télécharger la vidéo</a>
    <div style="font-size:12px;color:#9a9aa4;margin-top:12px">Sermon d'origine : {src_titre}</div>
  </div>"""


def _bloc_texte(rang: int, clip) -> str:
    lien = clip["download_url"] or clip["direct_url"] or ""
    return (f"--- EXTRAIT {rang} — note {clip['score_total'] or 0:.0f}/100 "
            f"({_duree_lisible(clip['duree_s'])}) ---\n"
            f"{clip['titre'] or ''}\n\n"
            f"LÉGENDE :\n{clip['legende'] or ''}\n\n"
            f"VIDÉO : {lien}\n")


def livrer(cfg: Config, db: Database, limite: int = 0) -> dict:
    """Envoie les extraits retenus par courriel et les marque LIVRE."""
    pret, raison = configure(cfg)
    if not pret:
        log.error("Envoi impossible : %s", raison)
        return {"envoyes": 0, "raison": raison}

    # Un extrait sans légende n'est pas publiable tel quel : l'envoyer
    # obligerait Michel à écrire le texte lui-même, ce que la machine est
    # censée faire. Il reste en file jusqu'à ce que sa légende soit rédigée.
    clips = [c for c in db.clips_par_etat("RETENU", limit=limite) if (c["legende"] or "").strip()]
    if not clips:
        return {"envoyes": 0, "raison": "aucun extrait avec légende prête"}

    sources = {}
    for c in clips:
        if c["source_id"] not in sources:
            sources[c["source_id"]] = db.conn.execute(
                "SELECT * FROM sources_yt WHERE youtube_id = ?", (c["source_id"],)
            ).fetchone()

    expediteur = cfg.courriel_expediteur or os.environ["SMTP_USER"]
    destinataires = list(cfg.courriel_destinataires)

    msg = EmailMessage()
    msg["Subject"] = f"Vortex — {len(clips)} extrait(s) prêt(s) à publier"
    msg["From"] = expediteur
    # L'en-tête To attend une chaîne : une liste Python y serait écrite telle
    # quelle (« ['a@b.c', ...] ») et aucun serveur ne l'accepterait.
    msg["To"] = ", ".join(destinataires)
    msg["Date"] = formatdate(localtime=True)

    intro_txt = (f"{len(clips)} extrait(s) découpé(s) automatiquement, classés du meilleur au moins bon.\n"
                 f"Chaque bloc contient la légende prête à coller sur TikTok et le lien de la vidéo.\n\n")
    corps_txt = intro_txt + "\n".join(_bloc_texte(i, c) for i, c in enumerate(clips, 1))

    blocs_html = "".join(_bloc_html(i, c, sources.get(c["source_id"]))
                         for i, c in enumerate(clips, 1))
    corps_html = f"""<html><body style="margin:0;padding:20px;background:#fbfbfd;
      font-family:-apple-system,Segoe UI,Roboto,sans-serif">
  <div style="max-width:620px;margin:0 auto">
    <h1 style="font-size:21px;color:#1a1a24;margin:0 0 6px">{len(clips)} extrait(s) prêt(s)</h1>
    <p style="font-size:14px;color:#6b6b76;margin:0 0 22px">
      Classés du meilleur au moins bon. La légende est à coller telle quelle.
    </p>
    {blocs_html}
    <p style="font-size:12px;color:#9a9aa4">Vortex Automator — découpage Submagic</p>
  </div></body></html>"""

    msg.set_content(corps_txt)
    msg.add_alternative(corps_html, subtype="html")

    # Pièces jointes : on s'arrête dès que le budget de taille est atteint,
    # sinon le serveur de messagerie rejette tout le message d'un bloc.
    jointes = 0
    if cfg.courriel_pieces_jointes:
        budget = cfg.courriel_taille_max_mo * 1024 * 1024
        for rang, clip in enumerate(clips, 1):
            lien = clip["download_url"] or clip["direct_url"]
            if not lien or budget <= 0:
                break
            donnees = _telecharger(lien, budget)
            if not donnees:
                continue
            nom = f"{rang:02d}-{_nom_fichier(clip['titre'])}.mp4"
            msg.add_attachment(donnees, maintype="video", subtype="mp4", filename=nom)
            budget -= len(donnees)
            jointes += 1

    contexte = ssl.create_default_context()
    try:
        with smtplib.SMTP(cfg.smtp_serveur, cfg.smtp_port, timeout=180) as serveur:
            serveur.starttls(context=contexte)
            serveur.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            serveur.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("Envoi du courriel échoué : %s", exc)
        return {"envoyes": 0, "raison": str(exc)[:300]}

    maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for clip in clips:
        db.maj_clip(clip["id"], etat="LIVRE", livre_at=maintenant)

    log.info("Courriel envoyé à %s : %d extrait(s), %d pièce(s) jointe(s)",
             ", ".join(destinataires), len(clips), jointes)
    return {"envoyes": len(clips), "pieces_jointes": jointes,
            "destinataires": destinataires}


def _nom_fichier(titre: str | None) -> str:
    base = unicodedata.normalize("NFD", titre or "extrait")
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    base = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()
    return (base or "extrait")[:50]

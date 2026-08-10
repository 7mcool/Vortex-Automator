"""Transcription maison, pour repérer la prédication quand YouTube se tait.

Pourquoi ce module existe (constaté le 10/08/2026) :

1. Un direct qui vient de se terminer n'a PAS encore de sous-titres YouTube —
   ils mettent des heures à apparaître. Or c'est précisément ce direct-là
   qu'on veut découper le soir même.
2. Le VPS, lui, ne peut plus rien lire du tout : YouTube bloque son adresse
   de datacenter (« Sign in to confirm you're not a bot »), quels que soient
   les cookies. Les mêmes cookies fonctionnent depuis le PC de Michel.

Ce module tourne donc SUR LE PC. Il télécharge la piste audio, en écoute des
échantillons répartis sur toute la durée, et rend un relevé de paroles
horodaté — exactement la forme que `fenetre.trouver()` attend en entrée.

On ne transcrit PAS les trois heures : à 45 secondes toutes les 5 minutes, on
couvre la vidéo entière pour un dixième du temps de calcul, et c'est amplement
suffisant pour reconnaître où la louange s'arrête et où la prédication
commence — on cherche un CHANGEMENT DE NATURE du discours, pas un verbatim.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent

# Un sondage toutes les 5 minutes, de 45 secondes. Sur un direct de 3 h cela
# fait 36 sondages, 27 minutes d'audio écoutées au lieu de 180.
PAS_S = 300
ECHANTILLON_S = 45


class EcouteError(RuntimeError):
    pass


def _cookies() -> str:
    from .fenetre import _cookies_youtube
    return _cookies_youtube()


def _moteur_js() -> list[str]:
    """yt-dlp exige un moteur JavaScript pour les défis anti-bot YouTube."""
    for moteur in ("deno", "node", "bun"):
        if shutil.which(moteur):
            return ["--js-runtimes", moteur]
    return []


def telecharger_audio(youtube_id: str, dossier: Path) -> Path:
    """Télécharge la piste audio seule. Retourne le chemin du fichier.

    Audio seul : un direct de 3 h pèse ainsi quelques dizaines de mégaoctets
    au lieu de plusieurs gigaoctets, et rien de tout cela ne transite par le
    serveur.
    """
    gabarit = str(dossier / f"{youtube_id}.%(ext)s")
    commande = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio/best",
        "--no-playlist", "--no-progress", "--quiet", "--no-warnings",
        "-o", gabarit,
        f"https://www.youtube.com/watch?v={youtube_id}",
    ]
    cookies = _cookies()
    if cookies:
        commande += ["--cookies", cookies]
    commande += _moteur_js()

    log.info("Téléchargement de la piste audio de %s…", youtube_id)
    resultat = subprocess.run(commande, capture_output=True, text=True, timeout=3600)
    fichiers = list(dossier.glob(f"{youtube_id}.*"))
    if not fichiers:
        detail = (resultat.stderr or resultat.stdout or "").strip()[:300]
        raise EcouteError(f"audio de {youtube_id} non téléchargé : {detail}")
    return fichiers[0]


def _extraire(source: Path, debut_s: int, duree_s: int, cible: Path) -> bool:
    """Découpe un échantillon en WAV 16 kHz mono (le format attendu par Whisper)."""
    commande = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-ss", str(debut_s), "-t", str(duree_s), "-i", str(source),
        "-ac", "1", "-ar", "16000", "-vn", str(cible),
    ]
    subprocess.run(commande, capture_output=True, timeout=180)
    return cible.is_file() and cible.stat().st_size > 1000


def transcrire_par_sondages(youtube_id: str, duree_s: int, *,
                            modele: str = "small", pas_s: int = PAS_S,
                            echantillon_s: int = ECHANTILLON_S,
                            ) -> list[tuple[float, str]]:
    """Relevé de paroles horodaté, obtenu par échantillonnage.

    Retourne une liste de (seconde, texte) directement exploitable par
    `fenetre.resumer_par_tranches()` puis `fenetre.trouver(lignes=…)`.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise EcouteError("faster-whisper absent — `pip install faster-whisper`") from exc

    if not shutil.which("ffmpeg"):
        raise EcouteError("ffmpeg absent du système")

    lignes: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory(prefix="vortex-ecoute-") as tmp:
        dossier = Path(tmp)
        audio = telecharger_audio(youtube_id, dossier)

        log.info("Chargement du modèle Whisper « %s »…", modele)
        moteur = WhisperModel(modele, device="cpu", compute_type="int8")

        points = list(range(0, max(0, duree_s - echantillon_s), pas_s))
        log.info("%d sondages de %d s sur %d min de vidéo",
                 len(points), echantillon_s, duree_s // 60)

        for i, depart in enumerate(points, 1):
            morceau = dossier / f"s{depart}.wav"
            if not _extraire(audio, depart, echantillon_s, morceau):
                continue
            try:
                segments, _ = moteur.transcribe(
                    str(morceau), language="fr", vad_filter=True,
                    condition_on_previous_text=False,
                )
                for seg in segments:
                    texte = (seg.text or "").strip()
                    if texte:
                        lignes.append((depart + seg.start, texte))
            except Exception:
                log.exception("Sondage à %ds illisible", depart)
            finally:
                morceau.unlink(missing_ok=True)
            if i % 6 == 0:
                log.info("  … %d/%d sondages", i, len(points))

    log.info("Transcription de %s : %d répliques relevées", youtube_id, len(lignes))
    return lignes


def reperer(youtube_id: str, duree_s: int, *, largeur_max_s: int,
            largeur_min_s: int = 600, modele: str = "small") -> dict:
    """Fenêtre de prédication, sous-titres YouTube d'abord, transcription ensuite.

    L'ordre compte : les sous-titres sont gratuits et immédiats quand ils
    existent. On ne dépense du temps de calcul que lorsqu'ils manquent.
    """
    from . import fenetre as mod_fenetre

    try:
        lignes = mod_fenetre.sous_titres_youtube(youtube_id)
        log.info("Sous-titres YouTube disponibles pour %s (%d lignes)",
                 youtube_id, len(lignes))
        resultat = mod_fenetre.trouver(youtube_id, duree_s,
                                       largeur_max_s=largeur_max_s,
                                       largeur_min_s=largeur_min_s,
                                       lignes=lignes)
        resultat["source"] = f"{resultat.get('source', 'IA')} (sous-titres YouTube)"
        return resultat
    except mod_fenetre.FenetreError as exc:
        log.info("Pas de sous-titres pour %s (%s) — on écoute la vidéo",
                 youtube_id, exc)

    lignes = transcrire_par_sondages(youtube_id, duree_s, modele=modele)
    if not lignes:
        raise EcouteError(f"aucune parole relevée sur {youtube_id}")
    resultat = mod_fenetre.trouver(youtube_id, duree_s,
                                   largeur_max_s=largeur_max_s,
                                   largeur_min_s=largeur_min_s,
                                   lignes=lignes)
    resultat["source"] = f"{resultat.get('source', 'IA')} (transcription maison)"
    return resultat

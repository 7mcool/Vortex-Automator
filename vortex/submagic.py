"""Client Submagic — le découpage intelligent est délégué à leur IA.

Pourquoi Submagic plutôt que notre propre découpeur (supprimé le 31/07) :

1. **Submagic télécharge la vidéo lui-même** depuis l'URL YouTube. Fini le
   blocage anti-robot des hébergeurs, fini les 7,5 Go d'un direct de 3 h qui
   dorment sur le disque du serveur, fini le passage obligé par le PC.
2. Il rend un clip **fini** : recadrage vertical suivant le visage, sous-titres
   animés, montage. C'est ce que notre moteur n'arrivait pas à égaler.
3. Il note chaque extrait (`viralityScores`). C'est exactement le levier qui
   manquait : à 4 publications par jour, ce n'est pas la cadence qui compte,
   c'est le CHOIX — l'écart entre une bonne et une mauvaise vidéo va de 1 à 20.

Ce que Vortex garde pour lui : la veille des chaînes, le dédoublonnage, le
choix des extraits sur la note, le SEO/hashtags français, et la livraison.

La clé vit dans .env (SUBMAGIC_API_KEY), jamais dans le code.
Doc : https://docs.submagic.co
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger("vortex.submagic")

API = "https://api.submagic.co/v1"

# 1 crédit Magic Clips par projet, quelle que soit la durée de la source :
# il vaut donc toujours mieux envoyer un direct de 3 h qu'un extrait de 10 min.
COUT_CREDIT_PAR_PROJET = 1

# Un projet Magic Clips passe par : processing -> (transcribing) -> completed.
ETATS_FINIS = {"completed", "failed"}


class SubmagicError(RuntimeError):
    """Erreur remontée par l'API (message lisible pour le journal)."""


def available() -> bool:
    return bool(os.environ.get("SUBMAGIC_API_KEY"))


def _requete(methode: str, chemin: str, corps: dict | None = None, *,
             essais: int = 3, timeout: int = 90) -> dict:
    cle = os.environ.get("SUBMAGIC_API_KEY")
    if not cle:
        raise SubmagicError("SUBMAGIC_API_KEY absente de l'environnement (.env)")

    data = json.dumps(corps).encode() if corps is not None else None
    entetes = {"x-api-key": cle}
    if data:
        entetes["Content-Type"] = "application/json"

    derniere = ""
    for tentative in range(essais):
        req = urllib.request.Request(f"{API}{chemin}", data=data, headers=entetes, method=methode)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            derniere = f"HTTP {exc.code} {detail}"
            # 4xx = la demande est fautive (crédits épuisés, URL invalide,
            # projet inconnu) : réessayer ne ferait que répéter la même erreur.
            # Seul 429 (trop de requêtes) mérite une nouvelle tentative.
            if 400 <= exc.code < 500 and exc.code != 429:
                raise SubmagicError(derniere) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            derniere = str(exc)
        log.warning("Submagic %s %s — tentative %d/%d : %s",
                    methode, chemin, tentative + 1, essais, derniere)
        time.sleep(3 * (tentative + 1))
    raise SubmagicError(derniere or "échec inconnu")


# --------------------------------------------------------------- création
def creer_magic_clips(*, titre: str, url_youtube: str, langue: str = "fr",
                      duree_min: int = 30, duree_max: int = 120,
                      gabarit: str = "Sara", suivi_visage: bool = True,
                      webhook: str = "") -> dict:
    """Lance le découpage d'une vidéo YouTube. Consomme 1 crédit Magic Clips.

    Retourne le projet créé (au minimum {id, status}). Le découpage est
    asynchrone : interroger `projet(id)` jusqu'à un état fini.
    """
    # Bornes de l'API : 1-100 pour le titre, 15-300 s pour les durées. On les
    # applique ici pour que l'erreur soit lisible dans NOTRE journal plutôt
    # qu'un 400 opaque une fois le crédit engagé.
    corps = {
        "title": (titre or "Vortex")[:100],
        "language": langue,
        "youtubeUrl": url_youtube,
        "minClipLength": max(15, min(300, int(duree_min))),
        "maxClipLength": max(15, min(300, int(duree_max))),
        "faceTracking": bool(suivi_visage),
        "templateName": gabarit,
    }
    if corps["maxClipLength"] < corps["minClipLength"]:
        corps["maxClipLength"] = corps["minClipLength"]
    if webhook:
        corps["webhookUrl"] = webhook
    return _requete("POST", "/projects/magic-clips", corps, timeout=120)


def projet(projet_id: str) -> dict:
    """État complet d'un projet, extraits compris quand il est terminé."""
    return _requete("GET", f"/projects/{projet_id}")


def gabarits() -> list[str]:
    return list(_requete("GET", "/templates").get("templates", []))


def texte_des_mots(donnees: dict, maxi: int = 6000) -> str:
    """Recolle la transcription horodatée d'un projet en texte lisible."""
    morceaux = []
    for mot in donnees.get("words") or []:
        if isinstance(mot, dict):
            texte = mot.get("word") or mot.get("text") or ""
        else:
            texte = str(mot or "")
        if texte:
            morceaux.append(str(texte))
    return " ".join(morceaux).strip()[:maxi]


def transcription_clip(clip_id: str) -> str:
    """Ce qui est dit DANS un extrait précis.

    La réponse Magic Clips ne donne ni le début ni la fin de chaque extrait
    dans le sermon d'origine : impossible de découper la transcription globale
    à la bonne tranche. Mais chaque extrait est lui-même un projet Submagic
    (son `previewUrl` est une adresse /view/<id> de projet), donc l'interroger
    directement rend SA transcription. Sans elle, le SEO n'aurait que le titre
    anglophone de Submagic pour travailler.

    Retourne une chaîne vide si l'extrait n'est pas interrogeable — l'appelant
    se rabat alors sur le titre.
    """
    if not clip_id:
        return ""
    try:
        return texte_des_mots(projet(clip_id))
    except SubmagicError as exc:
        log.info("Transcription de l'extrait %s indisponible : %s", clip_id, exc)
        return ""


# ------------------------------------------------------------- extraction
def _note(scores: dict, *cles: str) -> float:
    """Lit une note quel que soit le nom exact renvoyé (l'API mélange les styles)."""
    for cle in cles:
        for variante in (cle, cle.replace("_", ""), cle.lower()):
            if variante in scores:
                try:
                    return float(scores[variante])
                except (TypeError, ValueError):
                    return 0.0
    return 0.0


def clips_du_projet(donnees: dict) -> list[dict]:
    """Normalise la liste des extraits d'un projet terminé.

    Les noms de champs de l'API sont en anglais et pas tous garantis d'un
    projet à l'autre ; on ne garde que les extraits réellement téléchargeables.
    """
    bruts = donnees.get("magicClips") or donnees.get("clips") or []
    sortie = []
    for c in bruts:
        if not isinstance(c, dict):
            continue
        lien = c.get("downloadUrl") or c.get("directUrl") or ""
        if not lien:
            continue
        scores = c.get("viralityScores") or {}
        if not isinstance(scores, dict):
            scores = {}
        sortie.append({
            "id": str(c.get("id") or ""),
            "titre": (c.get("title") or "").strip(),
            "duree_s": float(c.get("duration") or 0),
            "etat": (c.get("status") or "").lower(),
            "score_total": _note(scores, "total", "overall"),
            "score_hook": _note(scores, "hook_strength", "hookStrength"),
            "score_partage": _note(scores, "shareability"),
            "score_histoire": _note(scores, "story_quality", "storyQuality"),
            "score_emotion": _note(scores, "emotional_impact", "emotionalImpact"),
            "download_url": c.get("downloadUrl") or "",
            "direct_url": c.get("directUrl") or "",
            "preview_url": c.get("previewUrl") or "",
        })
    # Le meilleur d'abord : c'est l'ordre dans lequel le pipeline retient.
    sortie.sort(key=lambda c: c["score_total"], reverse=True)
    return sortie


def publier(projet_id: str, plateformes: dict, planifie_pour: str = "") -> dict:
    """Publie un projet exporté vers les réseaux reliés au compte Submagic.

    Voie de secours pour TikTok : l'app « Sophos Publisher » a été REFUSÉE le
    31/07, donc l'API TikTok officielle nous est fermée. Submagic, lui, a déjà
    l'autorisation de publier — il suffit de relier le compte TikTok dans son
    tableau de bord (section Publishing). Non branché par défaut : Michel
    valide d'abord les extraits reçus par courriel.
    """
    corps: dict = {"platforms": plateformes}
    if planifie_pour:
        corps["scheduledFor"] = planifie_pour
    return _requete("POST", f"/projects/{projet_id}/publish", corps, timeout=120)

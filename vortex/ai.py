"""Renfort IA (DeepSeek) pour le SEO : titres, descriptions, tags.

- Corrige les erreurs de transcription (Whisper entend parfois de travers).
- Génère un titre accrocheur mais FIDÈLE au contenu (règles YouTube).
- La clé vit dans .env (DEEPSEEK_API_KEY), jamais dans le code.
- En cas d'échec (réseau, solde, réponse invalide), le pipeline retombe
  automatiquement sur la génération locale de metadata.py — jamais de
  métadonnées génériques publiées en silence.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger("vortex.ai")

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

PROMPT = """Tu es l'éditeur YouTube de la chaîne « {channel} », dédiée aux prédications et \
à la motivation chrétienne (en français, public francophone d'Afrique de l'Ouest).

ATTENTION — ORATEUR : les vidéos montrent différents prédicateurs (souvent l'un de : {speakers}). \
N'attribue un nom à la prédication QUE si l'orateur est clairement identifiable dans la légende \
ou la transcription (il se nomme, ou la légende le nomme). {speaker_hint}\
En cas de doute, n'emploie AUCUN nom propre : dis « le pasteur » ou « ce serviteur de Dieu ».

Voici les données d'une vidéo verticale de {duration:.0f} secondes :

LÉGENDE TIKTOK D'ORIGINE (peut être vide) :
{caption}

TRANSCRIPTION AUTOMATIQUE (contient des erreurs de reconnaissance vocale — corrige-les mentalement, \
par ex. « pastoie » = « pasteur ») :
{transcript}

Génère les métadonnées YouTube en JSON strict avec ces clés :
- "title" : titre accrocheur, 60 à 85 caractères, FIDÈLE au contenu, sans mensonge ni piège à clic, \
sans guillemets ni emoji, sans le mot Shorts (il sera ajouté automatiquement)
- "description" : 3 à 6 phrases : accroche forte, résumé fidèle du message, invitation à s'abonner \
et partager. Termine par 3 à 5 hashtags pertinents (#foi #motivation…)
- "tags" : liste de 12 à 15 mots-clés français pertinents (2-3 mots max chacun, total < 450 caractères)
- "hook" : la phrase la plus percutante du message, corrigée, max 100 caractères
- "speaker" : le nom de l'orateur SI clairement identifié, sinon chaîne vide ""
- "thumb_title" : titre ULTRA-COURT pour la miniature (4 à 6 mots, choc, MAJUSCULES naturelles, \
sans ponctuation finale) — ex : « Les ennemis de la foi »

Réponds UNIQUEMENT avec le JSON."""


def available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def generate_metadata(channel: str, speakers: list[str], caption: str, transcript: str,
                      duration: float, speaker_override: str = "") -> dict | None:
    """Retourne {title, description, tags, hook, speaker} ou None si l'IA est indisponible.

    speaker_override : orateur confirmé par un humain (prioritaire sur la détection)."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None

    speaker_hint = ""
    if speaker_override:
        speaker_hint = f"Pour CETTE vidéo, l'orateur confirmé est : {speaker_override}. "
    prompt = PROMPT.format(
        channel=channel, speakers=", ".join(speakers), speaker_hint=speaker_hint,
        duration=duration,
        caption=(caption or "(vide)")[:1500],
        transcript=(transcript or "(vide)")[:6000],
    )
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 1.0,
        "max_tokens": 900,
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                API_URL, data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=90) as r:
                resp = json.load(r)
            data = json.loads(resp["choices"][0]["message"]["content"])
            title = str(data.get("title", "")).strip()
            description = str(data.get("description", "")).strip()
            tags = [str(t).strip() for t in data.get("tags", []) if str(t).strip()]
            hook = str(data.get("hook", "")).strip()
            if not title or not description or len(tags) < 5:
                raise ValueError("réponse incomplète")
            # Garde-fous durs (limites API YouTube)
            while tags and len(", ".join(tags)) > 450:
                tags.pop()
            return {
                "title": title[:92],
                "description": description[:4800],
                "tags": tags[:15],
                "hook": hook[:100],
                "speaker": str(data.get("speaker", "")).strip(),
                "thumb_title": str(data.get("thumb_title", "")).strip()[:60],
            }
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError,
                ValueError, json.JSONDecodeError) as exc:
            log.warning("DeepSeek tentative %d/3 échouée : %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    log.error("DeepSeek indisponible — repli sur la génération locale.")
    return None

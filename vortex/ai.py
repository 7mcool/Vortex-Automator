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
# Modèle « Pro » (deepseek-v4-pro) pour la qualité du SEO — retour Michel 14/07 :
# utiliser la version Pro, pas le rapide. Vérifié : l'API n'expose que deux modèles,
# deepseek-v4-flash (rapide) et deepseek-v4-pro ; « deepseek-chat/reasoner » retombent
# sur le flash. Surchargeable via DEEPSEEK_MODEL.
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")


def _parse_json_obj(content: str) -> dict:
    """Extrait le 1er objet JSON d'une réponse (le modèle raisonnement peut
    l'entourer de texte ou de balises ```json)."""
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.lstrip().lower().startswith("json"):
            content = content.lstrip()[4:]
    try:
        return json.loads(content)
    except Exception:
        pass
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except Exception:
            pass
    return {}


# Ambiances visuelles autorisées pour la miniature (voir "thumb_theme").
THEMES_VISUELS = {
    "combat", "guerison", "priere", "prosperite", "avertissement",
    "esperance", "mort", "famille", "deliverance", "enseignement",
}
# Mots de liaison : une accroche qui finit dessus est un fragment coupé.
_MOTS_SUSPENDUS = {
    "et", "de", "des", "du", "la", "le", "les", "un", "une", "à", "au", "aux",
    "en", "ce", "cet", "cette", "qui", "que", "qu", "d", "l", "ou", "ni",
    "pour", "par", "sur", "dans", "avec", "sans", "mais", "donc", "car",
    "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes", "est", "sont",
}


def _clean_thumb_title(value) -> str:
    """Accepte l'accroche seulement si elle se lit seule.

    Le retour de Michel (24/07) portait sur des miniatures au « texte
    incompréhensible » : c'étaient des phrases coupées en plein milieu. Une
    accroche suspendue sur un mot de liaison, trop longue ou réduite à un ou
    deux mots est donc rejetée — le repli local reprend alors la main.
    """
    text = str(value or "").strip().strip("\"'«».,;:!?-—")
    if not text:
        return ""
    mots = text.split()
    # Le prompt demande 38 caractères ; on tolère jusqu'à 46 pour ne pas jeter
    # une bonne accroche qui dépasse de peu (la police s'adapte à l'affichage).
    if not 3 <= len(mots) <= 6 or len(text) > 46:
        return ""
    if mots[-1].lower().strip("'") in _MOTS_SUSPENDUS:
        return ""
    return text


def _clean_theme(value) -> str:
    theme = str(value or "").strip().lower()
    return theme if theme in THEMES_VISUELS else ""


PROMPT = """Tu es l'éditeur YouTube de la chaîne « {channel} », dédiée aux prédications et \
à la motivation chrétienne (en français, public francophone d'Afrique de l'Ouest).

ATTENTION — ORATEUR : les vidéos montrent différents prédicateurs (souvent l'un de : {speakers}). \
N'attribue un nom à la prédication QUE si l'orateur est clairement identifiable dans la légende \
ou la transcription (il se nomme, ou la légende le nomme). {speaker_hint}\
VÉRIFICATION : si la légende indique « Prédication de X » (le pasteur habituel de la chaîne source), \
renseigne "speaker" avec ce nom — SAUF si la transcription montre CLAIREMENT un AUTRE orateur ou un \
invité (on présente quelqu'un d'autre, une femme parle alors que X est un homme, etc.) : dans ce cas \
laisse "speaker" vide. \
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
- "thumb_title" : l'accroche de la miniature. C'est le texte que le spectateur lit AVANT de \
cliquer : il décide seul du clic. Règles impératives :
  * 3 à 6 mots, 38 caractères maximum ;
  * une idée COMPLÈTE et compréhensible seule, jamais un fragment de phrase coupé ;
  * il doit créer une tension : une promesse, un danger, un secret, un chiffre, un renversement ;
  * fidèle au contenu réel de la vidéo — aucune promesse que le message ne tient pas ;
  * pas de nom propre incertain, pas d'emoji, pas de ponctuation finale, pas de hashtag.
  BON : « Ce péché bloque ta prière », « Il est mort 20 minutes », « Dieu refuse ce jeûne », \
« L'erreur qui ruine ta foi »
  MAUVAIS : « Les ennemis de la foi » (plat, aucune tension), « Comment donner sans rater sa » \
(fragment coupé), « Message important pour toi » (creux, vrai pour tout)
- "thumb_theme" : UN SEUL mot-clé décrivant l'ambiance visuelle qui colle au message, choisi \
dans cette liste exacte : combat, guerison, priere, prosperite, avertissement, esperance, \
mort, famille, deliverance, enseignement

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
    reasoner = "reasoner" in MODEL
    # v4-pro EST un modèle de raisonnement : il consomme des reasoning_tokens
    # (mesuré : 1300-1800 tokens de réflexion AVANT la sortie) sur le budget
    # max_tokens. Avec 2000, la réflexion épuise le budget et le JSON SEO est
    # tronqué → « réponse incomplète » → repli local. On donne donc un gros
    # budget à tout modèle « pro »/« reasoner » (réflexion + sortie confortables).
    big_budget = reasoner or "pro" in MODEL
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 6000 if big_budget else 2000,
    }
    if not reasoner:  # deepseek-reasoner ignore/rejette temperature + response_format
        payload["response_format"] = {"type": "json_object"}
        payload["temperature"] = 1.0
    body = json.dumps(payload).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                API_URL, data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180 if big_budget else 90) as r:
                resp = json.load(r)
            data = _parse_json_obj(resp["choices"][0]["message"]["content"])
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
                # Une accroche trop longue serait tronquée à l'affichage et
                # redeviendrait le fragment illisible qu'on cherche à éviter :
                # mieux vaut la rejeter et laisser le repli local trancher.
                "thumb_title": _clean_thumb_title(data.get("thumb_title")),
                "thumb_theme": _clean_theme(data.get("thumb_theme")),
            }
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError,
                IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            log.warning("DeepSeek tentative %d/3 échouée : %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    log.error("DeepSeek indisponible — repli sur la génération locale.")
    return None

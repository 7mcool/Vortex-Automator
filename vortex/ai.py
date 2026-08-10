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
import re
import time
import unicodedata
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

ATTENTION — ORATEUR : les intervenants ne sont PAS tous des religieux (souvent l'un de : {speakers}). \
On y trouve des pasteurs et des prophètes, mais aussi des laïcs : un entrepreneur qui témoigne de sa \
réussite, un footballeur professionnel, des invités. N'attribue JAMAIS de titre religieux — « pasteur », \
« prophète », « serviteur de Dieu », « homme de Dieu » — à quelqu'un dont tu ne sais pas qu'il en porte un. \
N'attribue un nom QUE si l'orateur est clairement identifiable dans la légende ou la transcription \
(il se nomme, ou on le présente). {speaker_hint}\
PIÈGE À ÉVITER : la légende commence souvent par le nom du PROPRIÉTAIRE DU COMPTE qui republie \
(« @AVAHOUIN Hermann Djossè … »). Ce nom désigne celui qui PUBLIE, pas celui qui parle : il republie \
très souvent d'autres personnes. Ne l'utilise donc JAMAIS comme "speaker" sur la seule foi de la légende \
— il faut que la transcription montre que c'est bien lui qui s'exprime. Une prophétie d'un tiers lui a \
été attribuée à tort le 03/08/2026, et le titre est parti en ligne. \
En cas de doute, laisse "speaker" vide et n'emploie AUCUN nom propre : dis simplement « l'orateur ».

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


# --------------------------------------------------------------------------
# Légende TikTok d'un extrait de sermon découpé par Submagic.
#
# Submagic rend un extrait déjà monté et sous-titré, mais sa légende est
# générique et anglophone. Tout ce qui décide de la portée sur TikTok se joue
# ici : la première ligne (lue avant le déploiement du texte) et les hashtags.
PROMPT_CLIP = """Tu écris la légende TikTok d'un extrait de prédication chrétienne, \
en français, pour un public francophone d'Afrique de l'Ouest (Côte d'Ivoire, Bénin, Togo, \
Burkina, Sénégal, et diaspora).

EXTRAIT — titre donné par l'outil de découpage : {titre}
DURÉE : {duree:.0f} secondes
ORATEUR : {orateur}
⚠️ N'ajoute AUCUN titre à ce nom : s'il doit en porter un (« pasteur »,
« prophète »), il est déjà écrit ci-dessus. Ces chaînes reçoivent aussi des
laïcs — entrepreneurs, sportifs, invités. Si aucun orateur n'est indiqué, dis
« l'orateur » et jamais « le pasteur ».
ÉGLISE / CHAÎNE SOURCE : {eglise}
SERMON D'ORIGINE : {source}

CE QUI EST DIT DANS L'EXTRAIT (transcription automatique, peut contenir des erreurs \
de reconnaissance vocale — corrige-les mentalement) :
{transcription}

Rends un JSON strict avec ces clés :

- "accroche" : la PREMIÈRE ligne de la légende, 40 à 90 caractères. C'est la seule \
partie lue avant le clic sur « plus ». Elle doit créer une tension immédiate : une \
promesse, un danger, un renversement, une question qui dérange. Elle doit être VRAIE \
par rapport au contenu de l'extrait — aucune promesse que l'extrait ne tient pas. \
Pas de hashtag, pas d'emoji en début de ligne.
- "corps" : 1 à 3 phrases qui résument fidèlement le message et donnent envie de \
regarder jusqu'au bout. Termine par une invitation à commenter ou à partager.
- "hashtags" : 8 à 12 hashtags français SANS le caractère #, ordonnés du plus \
spécifique au plus large. Mélange obligatoire : 3 à 4 liés au SUJET PRÉCIS de \
l'extrait (ex. pardon, dettes, jeune, couple), 3 à 4 liés à la foi chrétienne \
francophone, 2 à 3 larges. Pas d'espace, pas d'accent, pas de majuscule, un seul mot \
ou des mots collés. Interdits : motsclés inventés, hashtags anglais, répétitions.
- "titre" : titre court et fidèle de l'extrait, 40 à 80 caractères, sans emoji, \
utilisable comme titre de Short YouTube.
- "sujet" : UN à TROIS mots qui nomment le thème réel de l'extrait (ex. « le pardon », \
« la dîme », « la peur de l'avenir »).
- "note" : entier de 0 à 100 — ta propre estimation de la force de cet extrait pris \
SEUL, sans le reste du sermon. Sois sévère : 90+ signifie qu'il se suffit à lui-même et \
qu'on le repartagerait. Moins de 40 signifie qu'il ne se comprend pas hors contexte.

Réponds UNIQUEMENT avec le JSON."""


def _eclater(valeurs) -> list[str]:
    """Accepte une liste OU une chaîne « a,b,c » / « #a #b ».

    Mesuré le 03/08 : malgré la consigne, deepseek-v4-pro rend parfois les
    hashtags en une seule chaîne séparée par des virgules. Sans ce garde-fou,
    `list("a,b,c")` donnait une liste de CARACTÈRES, tous rejetés — et la
    légende entière était déclarée incomplète puis abandonnée.
    """
    if valeurs is None:
        return []
    if isinstance(valeurs, str):
        return [m for m in re.split(r"[,;\s]+", valeurs) if m]
    sortie: list[str] = []
    for v in valeurs:
        sortie.extend(_eclater(v) if isinstance(v, (str, list, tuple)) else [str(v)])
    return sortie


def _nettoyer_hashtags(valeurs, fixes: list[str], maxi: int = 12) -> list[str]:
    """Normalise et dédoublonne, en gardant l'ordre. Les fixes viennent en fin."""
    sortie: list[str] = []
    vus: set[str] = set()
    for brut in _eclater(valeurs) + _eclater(fixes):
        tag = str(brut or "").strip().lstrip("#")
        if not tag:
            continue
        tag = unicodedata.normalize("NFD", tag)
        tag = "".join(c for c in tag if unicodedata.category(c) != "Mn")
        tag = "".join(c for c in tag.lower() if c.isalnum())
        # Un hashtag d'un ou deux caractères ne cible rien ; au-delà de 30 il
        # n'est plus tapé par personne.
        if not 3 <= len(tag) <= 30 or tag in vus:
            continue
        vus.add(tag)
        sortie.append(tag)
    return sortie[:maxi]


def generer_legende_clip(*, titre: str, duree: float, orateur: str, eglise: str,
                         source: str, transcription: str,
                         hashtags_fixes: list[str] | None = None) -> dict | None:
    """Légende TikTok d'un extrait : accroche, corps, hashtags, titre, note.

    Retourne None si l'IA est indisponible ou répond de travers — l'appelant
    retombe alors sur une légende locale (jamais rien de générique en silence).
    """
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None

    prompt = PROMPT_CLIP.format(
        titre=(titre or "(sans titre)")[:200],
        duree=duree or 0,
        orateur=orateur or "non identifié — n'invente aucun nom et aucun titre",
        eglise=eglise or "(inconnue)",
        source=(source or "(inconnu)")[:200],
        transcription=(transcription or "(non disponible)")[:6000],
    )
    reasoner = "reasoner" in MODEL
    big_budget = reasoner or "pro" in MODEL
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 6000 if big_budget else 2000,
    }
    if not reasoner:
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
            accroche = str(data.get("accroche", "")).strip().strip('"«»')
            corps = str(data.get("corps", "")).strip()
            hashtags = _nettoyer_hashtags(data.get("hashtags"), hashtags_fixes or [])
            if not accroche or len(hashtags) < 5:
                raise ValueError("réponse incomplète")
            try:
                note = max(0, min(100, int(float(data.get("note", 0)))))
            except (TypeError, ValueError):
                note = 0
            return {
                "accroche": accroche[:120],
                "corps": corps[:600],
                "hashtags": hashtags,
                "titre": str(data.get("titre", "")).strip()[:95] or accroche[:95],
                "sujet": str(data.get("sujet", "")).strip()[:60],
                "note_ia": note,
            }
        # TimeoutError doit figurer ici : un dépassement de délai en LECTURE
        # (le modèle réfléchit longtemps) ne passe pas par URLError, il
        # remontait donc tel quel et interrompait tout le traitement au lieu
        # de déclencher une nouvelle tentative. Constaté le 03/08 sur une
        # série de 25 légendes.
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                OSError, KeyError, IndexError, TypeError, ValueError,
                json.JSONDecodeError) as exc:
            log.warning("DeepSeek (légende clip) tentative %d/3 échouée : %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    log.error("DeepSeek indisponible — légende locale utilisée pour cet extrait.")
    return None


def generate_metadata(channel: str, speakers: list[str], caption: str, transcript: str,
                      duration: float, speaker_override: str = "") -> dict | None:
    """Retourne {title, description, tags, hook, speaker} ou None si l'IA est indisponible.

    speaker_override : orateur confirmé par un humain (prioritaire sur la détection)."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None

    speaker_hint = ""
    if speaker_override:
        from .intervenants import nomme
        # « pasteur Mohammed Sanogo », « Yann Amon » — le titre vient du registre,
        # jamais d'une supposition du modèle.
        speaker_hint = (f"Pour CETTE vidéo, l'orateur confirmé est : "
                        f"{nomme(speaker_override) or speaker_override}. ")

    # La liste vient du registre, avec le rôle de chacun : sans cela le modèle
    # voyait une suite de noms dans un contexte de prédication et en déduisait
    # que tous étaient pasteurs.
    from .intervenants import INTERVENANTS, role as _role
    connus = []
    for nom in (list(speakers) + list(INTERVENANTS)):
        if nom not in connus:
            connus.append(nom)
    listing = ", ".join(f"{n} ({_role(n)})" if _role(n) else f"{n} (laïc)"
                        for n in connus)

    prompt = PROMPT.format(
        channel=channel, speakers=listing, speaker_hint=speaker_hint,
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
        # TimeoutError doit figurer ici : un dépassement de délai en LECTURE
        # (le modèle réfléchit longtemps) ne passe pas par URLError, il
        # remontait donc tel quel et interrompait tout le traitement au lieu
        # de déclencher une nouvelle tentative. Constaté le 03/08 sur une
        # série de 25 légendes.
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                OSError, KeyError, IndexError, TypeError, ValueError,
                json.JSONDecodeError) as exc:
            log.warning("DeepSeek tentative %d/3 échouée : %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    log.error("DeepSeek indisponible — repli sur la génération locale.")
    return None

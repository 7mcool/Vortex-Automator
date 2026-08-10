"""Registre unique des personnes qui apparaissent dans les vidéos.

Avant ce fichier, trois listes séparées et toutes intitulées « pasteurs »
décrivaient les mêmes gens : `KNOWN_PASTORS` (textdetect), `SPEAKER_MARKERS`
(portraits) et `PASTOR_CHURCH` (pipeline). Elles divergeaient, et surtout elles
posaient que TOUT intervenant est un pasteur.

C'est faux, et Michel l'a corrigé le 03/08/2026 : l'archive contient aussi un
prophète, un entrepreneur, un footballeur et son propre père. Écrire « le
pasteur » à leur sujet est une erreur de fait, pas une maladresse de style.

Chaque entrée porte donc un RÔLE, utilisé pour formuler correctement les
descriptions et les légendes — et jamais deviné.
"""

from __future__ import annotations

import re
import unicodedata

# `role` : mot exact à employer devant le nom. Vide = aucun titre, on cite la
#          personne par son seul nom.
# `organisation` : église, entreprise, club — vide si inconnue.
# `motifs` : ce qui permet de la reconnaître à l'écran (OCR) ou dans un titre.
INTERVENANTS: dict[str, dict] = {
    "Jacques Amessan": {
        "role": "pasteur",
        "organisation": "La Maison de la Sagesse",
        "motifs": r"amess?an",
    },
    "Aimé Bodjiyé": {
        "role": "pasteur",
        "organisation": "Église Génération Daniel",
        "motifs": r"bodjiy|bodjy|generation daniel|génération daniel",
    },
    "Mohammed Sanogo": {
        "role": "pasteur",
        "organisation": "Église Vases d'Honneur",
        "motifs": r"sanogo|vases? d.?honneur",
    },
    "Yannick Djatti": {
        # Orthographe vérifiée sur ses comptes officiels (@Pasteurydjatti) :
        # Djatti prend deux T. La transcription rendait « Unique Jati ».
        "role": "pasteur",
        "organisation": "Centre Chrétien de Réveil",
        "motifs": r"dja?ti|djatti|centre chr.?tien de r.?veil|ccr",
    },
    "Mamadou Karambiri": {
        "role": "pasteur",
        "organisation": "Centre International d'Évangélisation",
        "motifs": r"karambiri",
    },
    "Marcello Tunassi": {
        "role": "pasteur",
        "organisation": "",
        "motifs": r"tunassi",
    },
    "Paulin Bakajika": {
        # « Pauline Bakajika » se lit parfois dans la base : c'est une faute de
        # frappe sur le même homme, que la normalisation ci-dessous rattrape.
        "role": "prophète",
        "organisation": "",
        "motifs": r"bakajika",
    },
    "Élie Padah": {
        "role": "prophète",
        "organisation": "",
        "motifs": r"padah|[ée]lie pada",
    },
    "Yann Amon": {
        # Entrepreneur, pas un religieux : il témoigne de sa réussite.
        "role": "entrepreneur",
        "organisation": "",
        "motifs": r"yann\s*amon",
    },
    "Jean-Michael Seri": {
        # Footballeur professionnel.
        "role": "footballeur",
        "organisation": "",
        "motifs": r"jean.?michael\s*seri|j\.?\s?m\.?\s?seri",
    },
    # Les quatre suivants portent le titre dans le nom même tel qu'il a été lu
    # sur la vidéo ou annoncé dans la légende : c'est la source qui l'affirme,
    # pas une déduction de notre part.
    "Yao Kouassi Emmanuel": {
        "role": "pasteur",
        "organisation": "",
        "motifs": r"yao\s*kouassi\s*emmanuel|emmanuel\s*kouassi",
    },
    "Huberson Lokpo": {
        "role": "pasteur",
        "organisation": "",
        "motifs": r"huberson\s*lokpo|lokpo",
    },
    "Jean-Pierre Arthur Kouassi": {
        "role": "pasteur",
        "organisation": "",
        "motifs": r"jean.?pierre\s*arthur\s*kouassi",
    },
    "Vaz Fernandes": {
        # Aucun titre lu nulle part : on le cite par son seul nom.
        "role": "",
        "organisation": "",
        "motifs": r"vaz\s*fernandes",
    },
    "Hermann Djossè": {
        # Père de Michel, et PROPRIÉTAIRE du compte TikTok @hedjav. Aucun titre
        # religieux. Voir `PROPRIETAIRE_DU_COMPTE` ci-dessous : son nom figure
        # dans les métadonnées de TOUTES les vidéos du compte, y compris celles
        # où quelqu'un d'autre parle.
        "role": "",
        "organisation": "",
        "motifs": r"avahouin|hermann\s*djoss",
    },
}

# Le compte @hedjav republie d'autres orateurs. Son propriétaire est nommé dans
# la légende et parfois à l'écran de vidéos où il ne parle PAS : le 03/08/2026,
# une prophétie d'Élie Padah lui avait été attribuée sur cette seule base, et la
# vidéo est partie en ligne sous un titre faux. On ne déduit donc JAMAIS qu'il
# est l'orateur : il faut une preuve dans le contenu lui-même.
PROPRIETAIRE_DU_COMPTE = "Hermann Djossè"


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFD", (value or "").lower())
    return "".join(c for c in value if not unicodedata.combining(c))


_MOTIFS = [
    (re.compile(donnees["motifs"], re.I), nom)
    for nom, donnees in INTERVENANTS.items()
]


def reconnaitre(texte: str, *, autoriser_proprietaire: bool = False) -> str | None:
    """Nom de l'intervenant reconnu dans un texte, ou None.

    `autoriser_proprietaire` reste faux par défaut : voir PROPRIETAIRE_DU_COMPTE.
    """
    brut = texte or ""
    sans_accent = _plain(brut)
    for motif, nom in _MOTIFS:
        if nom == PROPRIETAIRE_DU_COMPTE and not autoriser_proprietaire:
            continue
        if motif.search(brut) or motif.search(sans_accent):
            return nom
    return None


# La base contient le même homme sous « Jacques Amessan », « Jacques AMESSAN »,
# « Pasteur Mohammed Sanogo » ou « Elie Padah » sans accent. On indexe donc sur
# une forme normalisée — sans accent, sans casse, sans titre d'honneur — sinon
# la moitié des lignes ne retrouvait pas son rôle.
_TITRES = {"pasteur", "past", "pst", "pr", "prophete", "prophetesse",
           "evangeliste", "evangelist", "ev", "apotre", "reverend", "rev",
           "docteur", "dr", "frere", "soeur", "bishop", "mgr"}


# Fautes de frappe constatees en base, rattachees a la bonne personne.
_ALIAS = {
    "pauline bakajika": "paulin bakajika",
    "emmanuel kouassi": "yao kouassi emmanuel",
}


def _cle(nom: str) -> str:
    mots = [m for m in _plain(nom).replace(".", " ").split() if m]
    while mots and mots[0] in _TITRES:
        mots.pop(0)
    cle = " ".join(mots)
    return _ALIAS.get(cle, cle)


_INDEX = {_cle(nom): nom for nom in INTERVENANTS}


def canonique(nom: str) -> str:
    """Forme officielle du nom (« Jacques AMESSAN » -> « Jacques Amessan »)."""
    return _INDEX.get(_cle(nom), (nom or "").strip())


def role(nom: str) -> str:
    """« pasteur », « prophète », « entrepreneur »… ou '' si aucun titre."""
    return (INTERVENANTS.get(canonique(nom), {}) or {}).get("role", "")


def organisation(nom: str) -> str:
    return (INTERVENANTS.get(canonique(nom), {}) or {}).get("organisation", "")


def nomme(nom: str) -> str:
    """« pasteur Mohammed Sanogo », « Jean-Michael Seri » — jamais de titre inventé."""
    nom = canonique(nom)
    if not nom:
        return ""
    r = role(nom)
    return f"{r} {nom}" if r else nom


def designation_neutre() -> str:
    """Comment parler de quelqu'un qu'on n'a PAS identifié.

    Surtout pas « le pasteur » ni « ce serviteur de Dieu » : l'archive contient
    des laïcs, et ces formules affirment une qualité qu'on ignore.
    """
    return "l'orateur"

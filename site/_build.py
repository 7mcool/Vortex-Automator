"""Assemble le site : gabarit commun + contenu de chaque page."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _gabarit import page
from _contenu import ACCUEIL, FONCTIONNEMENT, CHAINE
from _legal import PRIVACY, TERMS

CIBLES = [
    ("index.html", "Accueil", "Sophos Publisher", ACCUEIL, False),
    ("fonctionnement.html", "Comment ça marche", "Comment fonctionne Sophos Publisher", FONCTIONNEMENT, False),
    ("chaine.html", "Notre chaîne", "La chaîne Sophos PropheTikos", CHAINE, False),
    ("privacy.html", "Confidentialité", "Politique de confidentialité", PRIVACY, True),
    ("terms.html", "Conditions", "Conditions d'utilisation", TERMS, True),
]
ici = Path(__file__).parent
for fichier, titre, h1, corps, legal in CIBLES:
    html = page(fichier, titre, h1, corps, legal=legal)
    (ici / fichier).write_text(html, encoding="utf-8")
    print(f"  {fichier:22} {len(html):6} octets")

"""Genere le site de Sophos Publisher, exige par la revue TikTok.

Le relecteur a refuse l'application le 29/07 pour quatre motifs, tous relatifs
au site :

  - l'URL ne devait pas etre une simple page d'atterrissage, mais un site
    reellement developpe et accessible publiquement ;
  - la politique de confidentialite etait juge insuffisante ;
  - les conditions d'utilisation etaient jugees insuffisantes ;
  - l'icone de l'application devait apparaitre dans l'onglet du navigateur ET
    en haut des pages legales.

Ce generateur produit donc un gabarit commun — en-tete avec l'icone, favicon,
navigation, pied de page — et cinq pages de contenu reel.

    python site/_gabarit.py        # ecrit les .html a cote
"""

from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parent
MAJ = "30 juillet 2026"
CONTACT = "hedjav@gmail.com"

PAGES = [
    ("index.html", "Accueil", "Sophos Publisher — publication assistée pour les ministères"),
    ("fonctionnement.html", "Comment ça marche", "Comment fonctionne Sophos Publisher"),
    ("chaine.html", "Notre chaîne", "La chaîne Sophos PropheTikos"),
    ("privacy.html", "Confidentialité", "Politique de confidentialité"),
    ("terms.html", "Conditions", "Conditions d'utilisation"),
]

STYLE = """
:root{--fond:#0d0d12;--carte:#16161f;--trait:#2a2a38;--encre:#e9e9f0;
      --doux:#9b9bab;--or:#d4a843;--lien:#7fb3ff}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--fond);color:var(--encre);
     font:16px/1.65 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--lien);text-decoration:none}
a:hover{text-decoration:underline}
.bandeau{border-bottom:1px solid var(--trait);background:#0a0a0f;
         position:sticky;top:0;z-index:10}
.bandeau .dedans{max-width:920px;margin:0 auto;padding:14px 22px;
                 display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.marque{display:flex;align-items:center;gap:12px;font-weight:700;font-size:1.05rem}
.marque img{width:42px;height:42px;border-radius:9px;display:block}
nav{margin-left:auto;display:flex;gap:18px;flex-wrap:wrap;font-size:.92rem}
nav a{color:var(--doux)}
nav a.ici{color:var(--or)}
main{max-width:920px;margin:0 auto;padding:38px 22px 60px}
h1{font-size:1.85rem;line-height:1.25;margin-bottom:10px}
h2{font-size:1.2rem;margin:34px 0 12px;padding-bottom:7px;
   border-bottom:1px solid var(--trait)}
h3{font-size:1.02rem;margin:22px 0 8px;color:var(--or)}
p,li{color:#d3d3de}
p{margin:12px 0}
ul,ol{margin:12px 0 12px 22px}
li{margin:7px 0}
.chapo{color:var(--doux);font-size:1.05rem;margin-bottom:26px}
.encart{background:var(--carte);border:1px solid var(--trait);
        border-radius:11px;padding:18px 20px;margin:22px 0}
.encart h3{margin-top:0}
.grille{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));margin:22px 0}
.duo{display:flex;align-items:center;gap:16px;margin-bottom:26px}
.duo img{width:76px;height:76px;border-radius:14px;flex:0 0 auto}
table{width:100%;border-collapse:collapse;margin:18px 0;font-size:.93rem}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--trait);vertical-align:top}
th{color:var(--or);font-weight:600}
code{background:#0a0a10;border:1px solid var(--trait);border-radius:5px;
     padding:1px 6px;font-size:.9em}
.date{color:var(--doux);font-size:.88rem}
footer{border-top:1px solid var(--trait);margin-top:50px}
footer .dedans{max-width:920px;margin:0 auto;padding:26px 22px;
               color:var(--doux);font-size:.88rem;
               display:flex;gap:16px;justify-content:space-between;flex-wrap:wrap}
footer nav{margin:0;gap:16px}
@media(max-width:620px){h1{font-size:1.5rem}nav{width:100%;margin-left:0}}
"""


def page(fichier: str, titre: str, h1: str, corps: str, legal: bool = False) -> str:
    liens = "".join(
        f'<a href="{f}"{" class=\'ici\'" if f == fichier else ""}>{n}</a>'
        for f, n, _ in PAGES
    )
    # Sur les pages legales, l'icone doit etre visible EN HAUT du contenu, pas
    # seulement dans le bandeau : c'est une exigence explicite du relecteur.
    entete = (
        f'<div class="duo"><img src="logo-1024.png" alt="Icône de Sophos Publisher">'
        f'<div><h1>{h1}</h1><p class="date">Dernière mise à jour : {MAJ}</p></div></div>'
        if legal else f"<h1>{h1}</h1>"
    )
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titre} — Sophos Publisher</title>
<meta name="description" content="Sophos Publisher : outil de publication assistée des prédications du ministère Sophos PropheTikos.">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="favicon-32.png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<style>{STYLE}</style>
</head>
<body>
<header class="bandeau"><div class="dedans">
  <span class="marque"><img src="logo-1024.png" alt="Icône de Sophos Publisher">Sophos Publisher</span>
  <nav>{liens}</nav>
</div></header>
<main>
{entete}
{corps}
</main>
<footer><div class="dedans">
  <span>Sophos Publisher — ministère Sophos PropheTikos, Cotonou (Bénin)</span>
  <nav><a href="privacy.html">Confidentialité</a><a href="terms.html">Conditions</a>
       <a href="mailto:{CONTACT}">Contact</a></nav>
</div></footer>
</body>
</html>
"""

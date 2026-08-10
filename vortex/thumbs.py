"""Covers v6 — maquette HTML/CSS rendue par un Chrome invisible (Playwright).

Chaîne par vidéo :
1. accroche courte (`thumb_title` de DeepSeek, sinon repli `derive_thumb_title`) ;
2. décor choisi selon l'ambiance du message (`thumb_theme`) ou photo du pasteur ;
3. mise en page ADAPTÉE au format demandé — 16:9 pour les vidéos, 9:16 pour les
   Shorts — puis photo de la maquette par Chrome (×3 → UHD).

Deux pannes réparées le 30/07/2026 (« les miniatures sont bad », Michel) :

* la maquette était figée à 1280×720 alors que le format vertical la
  photographiait dans une fenêtre 720×1280 : le texte sortait du cadre à droite
  et la moitié basse restait vide. Toute la géométrie est désormais calculée
  à partir des dimensions réelles demandées ;
* la police d'affichage (« Anton ») n'était installée nulle part sur le serveur.
  Chrome retombait sur un sans-serif large, bien plus encombrant que la taille
  estimée en Python : les lignes débordaient. La police est maintenant EMBARQUÉE
  dans la page (base64), et la taille du texte n'est plus estimée mais MESURÉE
  par le navigateur : on essaie toutes les coupes de lignes possibles et on
  garde celle qui autorise le plus gros texte tenant dans le cadre.
"""

from __future__ import annotations

import base64
import html as html_mod
import json
import logging
from pathlib import Path

from .config import Config
from .db import Database

log = logging.getLogger("vortex.thumbs")

# Espace de dessin (la capture est faite à ×3 → 3840×2160 ou 2160×3840).
W, H = 1280, 720
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"


def _b64(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def valid_thumbnail(path: str | Path | None) -> bool:
    """La miniature publiée doit être la génération UHD actuelle et <2 Mio."""
    if not path:
        return False
    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size > 2_000_000:
        return False
    try:
        from PIL import Image
        with Image.open(candidate) as image:
            return image.size in ((3840, 2160), (2160, 3840)) and image.format == "JPEG"
    except Exception:
        return False


_FONT_CACHE: str | None = None


def _font_face() -> str:
    """Police d'affichage EMBARQUÉE dans la page.

    Le conteneur n'a aucune police installée (`/usr/share/fonts` est vide) :
    sans cet embarquement, Chrome dessine avec son sans-serif de secours, large
    et banal — c'est ce qui faisait déborder le texte des covers.
    """
    global _FONT_CACHE
    if _FONT_CACHE is None:
        ttf = FONTS_DIR / "Anton-Regular.ttf"
        if ttf.is_file():
            _FONT_CACHE = (
                "@font-face{font-family:'CoverDisplay';font-style:normal;font-weight:400;"
                f"src:url({_b64(ttf.read_bytes(), 'font/ttf')}) format('truetype');}}"
            )
        else:
            log.warning("Police %s absente — rendu avec le sans-serif de secours", ttf.name)
            _FONT_CACHE = ""
    return _FONT_CACHE


# Mots qui portent la tension du message : ils passent en rouge.
IMPACT_WORDS = {"PAS", "JAMAIS", "ERREUR", "DANGER", "BLOQUE", "BLOQUES", "ATTENTION",
                "STOP", "FAUX", "PIÈGE", "PIEGE", "PÉCHÉ", "PECHE", "MORT", "PERDU",
                "PERDUES", "REFUSE", "TUE", "MENSONGE", "SECRET", "CACHÉE", "CACHÉ",
                "RIEN", "TROP", "TARD"}

STOP_TAIL = {":", "-", "—", "LA", "LE", "LES", "DE", "DES", "DU", "ET", "OU",
             "AVEC", "POUR", "QUI", "QUE", "EN", "UN", "UNE", "TA", "TON", "TES"}


def _short_words(title: str, max_words: int = 6) -> list[str]:
    words = title.replace(" #Shorts", "").strip().upper().split()
    truncated = len(words) > max_words
    words = words[:max_words]
    # jamais de fin bancale (« : LA… ») : on retire les petits mots de liaison
    while words and words[-1].strip(",;:-.…") in STOP_TAIL | {""}:
        words.pop()
        truncated = True
    if truncated and words:
        words[-1] = words[-1].rstrip(",;:-.") + "…"
    return words or ["MESSAGE", "PUISSANT"]


def _mots_json(title: str) -> str:
    """Les mots de l'accroche + leur mise en couleur, pour le calage navigateur."""
    mots = [{"t": w, "imp": w.rstrip("…!?.,") in IMPACT_WORDS} for w in _short_words(title)]
    return json.dumps(mots, ensure_ascii=False)


TINTS = [  # voile de couleur posé sur le décor (varié par vidéo)
    "rgba(30,6,50,.72)",   # violet nuit
    "rgba(5,10,40,.72)",   # bleu nuit
    "rgba(40,4,10,.74)",   # rouge sombre
    "rgba(20,14,2,.70)",   # brun doré
    "rgba(8,8,10,.74)",    # noir
]

COVER_ACCENTS = [  # (accent, halo r,g,b) — VARIÉS par vidéo (fini le tout-or)
    ("#00e5ff", "0,229,255"),    # cyan
    ("#ff3ea5", "255,62,165"),   # magenta
    ("#5cff7a", "92,255,122"),   # vert
    ("#ff8a2b", "255,138,43"),   # orange
    ("#4d9dff", "77,157,255"),   # bleu
    ("#ffd23e", "255,210,62"),   # or (une option)
    ("#c05cff", "192,92,255"),   # violet
]


# Ambiance du message → familles de décors qui lui correspondent. Michel a
# rejeté des miniatures au « fond incohérent » (24/07) : le décor était tiré au
# hasard, sans rapport avec le sujet. Le thème vient de l'IA (`thumb_theme`).
FONDS_PAR_THEME = {
    "combat":        ("nuages-dramatiques", "ciel-etoile"),
    "avertissement": ("nuages-dramatiques", "ciel-etoile"),
    "mort":          ("lumiere-tunnel", "nuages-dramatiques"),
    "deliverance":   ("lumiere-tunnel", "rayons-celestes"),
    "guerison":      ("lumiere-doree", "rayons-celestes"),
    "priere":        ("rayons-celestes", "lumiere-tunnel"),
    "esperance":     ("rayons-celestes", "lumiere-doree"),
    "prosperite":    ("abstrait-or", "lumiere-doree"),
    "famille":       ("marbre-clair", "lumiere-doree"),
    "enseignement":  ("marbre-clair", "abstrait-or"),
}


def _fond_uri(video_id: int, theme: str = "") -> str:
    """Décor de la miniature, choisi selon l'ambiance du message.

    À thème égal, `video_id` départage : deux vidéos du même sujet ne
    reçoivent pas le même décor, ce qui évite l'effet « produit en masse ».
    """
    fonds_dir = ASSETS_DIR / "fonds"
    if not fonds_dir.is_dir():
        return ""
    fonds = sorted(p for p in fonds_dir.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not fonds:
        return ""
    prefixes = FONDS_PAR_THEME.get((theme or "").lower())
    if prefixes:
        accordes = [p for p in fonds if p.name.startswith(prefixes)]
        # Un thème sans décor installé retombe sur la bibliothèque complète
        # plutôt que de faire échouer la miniature.
        if accordes:
            fonds = accordes
    return _b64(fonds[video_id % len(fonds)].read_bytes(), "image/jpeg")


# Script de calage : le navigateur MESURE le texte au lieu de laisser Python
# l'estimer. Il essaie toutes les découpes en lignes possibles et retient celle
# qui autorise le plus gros caractère tenant entièrement dans le cadre — plus
# aucun mot ne peut sortir de l'image, quelle que soit la police réellement
# utilisée ou la longueur de l'accroche.
_FIT_JS = r"""
const MOTS = @@MOTS@@, ACCENT = "@@ACCENT@@", ROUGE = "#ff2e2e";
const zone = document.getElementById('zone');
const titre = document.getElementById('titre');
const trait = document.getElementById('trait');

function batir(groupes) {
  titre.innerHTML = '';
  groupes.forEach(function (g, i) {
    const ligne = document.createElement('div');
    ligne.className = 'l';
    g.forEach(function (m, j) {
      const s = document.createElement('span');
      s.textContent = m.t;
      s.style.color = m.imp ? ROUGE : (i === 1 ? ACCENT : '#ffffff');
      ligne.appendChild(s);
      if (j < g.length - 1) ligne.appendChild(document.createTextNode(' '));
    });
    titre.appendChild(ligne);
  });
}

function tient(taille, maxW, maxH) {
  titre.style.fontSize = taille + 'px';
  titre.style.webkitTextStroke = Math.max(3, Math.round(taille * 0.03)) + 'px rgba(0,0,0,.92)';
  if (titre.scrollHeight > maxH) return false;
  for (const l of titre.children) if (l.scrollWidth > maxW) return false;
  return true;
}

function plusGrande(groupes, maxW, maxH) {
  batir(groupes);
  let bas = 18, haut = 460, meilleure = 0;
  while (bas <= haut) {
    const mid = (bas + haut) >> 1;
    if (tient(mid, maxW, maxH)) { meilleure = mid; bas = mid + 1; } else { haut = mid - 1; }
  }
  return meilleure;
}

// Toutes les façons de couper les mots en n lignes, l'ordre étant conservé.
function coupes(mots, n) {
  if (n === 1) return [[mots.slice()]];
  const res = [];
  for (let i = 1; i <= mots.length - (n - 1); i++) {
    for (const reste of coupes(mots.slice(i), n - 1)) res.push([mots.slice(0, i)].concat(reste));
  }
  return res;
}

function caler() {
  const maxW = zone.clientWidth;
  const maxH = zone.clientHeight - trait.offsetHeight - Math.round(zone.clientHeight * 0.06);
  let meilleur = null, taille = 0;
  for (let n = 1; n <= Math.min(MOTS.length, 4); n++) {
    for (const g of coupes(MOTS, n)) {
      const t = plusGrande(g, maxW, maxH);
      // À taille égale on préfère la découpe la plus équilibrée (moins de
      // lignes orphelines d'un seul mot).
      if (t > taille) { taille = t; meilleur = g; }
    }
  }
  if (!meilleur) { meilleur = [MOTS]; taille = 40; }
  batir(meilleur);
  tient(taille, maxW, maxH);
  return { taille: taille, lignes: meilleur.length };
}

// La police doit être CHARGÉE avant de mesurer. `fonts.ready` ne suffit pas :
// tant qu'aucun texte ne l'utilise, Chrome ne la télécharge pas, la promesse
// est donc déjà tenue et le calage se faisait sur le sans-serif de secours,
// bien plus large — d'où un texte final beaucoup plus petit que la place
// disponible. On force donc son chargement, puis on mesure.
if (document.fonts && document.fonts.load) {
  document.fonts.load("400 100px CoverDisplay")
    .then(function () { return document.fonts.ready; })
    .then(function () { window.__calage = caler(); })
    .catch(function () { window.__calage = caler(); });
} else {
  window.__calage = caler();
}
"""


def _geometrie(w: int, h: int, avec_photo: bool) -> dict:
    """Cadre de texte, logo et badge — calculés pour le format DEMANDÉ.

    C'est ici que se jouait la panne : la maquette raisonnait toujours en
    1280×720 même quand la capture était verticale.
    """
    marge = round(w * 0.05)
    logo = round(min(w, h) * 0.135)
    # Logo et badge se dimensionnent sur le PETIT côté : sinon le badge devient
    # énorme en 9:16, où la hauteur est le grand côté.
    badge_h = round(min(w, h) * 0.062)
    vertical = h > w

    if avec_photo and not vertical:
        # Poster : photo sur une moitié, texte sur l'autre.
        zone_w = round(w * 0.46)
        zone_h = round(h * 0.66)
        zone_top = round((h - zone_h) / 2)
        zone_x = marge
    elif avec_photo and vertical:
        # Vertical : texte en HAUT, photo en bas — le visage reste entier. Le
        # cadre de texte s'arrête là où le voile est encore opaque, sinon le
        # trait d'accent venait se poser sur le front du pasteur.
        zone_w = w - 2 * marge
        zone_top = marge + logo + round(h * 0.02)
        zone_h = round(h * 0.42) - zone_top
        zone_x = marge
    else:
        zone_w = w - 2 * marge
        zone_h = round(h * (0.62 if vertical else 0.64))
        zone_top = round((h - zone_h) / 2)
        zone_x = marge

    return {
        "marge": marge, "logo": logo, "badge_h": badge_h, "vertical": vertical,
        "zone_w": zone_w, "zone_h": zone_h, "zone_top": zone_top, "zone_x": zone_x,
    }


def _html(cfg: Config, video_id: int, title: str, w: int, h: int,
          theme: str = "", photo_uri: str = "") -> str:
    """Maquette de cover : décor (ou photo du pasteur), accroche géante calée
    par le navigateur, trait d'accent, logo de la chaîne et badge."""
    acc, rgb = COVER_ACCENTS[video_id % len(COVER_ACCENTS)]
    tint = TINTS[video_id % len(TINTS)]
    g = _geometrie(w, h, bool(photo_uri))
    gauche = video_id % 2 == 1          # pasteur à gauche ou à droite
    fond = "" if photo_uri else _fond_uri(video_id, theme)

    logo_uri = ""
    logo_file = ASSETS_DIR / "logo-chaine.png"
    if logo_file.exists():
        logo_uri = _b64(logo_file.read_bytes())

    # ---- décor -----------------------------------------------------------
    if photo_uri:
        # La photo se FOND dans le fond sombre par un masque dégradé, au lieu
        # d'être recouverte d'un voile opaque : plus de couture au raccord, et
        # surtout le visage garde sa lumière (il était noyé dans le noir).
        if g["vertical"]:
            photo_css = (
                f"left:0;bottom:0;width:100%;height:78%;"
                f"background:url('{photo_uri}') center/cover;"
                f"-webkit-mask-image:linear-gradient(180deg,transparent 0%,#000 17%);"
            )
            voile_css = "display:none;"
        else:
            cote = "left" if gauche else "right"
            sens = "90deg" if gauche else "270deg"
            photo_css = (
                f"{cote}:0;top:0;width:58%;height:100%;"
                f"background:url('{photo_uri}') center top/cover;"
                f"-webkit-mask-image:linear-gradient({sens},#000 78%,transparent 100%);"
            )
            voile_css = "display:none;"
        fond_body = "#0b0712"
    else:
        photo_css = voile_css = "display:none;"
        fond_body = (f"linear-gradient({tint},{tint}),url('{fond}') center/cover"
                     if fond else "linear-gradient(135deg,#14060f,#3a1030)")

    # Le texte est posé sur un voile sombre : sur un décor chargé, l'accroche
    # restait dure à lire (« couverture bad », Michel 30/07).
    zone_cx = round((g["zone_x"] + g["zone_w"] / 2) / w * 100)
    zone_cy = round((g["zone_top"] + g["zone_h"] / 2) / h * 100)

    modele = r"""<!doctype html><html><head><meta charset="utf-8"><style>
  @@FONT@@
  * { margin:0; padding:0; box-sizing:border-box; }
  body { width:@@W@@px; height:@@H@@px; overflow:hidden; position:relative;
         font-family:'CoverDisplay','Anton','Archivo Black',sans-serif;
         background:@@FOND_BODY@@; }
  .photo { position:absolute; z-index:1; @@PHOTO@@
           filter:saturate(1.20) contrast(1.08) brightness(1.04); }
  .voile { position:absolute; z-index:2; @@VOILE@@ }
  .vig { position:absolute; inset:0; z-index:3;
         background:radial-gradient(ellipse at @@CX@@% @@CY@@%, rgba(0,0,0,.55) 0%,
                    rgba(0,0,0,.34) 46%, transparent 72%),
                    radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,.52) 100%); }
  #zone { position:absolute; left:@@ZX@@px; top:@@ZT@@px;
          width:@@ZW@@px; height:@@ZH@@px; z-index:4;
          display:flex; flex-direction:column; align-items:center;
          justify-content:center; text-align:center; }
  /* 1.14 et non 1.04 : en capitales accentuées (« DÉCLENCHE »), l'accent du É
     venait toucher la ligne du dessus. */
  #titre { width:100%; line-height:1.14; letter-spacing:1px;
           text-shadow:0 4px 0 rgba(0,0,0,.55), 0 12px 30px rgba(0,0,0,.8),
                       0 0 40px rgba(@@RGB@@,.45); }
  #titre .l { white-space:nowrap; }
  #trait { @@TRAIT_VIS@@ width:62%; height:@@TRAIT@@px; margin-top:@@TMARGE@@px; border-radius:8px;
           transform:skewX(-16deg); flex:none;
           background:linear-gradient(90deg,transparent,@@ACC@@,#ffffff,@@ACC@@,transparent);
           box-shadow:0 0 26px rgba(@@RGB@@,.65); }
  .logo { position:absolute; top:@@MARGE@@px; left:@@MARGE@@px; z-index:6;
          width:@@LOGO@@px; height:@@LOGO@@px; border-radius:50%; border:4px solid #fff;
          box-shadow:0 8px 20px rgba(0,0,0,.55); }
  .badge { position:absolute; bottom:@@MARGE@@px; left:@@MARGE@@px; z-index:6;
           background:@@ACC@@; color:#0a0a12; font-weight:bold; white-space:nowrap;
           height:@@BADGE@@px; line-height:@@BADGE@@px; padding:0 @@BPAD@@px;
           font-size:@@BFS@@px; border-radius:@@BRAD@@px; border:3px solid #fff;
           font-family:'Archivo Black','DejaVu Sans',sans-serif;
           box-shadow:0 10px 24px rgba(0,0,0,.5),0 0 22px rgba(@@RGB@@,.5); }
</style></head><body>
  <div class="photo"></div><div class="voile"></div><div class="vig"></div>
  <div id="zone"><div id="titre"></div><div id="trait"></div></div>
  @@LOGO_IMG@@
  <div class="badge">@@CHAINE@@</div>
  <script>@@JS@@</script>
</body></html>"""

    remplace = {
        "@@FONT@@": _font_face(),
        "@@W@@": str(w), "@@H@@": str(h),
        "@@FOND_BODY@@": fond_body,
        "@@PHOTO@@": photo_css, "@@VOILE@@": voile_css,
        "@@CX@@": str(zone_cx), "@@CY@@": str(zone_cy),
        "@@ZX@@": str(g["zone_x"]), "@@ZT@@": str(g["zone_top"]),
        "@@ZW@@": str(g["zone_w"]), "@@ZH@@": str(g["zone_h"]),
        # En 9:16 avec photo, le texte s'arrête juste au-dessus du visage : le
        # trait d'accent venait alors barrer les yeux du pasteur.
        "@@TRAIT_VIS@@": "display:none;" if (g["vertical"] and photo_uri) else "",
        "@@TRAIT@@": str(max(6, round(min(w, h) * 0.018))),
        "@@TMARGE@@": str(round(min(w, h) * 0.035)),
        "@@ACC@@": acc, "@@RGB@@": rgb,
        "@@MARGE@@": str(g["marge"]), "@@LOGO@@": str(g["logo"]),
        "@@BADGE@@": str(g["badge_h"]),
        "@@BPAD@@": str(round(g["badge_h"] * 0.55)),
        "@@BFS@@": str(round(g["badge_h"] * 0.46)),
        "@@BRAD@@": str(round(g["badge_h"] / 2)),
        "@@LOGO_IMG@@": f'<img class="logo" src="{logo_uri}">' if logo_uri else "",
        "@@CHAINE@@": _echappe(cfg.channel_name.upper()),
        "@@JS@@": (_FIT_JS.replace("@@MOTS@@", _mots_json(title))
                          .replace("@@ACCENT@@", acc)),
    }
    for cle, valeur in remplace.items():
        modele = modele.replace(cle, valeur)
    return modele


def _echappe(texte: str) -> str:
    return html_mod.escape(texte)


def _portrait_raw(row, video_id: int) -> bytes | None:
    """Photo BRUTE du pasteur (sans détourage) depuis la bibliothèque, si l'orateur
    est identifié. Sert de fond de cover façon poster."""
    speaker = row["speaker"] if "speaker" in row.keys() and row["speaker"] else None
    if not speaker:
        return None
    folder = ASSETS_DIR / "portraits" / _slug(speaker)
    if not folder.is_dir():
        return None
    photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")
                    and not p.name.endswith(".cut.png"))
    if not photos:
        return None
    # Les portraits collectés automatiquement depuis les streams 1080p passent
    # avant les anciens screenshots. À défaut, refuser les sources minuscules :
    # les agrandir ne crée pas de détail et produisait les visages mous signalés.
    auto = [p for p in photos if p.name.startswith("auto-")]
    if auto:
        photos = auto
    else:
        try:
            from PIL import Image
            qualified = []
            for photo in photos:
                with Image.open(photo) as image:
                    width, height = image.size
                if width >= 700 and height >= 700:
                    qualified.append((width * height, photo))
            photos = [p for _, p in sorted(qualified, reverse=True)]
        except Exception as exc:
            log.warning("Contrôle qualité portraits impossible : %s", exc)
    if not photos:
        return None
    return photos[video_id % len(photos)].read_bytes()


def _portrait_video(row, vertical: bool) -> bytes | None:
    """Repli : le visage pris dans l'extrait lui-même.

    Sans ce repli, une vidéo dont l'orateur n'est pas identifié recevait une
    cover TOUT-TEXTE. Michel les a fait retirer le 10/08/2026 : elles ne
    rapportent rien. Le résultat est mis en cache — la recherche parcourt la
    vidéo entière, on ne la refait pas à chaque régénération.
    """
    chemin = None
    for colonne in ("render_path", "path"):
        if colonne in row.keys() and row[colonne]:
            candidat = Path(row[colonne])
            if candidat.is_file():
                chemin = candidat
                break
    if chemin is None:
        return None

    cache = ASSETS_DIR / "portraits" / "extraits"
    cache.mkdir(parents=True, exist_ok=True)
    fichier = cache / f"{row['name']}{'-v' if vertical else '-h'}.jpg"
    if fichier.is_file():
        return fichier.read_bytes()

    from .visage import portrait_depuis_video
    donnees = portrait_depuis_video(chemin, vertical=vertical)
    if donnees:
        fichier.write_bytes(donnees)
    return donnees


def _render_html(html: str, out_jpg: Path, vp_w: int = W, vp_h: int = H) -> bool:
    try:
        from PIL import Image
        from playwright.sync_api import sync_playwright
        masters = out_jpg.parent / "masters"
        masters.mkdir(parents=True, exist_ok=True)
        master = masters / out_jpg.name
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            # UHD (3840×2160 horizontal) ou VERTICAL (2160×3840 pour Shorts).
            # YouTube recommande 2160p pour les vignettes Shorts personnalisées.
            context = browser.new_context(
                viewport={"width": vp_w, "height": vp_h},
                device_scale_factor=3,
            )
            page = context.new_page()
            page.set_content(html)
            # Le calage du texte est fait par la page elle-même, APRÈS le
            # chargement de la police embarquée : photographier avant, c'est
            # capturer un texte encore mal dimensionné.
            try:
                page.wait_for_function("window.__calage !== undefined", timeout=20000)
                calage = page.evaluate("window.__calage")
                log.debug("Calage : %s", calage)
            except Exception as exc:
                log.warning("Calage du texte non confirmé (%s) — capture quand même", exc)
                page.wait_for_timeout(600)
            page.screenshot(path=str(master), type="jpeg", quality=95)
            context.close()
            browser.close()
        with Image.open(master) as image:
            final = image.convert("RGB")
            for quality in (92, 88, 84, 80, 76, 72, 68, 64, 60, 56, 52):
                final.save(out_jpg, "JPEG", quality=quality, optimize=True, progressive=True)
                if out_jpg.stat().st_size <= 1_900_000:
                    break
        if out_jpg.stat().st_size > 2_000_000:
            raise ValueError("miniature UHD impossible à compresser sous 2 Mio")
        return out_jpg.exists() and master.exists()
    except Exception as exc:
        log.error("Rendu Chrome impossible : %s", exc)
        return False


def _slug(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "-".join(s.split())


def est_short(row) -> bool:
    """Vrai Short (vidéo verticale) — et non « vidéo courte ».

    La durée seule ne suffit pas : le découpeur (supprimé depuis) produisait
    pour chaque extrait un jumeau HORIZONTAL de la même durée. Se fier à
    `duration_s <= 180` collait donc une couverture 9:16 à des vidéos 16:9
    (« cette vidéo n'est pas un short », Michel 30/07). La catégorie reste le
    bon critère pour tout le reste du catalogue.
    """
    categorie = (row["category"] or "") if "category" in row.keys() else ""
    if categorie:
        return categorie == "short"
    nom = (row["name"] or "") if "name" in row.keys() else ""
    return nom.endswith("_short")


def generate_thumb(cfg: Config, db: Database, video_id: int) -> bool:
    row = db.get(video_id)
    if row is None or not row["title"]:
        return False

    thumbs_dir = cfg.data_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    out = thumbs_dir / f"{row['name']}.jpg"

    # Le titre SEO fait 60-90 caractères : affiché tel quel sur la miniature, il
    # était tronqué et devenait illisible (« texte incompréhensible », Michel
    # 24/07). On redérive donc une accroche courte au lieu de le recopier.
    thumb_title = (row["thumb_title"] or "").strip() if "thumb_title" in row.keys() else ""
    if not thumb_title:
        from .metadata import derive_thumb_title
        thumb_title = derive_thumb_title(row["title"] or "")
    if not thumb_title:
        # Dernier recours : sans miniature la vidéo ne serait jamais publiée
        # (garde-fou du pipeline). Mieux vaut un titre raccourci proprement.
        mots = [m for m in (row["title"] or "").split() if any(c.isalnum() for c in m)]
        thumb_title = " ".join(mots[:5]).upper()
    if not thumb_title:
        log.warning("Aucun texte exploitable pour %s — miniature reportée", row["name"])
        return False

    theme = (row["thumb_theme"] or "") if "thumb_theme" in row.keys() else ""

    # Format : 9:16 pour les vrais Shorts (verticaux), 16:9 pour le reste.
    vertical = est_short(row)
    vp_w, vp_h = (H, W) if vertical else (W, H)

    # Cover PRO sans détourage : photo BRUTE du pasteur en poster (retour Michel
    # 15/07 : « plus de détouré, pas pro »).
    photo = _portrait_raw(row, video_id)
    if not photo:
        # Orateur non identifié : on va chercher son visage DANS l'extrait.
        # Le décor abstrait ne sert plus que de dernier recours — une cover
        # tout-texte est ce que Michel a fait retirer de la chaîne le 10/08.
        photo = _portrait_video(row, vertical)
    if not photo:
        log.warning("Aucun visage disponible pour %s — cover de repli sur décor",
                    row["name"])

    html = _html(cfg, video_id, thumb_title, vp_w, vp_h,
                 theme=theme, photo_uri=_b64(photo) if photo else "")

    if not _render_html(html, out, vp_w=vp_w, vp_h=vp_h):
        return False

    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "thumb_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN thumb_path TEXT")
        db.conn.commit()
    db.update_fields(video_id, thumb_path=str(out))
    log.info("Cover générée : %s [%s %dx%d]", out.name,
             "VERTICAL" if vertical else "horizontal", vp_w * 3, vp_h * 3)
    return True


def thumbs_pending(cfg: Config, db: Database, limit: int = 0) -> int:
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(videos)")]
    if "thumb_path" not in cols:
        db.conn.execute("ALTER TABLE videos ADD COLUMN thumb_path TEXT")
        db.conn.commit()
    # Covers pour TOUTES les vidéos, Shorts compris (décision de Michel :
    # c'est la cover qui fait cliquer dans la recherche et sur la page chaîne).
    rows = db.conn.execute(
        "SELECT id, thumb_path FROM videos WHERE state = 'READY' "
        # Même ordre que la publication : le récent d'abord.
        "ORDER BY rowid DESC, "
        "CASE WHEN duration_s BETWEEN 30 AND 180 THEN 0 ELSE 1 END, "
        "duration_s DESC").fetchall()
    done = 0
    for r in rows:
        if limit and done >= limit:
            break
        if valid_thumbnail(r["thumb_path"]):
            continue
        if r["thumb_path"]:
            db.update_fields(r["id"], thumb_path=None)
        if generate_thumb(cfg, db, r["id"]):
            done += 1
    return done

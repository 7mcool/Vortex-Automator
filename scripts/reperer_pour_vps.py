"""Repere la predication des sermons en attente, et depose le resultat sur le VPS.

POURQUOI CE PONT (constate le 10/08/2026)

Le serveur ne peut plus lire YouTube : son adresse de datacenter est bloquee
(« Sign in to confirm you're not a bot »), et les memes cookies qui marchent
depuis le PC y echouent. Il ne peut donc ni lire les sous-titres, ni
telecharger l'audio — donc pas de reperage precis de la predication.

Sans reperage, il retombe sur la regle proportionnelle (coeur du sermon vers
69 % de la video). C'est honnete en moyenne, mais sur un direct de 3 h cela
peut coller a cote et faire payer 45 credits de louange.

Ce script tourne SUR LE PC, ou YouTube repond. Il :
  1. demande au serveur quels sermons attendent une fenetre ;
  2. la calcule ici (sous-titres si YouTube les a deja generes, sinon
     transcription maison par sondages — voir vortex/ecoute.py) ;
  3. ecrit le resultat dans la base du serveur.

    python scripts/reperer_pour_vps.py            # tous ceux qui attendent
    python scripts/reperer_pour_vps.py -n 1       # le plus urgent seulement

A lancer apres chaque nouveau direct — ou automatiquement, via la tache
planifiee du PC.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

# La console Windows est en cp1252 : sans ceci, un titre accentue fait planter
# l'affichage avant meme que le reperage commence.
for flux in (sys.stdout, sys.stderr):
    try:
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CLE = Path(os.environ.get("USERPROFILE", Path.home())) / ".ssh" / "vortex_vps"
HOTE = "root@srv1769401.hstgr.cloud"
DB_VPS = "/opt/vortex/repo/data/vortex.db"
SSH = ["ssh", "-i", str(CLE), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]

log = logging.getLogger("reperage")


def _python_sur_vps(code: str) -> str:
    """Execute un bout de Python sur le serveur, renvoie sa sortie.

    Le code passe par l'entree standard : aucun echappement de guillemets,
    d'accents ni de sauts de ligne a gerer.
    """
    fait = subprocess.run(SSH + [HOTE, "python3 -"], input=code,
                          text=True, capture_output=True, encoding="utf-8")
    if fait.returncode != 0:
        raise RuntimeError((fait.stderr or "").strip()[:400])
    return fait.stdout


def sermons_en_attente(handles: list[str], bascule: str, combien: int) -> list[dict]:
    """Les sermons du serveur qui n'ont pas encore de fenetre reperee."""
    code = f"""
import json, sqlite3
db = sqlite3.connect({DB_VPS!r})
db.row_factory = sqlite3.Row
lignes = db.execute('''
    SELECT youtube_id, titre, duration_s, published_at, handle, etat
    FROM sources_yt
    WHERE etat IN ('REPERE', 'A_CONFIRMER')
      AND handle IN ({','.join(repr(h) for h in handles)})
      AND published_at >= ?
      AND duration_s IS NOT NULL AND duration_s > 0
      AND (fenetre_debut_s IS NULL OR fenetre_fin_s IS NULL)
    ORDER BY published_at DESC
''', ({bascule!r},)).fetchall()
print(json.dumps([dict(r) for r in lignes]))
"""
    sortie = _python_sur_vps(code).strip()
    tout = json.loads(sortie) if sortie else []
    return tout[:combien] if combien else tout


def deposer_fenetre(youtube_id: str, vue: dict) -> None:
    """Ecrit la fenetre reperee dans la base du serveur."""
    code = f"""
import sqlite3, datetime
db = sqlite3.connect({DB_VPS!r}, timeout=15)
db.execute('PRAGMA busy_timeout = 15000')
db.execute('''UPDATE sources_yt
              SET fenetre_debut_s = ?, fenetre_fin_s = ?, fenetre_certitude = ?,
                  fenetre_source = ?, fenetre_raison = ?, updated_at = ?
              WHERE youtube_id = ?''',
           ({int(vue['debut_s'])}, {int(vue['fin_s'])},
            {str(vue.get('certitude', ''))[:20]!r},
            {str(vue.get('source', ''))[:120]!r},
            {str(vue.get('raison', ''))[:300]!r},
            datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            {youtube_id!r}))
db.commit()
print('depose')
"""
    _python_sur_vps(code)


def _hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--count", type=int, default=0,
                        help="nombre de sermons a traiter (0 = tous)")
    parser.add_argument("--modele", default="small",
                        help="modele Whisper pour la transcription (small par defaut)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    if not CLE.is_file():
        sys.exit(f"Cle SSH introuvable : {CLE}")

    from vortex import ecoute
    from vortex.config import load_config

    cfg = load_config()
    handles = list(cfg.opus_chaines_reservees) or ["JACAMESSANLIVE", "lamaisondesagesse"]

    try:
        sermons = sermons_en_attente(handles, cfg.opus_traiter_a_partir_de, args.count)
    except RuntimeError as exc:
        sys.exit(f"Le serveur n'a pas repondu : {exc}")

    if not sermons:
        print("Aucun sermon n'attend de reperage.")
        return 0

    print(f"{len(sermons)} sermon(s) a reperer.\n")
    reussis = 0
    for s in sermons:
        duree = int(s["duration_s"])
        print(f"  {(s['titre'] or '')[:66]}")
        print(f"  {s['youtube_id']} — {duree // 60} min — {s['etat']}")
        try:
            vue = ecoute.reperer(s["youtube_id"], duree,
                                 largeur_max_s=cfg.opus_fenetre_max_s,
                                 largeur_min_s=cfg.opus_fenetre_min_s,
                                 modele=args.modele)
        except Exception as exc:
            print(f"  ECHEC : {exc}\n")
            continue

        largeur = (vue["fin_s"] - vue["debut_s"]) // 60
        print(f"  -> {_hms(vue['debut_s'])} a {_hms(vue['fin_s'])} ({largeur} min)")
        print(f"     certitude {vue.get('certitude', '?')} — {vue.get('source', '?')}")
        print(f"     {str(vue.get('raison', ''))[:120]}")

        # ON NE DEPOSE QUE CE QUI A ETE REELLEMENT ANALYSE.
        #
        # Une fenetre issue de la regle proportionnelle n'apporte rien au
        # serveur : il sait la calculer seul. Pire, la deposer la ferait
        # passer pour un reperage verifie, et le sermon partirait tout seul
        # sur une supposition pendant que Michel dort. Le silence ne vaut
        # accord que lorsqu'on sait vraiment ou est la predication.
        if not vue.get("precise"):
            print("     PAS DEPOSE : fenetre supposee (regle des 69 %),")
            print("     Michel devra repondre lui-meme.\n")
            continue
        try:
            deposer_fenetre(s["youtube_id"], vue)
            print("     depose sur le serveur\n")
            reussis += 1
        except RuntimeError as exc:
            print(f"     DEPOT ECHOUE : {exc}\n")

    print(f"{reussis}/{len(sermons)} fenetre(s) deposee(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

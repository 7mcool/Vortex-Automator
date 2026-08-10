"""Lanceur SERVEUR — pose les miniatures preparees par le PC.

Michel, 10/08/2026 : « que mon ordi soit allume ou pas tout doit passer ».

Le serveur ne sait PAS fabriquer ces miniatures : YouTube lui refuse tout
telechargement (« Sign in to confirm you're not a bot », verifie le 10/08
avec et sans cookies, depuis le conteneur). Il sait en revanche tres bien en
POSER une, puisque c'est lui qui publie chaque jour.

Le PC depose donc les images pretes dans data/miniatures_pretes/ (par scp) et
ce script les pose, quelques-unes a la fois, PC eteint.

Aucun risque de doublon avec le PC : avant de poser, on regarde la miniature
reellement en ligne. Une video deja traitee montre un visage et n'est plus
proposee.

    python3 /app/vps/poser_miniatures.py [nombre]
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app")

from vortex.miniatures import main  # noqa: E402

if __name__ == "__main__":
    combien = sys.argv[1] if len(sys.argv) > 1 else "6"
    raise SystemExit(main(["--poser", combien]))

"""Lanceur PC — remplacement des miniatures tout-texte de la chaîne.

Tout est dans `vortex/miniatures.py` : le module est copié dans l'image du
serveur (le Dockerfile n'embarque que `vortex/`, `assets/` et `vps/`), et les
deux machines partagent donc exactement le même code.

    python scripts/refaire_miniatures_youtube.py --analyser
    python scripts/refaire_miniatures_youtube.py --preparer 20 --envoyer
    python scripts/refaire_miniatures_youtube.py --poser 6
    python scripts/refaire_miniatures_youtube.py --resultats
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vortex.miniatures import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

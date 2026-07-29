"""Enregistre un habillage fait ailleurs (renfort depuis le PC).

Appele avec des arguments simples plutot que via une commande SQL passee par
SSH : empiler les guillemets de PowerShell, de SSH, du shell distant et de
Python finissait toujours par casser sur une parenthese.

    python3 /app/vps/maj_rendu.py <id> <chemin_rendu> [chemin_miniature]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path("/app/data/vortex.db")


def main() -> None:
    if len(sys.argv) < 3:
        print("usage : maj_rendu.py <id> <rendu> [miniature]")
        raise SystemExit(1)

    video_id = int(sys.argv[1])
    rendu = sys.argv[2]
    miniature = sys.argv[3] if len(sys.argv) > 3 else ""

    # Ne rien enregistrer qui n'existe pas : une base qui affirme un fichier
    # absent bloque la publication sans expliquer pourquoi.
    if not Path(rendu).is_file():
        print(f"rendu introuvable : {rendu}")
        raise SystemExit(2)

    db = sqlite3.connect(DB)
    if miniature and Path(miniature).is_file():
        db.execute("UPDATE videos SET render_path = ?, thumb_path = ? WHERE id = ?",
                   (rendu, miniature, video_id))
    else:
        db.execute("UPDATE videos SET render_path = ? WHERE id = ?",
                   (rendu, video_id))
    db.commit()
    db.close()
    print(f"video {video_id} : habillage enregistre")


if __name__ == "__main__":
    main()

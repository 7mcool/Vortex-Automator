"""Interface en ligne de commande.

    python -m vortex scan                  # détecter les vidéos (états DISCOVERED)
    python -m vortex transcribe [-n N]     # transcrire N vidéos (Whisper local)
    python -m vortex prepare [-n N]        # générer titre/description/tags
    python -m vortex plan [-n N]           # SIMULATION : afficher le plan de publication
    python -m vortex publish [-n N] --live # upload privé + programmation RÉELLE
    python -m vortex sync-channel          # lister les vidéos déjà sur la chaîne
    python -m vortex status                # compteurs par état
    python -m vortex auth                  # lancer/valider l'authentification OAuth

Par défaut TOUT est en simulation : seul `publish --live` touche YouTube
(et `sync-channel` / `auth`, en lecture seule ou consentement).
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .db import Database


def setup_logging(cfg) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(cfg.logs_dir / "vortex.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vortex", description="Vortex Automator — pipeline YouTube")
    parser.add_argument("command", choices=[
        "scan", "transcribe", "prepare", "plan", "publish", "sync-channel", "status", "auth", "retry",
    ])
    parser.add_argument("-n", "--count", type=int, default=5,
                        help="nombre de vidéos à traiter (défaut : 5)")
    parser.add_argument("--live", action="store_true",
                        help="désactive la simulation pour `publish` (upload réel, privé)")
    parser.add_argument("--config", default=None, help="chemin du config.toml")
    args = parser.parse_args(argv)

    from pathlib import Path
    cfg = load_config(Path(args.config) if args.config else None)
    setup_logging(cfg)
    db = Database(cfg.db_file)

    try:
        if args.command == "scan":
            from .scanner import scan
            stats = scan(cfg, db)
            print(f"Scan : {stats['seen']} vues, {stats['new']} nouvelles, "
                  f"{stats['known']} déjà connues, {stats['blocked']} bloquées, "
                  f"{stats['too_short']} trop courtes")

        elif args.command == "transcribe":
            from .transcribe import transcribe_pending
            n = transcribe_pending(cfg, db, limit=args.count)
            print(f"{n} vidéo(s) transcrite(s)")

        elif args.command == "prepare":
            from .metadata import prepare_pending
            n = prepare_pending(cfg, db, limit=args.count)
            print(f"{n} vidéo(s) prête(s) (titre/description/tags générés)")

        elif args.command in ("plan", "publish"):
            from .pipeline import plan_batch, execute_plan
            live = args.command == "publish" and args.live
            if args.command == "publish" and not args.live:
                print("`publish` sans --live = simulation. Ajoute --live pour envoyer réellement.")
            plan = plan_batch(cfg, db, args.count)
            execute_plan(cfg, db, plan, live=live)

        elif args.command == "retry":
            from .pipeline import retry_failed
            n = retry_failed(db)
            print(f"{n} vidéo(s) FAILED remise(s) en file (READY)")

        elif args.command == "sync-channel":
            from .pipeline import sync_channel
            n = sync_channel(cfg, db)
            print(f"{n} vidéo(s) déjà en ligne sur la chaîne (référence enregistrée)")

        elif args.command == "auth":
            from .youtube_client import get_service
            service = get_service(cfg)
            me = service.channels().list(part="snippet", mine=True).execute()
            title = me["items"][0]["snippet"]["title"] if me.get("items") else "?"
            print(f"Authentifié ✔ — chaîne : {title}")

        elif args.command == "status":
            counts = db.counts()
            total = sum(counts.values())
            print(f"Total : {total} vidéo(s)")
            for state, n in sorted(counts.items()):
                print(f"  {state:<12} {n}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

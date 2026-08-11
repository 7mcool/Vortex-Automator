"""Interface en ligne de commande.

    python -m vortex scan                  # détecter les vidéos (états DISCOVERED)
    python -m vortex transcribe [-n N]     # transcrire N vidéos (Whisper local)
    python -m vortex prepare [-n N]        # générer titre/description/tags
    python -m vortex plan [-n N]           # SIMULATION : afficher le plan de publication
    python -m vortex publish [-n N] --live # upload privé + programmation RÉELLE
    python -m vortex sync-channel          # lister les vidéos déjà sur la chaîne
    python -m vortex status                # compteurs par état
    python -m vortex auth                  # lancer/valider l'authentification OAuth

Découpage des longues vidéos YouTube (Submagic) :

    python -m vortex veille                # repérer les nouveaux directs des chaînes visées
    python -m vortex veille --resoudre     # afficher l'identifiant UC… des chaînes configurées
    python -m vortex clip [-n N]           # envoyer N sources au découpage (1 crédit chacune)
    python -m vortex recolter              # récupérer les extraits finis, noter, rédiger le SEO
    python -m vortex livrer [-n N]         # expédier les extraits retenus par courriel
    python -m vortex tiktok --live         # programmer les extraits sur TikTok (via Submagic)
    python -m vortex clips                 # état du découpage

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
        "scan", "transcribe", "prepare", "plan", "publish", "sync-channel", "status", "auth",
        "retry", "engage", "detect-text", "render", "thumbs",
        "story", "backfill-social", "detect-speaker",
        "veille", "clip", "recolter", "livrer", "clips", "tiktok", "opus",
        "confirmer", "valider", "habiller",
    ])
    parser.add_argument("--source", default=None,
                        help="`opus` : identifiant YouTube de la vidéo à traiter")
    parser.add_argument("--debut", default=None,
                        help="`opus` : forcer le début de la fenêtre (1:53:00)")
    parser.add_argument("--fin", default=None,
                        help="`opus` : forcer la fin de la fenêtre (2:53:00)")
    parser.add_argument("-n", "--count", type=int, default=5,
                        help="nombre de vidéos à traiter (défaut : 5)")
    parser.add_argument("--resoudre", action="store_true",
                        help="`veille` : afficher l'identifiant UC… de chaque chaîne configurée")
    parser.add_argument("--live", action="store_true",
                        help="désactive la simulation pour `publish` (upload réel, privé)")
    parser.add_argument("--maintenant", action="store_true",
                        help="publie tout de suite, hors grille horaire "
                             "(contenu d'actualité : conférence, direct du jour)")
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
            execute_plan(cfg, db, plan, live=live, tout_de_suite=args.maintenant)

        elif args.command == "engage":
            from .engage import run_engagement
            stats = run_engagement(cfg, db, max_actions=args.count if args.count != 5 else 20)
            print(f"Engagement : {stats}")

        elif args.command == "detect-text":
            from .textdetect import detect_pending
            stats = detect_pending(cfg, db, limit=args.count)
            print(f"Détection de texte : {stats}")

        elif args.command == "detect-speaker":
            from .textdetect import detect_speaker_pending
            stats = detect_speaker_pending(cfg, db, limit=args.count)
            print(f"Identification du pasteur : {stats}")

        elif args.command == "render":
            from .render import render_pending
            n = render_pending(cfg, db, limit=args.count)
            print(f"{n} vidéo(s) habillée(s) (hook + CTA + filigrane)")

        elif args.command == "thumbs":
            from .thumbs import thumbs_pending
            n = thumbs_pending(cfg, db, limit=args.count)
            print(f"{n} cover(s) générée(s) (style violet/or)")

        elif args.command == "story":
            from .pipeline import publish_daily_story
            res = publish_daily_story(cfg, db)
            print(f"Story du jour : {res}")

        elif args.command == "backfill-social":
            from .pipeline import backfill_social
            n = backfill_social(cfg, db, count=args.count if args.count != 5 else 12)
            print(f"Backfill : {n} clip(s) posté(s) sur Facebook + Instagram")

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

        elif args.command == "veille":
            from .veille import resoudre_handle, veiller
            if args.resoudre:
                for chaine in cfg.chaines_surveillees:
                    handle = chaine.get("handle", "")
                    trouve = resoudre_handle(handle) if handle else ""
                    marque = "=" if trouve == chaine.get("id") else "≠ À CORRIGER"
                    print(f"@{handle:<24} config={chaine.get('id','(vide)'):<26} "
                          f"réel={trouve or '(introuvable)':<26} {marque}")
            else:
                bilan = veiller(cfg, db)
                print(f"Veille : {bilan['vues']} vidéo(s) examinée(s), "
                      f"{bilan['nouvelles']} nouvelle(s) source(s) longue(s), "
                      f"{bilan.get('deja_connues', 0)} déjà connue(s), "
                      f"{bilan.get('trop_courtes', 0)} trop courte(s), "
                      f"{bilan.get('doublons', 0)} doublon(s) inter-chaînes")

        elif args.command == "clip":
            from .clipping import envoyer
            bilan = envoyer(cfg, db, limite=args.count if args.count != 5 else 0)
            print(f"Découpage : {bilan}")

        elif args.command == "recolter":
            from .clipping import recolter
            bilan = recolter(cfg, db, limite=args.count if args.count != 5 else 0)
            print(f"Récolte : {bilan}")

        elif args.command == "livrer":
            from .livraison import livrer
            bilan = livrer(cfg, db, limite=args.count if args.count != 5 else 0)
            print(f"Livraison : {bilan}")

        elif args.command == "opus":
            from . import opusclip
            if not opusclip.available():
                print("OPUSCLIP_API_KEY absente de .env")
                return 1
            if args.source:
                sources = [db.conn.execute(
                    "SELECT * FROM sources_yt WHERE youtube_id = ?", (args.source,)).fetchone()]
                if sources[0] is None:
                    print(f"Source inconnue : {args.source} — lance `vortex veille` d'abord.")
                    return 1
            else:
                # ⚠️ PLAFOND QUOTIDIEN. Le 10/08, le cycle automatique a
                # dépensé 90 crédits en vingt minutes : rien ne bridait la
                # cadence, seul le total mensuel était surveillé. On compte
                # donc d'abord ce qui est déjà parti AUJOURD'HUI.
                from datetime import datetime, timedelta, timezone
                debut_jour = (datetime.now(timezone.utc) - timedelta(hours=24)
                              ).strftime("%Y-%m-%dT%H:%M:%SZ")
                deja_aujourdhui = db.sources_envoyees_depuis(debut_jour)
                place = max(0, cfg.opus_sermons_par_jour - deja_aujourdhui)
                if place <= 0:
                    print(f"  Plafond du jour atteint : {deja_aujourdhui} sermon(s) "
                          f"envoyé(s) en 24 h (maximum {cfg.opus_sermons_par_jour}).")
                    return 0

                combien = min(place, args.count if args.count != 5 else place)
                sources, tri = opusclip.choisir_sources(cfg, db, combien)
                detail = (f"{tri['examinees']} sermon(s) en réserve : "
                          f"{tri['avant_bascule']} d'avant le {cfg.opus_traiter_a_partir_de}, "
                          f"{tri['trop_vieilles']} trop vieux")
                if tri.get("hors_reserve"):
                    detail += (f", {tri['hors_reserve']} hors des chaînes réservées "
                               f"(budget gardé pour Jacques Amessan jusqu'au "
                               f"{cfg.opus_jour_ouverture_autres} du mois)")
                print(f"  {detail}, {tri['retenues']} retenu(s).")
            if not sources:
                print("Aucun sermon récent à traiter. La veille en trouvera de nouveaux.")
                return 0

            # Budget RÉEL : ce qui a déjà été engagé depuis le 1er du mois.
            # L'API OpusClip n'expose aucun solde, donc c'est notre base
            # compte seule — et elle doit refléter les envois passés, sinon
            # elle laisserait dépasser le forfait sans rien dire.
            from datetime import datetime, timezone
            debut_mois = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            deja = db.credits_depenses_depuis(debut_mois)
            restants = cfg.opus_credits_par_mois - deja
            if deja:
                print(f"  {deja} crédit(s) déjà engagé(s) ce mois-ci, {restants} restant(s).")

            depense = 0
            for src in sources:
                try:
                    plan = opusclip.preparer(cfg, src)
                    # Fenêtre imposée à la main : elle prime sur le repérage.
                    if args.debut and args.fin:
                        d, f = opusclip.en_secondes(args.debut), opusclip.en_secondes(args.fin)
                        credits = opusclip.verifier_fenetre(
                            d, f, plan["duree_s"], cfg.opus_credits_max_par_projet)
                        plan["fenetre"] = {"debut_s": d, "fin_s": f, "certitude": "haute",
                                           "raison": "fenêtre imposée à la main",
                                           "source": "Michel"}
                        plan["credits"] = credits
                        plan["demande"]["curationPref"]["range"] = {"startSec": d, "endSec": f}
                except opusclip.OpusError as exc:
                    print(f"\n  {src['youtube_id']} — ÉCARTÉ : {exc}")
                    continue

                if plan["credits"] > restants - depense:
                    print(f"\n  {plan['titre'][:60]}")
                    print(f"  ÉCARTÉ : il faudrait {plan['credits']} crédits, "
                          f"il n'en reste que {restants - depense} ce mois-ci.")
                    break

                opusclip.afficher_plan(plan, restants - depense)
                if not args.live:
                    # On décompte aussi en simulation : sans cela, chaque ligne
                    # affichait le budget de départ et on ne voyait pas si le
                    # lot entier tenait dans le mois.
                    depense += plan["credits"]
                    continue
                try:
                    projet = opusclip.creer_projet(plan["demande"])
                except opusclip.OpusError as exc:
                    print(f"  ENVOI REFUSÉ : {exc}")
                    continue
                depense += plan["credits"]
                db.maj_source(src["youtube_id"], etat="ENVOYE",
                              submagic_id=f"opus:{projet.get('id', '')}",
                              credits=plan["credits"],
                              envoye_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                print(f"  ✔ envoyé — projet {projet.get('id', '?')}")

            if not args.live:
                print(f"\n  SIMULATION — rien n'a été envoyé, aucun crédit consommé.")
                print(f"  Ce lot coûterait {depense} crédits ; il en reste "
                      f"{restants} ce mois-ci.")
                print("  Ajoute --live pour lancer réellement.")
            else:
                print(f"\n  {depense} crédit(s) consommé(s), "
                      f"{restants - depense} restants ce mois-ci.")

        elif args.command == "tiktok":
            from .clipping import publier_tiktok
            if not args.live:
                print("`tiktok` sans --live = simulation. Ajoute --live pour programmer réellement.")
            bilan = publier_tiktok(cfg, db, limite=args.count if args.count != 5 else 0,
                                   live=args.live)
            print(f"TikTok : {bilan}")

        elif args.command == "clips":
            compteurs = db.compteurs_clipping()
            print("Sources YouTube longues :")
            for etat, n in sorted(compteurs["sources"].items()):
                print(f"  {etat:<10} {n}")
            print("Extraits :")
            for etat, n in sorted(compteurs["clips"].items()):
                print(f"  {etat:<10} {n}")
            for clip in db.clips_par_etat("RETENU", limit=10):
                print(f"  · {clip['score_total'] or 0:>3.0f}/100  "
                      f"{(clip['titre'] or '')[:64]}")

        elif args.command == "habiller":
            from .habillage import habiller
            from pathlib import Path as _P
            if not args.source:
                print("Usage : vortex habiller --source fichier.mp4")
                return 1
            entree = _P(args.source)
            sortie = entree.with_name(f"{entree.stem}-habille.mp4")
            print(f"Habillage -> {habiller(entree, sortie)}")

        elif args.command == "confirmer":
            from .confirmer import confirmer
            bilan = confirmer(cfg, db, limite=args.count if args.count != 5 else 1)
            print(f"Confirmation : {bilan['proposes']} proposé(s), "
                  f"{bilan['envoyes']} notifié(s), {bilan['erreurs']} erreur(s)")
            if bilan.get("raison"):
                print(f"  ({bilan['raison']})")

        elif args.command == "valider":
            from .valider import valider
            bilan = valider(cfg, db, live=args.live)
            print(f"Validation : {bilan['lances']} lancé(s) sur GO, "
                  f"{bilan.get('automatiques', 0)} parti(s) tout seul, "
                  f"{bilan['ecartes']} écarté(s), "
                  f"{bilan['rappels']} rappel(s), "
                  f"{bilan['abandonnes']} abandonné(s), "
                  f"{bilan['en_attente']} en attente")
            if bilan.get("raison"):
                print(f"  ({bilan['raison']})")

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

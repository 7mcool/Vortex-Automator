"""Releve les performances reelles des videos publiees.

Sans ces chiffres, tout choix de frequence de publication n'est qu'une
supposition. L'API YouTube donne les vues, les likes et les commentaires pour
cinquante videos par appel, pour une unite de quota — c'est negligeable.

    python3 /app/vps/stats_chaine.py [jours]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from vortex.config import load_config      # noqa: E402
from vortex import youtube_client          # noqa: E402

DB = Path("/app/data/vortex.db")


def _stats(service, identifiants: list[str]) -> dict:
    releve = {}
    for debut in range(0, len(identifiants), 50):
        lot = identifiants[debut:debut + 50]
        reponse = service.videos().list(
            part="statistics,snippet,contentDetails", id=",".join(lot)
        ).execute()
        for item in reponse.get("items", []):
            s = item.get("statistics", {})
            releve[item["id"]] = {
                "vues": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "commentaires": int(s.get("commentCount", 0)),
                "publiee": item["snippet"].get("publishedAt", ""),
                "titre": item["snippet"].get("title", ""),
                "duree": item.get("contentDetails", {}).get("duration", ""),
            }
    return releve


def main() -> None:
    jours = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()

    cfg = load_config()
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    lignes = db.execute(
        "SELECT youtube_id, name, publish_at, duration_s FROM videos "
        "WHERE state = 'PUBLISHED' AND youtube_id IS NOT NULL AND youtube_id != '' "
        "AND publish_at >= ? ORDER BY publish_at",
        (depuis,),
    ).fetchall()
    db.close()

    if not lignes:
        print("Aucune vidéo publiée sur la période.")
        return

    service = youtube_client.get_service(cfg)
    releve = _stats(service, [r["youtube_id"] for r in lignes])

    par_jour = defaultdict(list)
    for r in lignes:
        info = releve.get(r["youtube_id"])
        if not info:
            continue
        jour = (r["publish_at"] or "")[:10]
        par_jour[jour].append({**info, "duree_s": r["duration_s"] or 0})

    print(f"{len(releve)} vidéo(s) mesurée(s) sur {jours} jours\n")
    print(f"{'jour':12} {'nb':>3} {'vues tot':>9} {'vues/vidéo':>11} {'réactions':>10}")
    print("-" * 50)
    total_vues = total_videos = 0
    lignes_jour = []
    for jour in sorted(par_jour):
        v = par_jour[jour]
        vues = sum(x["vues"] for x in v)
        reactions = sum(x["likes"] + x["commentaires"] for x in v)
        total_vues += vues
        total_videos += len(v)
        lignes_jour.append((jour, len(v), vues, vues / len(v), reactions))
        print(f"{jour:12} {len(v):3} {vues:9} {vues / len(v):11.1f} {reactions:10}")

    print("-" * 50)
    print(f"{'TOTAL':12} {total_videos:3} {total_vues:9} "
          f"{total_vues / max(total_videos, 1):11.1f}")

    # Le point qui décide de la fréquence : publier plus fait-il monter le
    # total, ou seulement diluer l'audience sur davantage de vidéos ?
    print("\nRendement selon le nombre de publications dans la journée :")
    par_cadence = defaultdict(list)
    for _, nb, vues, moyenne, _r in lignes_jour:
        par_cadence[nb].append((vues, moyenne))
    for nb in sorted(par_cadence):
        groupe = par_cadence[nb]
        vues_jour = sum(g[0] for g in groupe) / len(groupe)
        par_video = sum(g[1] for g in groupe) / len(groupe)
        print(f"  {nb} vidéo(s)/jour : {vues_jour:7.1f} vues par jour, "
              f"{par_video:6.1f} par vidéo  ({len(groupe)} jour(s) observé(s))")

    meilleures = sorted(releve.values(), key=lambda x: -x["vues"])[:5]
    print("\nLes 5 vidéos les plus vues :")
    for m in meilleures:
        print(f"  {m['vues']:5} vues · {m['titre'][:62]}")

    sortie = Path("/app/data/stats_chaine.json")
    sortie.write_text(json.dumps(releve, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDétail complet : {sortie}")




def analyse_par_age() -> None:
    """Compare les cadences a AGE EGAL.

    Une video publiee hier a mecaniquement moins de vues qu'une video de la
    semaine derniere : comparer les cadences sans corriger ce biais conduirait
    a condamner a tort les journees les plus recentes. On mesure donc la
    vitesse d'acquisition — vues par jour d'existence — et on compare aussi
    les videos au meme age.
    """
    from collections import defaultdict
    from datetime import datetime, timezone

    releve = json.loads(Path("/app/data/stats_chaine.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    jour_de = {r["youtube_id"]: (r["publish_at"] or "")[:10]
               for r in db.execute(
                   "SELECT youtube_id, publish_at FROM videos WHERE youtube_id IS NOT NULL")}
    db.close()

    compte_jour = defaultdict(int)
    for vid in releve:
        j = jour_de.get(vid)
        if j:
            compte_jour[j] += 1

    maintenant = datetime.now(timezone.utc)
    par_cadence = defaultdict(list)
    for vid, info in releve.items():
        jour = jour_de.get(vid)
        if not jour or not info.get("publiee"):
            continue
        try:
            publiee = datetime.fromisoformat(info["publiee"].replace("Z", "+00:00"))
        except ValueError:
            continue
        age = max((maintenant - publiee).total_seconds() / 86400, 0.5)
        par_cadence[compte_jour[jour]].append((info["vues"], age))

    print("\nVitesse d'acquisition, biais d'age corrige :")
    print(f"  {'cadence':>10} {'vues/vidéo/jour':>17} {'vidéos':>8}")
    for nb in sorted(par_cadence):
        lot = par_cadence[nb]
        vitesse = sum(v / a for v, a in lot) / len(lot)
        print(f"  {nb:>4}/jour  {vitesse:17.1f} {len(lot):8}")

    print("\nÀ 3 jours d'existence exactement (comparaison la plus propre) :")
    for nb in sorted(par_cadence):
        jeunes = [v for v, a in par_cadence[nb] if 2.0 <= a <= 4.5]
        if jeunes:
            print(f"  {nb}/jour : {sum(jeunes) / len(jeunes):6.1f} vues/vidéo "
                  f"({len(jeunes)} vidéo(s))")


if __name__ == "__main__":
    main()
    analyse_par_age()

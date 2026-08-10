"""Verification : registre de credits local vs etat reel chez OpusClip.

Michel a supprime un projet le 10/08 ; la base, elle, compte toujours ses
credits. Ce script confronte les deux, puis liste les sermons d'Amessan
recents avec leur date et leur etat, pour decider de la bascule.

    docker compose -f docker-compose.vps.yml run --rm vortex python vps/verif_credits.py
"""

from datetime import datetime, timezone

from vortex import opusclip
from vortex.config import load_config
from vortex.db import Database

cfg = load_config()
db = Database(cfg.db_file)

print("=" * 78)
print("1. REGISTRE DE CREDITS (ce que dit la base)")
print("=" * 78)
debut_mois = datetime.now(timezone.utc).replace(
    day=1, hour=0, minute=0, second=0, microsecond=0
).strftime("%Y-%m-%dT%H:%M:%SZ")
lignes = db.conn.execute(
    "SELECT youtube_id, titre, submagic_id, credits, envoye_at, etat "
    "FROM sources_yt WHERE credits IS NOT NULL AND envoye_at >= ? "
    "ORDER BY envoye_at", (debut_mois,)).fetchall()
total = 0
for r in lignes:
    total += r["credits"] or 0
    print(f"  {r['envoye_at'][:16]} | {r['credits']:>3} cr | {r['etat']:<9} "
          f"| {r['submagic_id']}")
    print(f"                                        {(r['titre'] or '')[:56]}")
print(f"\n  TOTAL engage ce mois : {total} credits")
print(f"  => la base croit qu'il reste {cfg.opus_credits_par_mois - total} credits")

print()
print("=" * 78)
print("2. ETAT REEL CHEZ OPUSCLIP (verification par l'API)")
print("=" * 78)
if not opusclip.available():
    print("  OPUSCLIP_API_KEY absente — verification impossible.")
else:
    for r in lignes:
        pid = (r["submagic_id"] or "").replace("opus:", "")
        if not pid:
            continue
        try:
            donnees = opusclip.projet(pid)
            etat = opusclip.etat_projet(donnees)
            clips = opusclip.clips_du_projet(donnees)
            print(f"  {pid:<16} : {etat:<12} — {len(clips)} extrait(s)")
        except Exception as exc:
            print(f"  {pid:<16} : INTROUVABLE — {exc}")

print()
print("=" * 78)
print("3. SERMONS D'AMESSAN DEPUIS LE 1er AOUT")
print("=" * 78)
print(f"  (bascule actuelle : {cfg.opus_traiter_a_partir_de} — "
      f"fraicheur : {cfg.opus_fraicheur_max_jours} jours)")
print()
lignes = db.conn.execute(
    "SELECT youtube_id, handle, titre, published_at, duration_s, etat "
    "FROM sources_yt WHERE handle IN ('JACAMESSANLIVE', 'lamaisondesagesse') "
    "AND published_at >= '2026-08-01' ORDER BY published_at DESC").fetchall()
for r in lignes:
    mn = (r["duration_s"] or 0) // 60
    print(f"  {(r['published_at'] or '?')[:10]} | {mn:>3} min | {r['etat']:<11} "
          f"| {r['handle']:<18} | {(r['titre'] or '')[:48]}")
if not lignes:
    print("  (aucun)")

db.close()

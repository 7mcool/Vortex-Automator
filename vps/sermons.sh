#!/bin/sh
# Cycle complet des sermons longs — lancé par cron toutes les 30 minutes.
#
# Protocole en deux phases (Michel, 10/08) :
#   1. confirmer — détecte les nouveaux sermons d'Amessan, envoie un message
#      Telegram détaillé (titre, durée, fenêtre, coût), attend la réponse.
#   2. valider  — lit les réponses Telegram :
#        GO  → lance OpusClip (crédits dépensés)
#        NON → écarte la source
#
# Les étapes suivantes sont indépendantes de la confirmation :
#   3. recolter — extraits finis, tri, SEO français
#   4. tiktok   — publication sur la grille (nuit comprise)
#
# ⚠️ Ce fichier doit rester en fins de ligne LF. Édité depuis Windows, il
# passerait en CRLF et le pipeline s'arrêterait sans message d'erreur — deux
# jours de publications avaient été perdus ainsi début août 2026.
set -u
cd /app
echo "=== [$(date)] CYCLE SERMONS ==="

# 1. Nouveaux directs terminés (gratuit : flux RSS + 3 unités de quota).
python -m vortex veille

# 2. Phase 1 — détecter les sermons d'Amessan et notifier Michel sur Telegram.
#    Aucun crédit dépensé : le message contient tout pour décider.
python -m vortex confirmer

# 3. Phase 2 — lire les réponses Telegram et lancer OpusClip si GO.
#    --live = les crédits sont RÉELLEMENT dépensés.
python -m vortex valider --live

# 4. Récolte : extraits finis, tri, SEO. Traite Submagic comme OpusClip.
python -m vortex recolter

# 5. Publication TikTok — TOUT DE SUITE, hors grille horaire.
#    Michel, 12/08 : « publie aujourd'hui des la fin du taff », puis « cette
#    nuit ». Les extraits d'un culte partent donc des leur recolte, espaces de
#    quelques minutes, au lieu d'attendre les creneaux du lendemain.
python -m vortex tiktok --live --maintenant

python -m vortex clips
echo "=== [$(date)] FIN CYCLE SERMONS ==="

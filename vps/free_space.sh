#!/bin/sh
# Nettoie les fichiers vidéo déjà publiés pour libérer l'espace disque.
# - Exports : supprime les .mp4 dont l'état est PUBLISHED ou SCHEDULED (déjà sur YouTube)
# - Sources : supprime les sermons dont TOUS les extraits sont créés (clip_sources)
# - TikTok : ne touche PAS tiktok_queue (en attente d'approbation)
# Garde-fou : ne supprime jamais autre chose que des .mp4 dans data/exports/ ou videos/sources/

set -u
EXPORTS="/app/data/exports"
SOURCES="/app/videos/sources"
TIKTOK="/app/videos/tiktok_queue"
LIMIT_MB_BEFORE=5120   # nettoie dès qu'il reste moins de 5 Go
LIMIT_MB_AFTER=10240   # objectif : 10 Go libres après nettoyage
DRY_RUN="${CLEANUP_DRY_RUN:-false}"

log() { echo "[free_space] $(date -Iseconds) $*"; }

free_mb() {
    df -m "$EXPORTS" 2>/dev/null | awk 'NR==2{print $4}'
}

before=$(free_mb)
if [ "$before" -gt "$LIMIT_MB_BEFORE" ]; then
    log "Espace suffisant (${before} Mio > ${LIMIT_MB_BEFORE}) — rien à nettoyer"
    exit 0
fi

log "Espace faible (${before} Mio) — nettoyage..."

cleaned=0

# 1. Exports : rendus dont la vidéo est déjà publiée/programmée
if [ -d "$EXPORTS" ]; then
    for mp4 in "$EXPORTS"/*.mp4; do
        [ -f "$mp4" ] || continue
        stem=$(basename "$mp4" .mp4)
        # Les exports sont nommés {name}_v.mp4 → on enlève le suffixe _v
        name="${stem%_v}"
        if [ "$name" = "$stem" ]; then
            continue  # pas un _v.mp4 → on ne touche pas
        fi
        # Vérifie l'état dans la base
        state=$(python3 -c "
import sqlite3, sys
db = sqlite3.connect('/app/data/vortex.db')
row = db.execute(\"SELECT state FROM videos WHERE name = ?\", [sys.argv[1]]).fetchone()
print(row['state'] if row else '')
db.close()
" "$name" 2>/dev/null)
        case "$state" in
            PUBLISHED|SCHEDULED)
                size=$(stat -c%s "$mp4" 2>/dev/null || echo 0)
                if [ "$DRY_RUN" = "true" ]; then
                    log "[dry-run] Supprimerait $mp4 ($((size/1024/1024)) Mio, état=$state)"
                else
                    rm -f "$mp4"
                    log "Supprimé $mp4 ($((size/1024/1024)) Mio, état=$state)"
                fi
                cleaned=$((cleaned + 1))
                ;;
        esac
    done
fi

# 2. Sources YouTube : sermons dont le clip_sources indique que tout est fait
if [ -d "$SOURCES" ]; then
    for dir in "$SOURCES"/*/; do
        [ -d "$dir" ] || continue
        for mp4 in "$dir"/*.mp4; do
            [ -f "$mp4" ] || continue
            src_path="/app/videos/sources/$(basename "$dir")/$(basename "$mp4")"
            clipped=$(python3 -c "
import sqlite3, sys
db = sqlite3.connect('/app/data/vortex.db')
row = db.execute(\"SELECT clips_made FROM clip_sources WHERE source_path = ?\", [sys.argv[1]]).fetchone()
print(row['clips_made'] if row else '')
db.close()
" "$src_path" 2>/dev/null)
            if [ -n "$clipped" ] && [ "$clipped" -gt 0 ]; then
                size=$(stat -c%s "$mp4" 2>/dev/null || echo 0)
                if [ "$DRY_RUN" = "true" ]; then
                    log "[dry-run] Supprimerait $mp4 ($((size/1024/1024)) Mio, clips=$clipped)"
                else
                    rm -f "$mp4" "$mp4.info.json"
                    log "Supprimé $mp4 ($((size/1024/1024)) Mio, clips=$clipped)"
                fi
                cleaned=$((cleaned + 1))
            fi
        done
    done
fi

after=$(free_mb)
log "Nettoyage terminé : $cleaned fichier(s), disque ${before}→${after} Mio libres"

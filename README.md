# Vortex Automator

Usine de publication automatique pour la chaîne YouTube **Sophos PropheTikos** :
elle transforme chaque jour des vidéos courtes (TikTok) et de longs sermons
(YouTube) en publications habillées, sous-titrées et programmées — sans
intervention humaine.

## Ce que fait la machine, chaque jour

1. **Collecte** — téléchargement TikTok sur le VPS. Pour YouTube, la chaîne
   principale est lue depuis `@lamaisondesagesse/streams` et seuls les directs
   terminés d'au moins 20 minutes sont retenus. YouTube bloquant l'IP du VPS,
   la tâche Windows `Vortex YouTube Long Sermons` télécharge en 1080p puis
   transfère au serveur ; le VPS peut aussi utiliser un fichier cookies.
2. **Découpage intelligent** (`vortex clip`) — transcription
   horodatée (faster-whisper), choix des meilleurs passages par IA (DeepSeek),
   coupes aux frontières de phrases, retrait des silences, punch-ins légers,
   **deux formats par extrait** :
   - horizontal 16:9 → YouTube ;
   - vertical 9:16 recadré sur le visage à chaque plan (OpenCV) → Shorts/social.
3. **Compréhension** — transcription locale (Whisper), détection du texte déjà
   présent à l'image (Tesseract) pour ne jamais écrire par-dessus.
4. **SEO** — titre accrocheur, description et mots-clés générés par IA à partir
   du contenu réel ; aucun prédicateur n'est nommé sans certitude.
5. **Habillage** (`vortex render`) — 1080p pour les clips déjà montés et QHD
   pour les extraits bruts : phrase choc, sous-titres animés, CTA, filtres et
   audio normalisé à −14 LUFS. Les sous-titres commencent après l'accroche.
6. **Covers** (`vortex thumbs`) — miniatures générées en HTML/CSS rendu par
   Chromium en **3840×2160** : portrait HD du pasteur seulement si son nom est
   confirmé, titre court et logo. Les portraits nets sont collectés depuis les
   vidéos officielles avec URL, timecode, dimensions et hash dans un manifeste.
7. **Publication** — upload privé puis passage public programmé. Le code bloque
   désormais réellement tout upload sans rendu et miniature Vortex présents.
8. **Engagement** (`vortex engage`) — question épinglée sous chaque vidéo et
   réponses automatiques aux commentaires.
9. **TikTok** (`demo-tiktok/`) — mini-app de test vers les brouillons TikTok.
   La file automatique de Direct Post n'est pas encore branchée ; ne pas la
   présenter comme une publication TikTok entièrement autonome.

## Architecture

```
vps/daily.sh (cron quotidien, conteneur Docker)
  clip → scan → retry → detect-text → transcribe → prepare
       → render → thumbs → publish --live → engage → status
```

| Fichier | Rôle |
|---|---|
| `vortex/clipper.py` | découpage intelligent des longs sermons (2 formats) |
| `vortex/scanner.py` | inventaire + anti-doublons (SHA-256) |
| `vortex/textdetect.py` | OCR du texte incrusté existant |
| `vortex/transcribe.py` | transcription Whisper + mots horodatés |
| `vortex/metadata.py` | titres/descriptions/tags par IA + contrôle qualité |
| `vortex/render.py` | habillage vidéo : sous-titres, CTA, filtres, audio −14 LUFS |
| `vortex/thumbs.py` | covers HTML/CSS → JPEG UHD <2 Mio (Chromium + Pillow) |
| `vortex/pipeline.py` | plan de publication + créneaux + upload YouTube |
| `vortex/engage.py` | commentaires : question posée + réponses |
| `vortex/dashboard.py` | tableau de bord web (suivi mobile) |
| `demo-tiktok/app.py` | app OAuth + Direct Post pour la review TikTok |

## Déploiement

Tout tourne sur un VPS (Docker). Image : `Dockerfile` (Python 3.12, ffmpeg,
Tesseract, Playwright/Chromium, deno, yt-dlp). Lancement quotidien par cron via
`vps/daily.sh` avec `docker-compose.vps.yml`.

```bash
docker compose -f docker-compose.vps.yml build
bash vps/daily.sh
```

## Configuration

- `config.toml` — chemins, chaîne cible, cadence (aucun secret).
- `.env` (jamais commité, voir `.env.example`) — clés d'API.
- `secrets/` (jamais commité) — OAuth Google (`client_secret.json`, jeton).
- Guides : `docs/SETUP.md`, `docs/CONFIGURATION.md`, `docs/TROUBLESHOOTING.md`.

## Règles d'or du projet

- **Aucun secret dans le dépôt** (`.gitignore` strict, exemples fournis).
- **Jamais deux habillages identiques** — l'algorithme varie tout.
- **Jamais de texte par-dessus un texte existant** dans la vidéo.
- **Jamais de nom de pasteur sans identification certaine.**
- **Jamais de publication sans habillage réussi.**

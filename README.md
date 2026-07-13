# Vortex Automator

Usine de publication automatique pour la chaîne YouTube **Sophos PropheTikos** :
elle transforme chaque jour des vidéos courtes (TikTok) et de longs sermons
(YouTube) en publications habillées, sous-titrées et programmées — sans
intervention humaine.

## Ce que fait la machine, chaque jour

1. **Collecte** — téléchargement des nouvelles vidéos TikTok (yt-dlp) et des
   sermons des chaînes partenaires (avec l'accord de leurs responsables).
2. **Découpage intelligent** (`vortex clip`) — façon OpusClip : transcription
   horodatée (faster-whisper), choix des meilleurs passages par IA (DeepSeek),
   coupes aux frontières de phrases, **deux formats par extrait** :
   - horizontal 16:9 (jusqu'à 3840 px) → YouTube ;
   - vertical 9:16 recadré automatiquement sur le visage (OpenCV) → TikTok.
3. **Compréhension** — transcription locale (Whisper), détection du texte déjà
   présent à l'image (Tesseract) pour ne jamais écrire par-dessus.
4. **SEO** — titre accrocheur, description et mots-clés générés par IA à partir
   du contenu réel ; aucun prédicateur n'est nommé sans certitude.
5. **Habillage** (`vortex render`) — sortie **4K** (YouTube sert alors ses
   meilleurs codecs) : phrase choc, sous-titres animés mot à mot (karaoké),
   appels à l'action variés (s'abonner, like, partage), débruitage + netteté.
   Styles, couleurs et positions changent à chaque vidéo.
6. **Covers** (`vortex thumbs`) — miniatures générées en HTML/CSS rendu par
   Chromium headless : portrait du pasteur (si identifié), gros titres
   blanc/or, fonds dramatiques (`assets/fonds/`), logo de la chaîne.
7. **Publication** — 5 vidéos/jour, upload privé puis passage public programmé
   (9h, 12h, 15h, 18h, 21h). Une vidéo sans habillage n'est **jamais** publiée.
8. **Engagement** (`vortex engage`) — question épinglée sous chaque vidéo et
   réponses automatiques aux commentaires.
9. **TikTok** (`demo-tiktok/`) — mini-app web (Login Kit + Content Posting
   API) : publication des extraits verticaux sur le compte TikTok du ministère
   (dossier en cours de validation chez TikTok).

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
| `vortex/render.py` | habillage 4K : sous-titres animés, CTA, filtres |
| `vortex/thumbs.py` | covers HTML/CSS → JPEG (Chromium headless) |
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

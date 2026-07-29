"""Phase 5 — Le Clipper : découpage INTELLIGENT des longues vidéos sources
(type OpusClip/Submagic), validé par Michel avec l'accord des chaînes sources.

Chaîne complète pour UNE vidéo longue :
1. transcription horodatée (faster-whisper, segments avec début/fin) ;
2. DeepSeek lit la transcription minutée et propose des extraits typés
   (phrase choc / enseignement / témoignage / message complet), en coupant
   UNIQUEMENT aux frontières de phrases — jamais de coupure brutale ;
3. validation des bornes (calées sur les segments réels) ;
4. découpe ffmpeg précise en DEUX formats (décision de Michel) :
   - HORIZONTAL 16:9 (max 1920x1080) → dossier source du pipeline normal
     avec .info.json : circuit habituel vers la chaîne YouTube ;
   - VERTICAL 9:16 recadré centré sur le visage → file d'attente TikTok
     (/app/videos/tiktok_queue/), publiée dès l'approbation de l'API TikTok.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .config import Config
from .db import Database
from .textdetect import find_ffmpeg
from .scanner import find_ffprobe

log = logging.getLogger("vortex.clipper")


# Chaîne source → pasteur habituel (ministères d'UN SEUL pasteur, confirmés par
# Michel). Utilisé comme indice pour la cover (photo HD) ET vérifié par l'IA :
# si la vidéo montre clairement un invité, l'IA laisse le speaker vide.
CHANNEL_PASTORS = {
    "lamaisondesagesse": "Jacques Amessan",
    "EgliseGénérationDaniel": "Aimé Bodjiyé",
    "ÉgliseVasesdHonneur": "Mohammed Sanogo",
    "VasesdHonneur": "Mohammed Sanogo",
}

CLIP_PROMPT = """Tu es monteur pour une chaîne YouTube/TikTok de prédications chrétiennes francophones.
Voici la transcription HORODATÉE (en secondes) d'une longue vidéo ({duration:.0f} s au total) :

{transcript}

Titre de la vidéo source : « {titre_source} »

Propose jusqu'à {max_clips} EXTRAITS à découper, en JSON strict :
{{"evenement": "le nom de l'événement, tiré du titre source (ex : « Conférence Sophos 2026 », \
« Soirées de réveil de Yaoundé »). Vide si la vidéo n'appartient à aucun événement.",
 "clips": [{{"start": <s>, "end": <s>, "type": "court|moyen|long|sequence",
  "sujet": "le thème doctrinal en 2-4 mots (ex : « le pardon », « la dîme », « la foi qui agit »)",
  "serie": "voir SÉRIES ci-dessous — le plus souvent une chaîne vide",
  "title": "titre YouTube accrocheur fidèle (60-85 caractères)",
  "hook": "l'affirmation choc qui OUVRE l'extrait (max 90 caractères)",
  "description": "2-3 phrases fidèles au contenu"}}]}}

SÉRIES — à utiliser avec PARCIMONIE.
Une série regroupe 2 à 5 extraits CONSÉCUTIFS qui forment un récit à suspense : un
enseignement qui se déroule en étapes, une histoire drôle ou saisissante, un témoignage
qui monte, une démonstration qui appelle une suite. Ces extraits porteront « Partie 1/3 »,
« Partie 2/3 »… et un appel à voir la suite.
- donne à chaque extrait de la série LE MÊME libellé dans "serie" (ex : « Guéhazi et la lèpre ») ;
- laisse "serie" VIDE pour tout extrait qui se suffit à lui-même — c'est le cas le plus fréquent ;
- ne crée une série QUE si la coupure donne vraiment envie de voir la suite. Une série
  artificielle fait fuir l'audience : dans le doute, laisse vide.

STRUCTURE OBLIGATOIRE DE CHAQUE EXTRAIT — c'est la règle la plus importante.
Tout extrait doit contenir, DANS CET ORDRE :
  1. une AFFIRMATION CHOC — une déclaration forte, surprenante ou tranchante du prédicateur.
     L'extrait COMMENCE dessus (ou une phrase avant), jamais au milieu d'un développement ;
  2. son EXPLICATION COMPLÈTE — le prédicateur justifie, développe, illustre, cite l'Écriture.
     L'explication doit aller jusqu'à son terme : sa longueur naturelle décide de la durée ;
  3. une FIN NETTE — conclusion, application ou retombée de l'enseignement.

Un extrait qui pose une affirmation SANS l'expliquer est à REJETER.
Un extrait qui explique quelque chose SANS affirmation d'ouverture est à REJETER.

DURÉES — elles découlent de l'explication, jamais d'un gabarit :
- "court"    : 90 à 150 s   — l'affirmation et son explication tiennent en peu de mots ;
- "moyen"    : 150 à 300 s  — explication développée, avec une application ;
- "long"     : 300 à 600 s  — explication + illustration ou témoignage + conclusion ;
- "sequence" : 600 à 900 s  — un raisonnement entier qu'on ne peut pas couper sans le mutiler.
JAMAIS moins de 90 secondes. Si l'explication du prédicateur dure sept minutes, prends sept
minutes : ne tronque pas un raisonnement pour tenir dans un format.

AUTRES RÈGLES ABSOLUES :
- start/end doivent tomber sur des DÉBUTS/FINS de phrases visibles dans la transcription
  (utilise les horodatages fournis) — jamais au milieu d'une phrase ;
- chaque extrait doit se comprendre SEUL, sans avoir vu le reste du sermon ;
- pas de chevauchement entre extraits ;
- ne force pas le nombre : prends TOUS les passages qui méritent d'être gardés, et
  seulement ceux-là. Un sermon riche en donnera beaucoup, un sermon pauvre très peu ;
- le champ "sujet" servira plus tard à regrouper des extraits de sermons différents
  sur un même thème : sois précis et cohérent d'un extrait à l'autre.

✅ À GARDER (contenu spirituel fort et édifiant) : ENSEIGNEMENT biblique, EXHORTATION,
TÉMOIGNAGES, et les TEMPS DE PRIÈRE / DÉCLARATIONS / BÉNÉDICTIONS / INTERCESSION /
paroles prophétiques / moments d'adoration portés par un message. Ce sont d'excellents extraits.

⛔ INTERDIT ABSOLU — n'extrais JAMAIS ces passages (pièges qui ruinent la chaîne) :
- appels aux DONS / OFFRANDES / dîmes, coordonnées de paiement, numéros Mobile Money
  (Orange/MTN/Moov Money), IBAN, virements, Western Union, QR codes, « pour vos dons… » ;
- annonces, informations pratiques, programme, présentations de l'église, remerciements
  protocolaires, intro/générique/outro purement administratifs.
  → Ces segments existent dans presque toutes les vidéos d'église mais NE DOIVENT JAMAIS
    devenir des extraits : hors-sujet, allure de spam/arnaque, réputation du ministère.

TITRES : accrocheurs MAIS fidèles au message spirituel réel (jamais transactionnels, jamais
« envoyer de l'argent » ou « dons faciles »). Le titre doit refléter la vérité biblique,
la prière ou le témoignage réellement présents dans l'extrait.

Réponds UNIQUEMENT avec le JSON."""


def _audio_duration(path: str) -> float:
    out = subprocess.run(
        [find_ffprobe(), "-v", "quiet",
         "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=120)
    try:
        return float(out.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _transcribe_timed(cfg: Config, path: str) -> tuple[list, float]:
    # Repérage des extraits sur une source longue (jusqu'à 2 h). Sur un VPS avec
    # peu de RAM libre, transcrire 2 h d'un coup fait exploser la mémoire (OOM) :
    # faster-whisper décode TOUT l'audio en mémoire d'abord. On découpe donc en
    # tranches de 10 min transcrites une par une — la mémoire reste minuscule.
    # Modèle LÉGER 'base' : cette transcription ne sert qu'à SITUER les passages ;
    # chaque extrait court est re-transcrit en 'small' au stade des sous-titres,
    # donc aucune perte de qualité finale. Surchargeable via cfg.clip_whisper_model.
    from faster_whisper import WhisperModel
    import gc
    import os
    import tempfile

    model_name = getattr(cfg, "clip_whisper_model", None) or "base"
    chunk_s = int(getattr(cfg, "clip_chunk_seconds", 0) or 600)
    duration = _audio_duration(path)

    # Transcrire 3 h 25 prend trois quarts d'heure. Sans cache, la moindre
    # reprise (réponse de l'IA inexploitable, coupure réseau) recommencerait
    # tout depuis le début. Le cache vit à côté de la source et disparaît
    # avec elle.
    cache = Path(path).with_suffix(".segments.json")
    if cache.exists():
        try:
            enregistre = json.loads(cache.read_text(encoding="utf-8"))
            segs_caches = [tuple(s) for s in enregistre["segments"]]
            if segs_caches:
                log.info("Transcription reprise du cache (%d segments)", len(segs_caches))
                return segs_caches, float(enregistre.get("duration") or duration)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Cache de transcription illisible (%s) — on recommence", exc)

    log.info("Transcription de repérage (modèle '%s', source %.0f min, tranches de %d min)…",
             model_name, duration / 60, chunk_s // 60)
    model = WhisperModel(model_name, device=cfg.whisper_device,
                         compute_type=cfg.whisper_compute,
                         cpu_threads=os.cpu_count() or 2)
    segs: list = []
    try:
        if duration and duration > chunk_s * 1.5:
            ffmpeg = find_ffmpeg()
            start = 0.0
            while start < duration:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    wav = tf.name
                try:
                    subprocess.run(
                        [ffmpeg, "-v", "error", "-ss", f"{start:.1f}",
                         "-t", f"{chunk_s}", "-i", path,
                         "-vn", "-ac", "1", "-ar", "16000", "-y", wav],
                        capture_output=True, timeout=600, check=True)
                    seg_iter, _ = model.transcribe(wav, vad_filter=True)
                    for s in seg_iter:
                        if s.text.strip():
                            segs.append((round(s.start + start, 1),
                                         round(s.end + start, 1), s.text.strip()))
                finally:
                    try:
                        os.remove(wav)
                    except OSError:
                        pass
                    gc.collect()
                log.info("  … %.0f/%.0f min transcrites (%d segments)",
                         min(start + chunk_s, duration) / 60, duration / 60, len(segs))
                start += chunk_s
        else:
            seg_iter, info = model.transcribe(path, vad_filter=True)
            segs = [(round(s.start, 1), round(s.end, 1), s.text.strip())
                    for s in seg_iter if s.text.strip()]
            duration = duration or info.duration
    finally:
        del model
        gc.collect()

    if segs:
        try:
            cache.write_text(
                json.dumps({"duration": duration, "segments": segs}, ensure_ascii=False),
                encoding="utf-8")
        except OSError as exc:
            log.warning("Cache de transcription non écrit : %s", exc)
    return segs, duration


def _parse_json_obj(content: str) -> dict:
    """Extrait le 1er objet JSON d'une réponse (le modèle raisonnement peut
    l'entourer de texte ou de balises ```json)."""
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.lstrip().lower().startswith("json"):
            content = content.lstrip()[4:]
    try:
        return json.loads(content)
    except Exception:
        pass
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except Exception:
            pass
    return {}


def _ask_clips(cfg: Config, segs: list, duration: float,
               titre_source: str = "") -> tuple[list[dict], str]:
    """Sélection des extraits, par fenêtres successives du sermon.

    Un direct de 3 h 25 ne tient pas dans un seul appel : la transcription
    était tronquée à 90 000 caractères — plus de la moitié du sermon échappait
    à l'IA — et il fallait lui faire produire trente extraits d'un coup, ce qui
    épuisait le budget de tokens et rendait la réponse inexploitable.
    On découpe donc en fenêtres d'environ trois quarts d'heure, analysées
    l'une après l'autre : tout le sermon est vu, et chaque réponse reste courte.
    """
    if not segs:
        return [], ""
    fenetre_s = float(getattr(cfg, "clip_window_seconds", 0) or 2700)   # 45 min
    tous: list[dict] = []
    evenement = ""
    debut = segs[0][0]
    numero = 0
    while debut < duration:
        fin_fenetre = debut + fenetre_s
        tranche = [s for s in segs if s[0] >= debut and s[1] <= fin_fenetre]
        debut = fin_fenetre
        if len(tranche) < 5:
            continue
        numero += 1
        clips, evt = _ask_clips_fenetre(cfg, tranche, duration, titre_source)
        evenement = evenement or evt
        log.info("Fenêtre %d (%.0f-%.0f min) : %d extrait(s)",
                 numero, tranche[0][0] / 60, tranche[-1][1] / 60, len(clips))
        tous.extend(clips)
    return tous, evenement


def _ask_clips_fenetre(cfg: Config, segs: list, duration: float,
                       titre_source: str = "") -> tuple[list[dict], str]:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        log.error("DEEPSEEK_API_KEY absent — clipper indisponible")
        return [], ""
    lines = [f"[{s:.0f}-{e:.0f}] {t}" for s, e, t in segs]
    transcript = "\n".join(lines)
    if len(transcript) > 90000:
        transcript = transcript[:90000].rsplit("\n", 1)[0]
        log.warning("Fenêtre tronquée à %d caractères", len(transcript))
    # Environ un extrait par sept minutes de la FENÊTRE. Une réponse courte
    # tient dans le budget de tokens, réflexion du modèle comprise.
    couverte = segs[-1][1] - segs[0][0]
    max_clips = max(2, min(8, int(couverte // 420)))
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    reasoner = "reasoner" in model
    # v4-pro raisonne (reasoning_tokens ~1500-2000 avant la sortie) : gros budget
    # obligatoire sinon la réflexion épuise max_tokens et le JSON est tronqué → 0 extrait.
    big_budget = reasoner or "pro" in model
    # Chaque extrait pèse ~350 caractères de JSON ; trente en réclament donc bien
    # plus que le budget d'origine, réflexion comprise.
    budget = 8000 if big_budget else 5000
    if max_clips > 12:
        budget = 16000 if big_budget else 10000
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": CLIP_PROMPT.format(
            duration=duration, transcript=transcript, max_clips=max_clips,
            titre_source=titre_source or "(inconnu)")}],
        "max_tokens": budget,
    }
    if not reasoner:  # deepseek-reasoner ignore/rejette temperature + response_format
        payload["response_format"] = {"type": "json_object"}
        payload["temperature"] = 0.7
    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.load(r)
        brut = resp["choices"][0]["message"]["content"] or ""
        fin = (resp.get("choices") or [{}])[0].get("finish_reason", "")
        reponse = _parse_json_obj(brut)
        clips = reponse.get("clips", [])
        evenement = str(reponse.get("evenement", "")).strip()[:80]
        # Sans ces traces, une réponse tronquée ou vide donnait « 0 extrait »
        # sans le moindre indice sur la cause.
        if not clips:
            log.error(
                "DeepSeek n'a propose aucun extrait (finish_reason=%s, "
                "reponse de %d caracteres, JSON %s). Debut : %s",
                fin, len(brut),
                "illisible" if not reponse else f"sans cle 'clips' ({list(reponse)[:5]})",
                brut[:400].replace("\n", " "))
            if fin == "length":
                log.error("Reponse coupee par max_tokens — augmenter le budget "
                          "ou reduire max_clips")
    except Exception as exc:
        log.error("DeepSeek clipper échoué : %s", exc)
        return [], ""
    # Validation : bornes calées sur les segments réels, durées plausibles
    starts = [s for s, _, _ in segs]
    ends = [e for _, e, _ in segs]
    valid = []
    rejetes: list[str] = []
    for c in clips:
        try:
            start = min(starts, key=lambda x: abs(x - float(c["start"])))
            end = min(ends, key=lambda x: abs(x - float(c["end"])))
        except (KeyError, ValueError, TypeError):
            continue
        # Plancher à 90 s : en dessous, l'affirmation choc n'a pas la place
        # d'être expliquée, et c'est l'explication qui fait la valeur de
        # l'extrait (décision de Michel, 29/07). Plafond à 900 s pour le format
        # « sequence ». Une marge de 5 s absorbe le calage sur les segments.
        longueur = end - start
        if longueur < 85 or longueur > 900 or start >= end:
            rejetes.append(f"{start:.0f}-{end:.0f}s ({longueur:.0f}s)")
            continue
        valid.append({"start": start, "end": end,
                      "type": str(c.get("type", "moyen"))[:20],
                      # Thème doctrinal : c'est la clé qui permettra plus tard de
                      # rassembler des extraits de sermons différents sur un sujet.
                      "sujet": str(c.get("sujet", "")).strip()[:60],
                      # Libellé de série : seuls les extraits qui le partagent
                      # recevront « Partie i/N ».
                      "serie": str(c.get("serie", "")).strip()[:80],
                      "title": str(c.get("title", "")).strip()[:95],
                      "hook": str(c.get("hook", "")).strip()[:90],
                      "description": str(c.get("description", "")).strip()[:500]})
    if rejetes:
        # Une duree hors bornes est la cause la plus frequente d'un
        # decoupage vide : la nommer evite de chercher ailleurs.
        log.warning("%d extrait(s) ecarte(s) pour duree hors bornes (85-900 s) : %s",
                    len(rejetes), ", ".join(rejetes[:8]))
    return valid, evenement


def _numeroter_series(clips: list[dict]) -> None:
    """Attribue « Partie i/N » aux seuls extraits qui appartiennent à une série.

    Michel (29/07) : le suspense ne doit pas s'appliquer à tout, seulement aux
    passages qui donnent vraiment envie de voir la suite. Un extrait sans
    libellé de série, ou seul de son libellé, sort donc sans numérotation.
    """
    groupes: dict[str, list[dict]] = {}
    for clip in clips:
        libelle = clip.get("serie", "")
        if libelle:
            groupes.setdefault(libelle, []).append(clip)

    for clip in clips:
        clip["part"] = 0
        clip["total"] = 0
    for libelle, membres in groupes.items():
        if len(membres) < 2:
            # Une « série » d'un seul extrait n'a pas de suite à annoncer.
            membres[0]["serie"] = ""
            continue
        membres.sort(key=lambda c: c["start"])
        for rang, clip in enumerate(membres, start=1):
            clip["part"] = rang
            clip["total"] = len(membres)
        log.info("Série « %s » : %d parties", libelle, len(membres))


def _face_center_x(path: str, at: float, width: int, height: int) -> float:
    """Centre horizontal du visage (0-1) pour le recadrage vertical."""
    try:
        import cv2
        import numpy as np
        out = subprocess.run(
            [find_ffmpeg(), "-v", "quiet", "-ss", f"{at:.1f}", "-i", path,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=60)
        img = cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            return (x + w / 2) / img.shape[1]
    except Exception as exc:
        log.debug("Visage non détecté (%s)", exc)
    return 0.5


def _cut(src: str, start: float, end: float, out: Path, vf: str) -> bool:
    """Découpe précise ré-encodée avec le filtre vidéo donné."""
    cmd = [find_ffmpeg(), "-v", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
           "-i", src, "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-y", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3600, check=True)
        return out.exists()
    except subprocess.CalledProcessError as exc:
        log.error("Découpe échouée : %s", exc.stderr[-300:] if exc.stderr else exc)
        return False


def _speech_intervals(segs: list, start: float, end: float,
                      max_gap: float = 0.7, pad: float = 0.12) -> list[tuple]:
    """À partir des segments de parole, renvoie les intervalles à GARDER dans
    [start,end] en supprimant les silences > max_gap (coupe le « trop de silence »).
    Fusionne les segments proches ; borne le résultat à [start,end]."""
    spans = [(max(start, s), min(end, e)) for s, e, _ in segs
             if e > start and s < end]
    spans.sort()
    if not spans:
        return [(start, end)]
    merged: list[list] = [list(spans[0])]
    for s, e in spans[1:]:
        if s - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], e)   # petit silence : on garde tout
        else:
            merged.append([s, e])                    # gros silence : on coupe
    out = []
    for i, (s, e) in enumerate(merged):
        a = max(start, s - pad)
        b = min(end, e + pad)
        if b - a > 0.3:
            out.append((round(a, 2), round(b, 2)))
    return out or [(start, end)]


def _cut_montage(src: str, intervals: list[tuple], out: Path,
                 vf_per: str | list[str]) -> bool:
    """MONTAGE : ré-assemble uniquement les intervalles de parole (silences coupés),
    avec un filtre vidéo par morceau (vf_per). Garde la synchro audio/vidéo."""
    if not intervals:
        return False
    # Un seek d'entrée évite de redécoder les deux heures précédant chaque
    # extrait. Les trims du graphe deviennent donc relatifs à cette fenêtre.
    first = min(a for a, _ in intervals)
    last = max(b for _, b in intervals)
    seek = max(0.0, first - 0.25)
    window = max(0.5, last - seek + 0.25)

    parts_v, parts_a, n = [], [], len(intervals)
    fc = []
    for i, (a, b) in enumerate(intervals):
        a_rel, b_rel = max(0.0, a - seek), max(0.0, b - seek)
        vf = vf_per[i] if isinstance(vf_per, list) else vf_per
        # Normaliser SAR/pixel format : des crops/zooms différents ne peuvent
        # sinon pas être concaténés proprement par FFmpeg.
        fc.append(
            f"[0:v]trim={a_rel:.3f}:{b_rel:.3f},setpts=PTS-STARTPTS,{vf},"
            f"setsar=1,format=yuv420p[v{i}]"
        )
        fc.append(
            f"[0:a]atrim={a_rel:.3f}:{b_rel:.3f},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
        parts_v.append(f"[v{i}]")
        parts_a.append(f"[a{i}]")
    fc.append("".join(f"{parts_v[i]}{parts_a[i]}" for i in range(n))
              + f"concat=n={n}:v=1:a=1[outv][outa]")
    cmd = [find_ffmpeg(), "-v", "error", "-ss", f"{seek:.3f}",
           "-t", f"{window:.3f}", "-i", src,
           "-filter_complex", ";".join(fc), "-map", "[outv]", "-map", "[outa]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
           "-movflags", "+faststart", "-y", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=5400, check=True)
        return out.exists()
    except subprocess.CalledProcessError as exc:
        log.error("Montage échoué : %s", exc.stderr[-300:] if exc.stderr else exc)
        return False


def _cut_horizontal(src: str, start: float, end: float, out: Path,
                    src_w: int, src_h: int) -> bool:
    """Version YouTube : format d'origine 16:9, plafonné à 3840 de large (jamais de downscale)."""
    vf = "scale=3840:-2:flags=lanczos" if src_w > 3840 else f"scale={src_w}:{src_h}"
    return _cut(src, start, end, out, vf)


def _montage_filters(src: str, intervals: list[tuple],
                     src_w: int, src_h: int) -> tuple[list[str], list[str]]:
    """Plans horizontaux + verticaux par intervalle de parole.

    Chaque vraie pause devient une coupe. De légers punch-ins alternés donnent
    du rythme ; le vertical se recadre sur le visage à chaque nouveau plan.
    """
    horizontal, vertical = [], []
    for index, (start, end) in enumerate(intervals):
        zoom = 1.045 if index % 3 == 1 else 1.0
        if zoom > 1:
            crop_w = max(2, int(src_w / zoom) // 2 * 2)
            crop_h = max(2, int(src_h / zoom) // 2 * 2)
            horizontal.append(
                f"crop={crop_w}:{crop_h}:(iw-{crop_w})/2:(ih-{crop_h})/2,"
                f"scale={src_w}:{src_h}:flags=lanczos"
            )
        else:
            horizontal.append(f"scale={src_w}:{src_h}:flags=lanczos")

        if src_h > src_w:
            vertical.append("scale=1080:1920:force_original_aspect_ratio=increase,"
                            "crop=1080:1920")
            continue
        crop_h = max(2, int(src_h / zoom) // 2 * 2)
        crop_w = max(2, int(crop_h * 9 / 16) // 2 * 2)
        center = _face_center_x(src, (start + end) / 2, src_w, src_h)
        left = max(0, min(src_w - crop_w, int(center * src_w - crop_w / 2)))
        top = max(0, (src_h - crop_h) // 2)
        vertical.append(
            f"crop={crop_w}:{crop_h}:{left}:{top},"
            "scale=1080:1920:flags=lanczos"
        )
    return horizontal, vertical


def _smooth(vals: list[float], k: int = 2) -> list[float]:
    """Moyenne glissante (lissage du panoramique)."""
    out = []
    n = len(vals)
    for i in range(n):
        lo, hi = max(0, i - k), min(n, i + k + 1)
        out.append(sum(vals[lo:hi]) / (hi - lo))
    return out


def _track_x_expr(src: str, start: float, end: float, src_w: int, src_h: int,
                  crop_w: int) -> str | None:
    """RECADRAGE DYNAMIQUE (façon OpusClip) : échantillonne la position du visage
    tout au long de l'extrait, lisse, et renvoie une expression ffmpeg pour un
    crop.x qui SUIT le prédicateur en douceur (interpolation linéaire par
    morceaux). Renvoie None si le suivi n'est pas exploitable (→ crop statique)."""
    dur = end - start
    step = 1.6                       # un échantillon toutes ~1,6 s
    n = max(2, min(int(dur / step) + 1, 40))  # borne le nombre d'échantillons
    times = [dur * i / (n - 1) for i in range(n)]
    max_x = float(src_w - crop_w)
    xs: list[float] = []
    last = 0.5
    for t in times:
        cx = _face_center_x(src, start + t, src_w, src_h)
        if cx <= 0 or cx >= 1:       # visage non détecté → garde la dernière position
            cx = last
        last = cx
        xs.append(max(0.0, min(max_x, cx * src_w - crop_w / 2)))
    xs = _smooth(xs, k=2)
    kf = [(round(times[i], 2), int(round(xs[i]))) for i in range(n)]
    # supprime les points quasi identiques consécutifs (expression plus courte)
    trimmed = [kf[0]]
    for t, x in kf[1:]:
        if abs(x - trimmed[-1][1]) >= 3 or t == kf[-1][0]:
            trimmed.append((t, x))
    if len(trimmed) < 2:
        return None
    # expression x(t) : interpolation linéaire par morceaux (t relatif au clip)
    expr = str(trimmed[-1][1])
    for i in range(len(trimmed) - 2, -1, -1):
        t0, x0 = trimmed[i]
        t1, x1 = trimmed[i + 1]
        dt = (t1 - t0) or 0.001
        seg = f"({x0}+({x1 - x0})*(t-{t0})/{dt})"
        # virgules NON échappées : la valeur est protégée par des guillemets simples
        # dans le filtre (x='...'), donc les virgules y sont littérales.
        expr = f"if(lt(t,{t1}),{seg},{expr})"
    return expr


def _cut_vertical(src: str, start: float, end: float, out: Path,
                  src_w: int, src_h: int) -> bool:
    """Version TikTok/Short : recadrage 9:16 avec SUIVI DYNAMIQUE du visage."""
    crop_w = int(src_h * 9 / 16 // 2 * 2)
    if crop_w >= src_w:  # source déjà verticale/carrée : pas de recadrage
        return _cut(src, start, end, out, "scale=1080:-2")
    expr = _track_x_expr(src, start, end, src_w, src_h, crop_w)
    if expr:
        vf = f"crop={crop_w}:{src_h}:x='{expr}':y=0,scale=1080:1920"
    else:  # repli : crop statique centré sur le visage au milieu
        cx = _face_center_x(src, (start + end) / 2, src_w, src_h)
        x = int(max(0, min(src_w - crop_w, cx * src_w - crop_w / 2)))
        vf = f"crop={crop_w}:{src_h}:{x}:0,scale=1080:1920"
    return _cut(src, start, end, out, vf)


def _probe_dims(path: str) -> tuple[int, int]:
    out = subprocess.run(
        [find_ffprobe(), "-v", "quiet", "-print_format",
         "json", "-show_streams", path], capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    return int(v["width"]), int(v["height"])


def _probe_duration(path: str | Path) -> float | None:
    """Durée réellement encodée, utilisée notamment pour la limite Shorts."""
    try:
        out = subprocess.run(
            [find_ffprobe(), "-v", "error",
             "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
             str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _sans_chevauchement(clips: list[dict], marge: float = 30.0) -> list[dict]:
    """Écarte les extraits qui se recouvrent, sur une liste déjà triée par début.

    L'IA propose parfois deux passages quasi identiques : le sermon du 21/07 a
    produit deux extraits distants de 36 secondes, donc largement superposés.
    Publier les deux revient à sortir deux fois le même message, ce que YouTube
    traite comme du contenu répétitif. Le premier passage l'emporte ; `marge`
    tolère les enchaînements serrés mais réellement distincts.
    """
    gardes: list[dict] = []
    for clip in clips:
        if gardes and clip["start"] < gardes[-1]["end"] - marge:
            log.info(
                "Extrait ignoré (chevauche le précédent) : %.0fs-%.0fs",
                clip["start"], clip["end"],
            )
            continue
        gardes.append(clip)
    return gardes


def _ensure_table(db: Database) -> None:
    db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS clip_sources (
            path TEXT PRIMARY KEY,
            processed_at TEXT,
            clips_count INTEGER
        );
    """)
    db.conn.commit()


def process_one_source(cfg: Config, db: Database) -> int:
    """Traite UNE vidéo source non encore découpée. Retourne le nb d'extraits créés."""
    _ensure_table(db)
    if not cfg.sources_dir.is_dir():
        log.info("Aucun dossier sources (%s)", cfg.sources_dir)
        return 0
    candidates = sorted(cfg.sources_dir.glob("*/*.mp4"), key=lambda p: p.name, reverse=True)
    src = None
    for c in candidates:
        done = db.conn.execute("SELECT 1 FROM clip_sources WHERE path = ?", (str(c),)).fetchone()
        if not done:
            src = c
            break
    if src is None:
        log.info("Toutes les sources sont déjà découpées.")
        return 0

    log.info("Découpage de la source : %s", src.name)
    segs, duration = _transcribe_timed(cfg, str(src))
    if not segs:
        # Ne jamais archiver un échec comme un succès : la source doit être
        # retentée au passage suivant (modèle indisponible, audio illisible, etc.).
        log.error("Transcription vide pour %s — source conservée pour reprise", src.name)
        return 0
    # Le titre officiel donne à l'IA le nom de l'événement (« Conférence Sophos
    # 2026 »), qui servira de playlist.
    try:
        from .portraits import speaker_from_info
        _, infos_source = speaker_from_info(src)
        titre_source = str(infos_source.get("title") or "")
    except Exception:
        titre_source = ""

    clips, evenement = _ask_clips(cfg, segs, duration, titre_source)
    clips.sort(key=lambda c: c["start"])
    clips = _sans_chevauchement(clips)
    # « Partie i/N » réservée aux extraits que l'IA a réunis en série.
    _numeroter_series(clips)
    total = len(clips)
    log.info("%d extraits retenus%s", total,
             f" — événement : {evenement}" if evenement else "")

    src_w, src_h = _probe_dims(str(src))
    chan = src.parent.name
    tiktok_dir = cfg.tiktok_queue_dir
    tiktok_dir.mkdir(parents=True, exist_ok=True)
    # Le flux /streams contient aussi des invités. Ne jamais déduire « Jacques
    # Amessan » du seul nom de la chaîne : le nom doit être présent dans le titre.
    try:
        from .portraits import speaker_from_info
        pastor, _ = speaker_from_info(src)
    except Exception:
        pastor = None
    pastor = pastor or ""
    made = 0
    all_complete = total > 0
    for i, c in enumerate(clips, start=1):
        stem = f"clip_{chan}_{src.stem[:24]}_{i}_{int(c['start'])}"
        # Indice pasteur dans la légende (l'IA nomme si cohérent, sinon écarte l'invité)
        prefix = f"Prédication de {pastor}. " if pastor else ""
        # part/total viennent de la SÉRIE, pas du rang dans le sermon : un
        # extrait autonome sort sans « Partie i/N » (décision de Michel, 29/07).
        info = {"description": f"{prefix}{c['title']} — {c['hook']} {c['description']}",
                "part": c.get("part", 0), "total": c.get("total", 0),
                "serie": c.get("serie", ""),
                # L'événement devient la playlist YouTube ; le sujet servira au
                # regroupement d'extraits venus de sermons différents.
                "evenement": evenement,
                "sujet": c.get("sujet", ""), "type": c.get("type", "")}
        # Montage réel : les pauses >0,7 s sont retirées, avec punch-ins légers
        # et nouveau cadrage visage à chaque plan. Les anciennes fonctions
        # existaient mais n'étaient jamais appelées.
        intervals = _speech_intervals(segs, c["start"], c["end"])
        h_filters, v_filters = _montage_filters(
            str(src), intervals, src_w, src_h
        )
        # 1) version HORIZONTALE → pipeline YouTube habituel
        out_h = cfg.source_dir / f"{stem}.mp4"
        if not _cut_montage(str(src), intervals, out_h, h_filters):
            all_complete = False
            continue
        out_h.with_name(out_h.stem + ".info.json").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8")
        # 2) version VERTICALE (suivi dynamique du visage) → file d'attente TikTok
        out_v = tiktok_dir / f"{stem}_tiktok.mp4"
        clip_len = sum(end - start for start, end in intervals)
        vert_ok = _cut_montage(str(src), intervals, out_v, v_filters)
        short_created = False
        if vert_ok:
            vertical_len = _probe_duration(out_v) or clip_len
            out_v.with_name(out_v.stem + ".info.json").write_text(json.dumps(
                {"title": c["title"], "hook": c["hook"],
                 "description": c["description"], "type": c.get("type", ""),
                 "sujet": c.get("sujet", ""), "serie": c.get("serie", ""),
                 "evenement": evenement,
                 "part": c.get("part", 0), "total": c.get("total", 0)},
                ensure_ascii=False), encoding="utf-8")
            # 2b) le vertical part AUSSI en YouTube SHORT si ≤ 180 s (décision Michel :
            #     vertical = YouTube Short + TikTok ; horizontal = YouTube classique).
            # Marge de 0,5 s : l'encodage peut ajouter quelques images/audio.
            if vertical_len <= 179.5:
                short_stem = f"{stem}_short"
                out_s = cfg.source_dir / f"{short_stem}.mp4"
                try:
                    # Lien dur plutôt que copie : le fichier n'existe qu'une
                    # fois sur le disque et n'est jamais chargé en mémoire.
                    # `write_bytes(read_bytes())` doublait chaque vertical et
                    # faisait un pic de RAM égal à sa taille, sur une machine
                    # où il reste moins d'un gigaoctet libre.
                    #
                    # On passe par un fichier temporaire puis on bascule d'un
                    # coup : écrire directement sur out_s détruirait la version
                    # précédente avant de savoir si la nouvelle aboutit, et
                    # laisserait un fichier tronqué que le scanner ingérerait.
                    tmp_s = out_s.with_name(short_stem + ".tmp.mp4")
                    tmp_s.unlink(missing_ok=True)
                    try:
                        try:
                            os.link(out_v, tmp_s)
                        except OSError:
                            # Volumes différents ou système de fichiers sans
                            # liens durs : la copie reste correcte, seulement
                            # plus coûteuse.
                            shutil.copyfile(out_v, tmp_s)
                        os.replace(tmp_s, out_s)
                    except OSError:
                        tmp_s.unlink(missing_ok=True)
                        raise
                    out_s.with_name(short_stem + ".info.json").write_text(
                        json.dumps({"description": f"{prefix}{c['title']} — {c['hook']} "
                                    f"{c['description']}", "format": "short",
                                    "serie": c.get("serie", ""),
                                    "evenement": evenement,
                                    "sujet": c.get("sujet", ""),
                                    "part": c.get("part", 0),
                                    "total": c.get("total", 0)},
                                   ensure_ascii=False), encoding="utf-8")
                    short_created = True
                except OSError as exc:
                    all_complete = False
                    log.warning("Copie Short échouée : %s", exc)
        else:
            all_complete = False
        made += 1
        log.info("Extrait %d/%d : %s (%ds, %s) + vertical%s", i, len(clips),
                 out_h.name, int(clip_len), c["type"],
                 " + Short YouTube" if short_created else "")
    if made <= 0:
        # Même garde pour une réponse IA vide ou des coupes FFmpeg toutes
        # échouées. L'ancien comportement empoisonnait l'anti-doublon puis
        # supprimait le sermon original, rendant l'échec irréversible.
        log.error("Aucun extrait valide pour %s — source conservée pour reprise", src.name)
        return 0
    if not all_complete or made != total:
        # Un montage partiel est archivé quand même. Rejouer la source ne
        # reprend pas les extraits manquants : l'IA resélectionne d'autres
        # passages et produit un second jeu qui recouvre le premier. Le sermon
        # du 21/07 est ainsi sorti en douze extraits au lieu de six, avec des
        # accroches en double — exactement ce que YouTube pénalise.
        log.error(
            "Montage partiel pour %s (%d/%d) — archivé en l'état, pas de reprise",
            src.name, made, total,
        )

    # Constitue automatiquement une bibliothèque HD depuis la vidéo officielle.
    # Le nom du pasteur doit figurer dans le titre source ; sinon aucune image
    # n'est attribuée, ce qui évite de confondre un invité avec le pasteur habituel.
    try:
        from .portraits import harvest_portraits
        harvest_portraits(src, duration)
    except Exception as exc:
        log.warning("Collecte de portraits ignorée pour %s : %s", src.name, exc)

    db.conn.execute("INSERT OR REPLACE INTO clip_sources VALUES (?, datetime('now'), ?)",
                    (str(src), made))
    db.conn.commit()
    # Libère l'espace « au fur et à mesure » (demande de Michel) : une source de
    # sermon pèse souvent 0,5–2 Go et devient inutile DÈS que ses extraits sont créés.
    # On la supprime tout de suite (avec son .info.json) au lieu d'attendre le cron
    # nocturne, pour ne jamais saturer le disque du VPS partagé. L'archive de
    # téléchargement (.archive.txt) est conservée : elle évite de re-télécharger.
    try:
        src.unlink(missing_ok=True)
        src.with_suffix(".info.json").unlink(missing_ok=True)
        log.info("Source supprimée (espace libéré) : %s", src.name)
    except OSError as exc:
        log.warning("Suppression de la source impossible (%s) : %s", src.name, exc)
    return made

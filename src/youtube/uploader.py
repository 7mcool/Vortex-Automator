import os
import json
import time
from datetime import datetime, timezone, timedelta
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from utils.config import CONFIG
from utils.logger import log_error

def get_publish_time(target_date, slot):
    """Calcule l'heure de publication UTC avec validation"""
    try:
        if not target_date or len(target_date) != 10:
            raise ValueError("Format de date invalide. Utilisez YYYY-MM-DD")
        
        slot_index = slot % len(CONFIG['PUBLISH_HOURS'])
        hour_local = CONFIG['PUBLISH_HOURS'][slot_index]
        hour_utc = (hour_local - 1) % 24  # Conversion UTC+1 → UTC
        
        publish_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(
            hour=hour_utc, minute=0, second=0, tzinfo=timezone.utc)
        
        # Validation: Ne pas programmer dans le passé
        if publish_dt < datetime.now(timezone.utc) + timedelta(minutes=10):
            raise ValueError("Heure de publication dans le passé")
        
        return publish_dt.isoformat()
    
    except Exception as e:
        log_error(f"Erreur calcul heure publication: {str(e)}")
        # Fallback: 1 heure dans le futur
        return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

def upload_video(youtube_service, video_path, metadata, slot, target_date):
    """Upload une vidéo sur YouTube avec gestion robuste des erreurs"""
    try:
        # Validation des entrées
        if not youtube_service:
            raise ValueError("Service YouTube non initialisé")
        
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Fichier vidéo introuvable: {video_path}")
        
        # Construction du corps de la requête
        body = {
            "snippet": {
                "title": metadata["title"][:100],  # Limite YouTube: 100 caractères
                "description": metadata["description"][:5000],  # Limite YouTube: 5000 caractères
                "categoryId": CONFIG['YT_CATEGORY_ID'],
                "defaultLanguage": "fr",
                "defaultAudioLanguage": "fr"
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": get_publish_time(target_date, slot),
                "selfDeclaredMadeForKids": False
            }
        }
        
        # Ajout des chapitres manuels
        if metadata.get("manualChapters"):
            body["snippet"]["description"] += "\n\nChapitres:\n" + "\n".join(
                metadata["manualChapters"][:50]  # Limite à 50 chapitres
            )
        
        # Création du média
        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=10*1024*1024  # 10MB chunks
        )
        
        # Requête d'upload
        request = youtube_service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        # Exécution avec suivi de progression
        print("⬆️ Démarrage upload YouTube...")
        response = None
        retry_count = 0
        while response is None and retry_count < 3:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f"↗️ Progression: {int(status.progress() * 100)}%")
            except HttpError as e:
                error_details = json.loads(e.content.decode()).get('error', {})
                if error_details.get('errors', [{}])[0].get('reason') == 'quotaExceeded':
                    log_error("QUOTA EXCEEDED! Pause de 5 minutes...")
                    time.sleep(300)  # Attendre 5 minutes
                    retry_count += 1
                else:
                    raise
        
        if not response:
            raise TimeoutError("Échec de l'upload après 3 tentatives")
        
        return f"https://youtu.be/{response['id']}"
    
    except HttpError as e:
        error = json.loads(e.content.decode()).get('error', {})
        log_error(f"ERREUR YOUTUBE API [{e.resp.status}]: {error.get('message')}")
        raise
    except Exception as e:
        log_error(f"ERREUR UPLOAD: {str(e)}")
        raise
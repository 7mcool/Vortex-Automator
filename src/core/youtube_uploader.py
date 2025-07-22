from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
import os
import json
import logging

logger = logging.getLogger(__name__)

def get_youtube_service(token_path, client_secret_path, SCOPES):
    """Crée le service YouTube avec authentification OAuth 2.0"""
    if not os.path.exists(client_secret_path):
        logger.error("Fichier client_secret.json introuvable")
        raise FileNotFoundError("client_secret.json introuvable")
    
    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            logger.warning(f"Erreur lors du chargement du token: {str(e)}")
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Rafraîchissement du token...")
                creds.refresh(Request())
            except Exception as refresh_error:
                logger.error(f"Erreur rafraîchissement token: {refresh_error}")
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            logger.info("Authentification nécessaire...")
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    
    return build("youtube", "v3", credentials=creds)

def upload_video(youtube, file_path, metadata, publish_time, channel_id=None):
    """Upload une vidéo sur YouTube avec les métadonnées"""
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Fichier vidéo {file_path} introuvable")
        
        # Construction du corps avec valeurs par défaut
        body = {
            "snippet": {
                "title": metadata["title"],
                "description": metadata["description"],
                "categoryId": metadata.get("category_id", "27"),
                "defaultLanguage": metadata.get("default_language", "fr"),
                "defaultAudioLanguage": metadata.get("default_audio_language", "fr")
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_time,
                "selfDeclaredMadeForKids": False
            }
        }
        
        # Ajout des tags si disponibles
        if "tags" in metadata and metadata["tags"]:
            body["snippet"]["tags"] = metadata["tags"]
        
        # Spécifier la chaîne si nécessaire
        if channel_id:
            body["snippet"]["channelId"] = channel_id
        
        # Upload de la vidéo
        media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        logger.info("Démarrage de l'upload YouTube...")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Progression: {int(status.progress() * 100)}%")
        
        video_id = response["id"]
        return f"https://youtu.be/{video_id}"
        
    except HttpError as e:
        error = json.loads(e.content.decode()).get('error', {})
        logger.error(f"Erreur YouTube: {error.get('message')}")
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'upload: {str(e)}")
        raise
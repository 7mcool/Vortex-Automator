import os
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from utils.config import CONFIG
from utils.logger import log_error

def get_youtube_service(token_file):
    """Obtient un service YouTube authentifié avec gestion robuste des erreurs"""
    try:
        token_path = os.path.join(CONFIG['PROJECT_ROOT'], token_file)
        
        # Vérification des prérequis
        if not os.path.exists(CONFIG['CLIENT_SECRET_PATH']):
            raise FileNotFoundError(
                f"Fichier client_secret.json introuvable à: {CONFIG['CLIENT_SECRET_PATH']}\n"
                "Téléchargez-le depuis Google Cloud Console"
            )
        
        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, CONFIG['SCOPES'])
        
        # Gestion du flux d'authentification
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"⚠️ Erreur rafraîchissement token: {str(e)}")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        CONFIG['CLIENT_SECRET_PATH'], CONFIG['SCOPES'])
                    creds = flow.run_local_server(port=0)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CONFIG['CLIENT_SECRET_PATH'], CONFIG['SCOPES'])
                creds = flow.run_local_server(port=0)
            
            with open(token_path, "w") as token:
                token.write(creds.to_json())
        
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    
    except Exception as e:
        log_error(f"ERREUR AUTHENTIFICATION: {str(e)}")
        return None
import json
from googleapiclient.errors import HttpError
from utils.config import CONFIG
from utils.logger import log_error

def configure_channel_settings(youtube_service):
    """Configure les paramètres par défaut de la chaîne YouTube"""
    try:
        # Récupération des informations de la chaîne
        channels_response = youtube_service.channels().list(
            part="brandingSettings",
            mine=True
        ).execute()
        
        if not channels_response.get("items"):
            log_error("Aucune chaîne YouTube trouvée pour ce compte")
            return False
        
        channel = channels_response["items"][0]
        channel_id = channel["id"]
        branding_settings = channel.get("brandingSettings", {})
        
        # Mise à jour des paramètres
        branding_settings.setdefault("channel", {})["defaultLanguage"] = "fr"
        branding_settings.setdefault("channel", {})["country"] = "FR"
        
        # Configuration des valeurs par défaut pour les uploads
        upload_defaults = branding_settings.get("channel", {}).setdefault("uploadDefaults", {})
        upload_defaults["automaticChapters"] = False
        upload_defaults["automaticPlaces"] = False
        upload_defaults["automaticConcepts"] = False
        
        # Appel API pour mise à jour
        youtube_service.channels().update(
            part="brandingSettings",
            body={
                "id": channel_id,
                "brandingSettings": branding_settings
            }
        ).execute()
        
        print("✅ Configuration de la chaîne mise à jour")
        return True
        
    except HttpError as e:
        error = json.loads(e.content.decode()).get('error', {})
        log_error(f"ERREUR CONFIG CHAÎNE [{e.resp.status}]: {error.get('message')}")
        return False
    except Exception as e:
        log_error(f"ERREUR CONFIGURATION: {str(e)}")
        return False
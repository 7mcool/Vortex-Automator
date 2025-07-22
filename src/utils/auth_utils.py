import os
import json
import logging
from google.oauth2.credentials import Credentials

logger = logging.getLogger("Auth")

def validate_token(token_path, scopes):
    """Valide un token d'authentification Google"""
    try:
        if not os.path.exists(token_path):
            logger.warning(f"Token introuvable: {token_path}")
            return False
        
        creds = Credentials.from_authorized_user_file(token_path, scopes)
        return creds and creds.valid
    except Exception as e:
        logger.error(f"Erreur validation token {token_path}: {str(e)}")
        return False

def get_valid_channels(auth_dir, scopes):
    """Retourne les tokens valides pour les chaînes"""
    valid_tokens = []
    for filename in os.listdir(auth_dir):
        if filename.startswith("token_") and filename.endswith(".json"):
            token_path = os.path.join(auth_dir, filename)
            if validate_token(token_path, scopes):
                # Extraire le nom de la chaîne du nom de fichier
                channel_name = filename[6:-5].replace("_", " ").title()
                valid_tokens.append({
                    "token_file": filename,
                    "name": channel_name
                })
    
    if not valid_tokens:
        logger.error("Aucun token d'authentification valide trouvé!")
    
    return valid_tokens
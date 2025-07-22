import yaml
import os
import logging

logger = logging.getLogger(__name__)

def load_config(file_path):
    """Charge un fichier de configuration YAML"""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Erreur chargement configuration {file_path}: {str(e)}")
        return None

def load_all_configs(config_dir="config"):
    """Charge la configuration globale et toutes les configurations de chaînes"""
    configs = {
        "global": load_config(os.path.join(config_dir, "app_config.yaml")),
        "channels": []
    }
    
    channels_dir = os.path.join(config_dir, "channels")
    if os.path.exists(channels_dir):
        for filename in os.listdir(channels_dir):
            if filename.endswith((".yaml", ".yml")):
                channel_config = load_config(os.path.join(channels_dir, filename))
                if channel_config:
                    configs["channels"].append(channel_config)
    
    return configs

def validate_config(config):
    """Valide la configuration minimale requise"""
    errors = []
    
    # Vérification globale
    if "global" not in config:
        errors.append("Section 'global' manquante dans la configuration")
    else:
        required_global = ["default_source_dir", "publish_hours"]
        for field in required_global:
            if field not in config["global"]:
                errors.append(f"Champ global requis manquant: {field}")
    
    # Vérification des chaînes
    if not config.get("channels"):
        errors.append("Aucune configuration de chaîne trouvée")
    else:
        for i, channel in enumerate(config["channels"]):
            required_channel = ["name", "channel_id", "token_file", "daily_limit"]
            for field in required_channel:
                if field not in channel:
                    errors.append(f"Chaîne {i+1}: Champ requis manquant: {field}")
    
    if errors:
        for error in errors:
            logger.error(error)
        return False
    return True
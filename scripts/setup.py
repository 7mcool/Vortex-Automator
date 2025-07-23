#!/usr/bin/env python3
"""
🌪️ Vortex-Automator - Setup Wizard (v3.0)
Interactive + Auto mode + Validation + Multi-Channel
"""

import os, sys, yaml, json, shutil, re, requests
from datetime import datetime
from pathlib import Path

class Colors:
    HEADER = '\033[95m'
    OK = '\033[92m'
    WARN = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

STATE_FILE = '.setup_state.json'
CHANNEL_TEMPLATE = "config/channels/channel_template.yaml"

def save_state(step: str, data: dict):
    """Sauvegarde la progression avec vérification de l'état"""
    state = {}
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
        except json.JSONDecodeError:
            state = {}
    
    state[step] = data
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def load_state(step: str):
    """Reprend la configuration depuis l'étape sauvegardée"""
    if not Path(STATE_FILE).exists():
        return {}
    
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            return state.get(step, {})
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def validate_deepseek_key(key: str) -> bool:
    """Vérifie la validité de la clé DeepSeek avec timeout"""
    try:
        headers = {"Authorization": f"Bearer {key}"}
        r = requests.get("https://api.deepseek.com/v1/models", headers=headers, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False

def validate_youtube_id(channel_id: str) -> bool:
    """Vérifie le format des ID YouTube"""
    return re.match(r'^UC[\w-]{22}$', channel_id) is not None

def validate_directory(path: str) -> bool:
    """Vérifie si le chemin est un dossier accessible"""
    try:
        return Path(path).is_dir() and os.access(path, os.R_OK | os.W_OK)
    except OSError:
        return False

def configure_global_settings(auto_mode: bool = False) -> dict:
    """Configuration globale avec validation améliorée"""
    if (saved := load_state("global")):
        print(f"{Colors.OK}Configuration globale chargée depuis la sauvegarde{Colors.END}")
        return saved

    print(f"\n{Colors.HEADER}🌍 Configuration Globale{Colors.END}")

    config = {
        'default_source_dir': "./videos",
        'whisper_model': "medium",
        'deepseek_api_key': os.getenv("DEEPSEEK_API_KEY", ""),
        'publish_hours': [9, 12, 15, 18, 21],
        'log_retention_days': 30,
    }

    if not auto_mode:
        config.update({
            'default_source_dir': input("📁 Dossier source des vidéos [./videos]: ") or "./videos",
            'whisper_model': input("🎤 Modèle Whisper (base/small/medium/large) [medium]: ") or "medium",
            'deepseek_api_key': input("🧠 Clé DeepSeek: "),
            'log_retention_days': int(input("📆 Jours de rétention des logs [30]: ") or 30),
        })

    # Validation des entrées
    if not validate_deepseek_key(config['deepseek_api_key']):
        print(f"{Colors.FAIL}❌ Clé DeepSeek invalide ! Vérifiez la clé et réessayez.{Colors.END}")
        sys.exit(1)
    
    if not validate_directory(config['default_source_dir']):
        print(f"{Colors.WARN}⚠️ Le dossier source n'existe pas. Création...{Colors.END}")
        Path(config['default_source_dir']).mkdir(parents=True, exist_ok=True)

    save_state("global", config)
    return config

def configure_channel(channel_index: int, auto_mode: bool = False) -> dict:
    """Configure une chaîne YouTube avec validation"""
    print(f"\n{Colors.HEADER}📺 Configuration de la Chaîne #{channel_index}{Colors.END}")
    
    channel = {
        'name': f"Chaîne {channel_index}",
        'channel_id': "UCXXXXXXXXXXXXXXXXXXXXXX",  # Placeholder
        'token_file': f"token_channel_{channel_index}.json",
        'daily_limit': 3
    }

    if not auto_mode:
        channel.update({
            'name': input("🔤 Nom de la chaîne: "),
            'channel_id': input("🆔 ID de la chaîne (commence par UC...): "),
            'token_file': input("🔑 Nom du fichier token [token_channel.json]: ") or "token_channel.json",
            'daily_limit': int(input("🔢 Nombre de vidéos par jour [3]: ") or 3)
        })

    # Validation de l'ID YouTube
    if not validate_youtube_id(channel['channel_id']):
        print(f"{Colors.FAIL}❌ Format d'ID YouTube invalide ! Doit commencer par UC et faire 24 caractères.{Colors.END}")
        sys.exit(1)

    # Options avancées
    if not auto_mode and input("⚙️ Configurer des options avancées? (y/n): ").lower() == 'y':
        channel.update({
            'source_dir': input("📁 Dossier source spécifique (laisser vide pour utiliser le global): ") or None,
            'done_dir': input("📁 Dossier pour vidéos traitées [done_videos]: ") or "done_videos",
            'error_dir': input("📁 Dossier pour vidéos en échec [failed_uploads]: ") or "failed_uploads",
            'category_id': input("🏷️ Catégorie YouTube [27=Éducation]: ") or "27",
            'default_language': input("🌐 Langue par défaut [fr]: ") or "fr"
        })

    return channel

def setup_google_auth():
    """Guide l'utilisateur pour l'authentification Google"""
    print(f"\n{Colors.HEADER}🔐 Configuration de l'Authentification Google{Colors.END}")
    print(f"{Colors.BOLD}ÉTAPES REQUISES:{Colors.END}")
    print("1. Allez sur https://console.cloud.google.com/")
    print("2. Créez un projet et activez l'API YouTube Data v3")
    print("3. Configurez l'écran de consentement OAuth")
    print("4. Créez des identifiants OAuth 2.0 (Type: Application bureautique)")
    print("5. Téléchargez le fichier client_secret.json")
    print(f"\n{Colors.WARN}⚠️ Placez le fichier téléchargé dans le dossier 'auth/' avant de continuer{Colors.END}")
    input("\nAppuyez sur Entrée quand c'est fait...")

    # Vérification basique
    if not Path("auth/client_secret.json").exists():
        print(f"{Colors.FAIL}❌ Fichier client_secret.json introuvable !{Colors.END}")
        return False
    return True

def create_initial_state(channels: list):
    """Crée le fichier d'état initial avec les chaînes"""
    state = {
        "last_processed_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "channel_dates": {channel['channel_id']: {} for channel in channels}
    }
    with open('publishing_state.json', 'w') as f:
        json.dump(state, f, indent=2)

def generate_channel_template(channel_config: dict):
    """Crée un template de configuration de chaîne"""
    with open(CHANNEL_TEMPLATE, 'w') as f:
        yaml.dump(channel_config, f, sort_keys=False)
    print(f"{Colors.OK}✓ Template de chaîne créé: {CHANNEL_TEMPLATE}{Colors.END}")

def rollback():
    """Supprime les fichiers créés en cas d'erreur"""
    for path in [
        "config/app_config.yaml",
        "publishing_state.json",
        STATE_FILE,
        CHANNEL_TEMPLATE
    ] + list(Path("config/channels").glob("channel_*.yaml")):
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as e:
            print(f"{Colors.WARN}⚠️ Erreur suppression {path}: {e}{Colors.END}")
    
    print(f"{Colors.WARN}⚠️ Configuration annulée - Fichiers supprimés{Colors.END}")

def main():
    parser = argparse.ArgumentParser(description="Assistant de configuration pour Vortex-Automator")
    parser.add_argument("--auto", action="store_true", help="Mode non-interactif avec valeurs par défaut")
    parser.add_argument("--channels", type=int, default=1, help="Nombre de chaînes à configurer (mode auto)")
    args = parser.parse_args()

    try:
        # Création des dossiers de base
        Path("config/channels").mkdir(parents=True, exist_ok=True)
        Path("auth").mkdir(exist_ok=True)
        
        # Configuration globale
        global_config = configure_global_settings(args.auto)
        with open('config/app_config.yaml', 'w') as f:
            yaml.dump(global_config, f, sort_keys=False)

        # Configuration des chaînes
        channels = []
        channel_count = args.channels if args.auto else int(input("\nNombre de chaînes à configurer: ") or 1)
        
        for i in range(channel_count):
            channel = configure_channel(i+1, args.auto)
            channel_filename = f"config/channels/channel_{i+1}.yaml"
            with open(channel_filename, 'w') as f:
                yaml.dump(channel, f, sort_keys=False)
            channels.append(channel)
        
        # Créer un template pour les nouvelles chaînes
        generate_channel_template(channels[0])

        # Authentification Google
        if not args.auto and not setup_google_auth():
            print(f"{Colors.FAIL}❌ Authentification requise !{Colors.END}")
            rollback()
            sys.exit(1)

        # Initialisation de l'état de publication
        create_initial_state(channels)

        # Création des dossiers supplémentaires
        for folder in ["logs", "done_videos", "failed_uploads", "temp"]:
            Path(folder).mkdir(exist_ok=True)

        print(f"\n{Colors.OK}{Colors.BOLD}✅ Configuration terminée avec succès !{Colors.END}")
        print(f"Prochaines étapes:")
        print(f"1. Authentifiez vos chaînes avec: {Colors.BOLD}python src/main.py --authenticate{Colors.END}")
        print(f"2. Lancez l'automatisation: {Colors.BOLD}python src/main.py{Colors.END}")

    except Exception as e:
        print(f"{Colors.FAIL}❌ Erreur critique: {e}{Colors.END}")
        rollback()
        sys.exit(1)
    except KeyboardInterrupt:
        rollback()
        print(f"{Colors.WARN}⚠️ Configuration annulée par l'utilisateur{Colors.END}")
        sys.exit(0)

if __name__ == "__main__":
    import argparse
    main()
#!/usr/bin/env python3
"""
Vortex-Automator - Assistant de Configuration Complète
"""

import os
import sys
import yaml
import json
import shutil
from datetime import datetime

# Configuration des couleurs pour le terminal
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def clear_screen():
    """Efface l'écran du terminal"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    """Affiche l'en-tête du programme"""
    clear_screen()
    print(f"{bcolors.HEADER}{bcolors.BOLD}")
    print("=" * 60)
    print("⚙️ VORTEX-AUTOMATOR - CONFIGURATION COMPLÈTE")
    print("=" * 60)
    print(f"{bcolors.ENDC}")

def create_directory_structure():
    """Crée la structure de dossiers nécessaire"""
    dirs = [
        'config/channels',
        'auth',
        'logs',
        'done_videos',
        'failed_uploads',
        'temp'
    ]
    
    for directory in dirs:
        os.makedirs(directory, exist_ok=True)
        print(f"{bcolors.OKGREEN}✓{bcolors.ENDC} Dossier créé: {directory}")

def configure_global_settings():
    """Configure les paramètres globaux"""
    print(f"\n{bcolors.BOLD}🌍 CONFIGURATION GLOBALE{bcolors.ENDC}")
    print(f"{bcolors.OKBLUE}Remplissez les paramètres applicables à toutes les chaînes{bcolors.ENDC}")
    
    config = {
        'default_source_dir': input("\n📂 Dossier source des vidéos [D:/Videos]: ") or "D:/Videos",
        'whisper_model': input("🔊 Modèle Whisper (base/small/medium/large) [medium]: ") or "medium",
        'deepseek_api_key': input("🧠 Clé API DeepSeek: "),
        'publish_hours': [9, 12, 15, 18, 21],
        'log_retention_days': int(input("📆 Jours de rétention des logs [30]: ") or 30),
        'min_ram_gb': 8,
        'min_vram_gb': 4,
        'state_file': "publishing_state.json"
    }
    
    with open('config/app_config.yaml', 'w') as f:
        yaml.dump(config, f, sort_keys=False)
    
    print(f"{bcolors.OKGREEN}✓ Configuration globale sauvegardée!{bcolors.ENDC}")
    return config

def configure_channel():
    """Configure une chaîne YouTube individuelle"""
    print(f"\n{bcolors.BOLD}📺 CONFIGURATION D'UNE CHAÎNE YOUTUBE{bcolors.ENDC}")
    
    channel = {
        'name': input("\nNom de la chaîne: "),
        'channel_id': input("ID de la chaîne (commence par UC...): "),
        'token_file': input("Nom du fichier token [token_chaine1.json]: ") or "token_chaine1.json",
        'daily_limit': int(input("Nombre de vidéos par jour [3]: ") or 3)
    }
    
    # Options avancées
    if input("\nConfigurer des options avancées? (y/n): ").lower() == 'y':
        channel['source_dir'] = input("Dossier source spécifique (laisser vide pour utiliser le global): ") or None
        channel['done_dir'] = input("Dossier pour vidéos traitées [done_videos]: ") or "done_videos"
        channel['error_dir'] = input("Dossier pour vidéos en échec [failed_uploads]: ") or "failed_uploads"
        channel['category_id'] = input("Catégorie YouTube [27=Éducation]: ") or "27"
        channel['default_language'] = input("Langue par défaut [fr]: ") or "fr"
    
    return channel

def configure_channels():
    """Configure plusieurs chaînes YouTube"""
    channels = []
    channel_count = 1
    
    while True:
        print_header()
        print(f"\n{bcolors.BOLD}Chaîne #{channel_count}{bcolors.ENDC}")
        channel = configure_channel()
        channels.append(channel)
        channel_count += 1
        
        if input("\nAjouter une autre chaîne? (y/n): ").lower() != 'y':
            break
    
    # Sauvegarder les configurations
    for i, channel in enumerate(channels):
        filename = f"config/channels/channel_{i+1}.yaml"
        with open(filename, 'w') as f:
            yaml.dump(channel, f, sort_keys=False)
        print(f"{bcolors.OKGREEN}✓ Configuration sauvegardée: {filename}{bcolors.ENDC}")
    
    # Créer un template
    if channels:
        with open("config/channels/channel_template.yaml", 'w') as f:
            yaml.dump(channels[0], f, sort_keys=False)
    
    return len(channels)

def setup_authentication():
    """Guide l'utilisateur pour l'authentification Google"""
    print(f"\n{bcolors.BOLD}🔐 CONFIGURATION AUTHENTIFICATION GOOGLE{bcolors.ENDC}")
    print(f"\n{bcolors.WARNING}ÉTAPES REQUISES:{bcolors.ENDC}")
    print("1. Allez sur https://console.cloud.google.com/")
    print("2. Créez un projet et activez l'API YouTube Data v3")
    print("3. Configurez l'écran de consentement OAuth")
    print("4. Créez des identifiants OAuth 2.0 (Type: Application bureautique)")
    print("5. Téléchargez le fichier client_secret.json")
    print("\nPlacez le fichier téléchargé dans le dossier 'auth/'")
    
    input("\nAppuyez sur Entrée quand c'est fait...")
    
    # Vérifier la présence du fichier
    if not os.path.exists('auth/client_secret.json'):
        print(f"{bcolors.FAIL}❌ Fichier client_secret.json introuvable!{bcolors.ENDC}")
        return False
    
    return True

def generate_initial_state():
    """Génère le fichier d'état initial"""
    state = {
        "last_processed_date": datetime.now().strftime("%Y-%m-%d"),
        "channel_dates": {}
    }
    
    with open('publishing_state.json', 'w') as f:
        json.dump(state, f, indent=2)
    
    print(f"{bcolors.OKGREEN}✓ Fichier d'état généré!{bcolors.ENDC}")

def final_instructions():
    """Affiche les instructions finales"""
    print(f"\n{bcolors.BOLD}✅ CONFIGURATION TERMINÉE AVEC SUCCÈS!{bcolors.ENDC}")
    print("\nProchaines étapes:")
    print("1. Authentifiez chaque chaîne avec:")
    print("   python src/main.py --authenticate")
    print("2. Lancez l'automatisation:")
    print("   python src/main.py")
    print("\nPour modifier la configuration:")
    print("- Éditez les fichiers dans config/")
    print("- Ou relancez ce script")

def main():
    print_header()
    print(f"{bcolors.OKBLUE}Ce script va vous guider dans la configuration complète de Vortex-Automator{bcolors.ENDC}")
    
    # Créer la structure de dossiers
    create_directory_structure()
    
    # Configuration globale
    global_config = configure_global_settings()
    
    # Configuration des chaînes
    channel_count = configure_channels()
    
    # Configuration d'authentification
    if not setup_authentication():
        print(f"{bcolors.FAIL}❌ Configuration d'authentification incomplète!{bcolors.ENDC}")
        sys.exit(1)
    
    # Fichier d'état initial
    generate_initial_state()
    
    # Instructions finales
    final_instructions()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nConfiguration annulée.")
        sys.exit(0)
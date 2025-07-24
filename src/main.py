import os
import sys
import torch
from utils.logger import setup_logger
from utils.config import CONFIG
from core.processor import process_all_channels
from ai.whisper import load_whisper_model

def check_ffmpeg():
    """Vérifie que FFmpeg est installé"""
    try:
        result = subprocess.run(['ffprobe', '-version'], 
                                stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE,
                                text=True)
        if result.returncode != 0:
            print("❌ FFmpeg n'est pas installé ou configuré correctement")
            print("👉 Téléchargez-le depuis: https://ffmpeg.org/download.html")
            print("👉 Ajoutez le dossier bin de FFmpeg à votre PATH")
            sys.exit(1)
        return True
    except Exception:
        print("❌ Impossible d'exécuter ffprobe - Vérifiez l'installation de FFmpeg")
        sys.exit(1)

def main():
    """Point d'entrée principal de l'application"""
    # Initialisation du système
    print("=" * 60)
    print("🤖 VORTEX AUTOMATOR - ROBOT YOUTUBE PREMIUM")
    print("=" * 60)
    
    # Vérification des dépendances critiques
    print("\n🔍 Vérification des prérequis système...")
    check_ffmpeg()
    print("✅ FFmpeg est correctement installé")
    
    # Configuration du logger
    log_file = setup_logger()
    print(f"📝 Fichier journal: {log_file}")
    
    # Chargement du modèle Whisper
    print("\n🔈 Chargement du modèle de transcription audio...")
    try:
        whisper_model = load_whisper_model()
        device = "GPU 🔥" if CONFIG['WHISPER_DEVICE'] == "cuda" else "CPU"
        print(f"✅ Modèle '{CONFIG['WHISPER_MODEL']}' chargé sur {device}")
    except Exception as e:
        print(f"❌ ERREUR: Impossible de charger le modèle Whisper: {str(e)}")
        sys.exit(1)
    
    # Traitement principal
    print("\n" + "=" * 60)
    print("🚀 DÉMARRAGE DU TRAITEMENT DES VIDÉOS")
    print("=" * 60)
    
    try:
        process_all_channels(whisper_model, log_file)
        print("\n✅✅✅ TRAITEMENT RÉUSSI - VIDÉOS PROGRAMMÉES ✅✅✅")
    except Exception as e:
        print(f"\n❌❌❌ ERREUR CRITIQUE: {str(e)} ❌❌❌")
        sys.exit(1)
    
    # Fin du programme
    print("\n" + "=" * 60)
    print(f"📋 Rapport complet disponible dans: {log_file}")
    print("=" * 60)

if __name__ == "__main__":
    main()
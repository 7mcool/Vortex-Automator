import os
import time
import json
import glob
from datetime import datetime, timedelta, timezone
from utils.config import CONFIG
from utils.file_utils import get_video_duration, move_to_processed
from utils.logger import log_channel_header, log_video_start, log_video_progress, log_video_result
from utils.scheduler import load_publishing_state, save_publishing_state, get_next_publishing_date
from youtube.auth import get_youtube_service
from youtube.api import configure_channel_settings
from youtube.uploader import upload_video
from ai.whisper import transcribe_video
from ai.deepseek import generate_video_metadata

def get_videos_to_process(state, target_date):
    """Récupère et filtre les vidéos à traiter en fonction de l'état actuel"""
    try:
        source_dir = os.path.join(CONFIG['PROJECT_ROOT'], "source_videos")
        os.makedirs(source_dir, exist_ok=True)
        
        # Récupération de toutes les vidéos
        all_videos = sorted(glob.glob(os.path.join(source_dir, "*.mp4")))
        if not all_videos:
            print("ℹ️ Aucune vidéo trouvée dans le dossier source")
            return [], {}
        
        # Calcul des limites
        scheduled_today = state["scheduled_dates"].get(target_date, 0)
        total_daily_limit = CONFIG['DAILY_LIMIT'] * len(CONFIG['CHANNELS'])
        available_slots = total_daily_limit - scheduled_today
        
        if available_slots <= 0:
            print("ℹ️ Toutes les publications d'aujourd'hui sont programmées")
            return [], {}
        
        # Sélection des vidéos à traiter
        videos_to_process = all_videos[:min(available_slots, len(all_videos))]
        return videos_to_process, {
            "total_videos": len(all_videos),
            "scheduled_today": scheduled_today,
            "available_slots": available_slots,
            "processing_count": len(videos_to_process)
        }
    
    except Exception as e:
        print(f"❌ Erreur sélection vidéos: {str(e)}")
        return [], {}

def distribute_videos_to_channels(videos):
    """Répartit les vidéos entre les différentes chaînes"""
    distribution = {}
    videos_per_channel = CONFIG['DAILY_LIMIT']
    
    for channel in CONFIG['CHANNELS']:
        if not videos:
            break
        channel_videos = videos[:videos_per_channel]
        videos = videos[videos_per_channel:]
        distribution[channel['name']] = {
            "channel": channel,
            "videos": channel_videos
        }
    
    return distribution

def process_video(channel, video_path, slot, whisper_model, log_file, state):
    """Traite une vidéo individuelle avec gestion complète des erreurs"""
    video_name = os.path.basename(video_path)
    log_video_start(log_file, video_name, channel["name"])
    start_time = time.time()
    
    try:
        # Étape 1: Transcription
        log_video_progress(log_file, "Démarrage transcription audio...")
        transcript = transcribe_video(whisper_model, video_path)
        if not transcript:
            raise ValueError("La transcription a retourné un résultat vide")
        
        # Étape 2: Génération des métadonnées
        log_video_progress(log_file, "Création des métadonnées optimisées...")
        metadata = generate_video_metadata(transcript, video_path)
        
        # Étape 3: Upload YouTube
        log_video_progress(log_file, "Lancement de l'upload YouTube...")
        target_date = get_next_publishing_date(state)
        video_url = upload_video(
            get_youtube_service(channel["token_file"]),
            video_path,
            metadata,
            slot,
            target_date
        )
        
        # Étape 4: Déplacement de la vidéo traitée
        move_to_processed(video_path, channel["done_dir"])
        
        # Journalisation du résultat
        duration = time.time() - start_time
        log_video_result(log_file, metadata, duration, video_url)
        
        # Mise à jour de l'état
        state["scheduled_dates"][target_date] = state["scheduled_dates"].get(target_date, 0) + 1
        save_publishing_state(state)
        
        return True
    
    except Exception as e:
        log_video_progress(log_file, f"ERREUR: {str(e)}", is_error=True)
        
        # Déplacement vers le dossier d'erreur
        error_dir = os.path.join(CONFIG['PROJECT_ROOT'], "failed_uploads")
        os.makedirs(error_dir, exist_ok=True)
        move_to_processed(video_path, error_dir)
        log_video_progress(log_file, f"Vidéo déplacée vers: {error_dir}")
        
        return False

def process_channel(channel_data, whisper_model, log_file, state):
    """Traite toutes les vidéos attribuées à une chaîne"""
    channel = channel_data["channel"]
    videos = channel_data["videos"]
    
    if not videos:
        print(f"ℹ️ Aucune vidéo à traiter pour {channel['name']}")
        return 0, 0
    
    log_channel_header(log_file, channel, videos)
    
    # Initialisation du service YouTube
    try:
        youtube_service = get_youtube_service(channel["token_file"])
        if not youtube_service:
            raise ConnectionError("Échec de connexion à l'API YouTube")
        
        configure_channel_settings(youtube_service)
    except Exception as e:
        log_video_progress(log_file, f"ERREUR INITIALISATION: {str(e)}", is_error=True)
        return 0, len(videos)
    
    # Traitement des vidéos
    success_count = 0
    for i, video_path in enumerate(videos):
        if process_video(channel, video_path, i, whisper_model, log_file, state):
            success_count += 1
    
    return success_count, len(videos)

def process_all_channels(whisper_model, log_file):
    """Orchestre le traitement pour toutes les chaînes"""
    # Chargement de l'état
    state = load_publishing_state()
    target_date = get_next_publishing_date(state)
    print(f"📅 Date de publication cible: {target_date}")
    
    # Sélection des vidéos
    videos, stats = get_videos_to_process(state, target_date)
    if not videos:
        return
    
    print(f"🎯 Vidéos à traiter: {stats['processing_count']}/{stats['total_videos']}")
    print(f"📊 Statut: {stats['scheduled_today']} vidéos déjà programmées aujourd'hui")
    
    # Répartition des vidéos
    distribution = distribute_videos_to_channels(videos)
    
    # Traitement par chaîne
    total_success = 0
    total_processed = 0
    
    for channel_name, channel_data in distribution.items():
        print(f"\n📺 Traitement pour {channel_name}...")
        success, total = process_channel(channel_data, whisper_model, log_file, state)
        total_success += success
        total_processed += total
        print(f"  ✅ {success}/{total} vidéos traitées avec succès")
    
    # Rapport final
    print("\n" + "=" * 60)
    print(f"📊 RAPPORT FINAL: {total_success}/{total_processed} vidéos publiées")
    print("=" * 60)
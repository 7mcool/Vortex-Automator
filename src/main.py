import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from src.utils import logger, config_loader, file_utils, hardware_check, auth_utils
from src.core import youtube_uploader, transcriber, metadata_generator, scheduler

# Initialisation du système de journalisation
LOG_DIR = "logs"
log_file = logger.setup_logging(LOG_DIR)
logger.log_system_info()

# Récupération du logger principal
main_logger = logging.getLogger("Main")

def main():
    main_logger.info("=" * 60)
    main_logger.info("🤖 DÉMARRAGE DE VORTEX-AUTOMATOR")
    main_logger.info("=" * 60)
    
    try:
        # ========= CHARGEMENT DE LA CONFIGURATION ========= #
        main_logger.info("🔧 Chargement de la configuration...")
        config = config_loader.load_all_configs()
        
        if not config or "global" not in config:
            main_logger.error("Configuration globale manquante ou invalide")
            return
        
        if not config_loader.validate_config(config):
            main_logger.error("Erreurs de configuration détectées, arrêt du programme")
            return
        
        global_config = config["global"]
        channels_config = config["channels"]
        
        main_logger.info(f"📋 Configuration chargée: {len(channels_config)} chaîne(s) configurée(s)")
        
        # ========= VÉRIFICATION MATÉRIELLE ========= #
        main_logger.info("🔍 Vérification des ressources système...")
        hw_report = hardware_check.check_system_resources()
        hardware_check.log_resource_report(hw_report)
        
        if hw_report.get("issues"):
            if input("❌ Des problèmes matériels ont été détectés. Continuer? (y/n): ").lower() != 'y':
                main_logger.warning("Arrêt demandé par l'utilisateur")
                return
        
        # ========= VÉRIFICATION DES AUTHENTIFICATIONS ========= #
        main_logger.info("🔑 Vérification des authentifications YouTube...")
        scopes = youtube_uploader.SCOPES
        valid_channels = auth_utils.get_valid_channels("auth", scopes)
        
        if not valid_channels:
            main_logger.error("Aucune authentification valide, arrêt du programme")
            return
        
        main_logger.info(f"✅ Authentifications valides: {len(valid_channels)} chaîne(s)")
        
        # ========= CHARGEMENT DE L'ÉTAT ========= #
        state_file = global_config.get("state_file", "publishing_state.json")
        state = scheduler.load_publishing_state(state_file)
        main_logger.info("📊 État des publications chargé")
        
        # ========= TRAITEMENT PAR CHAÎNE ========= #
        for channel_config in channels_config:
            channel_name = channel_config["name"]
            channel_id = channel_config["channel_id"]
            
            main_logger.info("\n" + "=" * 40)
            main_logger.info(f"📺 TRAITEMENT DE LA CHAÎNE: {channel_name}")
            main_logger.info("=" * 40)
            
            # Trouver le dossier source pour cette chaîne
            source_dir = channel_config.get("source_dir", global_config["default_source_dir"])
            if not os.path.exists(source_dir):
                main_logger.error(f"❌ Dossier source introuvable: {source_dir}")
                continue
                
            # Trouver les vidéos à traiter
            video_files = file_utils.find_videos(source_dir)
            if not video_files:
                main_logger.warning(f"Aucune vidéo trouvée dans: {source_dir}")
                continue
                
            main_logger.info(f"🎬 Vidéos à traiter: {len(video_files)}")
            
            # Vérifier si le token est valide pour cette chaîne
            token_valid = any(
                chan["name"] == channel_name 
                for chan in valid_channels
            )
            if not token_valid:
                main_logger.error(f"Token invalide ou manquant pour {channel_name}")
                continue
                
            # Obtenir le service YouTube pour cette chaîne
            token_path = os.path.join("auth", channel_config["token_file"])
            client_secret_path = os.path.join("auth", "client_secret.json")
            
            try:
                youtube_service = youtube_uploader.get_youtube_service(
                    token_path, 
                    client_secret_path, 
                    scopes
                )
                main_logger.info("✅ Service YouTube initialisé avec succès")
            except Exception as e:
                main_logger.error(f"Échec initialisation YouTube: {str(e)}")
                continue
                
            # ========= TRAITEMENT DES VIDÉOS ========= #
            processed_count = 0
            daily_limit = channel_config["daily_limit"]
            
            for video_path in video_files[:daily_limit]:
                try:
                    video_name = os.path.basename(video_path)
                    main_logger.info("\n" + "-" * 40)
                    main_logger.info(f"🎬 Début traitement: {video_name}")
                    start_time = time.time()
                    
                    # ========= TRANSCRIPTION ========= #
                    main_logger.info("🔊 Démarrage transcription...")
                    whisper_model = global_config.get("whisper_model", "base")
                    transcription = transcriber.transcribe_video(
                        video_path, 
                        model_name=whisper_model
                    )
                    main_logger.info(f"📝 Transcription réussie ({len(transcription)} caractères)")
                    
                    # ========= DURÉE DE LA VIDÉO ========= #
                    duration = transcriber.get_video_duration(video_path)
                    main_logger.info(f"⏱️ Durée vidéo: {duration/60:.1f} minutes")
                    
                    # ========= GÉNÉRATION DES MÉTADONNÉES ========= #
                    main_logger.info("🧠 Génération des métadonnées...")
                    api_key = global_config.get("deepseek_api_key", "")
                    metadata = metadata_generator.generate_metadata(
                        api_key, 
                        transcription, 
                        video_path, 
                        duration
                    )
                    main_logger.info(f"✨ Métadonnées générées: {metadata['title']}")
                    
                    # ========= PLANIFICATION ========= #
                    publish_hours = global_config["publish_hours"]
                    publish_time = scheduler.get_next_publishing_slot(
                        state, 
                        channel_id, 
                        daily_limit, 
                        publish_hours
                    )
                    main_logger.info(f"⏰ Publication programmée: {publish_time}")
                    
                    # ========= UPLOAD YOUTUBE ========= #
                    main_logger.info("⬆️ Démarrage upload YouTube...")
                    video_url = youtube_uploader.upload_video(
                        youtube_service,
                        video_path,
                        metadata,
                        publish_time,
                        channel_id=channel_id
                    )
                    main_logger.info(f"✅ Vidéo publiée: {video_url}")
                    
                    # ========= DÉPLACEMENT DE LA VIDÉO ========= #
                    done_dir = channel_config.get("done_dir", "done_videos")
                    file_utils.safe_move(video_path, done_dir)
                    
                    # ========= MISE À JOUR DE L'ÉTAT ========= #
                    scheduler.record_publication(
                        state, 
                        channel_id, 
                        publish_time, 
                        state_file
                    )
                    
                    # ========= JOURNALISATION DES RÉSULTATS ========= #
                    processing_time = time.time() - start_time
                    main_logger.info(f"⏱️ Temps de traitement: {processing_time:.1f}s")
                    main_logger.info(f"✅ Traitement réussi: {video_name}")
                    
                    processed_count += 1
                    
                except Exception as e:
                    main_logger.error(f"❌ Échec traitement vidéo: {str(e)}")
                    error_dir = channel_config.get("error_dir", "failed_uploads")
                    file_utils.safe_move(video_path, error_dir, new_name=f"FAILED_{os.path.basename(video_path)}")
                    main_logger.info(f"📦 Vidéo déplacée vers: {error_dir}")
            
            main_logger.info(f"📊 Vidéos traitées pour {channel_name}: {processed_count}/{len(video_files[:daily_limit])}")
        
        # ========= NETTOYAGE FINAL ========= #
        main_logger.info("\n🧹 Nettoyage des anciens fichiers...")
        file_utils.cleanup_directory(LOG_DIR, max_age_days=global_config.get("log_retention_days", 30))
        file_utils.cleanup_directory("temp", max_age_days=1)
        
        main_logger.info("\n" + "=" * 60)
        main_logger.info("✅✅✅ TRAITEMENT TERMINÉ AVEC SUCCÈS ✅✅✅")
        main_logger.info("=" * 60)
        
    except Exception as e:
        main_logger.exception(f"❌❌❌ ERREUR CRITIQUE: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
import whisper
import torch
import subprocess
import logging

logger = logging.getLogger(__name__)

def get_video_duration(video_path):
    """Obtient la durée d'une vidéo en secondes avec ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries',
            'format=duration', '-of', 'csv=p=0', video_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"Erreur ffprobe: {result.stderr.strip()}")
            
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Erreur durée vidéo: {str(e)}")
        return 0

def transcribe_video(video_path, model_name="base", device=None):
    """Transcrit la vidéo avec Whisper et retourne le texte"""
    try:
        logger.info("Chargement du modèle Whisper...")
        
        # Détermination automatique du device si non spécifié
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        
        model = whisper.load_model(model_name, device=device)
        
        logger.info("Démarrage de la transcription...")
        result = model.transcribe(
            video_path,
            fp16=(device == "cuda"),
            language="fr"  # Force la détection du français
        )
        
        transcript = result["text"].strip()
        logger.info(f"Transcription réussie ({len(transcript)} caractères)")
        return transcript
        
    except Exception as e:
        logger.error(f"Erreur transcription: {str(e)}")
        return ""
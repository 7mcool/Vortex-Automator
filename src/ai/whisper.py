import whisper
import time
import os
import torch
from utils.config import CONFIG

def load_whisper_model(model_name=None, device=None):
    """Charge le modèle Whisper avec valeurs par défaut"""
    model = model_name or CONFIG.get('WHISPER_MODEL', 'base')
    device = device or CONFIG.get('WHISPER_DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
    
    print(f"🔊 Chargement du modèle Whisper: {model} (sur {device})")
    return whisper.load_model(model, device=device)

def transcribe_video(model, video_path):
    """Transcrit le contenu audio d'une vidéo"""
    try:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Fichier vidéo introuvable: {video_path}")
        
        start_time = time.time()
        result = model.transcribe(
            video_path,
            fp16=(model.device == "cuda"),
            language="fr"
        )
        duration = time.time() - start_time
        print(f"✅ Transcription réussie en {duration:.1f}s")
        return result["text"].strip()
    except Exception as e:
        print(f"❌ Erreur transcription: {str(e)}")
        return ""
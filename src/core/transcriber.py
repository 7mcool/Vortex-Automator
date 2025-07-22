import whisper
import torch
import subprocess

def get_video_duration(video_path):
    """Obtient la durée d'une vidéo en secondes"""
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries',
        'format=duration', '-of', 'csv=p=0', video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return float(result.stdout.strip())

def transcribe_video(model_name, video_path, device="cuda"):
    """Transcrit la vidéo avec Whisper"""
    model = whisper.load_model(model_name, device=device)
    result = model.transcribe(
        video_path,
        fp16=(device == "cuda"),
        language="fr"
    )
    return result["text"].strip()
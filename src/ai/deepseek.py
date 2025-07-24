import re
import json
from openai import OpenAI
from utils.config import CONFIG
from utils.file_utils import get_video_duration

def generate_video_metadata(transcript, video_path):
    """Génère les métadonnées pour une vidéo avec DeepSeek"""
    try:
        # Configuration par défaut
        api_key = CONFIG.get('DEEPSEEK_API_KEY', '')
        if not api_key:
            print("⚠️ Aucune clé API DeepSeek configurée - Utilisation des métadonnées par défaut")
            return get_default_metadata(video_path)
        
        # Calcul de la durée
        duration_sec = get_video_duration(video_path)
        duration_min = duration_sec / 60 if duration_sec else 0
        
        # Initialisation du client
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )
        
        # Construction du prompt
        prompt = f"""
        Tu es un expert YouTube. Pour la vidéo avec la transcription:
        {transcript[:2000]}{'[...]' if len(transcript) > 2000 else ''}
        
        Durée vidéo: {duration_min:.1f} minutes
        
        Consignes:
        1. Générer un TITRE en MAJUSCULES (max 60 caractères)
        2. Description courte (max 2 lignes) avec 3 hashtags maximum
        3. Si la durée > 5 minutes, générer des chapitres manuels (1 par minute environ)
        4. Format de sortie JSON:
        {{
            "title": "TITRE",
            "description": "Description...",
            "manualChapters": ["00:00 - Chapitre 1", ...]
        }}
        """
        
        # Appel à l'API
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=800
        )
        
        # Extraction des métadonnées
        metadata = json.loads(response.choices[0].message.content)
        
        # Post-traitement
        metadata["title"] = metadata.get("title", "VIDÉO PAR DÉFAUT").upper()
        
        # Limitation des hashtags
        desc = metadata.get("description", "")
        hashtags = re.findall(r'#\w+', desc)
        if len(hashtags) > 3:
            metadata["description"] = re.sub(r'(#\w+\s*){4,}', ' '.join(hashtags[:3]), desc)
        
        return metadata
    
    except Exception as e:
        print(f"❌ Erreur DeepSeek: {str(e)}")
        return get_default_metadata(video_path)

def get_default_metadata(video_path):
    """Retourne des métadonnées par défaut"""
    duration_sec = get_video_duration(video_path)
    duration_min = duration_sec / 60 if duration_sec else 0
    
    chapters = []
    if duration_min > 5:
        chapters = [
            "00:00 - Introduction",
            f"{int(duration_min/2)}:00 - Partie centrale",
            f"{int(duration_min)-1}:00 - Conclusion"
        ]
    
    return {
        "title": "VIDÉO EXCLUSIVE",
        "description": "Découvrez ce contenu premium !\n#youtube #contenu #viral",
        "manualChapters": chapters
    }
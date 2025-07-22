from openai import OpenAI
import re
import json
import logging
import time

logger = logging.getLogger(__name__)

def generate_metadata(api_key, transcript, video_path, duration_sec):
    """Génère les métadonnées optimisées selon les nouvelles consignes"""
    try:
        logger.info("Génération des métadonnées...")
        
        # Calcul de la durée en minutes
        duration_min = duration_sec / 60 if duration_sec > 0 else 0
        
        # Construction du prompt amélioré
        prompt = f"""
        Tu es un expert YouTube. Pour la vidéo avec la transcription:
        {transcript[:2000]}
        
        Durée vidéo: {duration_min:.1f} minutes
        
        Consignes:
        1. DÉTECTION DE LA DURÉE:
           - {"Désactiver les chapitres automatiques et ajouter des chapitres manuels" if duration_min > 5 else "Conserver les chapitres automatiques"}
        
        2. OPTIMISATION DES MÉTADONNÉES:
           - Générer un TITRE en MAJUSCULES (max 60 caractères) sans mention du CTR
           - Description ultracourte (≤ 2 lignes) avec 3 hashtags maximum
           - Ne conserver que les paires avec CTR estimé ≥ 7
        
        3. FORMAT DE SORTIE:
           ```json
           {{
             "title": "TITRE EN MAJUSCULES",
             "description": "Description\\n#hashtag1 #hashtag2 #hashtag3",
             "manualChapters": ["00:00 - Introduction", ...],
             "disableAutoChapters": true/false
           }}
           ```
        """
        
        # Création du client avec gestion des erreurs
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        
        # Tentative avec réessai
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    max_tokens=800,
                    temperature=0.7
                )
                
                # Parser la réponse JSON
                metadata = json.loads(response.choices[0].message.content)
                
                # Validation des champs requis
                for field in ["title", "description", "disableAutoChapters"]:
                    if field not in metadata:
                        raise ValueError(f"Champ manquant: {field}")
                
                # Conversion du titre en majuscules
                metadata["title"] = metadata["title"].upper()
                
                # Gestion des chapitres manuels
                if duration_min > 5:
                    if "manualChapters" not in metadata or not isinstance(metadata["manualChapters"], list):
                        logger.warning("Chapitres manuels manquants, génération de secours...")
                        metadata["manualChapters"] = [
                            "00:00 - Introduction",
                            "01:00 - Partie principale",
                            f"{int(duration_min)-1}:00 - Conclusion"
                        ]
                    metadata["disableAutoChapters"] = True
                else:
                    metadata["disableAutoChapters"] = False
                    metadata["manualChapters"] = []
                
                # Limiter à 3 hashtags maximum
                desc = metadata["description"]
                hashtags = re.findall(r'#\w+', desc)
                if len(hashtags) > 3:
                    metadata["description"] = re.sub(r'(#\w+\s*){4,}', ' '.join(hashtags[:3]), desc)
                
                return metadata
                
            except Exception as e:
                logger.warning(f"Tentative {attempt+1}/3 échouée: {str(e)}")
                time.sleep(2)  # Attente avant réessai
        
        # Fallback après 3 tentatives
        logger.error("Échec de génération des métadonnées, utilisation des valeurs par défaut")
        return {
            "title": "TITRE PAR DÉFAUT",
            "description": "Description par défaut\n#default",
            "disableAutoChapters": duration_min > 5,
            "manualChapters": [
                "00:00 - Introduction",
                "01:00 - Partie principale",
                f"{int(duration_min)-1}:00 - Conclusion"
            ] if duration_min > 5 else []
        }
        
    except Exception as e:
        logger.error(f"Erreur critique: {str(e)}")
        return {
            "title": "ERREUR DE GÉNÉRATION",
            "description": "Une erreur est survenue lors de la génération des métadonnées",
            "disableAutoChapters": False,
            "manualChapters": []
        }
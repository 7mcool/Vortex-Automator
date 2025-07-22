import os
import shutil
import glob
import logging

logger = logging.getLogger(__name__)

def safe_move(source, target_dir, new_name=None):
    """Déplace un fichier en gérant les conflits de noms"""
    try:
        os.makedirs(target_dir, exist_ok=True)
        
        # Déterminer le nom de destination
        filename = new_name if new_name else os.path.basename(source)
        target_path = os.path.join(target_dir, filename)
        
        # Gérer les doublons
        if os.path.exists(target_path):
            base, ext = os.path.splitext(filename)
            counter = 1
            while True:
                new_filename = f"{base}_{counter}{ext}"
                new_target = os.path.join(target_dir, new_filename)
                if not os.path.exists(new_target):
                    target_path = new_target
                    break
                counter += 1
        
        shutil.move(source, target_path)
        logger.info(f"Déplacé: {source} -> {target_path}")
        return target_path
    except Exception as e:
        logger.error(f"Erreur déplacement fichier: {source} -> {target_dir}: {str(e)}")
        return None

def find_videos(directory, patterns=("*.mp4", "*.mov", "*.avi")):
    """Trouve tous les fichiers vidéo dans un répertoire"""
    videos = []
    try:
        for pattern in patterns:
            videos.extend(glob.glob(os.path.join(directory, pattern), recursive=False))
        return sorted(videos)
    except Exception as e:
        logger.error(f"Erreur recherche vidéos dans {directory}: {str(e)}")
        return []

def cleanup_directory(directory, max_age_days=30):
    """Nettoie les fichiers anciens dans un répertoire"""
    try:
        now = time.time()
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            file_age = now - os.path.getmtime(file_path)
            
            if file_age > max_age_days * 86400:  # jours en secondes
                os.remove(file_path)
                logger.info(f"Fichier supprimé: {file_path} (âge: {file_age/86400:.1f} jours)")
    except Exception as e:
        logger.error(f"Erreur nettoyage {directory}: {str(e)}")
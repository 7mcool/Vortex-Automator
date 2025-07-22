import logging
import os
from datetime import datetime

def setup_logging(log_dir="logs", log_level=logging.INFO):
    """Configure le système de journalisation global"""
    # Créer le dossier de logs
    os.makedirs(log_dir, exist_ok=True)
    
    # Formateur personnalisé
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler fichier
    log_file = os.path.join(log_dir, f"vortex_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    
    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Configurer le logger racine
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return log_file

def log_system_info():
    """Journalise les informations système importantes"""
    import platform, torch, psutil
    
    logger = logging.getLogger("System")
    logger.info("=" * 60)
    logger.info(f"Système: {platform.system()} {platform.release()}")
    logger.info(f"Processeur: {platform.processor()}")
    logger.info(f"Mémoire RAM: {psutil.virtual_memory().total / (1024**3):.1f} GB")
    
    if torch.cuda.is_available():
        device = torch.cuda.get_device_properties(0)
        logger.info(f"GPU: {device.name}")
        logger.info(f"VRAM: {device.total_memory / (1024**3):.1f} GB")
    else:
        logger.warning("Aucun GPU compatible CUDA détecté")
    
    logger.info("=" * 60)
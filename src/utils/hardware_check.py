import torch
import psutil
import logging

logger = logging.getLogger("Hardware")

def check_system_resources():
    """Vérifie les ressources système disponibles"""
    results = {
        "cuda_available": torch.cuda.is_available(),
        "ram_available": psutil.virtual_memory().available / (1024 ** 3),  # GB
        "cpu_usage": psutil.cpu_percent(),
        "issues": []
    }
    
    # Vérifier la disponibilité CUDA
    if not results["cuda_available"]:
        results["issues"].append("CUDA non disponible - Les transcriptions seront lentes")
    
    # Vérifier la mémoire RAM
    if results["ram_available"] < 4:
        results["issues"].append(f"Mémoire RAM faible: {results['ram_available']:.1f} GB disponible")
    
    # Vérifier l'utilisation CPU
    if results["cpu_usage"] > 90:
        results["issues"].append(f"CPU surchargé: {results['cpu_usage']}% d'utilisation")
    
    return results

def log_resource_report(resources):
    """Journalise un rapport sur les ressources système"""
    logger.info("=" * 40)
    logger.info("📊 RAPPORT RESSOURCES SYSTÈME")
    logger.info("=" * 40)
    logger.info(f"CUDA disponible: {'✅' if resources['cuda_available'] else '❌'}")
    logger.info(f"Mémoire RAM disponible: {resources['ram_available']:.1f} GB")
    logger.info(f"Utilisation CPU: {resources['cpu_usage']:.1f}%")
    
    if resources["issues"]:
        logger.warning("⚠️ Problèmes détectés:")
        for issue in resources["issues"]:
            logger.warning(f"  - {issue}")
    else:
        logger.info("✅ Toutes les ressources sont suffisantes")
    
    logger.info("=" * 40)
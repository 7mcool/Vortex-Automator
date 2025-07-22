import json
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

def load_publishing_state(state_file):
    """Charge l'état des publications avec support multi-chaînes"""
    default_state = {
        "last_processed_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "channel_dates": defaultdict(dict)
    }
    
    if not os.path.exists(state_file):
        return default_state
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            # Convertir en defaultdict
            state["channel_dates"] = defaultdict(dict, state.get("channel_dates", {}))
            return state
    except Exception as e:
        logger.error(f"Erreur chargement état: {str(e)}")
        return default_state

def save_publishing_state(state, state_file):
    """Sauvegarde l'état des publications"""
    try:
        # Convertir defaultdict en dict pour sérialisation
        state_to_save = {
            "last_processed_date": state["last_processed_date"],
            "channel_dates": dict(state["channel_dates"])
        }
        
        with open(state_file, 'w') as f:
            json.dump(state_to_save, f, indent=2)
    except Exception as e:
        logger.error(f"Erreur sauvegarde état: {str(e)}")

def get_next_publishing_slot(state, channel_id, daily_limit, publish_hours):
    """Trouve le prochain créneau de publication disponible"""
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    
    # Réinitialiser si nouveau jour
    if state["last_processed_date"] != today_str:
        state["last_processed_date"] = today_str
        state["channel_dates"] = defaultdict(dict)
    
    # Obtenir les publications déjà planifiées pour cette chaîne
    channel_data = state["channel_dates"][channel_id]
    today_count = channel_data.get(today_str, 0)
    
    # Vérifier la limite quotidienne
    if today_count >= daily_limit:
        # Trouver le prochain jour disponible
        next_date = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
        next_time = datetime.strptime(next_date, "%Y-%m-%d").replace(
            hour=(publish_hours[0] - 1) % 24,  # Conversion UTC+1 -> UTC
            minute=0,
            second=0,
            tzinfo=timezone.utc
        )
        logger.info(f"Limite atteinte aujourd'hui, programmation pour {next_date}")
        return next_time.isoformat()
    
    # Trouver le prochain créneau horaire disponible aujourd'hui
    current_hour = now_utc.hour
    for hour in publish_hours:
        utc_hour = (hour - 1) % 24  # Conversion UTC+1 -> UTC
        
        # Vérifier si le créneau est dans le futur
        if utc_hour > current_hour or (utc_hour == current_hour and now_utc.minute < 30):
            publish_time = now_utc.replace(
                hour=utc_hour,
                minute=0,
                second=0,
                microsecond=0
            )
            logger.info(f"Créneau trouvé: {publish_time.isoformat()}")
            return publish_time.isoformat()
    
    # Si aucun créneau aujourd'hui, passer à demain
    next_date = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    next_time = datetime.strptime(next_date, "%Y-%m-%d").replace(
        hour=(publish_hours[0] - 1) % 24,
        minute=0,
        second=0,
        tzinfo=timezone.utc
    )
    logger.info(f"Aucun créneau disponible aujourd'hui, programmation pour {next_date}")
    return next_time.isoformat()

def record_publication(state, channel_id, publish_time, state_file):
    """Enregistre une publication dans l'état"""
    try:
        date_str = publish_time[:10]  # Extraire YYYY-MM-DD
        state["channel_dates"][channel_id][date_str] = state["channel_dates"][channel_id].get(date_str, 0) + 1
        save_publishing_state(state, state_file)
    except Exception as e:
        logger.error(f"Erreur enregistrement publication: {str(e)}")
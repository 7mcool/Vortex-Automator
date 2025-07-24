import os
import json
from datetime import datetime, timedelta, timezone

def load_publishing_state():
    """Charge l'état des publications depuis le fichier"""
    state_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "publishing_state.json")
    
    default_state = {
        "last_processed_date": None,
        "scheduled_dates": {}
    }
    
    if not os.path.exists(state_file):
        return default_state
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            # Validation de la structure
            if "last_processed_date" in state and "scheduled_dates" in state:
                return state
            return default_state
    except Exception as e:
        print(f"⚠️ Erreur chargement état: {str(e)}")
        return default_state

def save_publishing_state(state):
    """Sauvegarde l'état des publications dans le fichier"""
    try:
        state_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "publishing_state.json")
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as e:
        print(f"❌ Erreur sauvegarde état: {str(e)}")
        return False

def get_next_publishing_date(state):
    """Détermine la prochaine date de publication disponible"""
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    
    # Réinitialisation quotidienne
    if state["last_processed_date"] != today_str:
        state["last_processed_date"] = today_str
        state["scheduled_dates"] = {}
        save_publishing_state(state)
    
    # Vérification des limites
    scheduled_today = state["scheduled_dates"].get(today_str, 0)
    total_daily_limit = CONFIG['DAILY_LIMIT'] * len(CONFIG['CHANNELS'])
    
    if scheduled_today >= total_daily_limit:
        # Passage au jour suivant
        next_date = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"↪️ Toutes les publications d'aujourd'hui sont programmées")
        print(f"↪️ Passage à la date du lendemain: {next_date}")
        return next_date
    
    return today_str
import json
import os
from datetime import datetime, timedelta, timezone

def load_publishing_state(state_file):
    """Charge l'état des publications"""
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except:
            return {"last_processed_date": None, "scheduled_dates": {}}
    return {"last_processed_date": None, "scheduled_dates": {}}

def save_publishing_state(state, state_file):
    """Sauvegarde l'état des publications"""
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)

def get_next_publishing_date(state, daily_limit, channel_count):
    """Détermine la prochaine date de publication"""
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    
    if state["last_processed_date"] != today_str:
        state["last_processed_date"] = today_str
        state["scheduled_dates"] = {}
    
    today_videos = state["scheduled_dates"].get(today_str, 0)
    total_daily_limit = daily_limit * channel_count
    
    if today_videos >= total_daily_limit:
        return (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    
    return today_str

def get_publish_time(target_date, slot, publish_hours):
    """Calcule l'heure de publication UTC"""
    slot_index = slot % len(publish_hours)
    hour_utc = (publish_hours[slot_index] - 1) % 24  # Conversion UTC+1 -> UTC
    
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(
        hour=hour_utc, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )
    return target_dt.isoformat()
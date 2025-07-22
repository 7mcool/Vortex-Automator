from src.core import youtube_uploader, transcriber, metadata_generator, scheduler
from src.utils import logger
import os
import glob
import shutil
import time
import json
import torch
from datetime import datetime

# Configuration
CONFIG = {
    "script_dir": "D:/Youtube/mini-programme",
    "source_dir": "D:/4K Tokkit/hedjav",
    "log_dir": "logs",
    "state_file": "publishing_state.json",
    "publish_hours": [9, 12, 15, 18, 21],
    "daily_limit": 5,
    "whisper_model": "medium",
    "channels": [
        {
            "name": "Chaîne 1",
            "token_file": "auth/token_channel1.json",
            "done_dir": "done_channel1"
        }
    ]
}

def main():
    # Initialisation
    log_file = logger.create_log_file(CONFIG["log_dir"])
    
    # Chargement état
    state = scheduler.load_publishing_state(CONFIG["state_file"])
    target_date = scheduler.get_next_publishing_date(
        state, 
        CONFIG["daily_limit"], 
        len(CONFIG["channels"])
    )
    
    # Traitement des vidéos
    videos = sorted(glob.glob(os.path.join(CONFIG["source_dir"], "*.mp4")))
    
    # ... (logique de traitement similaire à l'original mais utilisant les modules)
    
if __name__ == "__main__":
    main()
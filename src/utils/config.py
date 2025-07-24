import os
import torch

# Chemins importants
PROJECT_ROOT = os.path.dirnameos.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
STATE_FILE = os.path.join(PROJECT_ROOT, "publishing_state.json")
CLIENT_SECRET_PATH = os.path.join(PROJECT_ROOT, "client_secret.json")

# Créer les dossiers si nécessaire
os.makedirs(LOG_DIR, exist_ok=True)

# Configuration globale
CONFIG = {
    "SRC_DIR": SRC_DIR,
    "LOG_DIR": LOG_DIR,
    "STATE_FILE": STATE_FILE,
    "CLIENT_SECRET_PATH": CLIENT_SECRET_PATH,
    "PUBLISH_HOURS": [9, 12, 15, 18, 21],
    "DAILY_LIMIT": 5,
    "YT_CATEGORY_ID": "27",
    "WHISPER_MODEL": "medium",
    "WHISPER_DEVICE": "cuda" if torch.cuda.is_available() else "cpu",
    "DEEPSEEK_API_KEY": "sk-0a1c07035e5b4481b1ada0f91c6dd1b4",
    "SCOPES": [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtubepartner"
    ],
    "CHANNELS": [
        {
            "name": "Chaîne 1",
            "token_file": "token_channel1.json",
            "done_dir": os.path.join(PROJECT_ROOT, "done_channel1")
        },
        {
            "name": "Chaîne 2",
            "token_file": "token_channel2.json",
            "done_dir": os.path.join(PROJECT_ROOT, "done_channel2")
        }
    ]
}
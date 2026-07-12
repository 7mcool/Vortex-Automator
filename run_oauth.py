"""Authentification OAuth YouTube sans ouverture automatique du navigateur.
Usage ponctuel pour la première autorisation ; supprimable ensuite."""
import sys

from vortex.config import load_config
from vortex.youtube_client import SCOPES

from google_auth_oauthlib.flow import InstalledAppFlow

cfg = load_config()
flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secret_file), SCOPES)
creds = flow.run_local_server(port=8765, prompt="consent", open_browser=False)
cfg.token_file.parent.mkdir(parents=True, exist_ok=True)
cfg.token_file.write_text(creds.to_json(), encoding="utf-8")
print("TOKEN_ENREGISTRE:", cfg.token_file)

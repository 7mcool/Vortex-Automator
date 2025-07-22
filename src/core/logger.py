import os
from datetime import datetime

def create_log_file(log_dir):
    log_filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    log_path = os.path.join(log_dir, log_filename)
    
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Vortex Automator - Execution {datetime.now()}\n")
    
    return log_path

def log_message(log_file, message, is_error=False):
    prefix = "❌ " if is_error else "✅ "
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{prefix}{message}\n")
"""
config.py - Configuration loader
Loads API key, SMTP credentials, and monitor settings
"""

import os
import sys
import json

# =============================================================================
# MONITOR SETTINGS - EDIT THESE
# =============================================================================
CHECK_INTERVAL = 600        # seconds between checks (600 = 10 minutes)
STATUS_FILE = "device_status_cache.json"
BASE_URL = "https://falcon.production.engenius.ai/v2"
MAX_RETRIES = 3
RETRY_DELAY = 2

# =============================================================================
# FILE PATHS
# =============================================================================
API_KEY_FILE = "api_key.txt"
SMTP_CREDS_FILE = "smtp_creds.json"


def load_api_key():
    """Load API key from file"""
    key_files = [API_KEY_FILE, "apikey.txt", "API_KEY.txt"]
    for f in key_files:
        if os.path.exists(f):
            with open(f, 'r') as file:
                key = file.read().strip()
                print(f"[INFO] Loaded API key from {f} ({len(key)} characters)")
                return key
    print("[ERROR] No api_key.txt found in current directory")
    print("[ERROR] Create api_key.txt with your EnGenius Cloud API key")
    sys.exit(1)


def load_smtp_config():
    """Load SMTP configuration from external json file"""
    if not os.path.exists(SMTP_CREDS_FILE):
        print(f"[INFO] SMTP config not found: {SMTP_CREDS_FILE} (alerts disabled)")
        return {"enabled": False}
    
    try:
        with open(SMTP_CREDS_FILE, 'r') as f:
            config = json.load(f)
        
        if config.get("enabled"):
            print(f"[INFO] SMTP config loaded from {SMTP_CREDS_FILE}")
            print(f"[INFO] SMTP server: {config.get('server')}:{config.get('port')}")
            print(f"[INFO] SMTP from: {config.get('from_addr')}")
            print(f"[INFO] SMTP to: {config.get('to_addr')}")
        else:
            print(f"[INFO] SMTP config loaded but disabled (set enabled: true to activate)")
        
        return config
    except Exception as e:
        print(f"[WARN] Failed to load SMTP config: {e}")
        return {"enabled": False}

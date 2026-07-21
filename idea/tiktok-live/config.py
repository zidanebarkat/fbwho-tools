"""Application configuration loaded from environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'


class Config:
    BASE_DIR = BASE_DIR
    DATA_DIR = DATA_DIR
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', '')
    PANEL_PASSWORD = os.environ.get('PANEL_PASSWORD', 'admin')

    # TikTok
    PASSPORT_APP_KEY = '884c28a44b61b78f9d837fc8b0967178'
    PASSPORT_WEB_SDK_VERSION = '2.1.9'
    LIVE_STUDIO_AID = 8311

    # GitHub
    GITHUB_API = 'https://api.github.com'
    GITHUB_OWNER = os.environ.get('GITHUB_OWNER', 'zidanebarkat')
    GITHUB_REPO = os.environ.get('GITHUB_REPO', '8dca7ff25e47b8cc0e104b9f-tt')

    # File paths
    CHANNEL_CONFIG_FILE = DATA_DIR / 'channel_config.json'
    SESSION_FILE = DATA_DIR / 'session.json'
    SECURE_STORE_FILE = DATA_DIR / 'secrets.enc'
    HISTORY_FILE = DATA_DIR / 'history.json'
    QR_STATE_FILE = DATA_DIR / 'qr_state.json'

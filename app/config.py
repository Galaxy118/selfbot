import os
import secrets
from cryptography.fernet import Fernet
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENV_PATH = os.environ.get("ENV_PATH", ".env")
load_dotenv(ENV_PATH)

DB_PATH = os.environ.get("DB_PATH", "data.db")
CLIENT_ID = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8001/auth/callback")
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
OWNER_IDS = [uid.strip() for uid in os.environ.get("OWNER_IDS", "").split(",") if uid.strip()]

DISCORD_API_URL = "https://discord.com/api/v10"

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    logger.warning("ENCRYPTION_KEY not found in .env. A temporary one was generated. Tokens will be lost on restart if not saved.")

fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt_token(token: str) -> str:
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    return fernet.decrypt(encrypted_token.encode()).decode()

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# Google Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

# Primary and Fallback Gemini Models
GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-pro-latest"
]

# Max history messages per user session
MAX_HISTORY_LEN = 20

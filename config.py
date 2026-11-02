import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Only secrets and hosting values live here. Everything else is changed live from /settings."""

    API_ID = int(os.environ["API_ID"])
    API_HASH = os.environ["API_HASH"]
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    MONGO_URI = os.environ["MONGO_URI"]
    DB_NAME = os.getenv("DB_NAME", "AutoFilterBot")
    PORT = int(os.getenv("PORT", 10000))  # Render sets PORT automatically (default 10000)
    ADMINS = [int(x) for x in os.getenv("ADMINS", "").replace(",", " ").split()]
    # public https URL of this server (Render sets RENDER_EXTERNAL_URL automatically)
    BASE_URL = (os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    RICH_BUTTONS = os.getenv("RICH_BUTTONS", "1") != "0"  # 0 = normal inline buttons everywhere
    BOT_USERNAME = ""  # filled at startup

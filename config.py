import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8554402317"))
REST_LAT = float(os.getenv("REST_LAT", "41.359813"))
REST_LON = float(os.getenv("REST_LON", "69.172063"))
DB_PATH = os.getenv("DB_PATH", "restoran.db")

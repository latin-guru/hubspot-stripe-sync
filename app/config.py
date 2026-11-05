"""Settings loaded from .env (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
HUBSPOT_SERVICE_KEY = os.getenv("HUBSPOT_SERVICE_KEY", "")
DB_PATH = os.getenv("SYNC_DB_PATH", "sync_state.db")

# Every write the integration makes is stamped with this, so Phase 3 can ignore
# changes that the integration itself caused (loop guard).
SYNC_SOURCE_STRIPE = "stripe"
SYNC_SOURCE_HUBSPOT = "hubspot"

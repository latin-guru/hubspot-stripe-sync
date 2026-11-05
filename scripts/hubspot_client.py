"""Shim so the scripts in this folder share the app's HubSpot client."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.hubspot_client import BASE_URL, HubSpotClient, HubSpotError  # noqa: E402,F401

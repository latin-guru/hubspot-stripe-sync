"""Minimal HubSpot REST client: Service Key auth, retries on 429/5xx with backoff."""
import os
import time
import warnings

# macOS system Python 3.9 is built on LibreSSL; urllib3 warns about it on every run. Harmless here.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import requests  # noqa: E402
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.hubapi.com"


class HubSpotError(Exception):
    pass


class HubSpotClient:
    def __init__(self, token=None, max_retries: int = 5):
        self.token = token or os.getenv("HUBSPOT_SERVICE_KEY")
        if not self.token:
            raise HubSpotError("HUBSPOT_SERVICE_KEY is not set. Copy .env.example to .env and fill it in.")
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            resp = self.session.request(method, BASE_URL + path, timeout=30, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    break
                # Honor Retry-After when HubSpot sends it; otherwise exponential backoff.
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"  {resp.status_code} from HubSpot, retrying in {wait:.0f}s...")
                time.sleep(wait)
                continue
            return resp
        raise HubSpotError(f"{method} {path} failed after retries: {resp.status_code} {resp.text}")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

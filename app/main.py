"""Northwind Loop billing sync: receives Stripe webhooks and updates HubSpot.

Run:  uvicorn app.main:app --port 8000
"""
import json
import logging

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from . import config
from .handlers import StripeToHubSpot, ordering_key
from .hubspot_api import HubSpotAPI
from .hubspot_client import HubSpotClient
from .store import EventStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("sync")
logging.getLogger("stripe").setLevel(logging.WARNING)

app = FastAPI(title="Northwind Loop billing sync")
state = {}


def get_state():
    """Build clients on first use so the app can start (and /health works) before keys are set."""
    if not state:
        stripe.api_key = config.STRIPE_SECRET_KEY
        state["store"] = EventStore(config.DB_PATH)
        state["sync"] = StripeToHubSpot(HubSpotAPI(HubSpotClient(config.HUBSPOT_SERVICE_KEY)), state["store"])
    return state


@app.get("/health")
def health():
    return {"ok": True}


def process_event(event: dict) -> dict:
    s = get_state()
    store, sync = s["store"], s["sync"]
    event_id, event_type = event["id"], event["type"]
    obj = event["data"]["object"]

    handler = sync.routes().get(event_type)
    if handler is None:
        return {"status": "ignored", "type": event_type}

    key = ordering_key(event_type, obj)
    with store.lock_for(key):
        if store.seen(event_id):
            log.info("DUPLICATE  %s %s (already applied, skipped)", event_type, event_id)
            return {"status": "duplicate"}

        if store.is_stale(key, event["created"]):
            log.info("STALE      %s %s (newer data already applied, skipped)", event_type, event_id)
            store.mark(event_id, event_type, "stale")
            return {"status": "stale"}

        result = handler(obj)  # any exception -> 500 -> Stripe retries the event later
        store.touch(key, event["created"])
        store.mark(event_id, event_type, result)
    log.info("APPLIED    %-30s %s", event_type, result)
    return {"status": "applied", "result": result}


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        # Reject anything not signed with our webhook secret.
        stripe.WebhookSignature.verify_header(payload.decode("utf-8"), signature,
                                              config.STRIPE_WEBHOOK_SECRET, tolerance=300)
    except Exception:
        log.warning("REJECTED   bad or missing Stripe signature")
        raise HTTPException(status_code=400, detail="invalid signature")

    event = json.loads(payload)
    try:
        return await run_in_threadpool(process_event, event)
    except Exception as exc:
        log.exception("FAILED     %s %s: %s", event.get("type"), event.get("id"), exc)
        raise HTTPException(status_code=500, detail="processing failed; Stripe will retry")

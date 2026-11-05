"""Northwind Loop billing sync.

- POST /webhooks/stripe   Stripe -> HubSpot (Phase 2): billing fields, deals, at-risk flag
- POST /webhooks/hubspot  HubSpot -> Stripe (Phase 3): rep changes plan tier, Stripe follows

Run:  uvicorn app.main:app --port 8000
"""
import hmac
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
from .stripe_push import HubSpotToStripe, extract_contact_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("stripe").setLevel(logging.WARNING)
log = logging.getLogger("sync")

app = FastAPI(title="Northwind Loop billing sync")
state = {}


def get_state():
    """Build clients on first use so the app can start (and /health works) before keys are set."""
    if not state:
        stripe.api_key = config.STRIPE_SECRET_KEY
        hubspot = HubSpotAPI(HubSpotClient(config.HUBSPOT_SERVICE_KEY))
        state["store"] = EventStore(config.DB_PATH)
        state["sync"] = StripeToHubSpot(hubspot, state["store"])
        state["push"] = HubSpotToStripe(hubspot)
    return state


@app.get("/health")
def health():
    return {"ok": True}


# ---------------- Stripe -> HubSpot ----------------

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


# ---------------- HubSpot -> Stripe ----------------

def secret_ok(request: Request) -> bool:
    expected = config.HUBSPOT_WEBHOOK_SECRET
    if not expected:
        return False
    given = (request.headers.get("x-sync-secret") or request.headers.get("x-api-key")
             or request.query_params.get("secret") or "")
    return hmac.compare_digest(given, expected)


def process_plan_change(contact_id: str) -> dict:
    s = get_state()
    with s["store"].lock_for(f"contact:{contact_id}"):
        result = s["push"].plan_changed(contact_id)
    label = "SKIPPED   " if result.startswith("skipped") or "nothing to do" in result else "PUSHED    "
    log.info("%s hubspot.plan_tier_changed      %s", label, result)
    return {"status": "ok", "result": result}


@app.post("/webhooks/hubspot")
async def hubspot_webhook(request: Request):
    if not secret_ok(request):
        log.warning("REJECTED   HubSpot call with missing or wrong secret")
        raise HTTPException(status_code=401, detail="invalid secret")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")

    contact_id = extract_contact_id(body)
    if not contact_id:
        keys = list(body.keys()) if isinstance(body, dict) else type(body).__name__
        log.warning("REJECTED   HubSpot payload has no contact ID (keys: %s)", keys)
        raise HTTPException(status_code=400, detail="no contact id in payload")
    try:
        return await run_in_threadpool(process_plan_change, contact_id)
    except Exception as exc:
        log.exception("FAILED     hubspot plan change for contact %s: %s", contact_id, exc)
        raise HTTPException(status_code=500, detail="processing failed; HubSpot will retry")

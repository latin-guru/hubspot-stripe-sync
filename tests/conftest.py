"""Shared fakes. No test touches the network: HubSpot and Stripe are replaced with
small in-memory stand-ins that record what the sync tried to do."""
import copy
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.handlers import StripeToHubSpot
from app.store import EventStore
from app.stripe_push import HubSpotToStripe

WEBHOOK_SECRET = "whsec_test_secret"
HUBSPOT_SECRET = "hs_test_secret"
EMAIL = "pat.lee@acme.example.com"


def price(tier, cents):
    return {"id": f"price_{tier}", "unit_amount": cents, "lookup_key": f"nwl_{tier}_monthly",
            "recurring": {"interval": "month", "interval_count": 1}, "metadata": {"plan_tier": tier}}


PRICES = {"starter": price("starter", 9900), "growth": price("growth", 29900), "scale": price("scale", 79900)}


def subscription(tier="growth", status="active", sub_id="sub_1", customer="cus_1"):
    return {"id": sub_id, "object": "subscription", "customer": customer, "status": status, "metadata": {},
            "items": {"data": [{"id": "si_1", "quantity": 1, "price": copy.deepcopy(PRICES[tier])}]}}


class FakeHubSpot:
    """Records every write; companies exist for *.example.com domains."""

    def __init__(self):
        self.calls = []
        self.contacts = {"101": {"email": EMAIL, "plan_tier": "growth", "stripe_customer_id": "cus_1"}}
        self.deals_by_sub = {}
        self.search_lag = False
        self._n = 0

    def upsert_contact(self, email, props):
        self.calls.append(("upsert_contact", email, dict(props)))
        return "101"

    def find_company_by_domain(self, domain):
        return "201" if domain.endswith(".example.com") else None

    def find_deal_by_subscription(self, sub_id):
        return None if self.search_lag else self.deals_by_sub.get(sub_id)

    def update(self, obj, record_id, props):
        self.calls.append(("update", obj, record_id, dict(props)))

    def create_deal(self, props):
        self._n += 1
        deal_id = f"d{self._n}"
        self.deals_by_sub[props["stripe_subscription_id"]] = deal_id
        self.calls.append(("create_deal", dict(props)))
        return deal_id

    def associate(self, *args):
        self.calls.append(("associate",) + args)

    def get_contact(self, contact_id, props):
        c = self.contacts.get(str(contact_id))
        return {"id": str(contact_id), "properties": dict(c)} if c else None

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]


class FakeStripe:
    """Just enough of the stripe library: Customer, Price, Subscription."""

    def __init__(self):
        self.customers = {"cus_1": {"id": "cus_1", "email": EMAIL, "name": "Acme"}}
        self.subs = {"cus_1": [subscription()]}
        self.modified = []
        outer = self

        class Customer:
            @staticmethod
            def retrieve(cid):
                return copy.deepcopy(outer.customers.get(cid, {"id": cid, "deleted": True}))

        class Price:
            @staticmethod
            def list(lookup_keys, limit):
                tier = lookup_keys[0].split("_")[1]
                return {"data": [PRICES[tier]] if tier in PRICES else []}

        class Subscription:
            @staticmethod
            def list(customer, status, limit):
                return {"data": copy.deepcopy(outer.subs.get(customer, []))}

            @staticmethod
            def modify(sub_id, **kwargs):
                outer.modified.append((sub_id, kwargs))
                tier = kwargs["items"][0]["price"].split("_")[1]
                for subs in outer.subs.values():
                    for s in subs:
                        if s["id"] == sub_id:
                            s["items"]["data"][0]["price"] = copy.deepcopy(PRICES[tier])
                return {"id": sub_id}

        self.Customer, self.Price, self.Subscription = Customer, Price, Subscription


@pytest.fixture
def hubspot():
    return FakeHubSpot()


@pytest.fixture
def stripe_fake():
    return FakeStripe()


@pytest.fixture
def store(tmp_path):
    return EventStore(str(tmp_path / "state.db"))


@pytest.fixture
def client(monkeypatch, hubspot, stripe_fake, store):
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr(config, "HUBSPOT_WEBHOOK_SECRET", HUBSPOT_SECRET)
    main.state.clear()
    main.state.update(store=store, sync=StripeToHubSpot(hubspot, store, stripe_fake),
                      push=HubSpotToStripe(hubspot, stripe_fake))
    yield TestClient(main.app)
    main.state.clear()


def signed(payload: dict, secret=WEBHOOK_SECRET):
    body = json.dumps(payload)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={ts},v1={sig}", "content-type": "application/json"}


def event(event_id, event_type, obj, created=1000):
    return {"id": event_id, "type": event_type, "created": created, "data": {"object": obj}}


@pytest.fixture
def send_stripe(client):
    def _send(evt, secret=WEBHOOK_SECRET):
        body, headers = signed(evt, secret)
        return client.post("/webhooks/stripe", content=body, headers=headers)
    return _send


@pytest.fixture
def send_hubspot(client):
    def _send(body, secret=HUBSPOT_SECRET):
        headers = {"X-Sync-Secret": secret} if secret is not None else {}
        return client.post("/webhooks/hubspot", json=body, headers=headers)
    return _send

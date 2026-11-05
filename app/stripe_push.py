"""HubSpot -> Stripe: when a rep changes Plan tier on a contact, switch the Stripe subscription.

Loop guard: before changing anything, compare HubSpot's plan with what Stripe already has.
If they match, do nothing. That is what stops the two systems from ping-ponging:

  rep sets Scale in HubSpot -> we switch Stripe to Scale
  -> Stripe sends subscription.updated -> Phase 2 writes Scale back to HubSpot
  -> the plan didn't actually change, so nothing re-fires; and if it did,
     Stripe already says Scale, so this handler is a no-op.
"""
import logging
from typing import Optional

import stripe

from .mapping import VALID_PLANS, as_dict, plan_and_mrr

log = logging.getLogger("sync")

LIVE_STATUSES = {"active", "trialing", "past_due"}


class HubSpotToStripe:
    def __init__(self, hubspot, stripe_client=stripe):
        self.hubspot = hubspot
        self.stripe = stripe_client
        self._prices = {}

    def price_for(self, tier: str) -> str:
        if tier not in self._prices:
            found = as_dict(self.stripe.Price.list(lookup_keys=[f"nwl_{tier}_monthly"], limit=1))["data"]
            if not found:
                raise RuntimeError(f"No Stripe price for plan '{tier}'. Run scripts/seed_stripe.py first.")
            self._prices[tier] = found[0]["id"]
        return self._prices[tier]

    def _live_subscription(self, customer_id: str) -> Optional[dict]:
        subs = as_dict(self.stripe.Subscription.list(customer=customer_id, status="all", limit=10))["data"]
        return next((s for s in subs if s.get("status") in LIVE_STATUSES), None)

    def plan_changed(self, contact_id: str) -> str:
        contact = self.hubspot.get_contact(contact_id, ["email", "plan_tier", "stripe_customer_id"])
        if not contact:
            return f"skipped: contact {contact_id} not found"
        props = contact.get("properties") or {}
        email, tier = props.get("email"), (props.get("plan_tier") or "").strip()

        if tier not in VALID_PLANS:
            return f"skipped: {email} has no valid plan tier ({tier or 'blank'})"
        customer_id = props.get("stripe_customer_id")
        if not customer_id:
            return f"skipped: {email} is not linked to a Stripe customer yet"

        sub = self._live_subscription(customer_id)
        if not sub:
            return f"skipped: {email} has no active subscription in Stripe"

        current, _ = plan_and_mrr(sub)
        if current == tier:
            return f"{email}: Stripe already on {tier}, nothing to do (loop guard)"

        item = sub["items"]["data"][0]
        self.stripe.Subscription.modify(
            sub["id"],
            items=[{"id": item["id"], "price": self.price_for(tier)}],
            proration_behavior="create_prorations",
            metadata={"last_plan_change_source": "hubspot", "hubspot_contact_id": str(contact_id)},
        )
        return f"{email}: {current} -> {tier} pushed to Stripe ({sub['id']})"


def extract_contact_id(body) -> Optional[str]:
    """HubSpot workflow webhooks can send a few shapes; accept the common ones."""
    if isinstance(body, list) and body:
        body = body[0]
    if not isinstance(body, dict):
        return None
    for key in ("objectId", "contactId", "hs_object_id", "vid", "id"):
        val = body.get(key)
        if isinstance(val, dict):
            val = val.get("value")
        if val:
            return str(val)
    props = body.get("properties")
    if isinstance(props, dict):
        val = props.get("hs_object_id")
        if isinstance(val, dict):
            val = val.get("value")
        if val:
            return str(val)
    return None

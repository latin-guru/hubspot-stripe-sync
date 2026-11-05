"""Stripe -> HubSpot event handlers.

Source-of-truth rules (docs/source-of-truth.md): these handlers only ever write
billing fields. Lifecycle stage and owner belong to HubSpot and are never touched here.
Every write stamps sync_source=stripe so Phase 3 can ignore our own changes.
"""
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

import stripe

from .config import SYNC_SOURCE_STRIPE
from .hubspot_api import HubSpotAPI
from .mapping import as_dict, billing_status, email_domain, plan_and_mrr, to_hs_date

log = logging.getLogger("sync")


class StripeToHubSpot:
    def __init__(self, hubspot: HubSpotAPI, store, stripe_client=stripe):
        self.hubspot = hubspot
        self.store = store
        self.stripe = stripe_client

    # ---------- helpers ----------
    def _customer(self, customer_id: str) -> Optional[dict]:
        cust = as_dict(self.stripe.Customer.retrieve(customer_id))
        return None if cust.get("deleted") else cust

    def _write_billing(self, email: str, props: dict) -> Dict[str, Optional[str]]:
        """Write billing props to the contact (by email) and its company (by domain)."""
        props = {k: v for k, v in props.items() if v is not None}
        props["sync_source"] = SYNC_SOURCE_STRIPE
        contact_id = self.hubspot.upsert_contact(email, props)
        company_id = self.hubspot.find_company_by_domain(email_domain(email))
        if company_id:
            self.hubspot.update("companies", company_id, props)
            self.hubspot.associate("contacts", contact_id, "companies", company_id)
        return {"contact_id": contact_id, "company_id": company_id}

    # ---------- handlers ----------
    def customer_created(self, customer: dict) -> str:
        email = customer.get("email")
        if not email:
            return "skipped: customer has no email"
        ids = self._write_billing(email, {"stripe_customer_id": customer["id"]})
        return f"linked {email} (contact {ids['contact_id']}, company {ids['company_id'] or 'none'})"

    def subscription_changed(self, sub: dict) -> str:
        cust = self._customer(sub["customer"])
        if not cust or not cust.get("email"):
            return "skipped: customer missing or has no email"
        email = cust["email"]
        plan, mrr = plan_and_mrr(sub)
        status = billing_status(sub.get("status", ""))
        if status == "canceled":
            mrr = 0.0
        ids = self._write_billing(email, {
            "stripe_customer_id": cust["id"], "plan_tier": plan,
            "mrr": mrr, "billing_status": status,
        })

        deal_id = self.store.get_link(sub["id"]) or self.hubspot.find_deal_by_subscription(sub["id"])
        deal_props = {"amount": round(mrr * 12, 2)}  # deal amount = annual run rate
        if deal_id:
            self.hubspot.update("deals", deal_id, deal_props)
            action = f"updated deal {deal_id}"
        elif status != "canceled":
            deal_id = self.hubspot.create_deal({
                **deal_props,
                "dealname": f"{cust.get('name') or email} - {(plan or 'subscription').title()} plan",
                "pipeline": "default",
                "dealstage": "closedwon",
                "closedate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "stripe_subscription_id": sub["id"],
            })
            self.store.set_link(sub["id"], deal_id)
            self.hubspot.associate("deals", deal_id, "contacts", ids["contact_id"])
            if ids["company_id"]:
                self.hubspot.associate("deals", deal_id, "companies", ids["company_id"])
            action = f"created deal {deal_id}"
        else:
            action = "no deal (canceled)"
        return f"{email}: {plan or '?'} ${mrr}/mo, {status}, {action}"

    def invoice_paid(self, invoice: dict) -> str:
        cust = self._customer(invoice["customer"])
        if not cust or not cust.get("email"):
            return "skipped: customer missing or has no email"
        paid_at = (invoice.get("status_transitions") or {}).get("paid_at") or invoice.get("created")
        self._write_billing(cust["email"], {
            "stripe_customer_id": cust["id"], "billing_status": "active",
            "last_payment_date": to_hs_date(paid_at),
        })
        return f"{cust['email']}: paid {to_hs_date(paid_at)}, active"

    def invoice_payment_failed(self, invoice: dict) -> str:
        cust = self._customer(invoice["customer"])
        if not cust or not cust.get("email"):
            return "skipped: customer missing or has no email"
        self._write_billing(cust["email"], {"stripe_customer_id": cust["id"], "billing_status": "at_risk"})
        return f"{cust['email']}: payment FAILED, at_risk"

    def routes(self) -> Dict[str, Callable[[dict], str]]:
        return {
            "customer.created": self.customer_created,
            "customer.subscription.created": self.subscription_changed,
            "customer.subscription.updated": self.subscription_changed,
            "customer.subscription.deleted": self.subscription_changed,
            "invoice.paid": self.invoice_paid,
            "invoice.payment_failed": self.invoice_payment_failed,
        }


def ordering_key(event_type: str, obj: dict) -> str:
    """Which object an event's freshness is tracked against.

    Subscription events track the subscription; invoice events track the customer's
    payment state, so a late invoice.paid can't undo a newer payment failure.
    """
    if event_type.startswith("customer.subscription."):
        return f"sub:{obj['id']}"
    if event_type.startswith("invoice."):
        return f"payments:{obj.get('customer')}"
    return f"{obj.get('object', 'obj')}:{obj.get('id')}"

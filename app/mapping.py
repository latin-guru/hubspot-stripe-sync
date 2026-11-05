"""Pure functions that translate Stripe data into HubSpot values. No network calls,
so they are easy to unit test (Phase 4)."""
from datetime import datetime, timezone
from typing import Optional, Tuple

# Stripe subscription status -> HubSpot billing_status option
STATUS_MAP = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "at_risk",
    "unpaid": "at_risk",
    "incomplete": "at_risk",
    "paused": "at_risk",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}

VALID_PLANS = {"starter", "growth", "scale"}


def as_dict(obj):
    """Turn a Stripe library object into a plain dict, across library versions."""
    if type(obj) is dict:
        return obj
    for name in ("to_dict_recursive", "to_dict"):
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn()
    return dict(obj)


def billing_status(subscription_status: str) -> str:
    return STATUS_MAP.get(subscription_status, "at_risk")


def monthly_amount(price: dict, quantity: int = 1) -> float:
    """Normalize any recurring price to a monthly amount in dollars."""
    cents = (price.get("unit_amount") or 0) * (quantity or 1)
    recurring = price.get("recurring") or {}
    interval = recurring.get("interval", "month")
    count = recurring.get("interval_count") or 1
    per_month = {"month": 1, "year": 1 / 12, "week": 52 / 12, "day": 365 / 12}.get(interval, 1)
    return round(cents / 100 * per_month / count, 2)


def plan_and_mrr(subscription: dict) -> Tuple[Optional[str], float]:
    """Plan tier comes from price metadata (or lookup_key); MRR sums all items."""
    plan, mrr = None, 0.0
    for item in (subscription.get("items") or {}).get("data", []):
        price = item.get("price") or {}
        mrr += monthly_amount(price, item.get("quantity") or 1)
        tier = (price.get("metadata") or {}).get("plan_tier")
        if not tier and price.get("lookup_key"):
            tier = next((p for p in VALID_PLANS if p in price["lookup_key"]), None)
        if tier in VALID_PLANS:
            plan = tier
    return plan, round(mrr, 2)


def to_hs_date(unix_ts: Optional[int]) -> Optional[str]:
    """HubSpot date properties accept YYYY-MM-DD (midnight UTC)."""
    if not unix_ts:
        return None
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d")


def email_domain(email: str) -> str:
    return email.split("@")[-1].lower().strip() if email and "@" in email else ""

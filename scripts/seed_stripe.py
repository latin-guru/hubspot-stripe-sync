"""Create Northwind Loop's plans, customers and subscriptions in Stripe TEST mode.

Each customer is a sample company's billing contact, on the plan from
data/sample_companies.csv, paying with Stripe's test Visa (pm_card_visa).
Stripe then sends webhooks, and the sync service updates HubSpot.

Re-runnable: existing prices, customers and subscriptions are reused.

Usage:  python scripts/seed_stripe.py            (all 30)
        python scripts/seed_stripe.py --limit 3  (try a few first)
"""
import argparse
import time

from stripe_common import as_dict, billing_contacts, find_customer, stripe

PLANS = {"starter": 9900, "growth": 29900, "scale": 79900}  # cents per month


def get_or_create_price(tier: str) -> str:
    key = f"nwl_{tier}_monthly"
    found = as_dict(stripe.Price.list(lookup_keys=[key], limit=1))["data"]
    if found:
        return found[0]["id"]
    product = as_dict(stripe.Product.create(name=f"Northwind Loop {tier.title()}",
                                            metadata={"plan_tier": tier}))
    price = as_dict(stripe.Price.create(
        product=product["id"], unit_amount=PLANS[tier], currency="usd",
        recurring={"interval": "month"}, lookup_key=key, metadata={"plan_tier": tier}))
    print(f"  created plan {tier}: ${PLANS[tier] / 100:.0f}/mo")
    return price["id"]


def ensure_customer(contact, company) -> str:
    existing = find_customer(contact["email"])
    if existing:
        return existing["id"]
    cust = as_dict(stripe.Customer.create(
        email=contact["email"], name=company["company_name"],
        payment_method="pm_card_visa",
        metadata={"company_domain": company["domain"], "sample_data": "true"}))
    pm = as_dict(stripe.PaymentMethod.list(customer=cust["id"], type="card", limit=1))["data"][0]
    stripe.Customer.modify(cust["id"], invoice_settings={"default_payment_method": pm["id"]})
    return cust["id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    print("Plans:")
    prices = {tier: get_or_create_price(tier) for tier in PLANS}

    rows = billing_contacts()[: args.limit]
    print(f"\nCustomers and subscriptions ({len(rows)}):")
    for contact, company in rows:
        cust_id = ensure_customer(contact, company)
        subs = as_dict(stripe.Subscription.list(customer=cust_id, status="all", limit=1))["data"]
        if subs:
            print(f"  {contact['email']}: already subscribed ({subs[0]['status']})")
            continue
        tier = company["intended_plan_tier"]
        sub = as_dict(stripe.Subscription.create(
            customer=cust_id, items=[{"price": prices[tier]}], metadata={"sample_data": "true"}))
        print(f"  {contact['email']}: {tier} -> {sub['status']}")
        time.sleep(1.5)  # pace the webhook burst so HubSpot rate limits stay comfortable

    print("\nDone. Watch the sync service terminal for APPLIED lines.")


if __name__ == "__main__":
    main()

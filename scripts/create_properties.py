"""Create the billing property group and custom properties on Contact and Company.

Safe to run more than once: existing groups/properties are skipped (HTTP 409).

Usage:  python scripts/create_properties.py
"""
from hubspot_client import HubSpotClient, HubSpotError

GROUP = {"name": "billing_sync", "label": "Billing (synced from Stripe)", "displayOrder": -1}

PLAN_OPTIONS = [
    {"label": "Starter", "value": "starter", "displayOrder": 0},
    {"label": "Growth", "value": "growth", "displayOrder": 1},
    {"label": "Scale", "value": "scale", "displayOrder": 2},
]
STATUS_OPTIONS = [
    {"label": "Active", "value": "active", "displayOrder": 0},
    {"label": "Trialing", "value": "trialing", "displayOrder": 1},
    {"label": "At risk (payment failed)", "value": "at_risk", "displayOrder": 2},
    {"label": "Canceled", "value": "canceled", "displayOrder": 3},
]

PROPERTIES = [
    {"name": "plan_tier", "label": "Plan tier", "type": "enumeration", "fieldType": "select",
     "options": PLAN_OPTIONS, "description": "Subscription plan. HubSpot can change it (Phase 3 pushes it to Stripe)."},
    {"name": "mrr", "label": "MRR", "type": "number", "fieldType": "number",
     "numberDisplayHint": "currency", "description": "Monthly recurring revenue in USD. Owned by Stripe."},
    {"name": "billing_status", "label": "Billing status", "type": "enumeration", "fieldType": "select",
     "options": STATUS_OPTIONS, "description": "Owned by Stripe."},
    {"name": "stripe_customer_id", "label": "Stripe customer ID", "type": "string", "fieldType": "text",
     "description": "Stripe cus_ ID. Owned by Stripe."},
    {"name": "last_payment_date", "label": "Last payment date", "type": "date", "fieldType": "date",
     "description": "Date of last paid invoice. Owned by Stripe."},
    {"name": "sync_source", "label": "Last sync source", "type": "string", "fieldType": "text",
     "description": "Loop guard: which system made the last synced write (stripe or hubspot)."},
]

OBJECTS = ["contacts", "companies"]

DEAL_PROPERTY = {
    "name": "stripe_subscription_id", "label": "Stripe subscription ID", "type": "string",
    "fieldType": "text", "groupName": "dealinformation", "hasUniqueValue": True,
    "description": "Stripe sub_ ID. Unique, so one subscription can never create two deals.",
}


def main() -> None:
    hs = HubSpotClient()
    for obj in OBJECTS:
        print(f"\n== {obj} ==")
        r = hs.post(f"/crm/v3/properties/{obj}/groups", json=GROUP)
        if r.status_code in (200, 201):
            print(f"  created group {GROUP['name']}")
        elif r.status_code == 409:
            print(f"  group {GROUP['name']} already exists")
        else:
            raise HubSpotError(f"group create failed on {obj}: {r.status_code} {r.text}")

        for prop in PROPERTIES:
            body = {**prop, "groupName": GROUP["name"]}
            r = hs.post(f"/crm/v3/properties/{obj}", json=body)
            if r.status_code in (200, 201):
                print(f"  created {prop['name']}")
            elif r.status_code == 409:
                print(f"  {prop['name']} already exists (skipped)")
            else:
                raise HubSpotError(f"{prop['name']} on {obj} failed: {r.status_code} {r.text}")

    # Deals: one property linking each deal to its Stripe subscription (Phase 2).
    print("\n== deals ==")
    r = hs.post("/crm/v3/properties/deals", json=DEAL_PROPERTY)
    if r.status_code in (200, 201):
        print(f"  created {DEAL_PROPERTY['name']}")
    elif r.status_code == 409:
        print(f"  {DEAL_PROPERTY['name']} already exists (skipped)")
    elif r.status_code == 403:
        raise HubSpotError("403 on deals: add the crm.schemas.deals.write scope to your Service Key, then rerun.")
    else:
        raise HubSpotError(f"deal property failed: {r.status_code} {r.text}")
    print("\nDone. Check Settings > Properties > group 'Billing (synced from Stripe)'.")


if __name__ == "__main__":
    main()

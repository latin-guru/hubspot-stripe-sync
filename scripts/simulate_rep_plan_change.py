"""Act like a sales rep: change a contact's Plan tier in HubSpot, then send the same
webhook the HubSpot workflow would send. Lets you test Phase 3 before the workflow exists.

Usage:  python scripts/simulate_rep_plan_change.py --plan scale
        python scripts/simulate_rep_plan_change.py --email someone@x.example.com --plan starter
"""
import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.hubspot_api import HubSpotAPI  # noqa: E402
from app.hubspot_client import HubSpotClient  # noqa: E402
from stripe_common import billing_contacts  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="contact email (defaults to the first sample billing contact)")
    parser.add_argument("--plan", required=True, choices=["starter", "growth", "scale"])
    parser.add_argument("--url", default="http://localhost:8000/webhooks/hubspot")
    args = parser.parse_args()

    if not config.HUBSPOT_WEBHOOK_SECRET:
        sys.exit("Set HUBSPOT_WEBHOOK_SECRET in .env first.")

    email = args.email or billing_contacts()[0][0]["email"]
    hubspot = HubSpotAPI(HubSpotClient(config.HUBSPOT_SERVICE_KEY))
    contact = hubspot.find_contact_by_email(email)
    if not contact:
        sys.exit(f"No HubSpot contact with email {email}.")

    print(f"Rep changes {email}: {contact['properties'].get('plan_tier')} -> {args.plan}")
    hubspot.update("contacts", contact["id"], {"plan_tier": args.plan})

    resp = requests.post(args.url, json={"objectId": int(contact["id"])},
                         headers={"X-Sync-Secret": config.HUBSPOT_WEBHOOK_SECRET}, timeout=60)
    print(f"Sync service answered {resp.status_code}: {resp.json()}")
    print("Watch the sync terminal: PUSHED, then a customer.subscription.updated APPLIED line from Stripe.")


if __name__ == "__main__":
    main()

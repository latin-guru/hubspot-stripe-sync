"""Shared setup for the Stripe helper scripts. Refuses to run with a live key."""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import stripe  # noqa: E402

from app import config  # noqa: E402
from app.mapping import as_dict  # noqa: E402,F401

if not config.STRIPE_SECRET_KEY.startswith("sk_test_"):
    sys.exit("STRIPE_SECRET_KEY must be a TEST key (sk_test_...). This project never touches live mode.")
stripe.api_key = config.STRIPE_SECRET_KEY


def billing_contacts():
    """One billing contact per sample company, joined with its company row."""
    data = ROOT / "data"
    with open(data / "sample_companies.csv") as f:
        companies = {c["domain"]: c for c in csv.DictReader(f)}
    with open(data / "sample_contacts.csv") as f:
        contacts = [c for c in csv.DictReader(f) if c["is_billing_contact"] == "true"]
    return [(c, companies[c["company_domain"]]) for c in contacts if c["company_domain"] in companies]


def find_customer(email):
    found = as_dict(stripe.Customer.list(email=email, limit=1))["data"]
    return found[0] if found else None

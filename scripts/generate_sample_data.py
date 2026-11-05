"""Generate fictional companies and contacts for the HubSpot <-> Stripe sync showcase.

All data is fake (Faker, fixed seed) for the fictional SaaS company "Northwind Loop".
Output: data/sample_companies.csv and data/sample_contacts.csv

Usage:  python scripts/generate_sample_data.py
"""
import csv
import random
from pathlib import Path

from faker import Faker

SEED = 42
NUM_COMPANIES = 30
OUT_DIR = Path(__file__).resolve().parent.parent / "data"

fake = Faker("en_US")
Faker.seed(SEED)
random.seed(SEED)

INDUSTRIES = ["Marketing agency", "E-commerce", "Media publisher", "SaaS", "Consumer brand", "Travel"]
SIZE_BANDS = ["1-10", "11-50", "51-200", "201-500"]
# plan_tier -> monthly price in USD. Stripe will own this later; kept here so Phase 2 can seed Stripe.
PLANS = {"starter": 99, "growth": 299, "scale": 799}
PLAN_WEIGHTS = [0.5, 0.35, 0.15]


def slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())[:20]


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    companies, contacts, used_domains = [], [], set()

    while len(companies) < NUM_COMPANIES:
        name = fake.company().replace(",", "")
        # Subdomains of example.com (reserved, RFC 2606), so no real business can own them. HubSpot rejects bare .example emails.
        domain = f"{slug(name)}.example.com"
        if domain in used_domains:
            continue
        used_domains.add(domain)
        plan = random.choices(list(PLANS), weights=PLAN_WEIGHTS)[0]
        companies.append({
            "company_name": name,
            "domain": domain,
            "industry": random.choice(INDUSTRIES),
            "size_band": random.choice(SIZE_BANDS),
            "city": fake.city(),
            "state": fake.state_abbr(),
            "intended_plan_tier": plan,
            "intended_mrr": PLANS[plan],
        })

    for c in companies:
        # One billing contact per company, plus a second contact for about a third of them.
        for i in range(1 if random.random() > 0.33 else 2):
            first, last = fake.first_name(), fake.last_name()
            contacts.append({
                "email": f"{first.lower()}.{last.lower()}@{c['domain']}",
                "firstname": first,
                "lastname": last,
                "jobtitle": "Finance Manager" if i == 0 else fake.job().replace(",", ""),
                "company_domain": c["domain"],
                "is_billing_contact": "true" if i == 0 else "false",
            })

    for path, rows in [("sample_companies.csv", companies), ("sample_contacts.csv", contacts)]:
        with open(OUT_DIR / path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    print(f"Wrote {len(companies)} companies and {len(contacts)} contacts to {OUT_DIR}")


if __name__ == "__main__":
    main()

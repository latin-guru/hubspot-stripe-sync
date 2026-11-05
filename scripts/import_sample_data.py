"""Load the fake companies and contacts into HubSpot and associate them.

- Companies: looked up by domain first, created only if missing (re-runnable).
- Contacts: batch upsert keyed on email (re-runnable, no duplicates).
- Each contact is associated to its company with the default association.
- Billing fields are left EMPTY on purpose: Stripe owns them and fills them in Phase 2.

Usage:  python scripts/import_sample_data.py
"""
import csv
import time
from pathlib import Path

from hubspot_client import HubSpotClient, HubSpotError

DATA = Path(__file__).resolve().parent.parent / "data"
BATCH = 100  # HubSpot batch endpoints accept up to 100 inputs


def read_csv(name):
    with open(DATA / name) as f:
        return list(csv.DictReader(f))


def find_company_by_domain(hs, domain):
    body = {"filterGroups": [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}],
            "properties": ["domain"], "limit": 1}
    r = hs.post("/crm/v3/objects/companies/search", json=body)
    if r.status_code != 200:
        raise HubSpotError(f"company search failed: {r.status_code} {r.text}")
    results = r.json().get("results", [])
    return results[0]["id"] if results else None


def main() -> None:
    hs = HubSpotClient()
    companies = read_csv("sample_companies.csv")
    contacts = read_csv("sample_contacts.csv")

    # 1) Companies
    domain_to_id, to_create = {}, []
    for c in companies:
        existing = find_company_by_domain(hs, c["domain"])
        time.sleep(0.25)  # search API has a lower rate limit than other endpoints
        if existing:
            domain_to_id[c["domain"]] = existing
        else:
            to_create.append(c)
    print(f"Companies: {len(domain_to_id)} already in HubSpot, {len(to_create)} to create")

    for i in range(0, len(to_create), BATCH):
        chunk = to_create[i:i + BATCH]
        inputs = [{"properties": {
            "name": c["company_name"], "domain": c["domain"], "city": c["city"], "state": c["state"],
            "description": f"{c['industry']} · {c['size_band']} employees (fictional sample data)",
            "lifecyclestage": "opportunity",
        }} for c in chunk]
        r = hs.post("/crm/v3/objects/companies/batch/create", json={"inputs": inputs})
        if r.status_code not in (200, 201):
            raise HubSpotError(f"company batch create failed: {r.status_code} {r.text}")
        for res in r.json()["results"]:
            domain_to_id[res["properties"]["domain"]] = res["id"]

    # 2) Contacts (upsert by email)
    contact_ids = {}
    for i in range(0, len(contacts), BATCH):
        chunk = contacts[i:i + BATCH]
        inputs = [{"idProperty": "email", "id": p["email"], "properties": {
            "email": p["email"], "firstname": p["firstname"], "lastname": p["lastname"],
            "jobtitle": p["jobtitle"], "lifecyclestage": "opportunity",
        }} for p in chunk]
        r = hs.post("/crm/v3/objects/contacts/batch/upsert", json={"inputs": inputs})
        if r.status_code not in (200, 201):
            raise HubSpotError(f"contact batch upsert failed: {r.status_code} {r.text}")
        for res in r.json()["results"]:
            contact_ids[res["properties"]["email"].lower()] = res["id"]
    print(f"Contacts upserted: {len(contact_ids)}")

    # 3) Associate contact -> company (default association label)
    pairs = [{"from": {"id": contact_ids[p["email"].lower()]}, "to": {"id": domain_to_id[p["company_domain"]]}}
             for p in contacts if p["email"].lower() in contact_ids and p["company_domain"] in domain_to_id]
    for i in range(0, len(pairs), BATCH):
        r = hs.post("/crm/v4/associations/contacts/companies/batch/associate/default",
                    json={"inputs": pairs[i:i + BATCH]})
        if r.status_code not in (200, 201):
            raise HubSpotError(f"association failed: {r.status_code} {r.text}")
    print(f"Associations created: {len(pairs)}")
    print("\nDone. Open Contacts in HubSpot and check a record shows its company.")


if __name__ == "__main__":
    main()

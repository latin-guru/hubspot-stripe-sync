"""Archive the sample companies and contacts so the import can start clean.

Only touches records on reserved sample domains (ending in .example or .example.com),
so it can never remove anything else in the portal. Archived records go to HubSpot's
recycle bin, where they can be restored for 90 days.

Usage:  python scripts/reset_sample_data.py
"""
from hubspot_client import HubSpotClient, HubSpotError

SAMPLE_SUFFIXES = (".example", ".example.com")


def is_sample(value):
    value = (value or "").lower()
    domain = value.split("@")[-1]
    return domain.endswith(SAMPLE_SUFFIXES)


def list_all(hs, obj, prop):
    records, after = [], None
    while True:
        params = {"limit": 100, "properties": prop}
        if after:
            params["after"] = after
        r = hs.get(f"/crm/v3/objects/{obj}", params=params)
        if r.status_code != 200:
            raise HubSpotError(f"list {obj} failed: {r.status_code} {r.text}")
        data = r.json()
        records += data.get("results", [])
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            return records


def archive(hs, obj, ids):
    for i in range(0, len(ids), 100):
        r = hs.post(f"/crm/v3/objects/{obj}/batch/archive",
                    json={"inputs": [{"id": x} for x in ids[i:i + 100]]})
        if r.status_code not in (200, 204):
            raise HubSpotError(f"archive {obj} failed: {r.status_code} {r.text}")


def main() -> None:
    hs = HubSpotClient()
    for obj, prop in [("contacts", "email"), ("companies", "domain")]:
        ids = [rec["id"] for rec in list_all(hs, obj, prop) if is_sample(rec["properties"].get(prop))]
        archive(hs, obj, ids)
        print(f"Archived {len(ids)} sample {obj}")
    print("Done. Run import_sample_data.py again for a clean load.")


if __name__ == "__main__":
    main()
